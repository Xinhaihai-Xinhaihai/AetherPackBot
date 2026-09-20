"""Brain dialects.

Each dialect is a wire recipe, not an SDK wrapper.
The Cortex speaks one internal request; dialects only translate.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from aetherpackbot.protocols.providers import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    StreamingChunk,
)
from aetherpackbot.providers.wire import (
    BrainWireError,
    HttpLane,
    WireCall,
    join_url,
    normalize_openai_base,
)
from aetherpackbot.kernel.logging import get_logger

logger = get_logger("brain.dialect")


def classify_lane(api_base: str | None) -> str:
    """local = loopback/LAN; cloud = public host."""
    if not api_base:
        return "cloud"
    host = (urlparse(api_base).hostname or "").lower()
    if not host:
        return "cloud"
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return "local"
    if host.endswith(".local"):
        return "local"
    parts = host.split(".")
    if parts and parts[0].isdigit() and len(parts) == 4:
        a, b = int(parts[0]), int(parts[1])
        if a == 10 or a == 127 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31):
            return "local"
    return "cloud"


def _text_of(msg: LLMMessage) -> str:
    return msg.content if isinstance(msg.content, str) else str(msg.content or "")


def _openai_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        item: dict[str, Any] = {"role": msg.role, "content": _text_of(msg)}
        if msg.name:
            item["name"] = msg.name
        if msg.tool_call_id:
            item["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            item["tool_calls"] = msg.tool_calls
            if not item["content"]:
                item["content"] = None
        out.append(item)
    return out


def _usage(raw: dict[str, Any] | None) -> dict[str, int]:
    if not raw:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0),
        "completion_tokens": int(raw.get("completion_tokens") or raw.get("output_tokens") or 0),
        "total_tokens": int(raw.get("total_tokens") or 0),
    }


def _openai_body(req: LLMRequest, model: str, stream: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": req.model or model,
        "messages": _openai_messages(req.messages),
        "temperature": req.temperature,
    }
    if stream:
        body["stream"] = True
    max_tokens = req.max_tokens
    if max_tokens:
        # newer OpenAI models prefer max_completion_tokens; compat gates still want max_tokens
        body["max_tokens"] = max_tokens
    if req.tools:
        body["tools"] = req.tools
        if req.tool_choice:
            body["tool_choice"] = req.tool_choice
    if req.extra:
        body.update(req.extra)
    return body


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for part in content:
            if isinstance(part, dict):
                bits.append(part.get("text") or part.get("content") or "")
            else:
                bits.append(str(part))
        return "".join(bits)
    return str(content)


def _parse_openai_message(choice: dict[str, Any], model: str, raw: Any) -> LLMResponse:
    message = choice.get("message") or {}
    content = _flatten_content(message.get("content"))
    if not content:
        # reasoning models (deepseek-r1 / v4, grok, kimi) may spend the budget on thinking
        content = _flatten_content(
            message.get("reasoning_content")
            or message.get("reasoning")
            or message.get("refusal")
        )
    tool_calls = message.get("tool_calls")
    usage = raw.get("usage") if isinstance(raw, dict) else None
    return LLMResponse(
        content=content or "",
        model=raw.get("model", model) if isinstance(raw, dict) else model,
        finish_reason=choice.get("finish_reason") or "",
        tool_calls=tool_calls,
        usage=_usage(usage),
        raw_response=raw,
    )


class Dialect:
    name = "base"

    def __init__(self, lane: HttpLane) -> None:
        self.lane = lane

    def default_base(self) -> str:
        raise NotImplementedError

    def prepare_base(self, api_base: str | None) -> str:
        return (api_base or self.default_base()).rstrip("/")

    def auth_headers(self, api_key: str, extra: dict[str, Any]) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        custom = extra.get("headers") or extra.get("custom_headers") or {}
        if isinstance(custom, dict):
            headers.update({str(k): str(v) for k, v in custom.items()})
        return headers

    async def chat(
        self,
        api_key: str,
        api_base: str | None,
        model: str,
        request: LLMRequest,
        timeout: float,
        extra: dict[str, Any],
    ) -> LLMResponse:
        raise NotImplementedError

    async def chat_stream(
        self,
        api_key: str,
        api_base: str | None,
        model: str,
        request: LLMRequest,
        timeout: float,
        extra: dict[str, Any],
    ) -> AsyncIterator[StreamingChunk]:
        raise NotImplementedError
        yield StreamingChunk()  # pragma: no cover

    async def pulse(
        self,
        api_key: str,
        api_base: str | None,
        model: str,
        timeout: float,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError


class OpenAICompatDialect(Dialect):
    """Any OpenAI-style /v1/chat/completions gate, including official."""

    name = "openai_compat"

    def default_base(self) -> str:
        return "https://api.openai.com/v1"

    def prepare_base(self, api_base: str | None) -> str:
        return normalize_openai_base(api_base or self.default_base())

    def auth_headers(self, api_key: str, extra: dict[str, Any]) -> dict[str, str]:
        headers = super().auth_headers(api_key, extra)
        if api_key:
            headers.setdefault("Authorization", f"Bearer {api_key}")
        return headers

    def _call(
        self,
        api_key: str,
        api_base: str | None,
        model: str,
        request: LLMRequest,
        timeout: float,
        extra: dict[str, Any],
        stream: bool,
    ) -> WireCall:
        base = self.prepare_base(api_base)
        return WireCall(
            method="POST",
            url=join_url(base, "/chat/completions"),
            headers=self.auth_headers(api_key, extra),
            json_body=_openai_body(request, model, stream),
            timeout=timeout,
        )

    async def chat(self, api_key, api_base, model, request, timeout, extra) -> LLMResponse:
        reply = await self.lane.request(self._call(api_key, api_base, model, request, timeout, extra, False))
        if not reply.ok:
            raise BrainWireError(
                f"{self.name} http {reply.status}: {reply.text[:400]}",
                status=reply.status,
                body=reply.text,
            )
        data = reply.json if isinstance(reply.json, dict) else {}
        choices = data.get("choices") or []
        if not choices:
            raise BrainWireError(f"{self.name} empty choices: {reply.text[:300]}", body=reply.text)
        return _parse_openai_message(choices[0], model, data)

    async def chat_stream(self, api_key, api_base, model, request, timeout, extra):
        call = self._call(api_key, api_base, model, request, timeout, extra, True)
        async for payload in self.lane.sse(call):
            choices = payload.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            content = delta.get("content") or ""
            if not content:
                content = delta.get("reasoning_content") or delta.get("reasoning") or ""
            tool_calls = delta.get("tool_calls")
            finish = choice.get("finish_reason")
            if content or tool_calls or finish:
                yield StreamingChunk(
                    content=content,
                    is_final=bool(finish),
                    tool_calls=tool_calls,
                    finish_reason=finish,
                )

    async def pulse(self, api_key, api_base, model, timeout, extra) -> dict[str, Any]:
        base = self.prepare_base(api_base)
        reply = await self.lane.request(
            WireCall(
                method="GET",
                url=join_url(base, "/models"),
                headers=self.auth_headers(api_key, extra),
                timeout=min(timeout, 12),
            )
        )
        return {
            "reachable": reply.status != 0,
            "status": reply.status,
            "ok": reply.ok,
            "hint": "models listed" if reply.ok else reply.text[:160],
        }


class OpenAIOfficialDialect(OpenAICompatDialect):
    name = "openai_official"

    def default_base(self) -> str:
        return "https://api.openai.com/v1"

    def prepare_base(self, api_base: str | None) -> str:
        if not api_base:
            return self.default_base()
        return normalize_openai_base(api_base)

    async def chat(self, api_key, api_base, model, request, timeout, extra) -> LLMResponse:
        # official gpt-4o/gpt-5 family often wants max_completion_tokens
        body_extra = dict(extra)
        req = request
        if request.max_tokens:
            cloned = LLMRequest(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=None,
                tools=request.tools,
                tool_choice=request.tool_choice,
                stream=request.stream,
                extra={**(request.extra or {}), "max_completion_tokens": request.max_tokens},
            )
            req = cloned
        try:
            return await super().chat(api_key, api_base, model, req, timeout, body_extra)
        except BrainWireError as e:
            if request.max_tokens and "max_completion_tokens" in (e.body or ""):
                return await super().chat(api_key, api_base, model, request, timeout, extra)
            raise


class GeminiNativeDialect(Dialect):
    name = "gemini"

    def default_base(self) -> str:
        return "https://generativelanguage.googleapis.com/v1beta"

    def prepare_base(self, api_base: str | None) -> str:
        base = (api_base or self.default_base()).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3] + "/v1beta"
        return base

    def _contents(self, messages: list[LLMMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        system = None
        contents: list[dict[str, Any]] = []
        for msg in messages:
            text = _text_of(msg)
            if msg.role == "system":
                system = (system + "\n" + text) if system else text
            elif msg.role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
            elif msg.role == "tool":
                contents.append({"role": "user", "parts": [{"text": f"[tool:{msg.tool_call_id}] {text}"}]})
            else:
                contents.append({"role": "user", "parts": [{"text": text}]})
        return system, contents

    def _url(self, api_base: str | None, model: str, stream: bool, api_key: str) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        path = f"/models/{model}:{action}"
        url = join_url(self.prepare_base(api_base), path)
        if api_key and "key=" not in url:
            url += ("&" if "?" in url else "?") + f"key={api_key}"
        if stream and "alt=sse" not in url:
            url += ("&" if "?" in url else "?") + "alt=sse"
        return url

    def _body(self, request: LLMRequest) -> dict[str, Any]:
        system, contents = self._contents(request.messages)
        generation: dict[str, Any] = {"temperature": request.temperature}
        if request.max_tokens:
            generation["maxOutputTokens"] = request.max_tokens
        body: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def _text_from(self, data: dict[str, Any]) -> tuple[str, str]:
        cands = data.get("candidates") or []
        if not cands:
            return "", data.get("error", {}).get("message", "empty candidates")
        parts = ((cands[0].get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        finish = cands[0].get("finishReason") or "STOP"
        return text, finish

    async def chat(self, api_key, api_base, model, request, timeout, extra) -> LLMResponse:
        reply = await self.lane.request(
            WireCall(
                method="POST",
                url=self._url(api_base, request.model or model, False, api_key),
                headers=self.auth_headers(api_key, extra),
                json_body=self._body(request),
                timeout=timeout,
            )
        )
        if not reply.ok:
            raise BrainWireError(
                f"gemini http {reply.status}: {reply.text[:400]}",
                status=reply.status,
                body=reply.text,
            )
        data = reply.json if isinstance(reply.json, dict) else {}
        text, finish = self._text_from(data)
        usage_meta = data.get("usageMetadata") or {}
        return LLMResponse(
            content=text,
            model=request.model or model,
            finish_reason=finish,
            usage={
                "prompt_tokens": int(usage_meta.get("promptTokenCount") or 0),
                "completion_tokens": int(usage_meta.get("candidatesTokenCount") or 0),
                "total_tokens": int(usage_meta.get("totalTokenCount") or 0),
            },
            raw_response=data,
        )

    async def chat_stream(self, api_key, api_base, model, request, timeout, extra):
        call = WireCall(
            method="POST",
            url=self._url(api_base, request.model or model, True, api_key),
            headers=self.auth_headers(api_key, extra),
            json_body=self._body(request),
            timeout=timeout,
        )
        async for payload in self.lane.sse(call):
            text, finish = self._text_from(payload)
            if text:
                yield StreamingChunk(content=text, is_final=finish not in ("", "STOP", None), finish_reason=finish)

    async def pulse(self, api_key, api_base, model, timeout, extra) -> dict[str, Any]:
        base = self.prepare_base(api_base)
        url = join_url(base, "/models")
        if api_key:
            url += f"?key={api_key}"
        reply = await self.lane.request(WireCall("GET", url, timeout=min(timeout, 12)))
        return {
            "reachable": reply.status != 0,
            "status": reply.status,
            "ok": reply.ok,
            "hint": "models listed" if reply.ok else reply.text[:160],
        }


class AnthropicDialect(Dialect):
    name = "anthropic"

    def default_base(self) -> str:
        return "https://api.anthropic.com/v1"

    def auth_headers(self, api_key: str, extra: dict[str, Any]) -> dict[str, str]:
        headers = super().auth_headers(api_key, extra)
        if api_key:
            headers["x-api-key"] = api_key
        headers.setdefault("anthropic-version", extra.get("anthropic_version") or "2023-06-01")
        return headers

    def _body(self, request: LLMRequest, model: str, stream: bool) -> dict[str, Any]:
        system = ""
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system = (system + "\n" + _text_of(msg)).strip()
            elif msg.role == "tool":
                messages.append({"role": "user", "content": f"[tool:{msg.tool_call_id}] {_text_of(msg)}"})
            elif msg.role in ("user", "assistant"):
                messages.append({"role": msg.role, "content": _text_of(msg)})
        body: dict[str, Any] = {
            "model": request.model or model,
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
        }
        if system:
            body["system"] = system
        if stream:
            body["stream"] = True
        if request.tools:
            body["tools"] = [
                {
                    "name": t.get("function", {}).get("name"),
                    "description": t.get("function", {}).get("description", ""),
                    "input_schema": t.get("function", {}).get("parameters", {"type": "object", "properties": {}}),
                }
                for t in request.tools
                if t.get("function")
            ]
        return body

    async def chat(self, api_key, api_base, model, request, timeout, extra) -> LLMResponse:
        reply = await self.lane.request(
            WireCall(
                method="POST",
                url=join_url(self.prepare_base(api_base), "/messages"),
                headers=self.auth_headers(api_key, extra),
                json_body=self._body(request, model, False),
                timeout=timeout,
            )
        )
        if not reply.ok:
            raise BrainWireError(
                f"anthropic http {reply.status}: {reply.text[:400]}",
                status=reply.status,
                body=reply.text,
            )
        data = reply.json if isinstance(reply.json, dict) else {}
        content = ""
        tool_calls = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                content += block.get("text") or ""
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    }
                )
        usage = data.get("usage") or {}
        return LLMResponse(
            content=content,
            model=data.get("model") or model,
            finish_reason=data.get("stop_reason") or "",
            tool_calls=tool_calls or None,
            usage={
                "prompt_tokens": int(usage.get("input_tokens") or 0),
                "completion_tokens": int(usage.get("output_tokens") or 0),
                "total_tokens": int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0),
            },
            raw_response=data,
        )

    async def chat_stream(self, api_key, api_base, model, request, timeout, extra):
        call = WireCall(
            method="POST",
            url=join_url(self.prepare_base(api_base), "/messages"),
            headers=self.auth_headers(api_key, extra),
            json_body=self._body(request, model, True),
            timeout=timeout,
        )
        async for payload in self.lane.sse(call):
            if payload.get("type") == "content_block_delta":
                delta = payload.get("delta") or {}
                text = delta.get("text") or ""
                if text:
                    yield StreamingChunk(content=text)
            elif payload.get("type") == "message_stop":
                yield StreamingChunk(is_final=True, finish_reason="stop")

    async def pulse(self, api_key, api_base, model, timeout, extra) -> dict[str, Any]:
        reply = await self.lane.request(
            WireCall(
                method="GET",
                url=join_url(self.prepare_base(api_base), "/models"),
                headers=self.auth_headers(api_key, extra),
                timeout=min(timeout, 12),
            )
        )
        return {
            "reachable": reply.status != 0,
            "status": reply.status,
            "ok": reply.ok,
            "hint": "models listed" if reply.ok else reply.text[:160],
        }


class OllamaLocalDialect(OpenAICompatDialect):
    """Local Ollama / llama.cpp / vLLM. Prefers loopback OpenAI-compat, falls back to /api/chat."""

    name = "ollama"

    def default_base(self) -> str:
        return "http://127.0.0.1:11434/v1"

    def prepare_base(self, api_base: str | None) -> str:
        base = (api_base or self.default_base()).rstrip("/")
        if base.endswith("/api"):
            base = base[:-4] + "/v1"
        if not base.endswith("/v1"):
            base = base + "/v1"
        return base

    async def chat(self, api_key, api_base, model, request, timeout, extra) -> LLMResponse:
        try:
            return await super().chat(api_key or "ollama", api_base, model, request, timeout, extra)
        except BrainWireError:
            native = self.prepare_base(api_base)
            if native.endswith("/v1"):
                native = native[:-3]
            body = {
                "model": request.model or model,
                "messages": _openai_messages(request.messages),
                "stream": False,
                "options": {"temperature": request.temperature},
            }
            reply = await self.lane.request(
                WireCall(
                    method="POST",
                    url=join_url(native, "/api/chat"),
                    headers=self.auth_headers(api_key or "ollama", extra),
                    json_body=body,
                    timeout=timeout,
                )
            )
            if not reply.ok:
                raise BrainWireError(
                    f"ollama http {reply.status}: {reply.text[:400]}",
                    status=reply.status,
                    body=reply.text,
                )
            data = reply.json if isinstance(reply.json, dict) else {}
            msg = data.get("message") or {}
            return LLMResponse(
                content=msg.get("content") or "",
                model=data.get("model") or model,
                finish_reason="stop" if data.get("done") else "",
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                raw_response=data,
            )

    async def pulse(self, api_key, api_base, model, timeout, extra) -> dict[str, Any]:
        native = self.prepare_base(api_base)
        if native.endswith("/v1"):
            native = native[:-3]
        reply = await self.lane.request(
            WireCall("GET", join_url(native, "/api/tags"), timeout=min(timeout, 8))
        )
        if reply.ok:
            return {"reachable": True, "status": reply.status, "ok": True, "hint": "local ollama up"}
        return await super().pulse(api_key or "ollama", api_base, model, timeout, extra)


class DeepSeekDialect(OpenAICompatDialect):
    name = "deepseek"

    def default_base(self) -> str:
        return "https://api.deepseek.com/v1"


class MoonshotDialect(OpenAICompatDialect):
    name = "moonshot"

    def default_base(self) -> str:
        return "https://api.moonshot.cn/v1"


class DashScopeDialect(OpenAICompatDialect):
    name = "dashscope"

    def default_base(self) -> str:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


class ZhipuDialect(OpenAICompatDialect):
    name = "zhipu"

    def default_base(self) -> str:
        return "https://open.bigmodel.cn/api/paas/v4"

    def prepare_base(self, api_base: str | None) -> str:
        return (api_base or self.default_base()).rstrip("/")


class GroqDialect(OpenAICompatDialect):
    name = "groq"

    def default_base(self) -> str:
        return "https://api.groq.com/openai/v1"


class OpenRouterDialect(OpenAICompatDialect):
    name = "openrouter"

    def default_base(self) -> str:
        return "https://openrouter.ai/api/v1"

    def auth_headers(self, api_key: str, extra: dict[str, Any]) -> dict[str, str]:
        headers = super().auth_headers(api_key, extra)
        headers.setdefault("HTTP-Referer", extra.get("referer") or "https://aetherpackbot.local")
        headers.setdefault("X-Title", extra.get("title") or "AetherPackBot")
        return headers


class XAIDialect(OpenAICompatDialect):
    name = "xai"

    def default_base(self) -> str:
        return "https://api.x.ai/v1"


class MistralDialect(OpenAICompatDialect):
    name = "mistral"

    def default_base(self) -> str:
        return "https://api.mistral.ai/v1"


class TogetherDialect(OpenAICompatDialect):
    name = "together"

    def default_base(self) -> str:
        return "https://api.together.xyz/v1"


class SiliconFlowDialect(OpenAICompatDialect):
    name = "siliconflow"

    def default_base(self) -> str:
        return "https://api.siliconflow.cn/v1"


class MiniMaxDialect(OpenAICompatDialect):
    name = "minimax"

    def default_base(self) -> str:
        return "https://api.minimax.chat/v1"


class AzureOpenAIDialect(OpenAICompatDialect):
    name = "azure"

    def default_base(self) -> str:
        return ""

    def prepare_base(self, api_base: str | None) -> str:
        return (api_base or "").rstrip("/")

    def auth_headers(self, api_key: str, extra: dict[str, Any]) -> dict[str, str]:
        headers = super().auth_headers(api_key, extra)
        if api_key:
            headers["api-key"] = api_key
            headers.pop("Authorization", None)
        return headers

    def _call(self, api_key, api_base, model, request, timeout, extra, stream):
        base = self.prepare_base(api_base)
        api_version = extra.get("api_version") or "2024-10-21"
        deployment = extra.get("deployment") or request.model or model
        url = f"{base}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
        return WireCall(
            method="POST",
            url=url,
            headers=self.auth_headers(api_key, extra),
            json_body=_openai_body(request, model, stream),
            timeout=timeout,
        )


class FireworksDialect(OpenAICompatDialect):
    name = "fireworks"

    def default_base(self) -> str:
        return "https://api.fireworks.ai/inference/v1"


class NovitaDialect(OpenAICompatDialect):
    name = "novita"

    def default_base(self) -> str:
        return "https://api.novita.ai/v3/openai"


class PerplexityDialect(OpenAICompatDialect):
    name = "perplexity"

    def default_base(self) -> str:
        return "https://api.perplexity.ai"


class VolcengineDialect(OpenAICompatDialect):
    name = "volcengine"

    def default_base(self) -> str:
        return "https://ark.cn-beijing.volces.com/api/v3"


class BaichuanDialect(OpenAICompatDialect):
    name = "baichuan"

    def default_base(self) -> str:
        return "https://api.baichuan-ai.com/v1"


class LingyiDialect(OpenAICompatDialect):
    name = "lingyi"

    def default_base(self) -> str:
        return "https://api.lingyiwanwu.com/v1"


class StepFunDialect(OpenAICompatDialect):
    name = "stepfun"

    def default_base(self) -> str:
        return "https://api.stepfun.com/v1"


class InfiniDialect(OpenAICompatDialect):
    name = "infini"

    def default_base(self) -> str:
        return "https://cloud.infini-ai.com/maas/v1"


class NvidiaNimDialect(OpenAICompatDialect):
    name = "nvidia"

    def default_base(self) -> str:
        return "https://integrate.api.nvidia.com/v1"


class CohereDialect(Dialect):
    name = "cohere"

    def default_base(self) -> str:
        return "https://api.cohere.ai/v2"

    def auth_headers(self, api_key: str, extra: dict[str, Any]) -> dict[str, str]:
        headers = super().auth_headers(api_key, extra)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def chat(self, api_key, api_base, model, request, timeout, extra) -> LLMResponse:
        system = ""
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system = _text_of(msg)
            else:
                messages.append({"role": "assistant" if msg.role == "assistant" else "user", "content": _text_of(msg)})
        body: dict[str, Any] = {"model": request.model or model, "messages": messages}
        if system:
            body["preamble"] = system
        reply = await self.lane.request(
            WireCall(
                method="POST",
                url=join_url(self.prepare_base(api_base), "/chat"),
                headers=self.auth_headers(api_key, extra),
                json_body=body,
                timeout=timeout,
            )
        )
        if not reply.ok:
            raise BrainWireError(f"cohere http {reply.status}: {reply.text[:400]}", status=reply.status, body=reply.text)
        data = reply.json if isinstance(reply.json, dict) else {}
        text = ""
        msg = data.get("message") or {}
        for part in msg.get("content") or []:
            if isinstance(part, dict) and part.get("text"):
                text += part["text"]
        return LLMResponse(content=text, model=request.model or model, finish_reason="stop", raw_response=data)

    async def chat_stream(self, api_key, api_base, model, request, timeout, extra):
        yield StreamingChunk(content="", is_final=True)

    async def pulse(self, api_key, api_base, model, timeout, extra) -> dict[str, Any]:
        reply = await self.lane.request(
            WireCall(
                method="GET",
                url=join_url(self.prepare_base(api_base), "/models"),
                headers=self.auth_headers(api_key, extra),
                timeout=min(timeout, 12),
            )
        )
        return {"reachable": reply.status != 0, "status": reply.status, "ok": reply.ok, "hint": reply.text[:160]}


DIALECTS: dict[str, type[Dialect]] = {
    "openai": OpenAICompatDialect,
    "openai_compat": OpenAICompatDialect,
    "openai_official": OpenAIOfficialDialect,
    "gemini": GeminiNativeDialect,
    "gemini_native": GeminiNativeDialect,
    "anthropic": AnthropicDialect,
    "claude": AnthropicDialect,
    "ollama": OllamaLocalDialect,
    "local": OllamaLocalDialect,
    "deepseek": DeepSeekDialect,
    "moonshot": MoonshotDialect,
    "kimi": MoonshotDialect,
    "dashscope": DashScopeDialect,
    "qwen": DashScopeDialect,
    "zhipu": ZhipuDialect,
    "glm": ZhipuDialect,
    "groq": GroqDialect,
    "openrouter": OpenRouterDialect,
    "xai": XAIDialect,
    "grok": XAIDialect,
    "mistral": MistralDialect,
    "together": TogetherDialect,
    "siliconflow": SiliconFlowDialect,
    "minimax": MiniMaxDialect,
    "azure": AzureOpenAIDialect,
    "azure_openai": AzureOpenAIDialect,
    "fireworks": FireworksDialect,
    "novita": NovitaDialect,
    "perplexity": PerplexityDialect,
    "volcengine": VolcengineDialect,
    "doubao": VolcengineDialect,
    "baichuan": BaichuanDialect,
    "lingyi": LingyiDialect,
    "yi": LingyiDialect,
    "stepfun": StepFunDialect,
    "step": StepFunDialect,
    "infini": InfiniDialect,
    "nvidia": NvidiaNimDialect,
    "nim": NvidiaNimDialect,
    "cohere": CohereDialect,
}


def resolve_dialect(name: str, lane: HttpLane) -> Dialect:
    key = (name or "openai_compat").strip().lower()
    cls = DIALECTS.get(key)
    if not cls:
        raise ValueError(f"unknown dialect: {name}")
    return cls(lane)
