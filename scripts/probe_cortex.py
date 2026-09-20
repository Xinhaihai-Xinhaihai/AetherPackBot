# -*- coding: utf-8 -*-
"""Exercise the new brain layer against live gates."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(r"D:\AetherPackBot")
sys.path.insert(0, str(ROOT))

from aetherpackbot.protocols.providers import LLMMessage, LLMRequest, ProviderConfig, ProviderType
from aetherpackbot.providers.cortex import CortexNode
from aetherpackbot.providers.dialects import DIALECTS, classify_lane, resolve_dialect
from aetherpackbot.providers.wire import HttpLane

OUT = ROOT / "scripts" / "probe_cortex_result.json"


def cfg():
    return json.loads((ROOT / "data" / "config" / "config.json").read_text(encoding="utf-8"))


async def ping_node(node: CortexNode) -> dict:
    pulse = await node.beat()
    chat = {"ok": False, "content": "", "ms": 0, "err": None}
    if node.lane_kind == "local" and not pulse.ok:
        return {
            "id": node.provider_id,
            "dialect": node.dialect_name,
            "lane": node.lane_kind,
            "pulse": pulse.__dict__,
            "chat": {"ok": False, "err": "local gate down, skipped chat"},
        }
    try:
        import time
        t0 = time.time()
        resp = await node.chat(
            LLMRequest(
                messages=[LLMMessage(role="user", content="Reply with exactly: PONG")],
                max_tokens=128,
                temperature=0,
            )
        )
        chat = {
            "ok": bool(resp.content),
            "content": (resp.content or "")[:80],
            "ms": int((time.time() - t0) * 1000),
            "model": resp.model,
            "err": None,
        }
    except Exception as e:
        chat = {"ok": False, "content": "", "ms": 0, "err": str(e)[:240]}
    return {
        "id": node.provider_id,
        "dialect": node.dialect_name,
        "lane": node.lane_kind,
        "pulse": {
            "ok": pulse.ok,
            "status": pulse.status,
            "latency_ms": pulse.latency_ms,
            "hint": pulse.hint[:160],
        },
        "chat": chat,
        "score": round(node.score(), 2),
    }


async def probe_official(lane: HttpLane) -> list[dict]:
    from aetherpackbot.providers.wire import WireCall

    cases = [
        ("openai_official", "https://api.openai.com/v1/models"),
        ("anthropic", "https://api.anthropic.com/v1/models"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/models?key=none"),
        ("deepseek", "https://api.deepseek.com/v1/models"),
        ("moonshot", "https://api.moonshot.cn/v1/models"),
        ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1/models"),
        ("zhipu", "https://open.bigmodel.cn/api/paas/v4/models"),
        ("groq", "https://api.groq.com/openai/v1/models"),
        ("openrouter", "https://openrouter.ai/api/v1/models"),
        ("xai", "https://api.x.ai/v1/models"),
        ("mistral", "https://api.mistral.ai/v1/models"),
        ("together", "https://api.together.xyz/v1/models"),
        ("siliconflow", "https://api.siliconflow.cn/v1/models"),
        ("minimax", "https://api.minimax.chat/v1/models"),
        ("fireworks", "https://api.fireworks.ai/inference/v1/models"),
        ("novita", "https://api.novita.ai/v3/openai/models"),
        ("perplexity", "https://api.perplexity.ai/models"),
        ("volcengine", "https://ark.cn-beijing.volces.com/api/v3/models"),
        ("stepfun", "https://api.stepfun.com/v1/models"),
        ("nvidia", "https://integrate.api.nvidia.com/v1/models"),
        ("cohere", "https://api.cohere.ai/v2/models"),
        ("ollama_local", "http://127.0.0.1:11434/api/tags"),
    ]
    out = []
    for name, url in cases:
        headers = {"Accept": "application/json"}
        if name == "anthropic":
            headers["x-api-key"] = "none"
            headers["anthropic-version"] = "2023-06-01"
        elif name not in {"gemini", "ollama_local"}:
            headers["Authorization"] = "Bearer none"
        try:
            reply = await lane.request(WireCall("GET", url, headers=headers, timeout=10))
            out.append(
                {
                    "name": name,
                    "url": url,
                    "reachable": reply.status != 0,
                    "status": reply.status,
                    "ok": reply.ok,
                    "auth_needed": reply.status in (401, 403, 400),
                    "hint": (reply.text or "")[:140],
                }
            )
        except Exception as e:
            out.append(
                {
                    "name": name,
                    "url": url,
                    "reachable": False,
                    "status": 0,
                    "ok": False,
                    "auth_needed": False,
                    "hint": str(e)[:140],
                }
            )
        print(f"OFFICIAL {name} status={out[-1]['status']} reachable={out[-1]['reachable']}")
    return out


async def main():
    lane = HttpLane()
    await lane.open()
    result = {
        "dialects": sorted(set(c.name for c in DIALECTS.values())),
        "aliases": sorted(DIALECTS.keys()),
        "configured": [],
        "official": [],
        "lanes": {
            "http://127.0.0.1:11434/v1": classify_lane("http://127.0.0.1:11434/v1"),
            "http://192.168.1.8:8000/v1": classify_lane("http://192.168.1.8:8000/v1"),
            "https://api.openai.com/v1": classify_lane("https://api.openai.com/v1"),
        },
    }

    bot = cfg()
    for item in bot.get("providers", []):
        dialect = resolve_dialect(item.get("type") or "openai_compat", lane)
        node = CortexNode(
            ProviderConfig(
                provider_id=item["id"],
                provider_type=ProviderType.LLM,
                provider_name=item.get("name") or item["id"],
                api_key=item.get("api_key") or "",
                api_base_url=item.get("api_base_url"),
                model=item.get("model") or "",
                extra={"timeout": item.get("timeout", 60)},
            ),
            dialect,
            item.get("lane") or classify_lane(item.get("api_base_url")),
        )
        print(f"NODE {node.provider_id} dialect={node.dialect_name} lane={node.lane_kind}")
        row = await ping_node(node)
        result["configured"].append(row)
        print(f"  pulse={row['pulse']['ok']} chat={row['chat']['ok']} err={row['chat'].get('err')}")

    result["official"] = await probe_official(lane)
    await lane.close()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT)


if __name__ == "__main__":
    asyncio.run(main())
