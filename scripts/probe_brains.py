# -*- coding: utf-8 -*-
"""Probe live LLM endpoints. Keys stay local, never printed."""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(r"D:\AetherPackBot\scripts\probe_brains_result.json")


def load_sources():
    cfg = json.loads(
        Path(r"C:\Users\asus\.astrbot\data\cmd_config.json").read_text(encoding="utf-8-sig")
    )
    sources = {}
    for s in cfg.get("provider_sources", []):
        keys = s.get("key") or []
        sources[s["id"]] = {
            "base": (s.get("api_base") or "").rstrip("/"),
            "key": keys[0] if keys else "",
            "enable": s.get("enable", True),
        }
    models = []
    for p in cfg.get("provider", []):
        models.append(
            {
                "id": p.get("id"),
                "src": p.get("provider_source_id"),
                "model": p.get("model"),
                "enable": p.get("enable", True),
            }
        )
    return sources, models


def http_json(method, url, headers=None, body=None, timeout=25):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", "replace")
            parsed = None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            return {
                "ok": True,
                "status": resp.status,
                "ms": int((time.time() - t0) * 1000),
                "json": parsed,
                "text": text[:400],
            }
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        return {
            "ok": False,
            "status": e.code,
            "ms": int((time.time() - t0) * 1000),
            "text": raw[:500],
        }
    except Exception as e:
        return {
            "ok": False,
            "status": 0,
            "ms": int((time.time() - t0) * 1000),
            "text": f"{type(e).__name__}: {e}",
        }


def openai_headers(key):
    h = {"Accept": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def list_models(base, key):
    return http_json("GET", f"{base}/models", headers=openai_headers(key), timeout=20)


def chat(base, key, model, timeout=40):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
        "max_tokens": 16,
        "temperature": 0,
    }
    r = http_json(
        "POST",
        f"{base}/chat/completions",
        headers=openai_headers(key),
        body=body,
        timeout=timeout,
    )
    content = ""
    if r.get("json") and isinstance(r["json"], dict):
        try:
            content = r["json"]["choices"][0]["message"]["content"] or ""
        except Exception:
            content = ""
    r["content"] = content[:80]
    r.pop("json", None)
    return r


def probe_official_no_key():
    cases = [
        ("openai_official", "GET", "https://api.openai.com/v1/models", {"Authorization": "Bearer none"}),
        ("anthropic_official", "GET", "https://api.anthropic.com/v1/models", {"x-api-key": "none", "anthropic-version": "2023-06-01"}),
        ("gemini_official", "GET", "https://generativelanguage.googleapis.com/v1beta/models?key=none", None),
        ("deepseek_official", "GET", "https://api.deepseek.com/v1/models", {"Authorization": "Bearer none"}),
        ("moonshot_official", "GET", "https://api.moonshot.cn/v1/models", {"Authorization": "Bearer none"}),
        ("dashscope_official", "GET", "https://dashscope.aliyuncs.com/compatible-mode/v1/models", {"Authorization": "Bearer none"}),
        ("zhipu_official", "GET", "https://open.bigmodel.cn/api/paas/v4/models", {"Authorization": "Bearer none"}),
        ("groq_official", "GET", "https://api.groq.com/openai/v1/models", {"Authorization": "Bearer none"}),
        ("openrouter_official", "GET", "https://openrouter.ai/api/v1/models", {"Authorization": "Bearer none"}),
        ("xai_official", "GET", "https://api.x.ai/v1/models", {"Authorization": "Bearer none"}),
        ("mistral_official", "GET", "https://api.mistral.ai/v1/models", {"Authorization": "Bearer none"}),
        ("together_official", "GET", "https://api.together.xyz/v1/models", {"Authorization": "Bearer none"}),
        ("ollama_local", "GET", "http://127.0.0.1:11434/api/tags", None),
        ("siliconflow", "GET", "https://api.siliconflow.cn/v1/models", {"Authorization": "Bearer none"}),
        ("minimax", "GET", "https://api.minimax.chat/v1/models", {"Authorization": "Bearer none"}),
    ]
    out = []
    for name, method, url, headers in cases:
        r = http_json(method, url, headers=headers or {}, timeout=12)
        out.append(
            {
                "name": name,
                "url": url,
                "ok": r["ok"],
                "status": r["status"],
                "ms": r["ms"],
                "text": r.get("text", "")[:180],
            }
        )
        print(f"OFFICIAL {name} status={r['status']} ok={r['ok']} ms={r['ms']}")
    return out


def main():
    sources, models = load_sources()
    result = {"sources": {}, "models": [], "official": []}

    for sid, s in sources.items():
        print(f"LIST {sid} {s['base']}")
        r = list_models(s["base"], s["key"])
        names = []
        if r.get("json") and isinstance(r["json"], dict):
            data = r["json"].get("data") or []
            names = [m.get("id") for m in data if isinstance(m, dict)][:30]
        result["sources"][sid] = {
            "base": s["base"],
            "list_ok": r["ok"],
            "status": r["status"],
            "ms": r["ms"],
            "model_count": len(names),
            "sample": names[:12],
            "err": None if r["ok"] else r.get("text", "")[:200],
        }
        print(f"  status={r['status']} count={len(names)} sample={names[:6]}")

    for m in models:
        src = sources.get(m["src"])
        if not src:
            row = {"id": m["id"], "ok": False, "err": "missing source"}
            result["models"].append(row)
            print("CHAT skip", m["id"])
            continue
        print(f"CHAT {m['id']}")
        r = chat(src["base"], src["key"], m["model"])
        row = {
            "id": m["id"],
            "model": m["model"],
            "src": m["src"],
            "ok": bool(r.get("ok") and r.get("content")),
            "status": r.get("status"),
            "ms": r.get("ms"),
            "content": r.get("content", ""),
            "err": None if r.get("ok") else r.get("text", "")[:220],
        }
        result["models"].append(row)
        print(f"  status={row['status']} ok={row['ok']} ms={row['ms']} content={row['content']!r}")

    result["official"] = probe_official_no_key()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
