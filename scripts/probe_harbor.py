# -*- coding: utf-8 -*-
"""Probe Harbor berths: OneBot protocol sides + public IM gates.

OneBot sides from GitHub:
  NapCatQQ, SnowLuma, LLOneBot/LuckyLilliaBot, Lagrange.Core, go-cqhttp
Local scan on common HTTP/WS ports, then public IM HTTP ping.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(r"D:\AetherPackBot")
sys.path.insert(0, str(ROOT))

from aetherpackbot.harbor.berth import BERTHS, resolve_berth  # noqa: E402
from aetherpackbot.harbor.wire import DockLane, TideCall, join_url  # noqa: E402
from aetherpackbot.protocols.providers import LLMMessage, LLMRequest, ProviderConfig, ProviderType  # noqa: E402
from aetherpackbot.providers.cortex import CortexNode  # noqa: E402
from aetherpackbot.providers.dialects import classify_lane, resolve_dialect  # noqa: E402
from aetherpackbot.providers.wire import HttpLane  # noqa: E402

OUT = ROOT / "scripts" / "probe_harbor_result.json"

ONEBOT_PORTS = [
    3000, 3001, 3008, 3080, 5700, 5701, 5800, 5890, 6099, 6199,
    6700, 6701, 8080, 8081, 8088, 6090, 16530, 16531, 2536, 5140,
    6098, 30000, 58100, 4243, 6555, 1869, 6091,
]

ONEBOT_ACTIONS = [
    "get_login_info",
    "get_version_info",
    "get_status",
    "get_friend_list",
    "get_group_list",
]


def load_cfg() -> dict:
    return json.loads((ROOT / "data" / "config" / "config.json").read_text(encoding="utf-8"))


def weixin_creds() -> dict:
    astr = Path(r"C:\Users\asus\.astrbot\data\cmd_config.json")
    cfg = json.loads(astr.read_text(encoding="utf-8-sig"))
    p = (cfg.get("platform") or [{}])[0]
    return {
        "base_url": p.get("weixin_oc_base_url") or "https://ilinkai.weixin.qq.com",
        "token": p.get("weixin_oc_token") or "",
        "sync_buf": p.get("weixin_oc_sync_buf") or "",
        "account_id": p.get("weixin_oc_account_id") or "",
        "context_tokens": p.get("weixin_oc_context_tokens") or {},
    }


def tcp_open(host: str, port: int, timeout: float = 0.25) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


async def probe_onebot_http(lane: DockLane, base: str) -> dict:
    out = {"base": base, "actions": {}}
    for action in ONEBOT_ACTIONS:
        t0 = time.time()
        try:
            reply = await lane.request(
                TideCall(
                    method="POST",
                    url=join_url(base, action),
                    headers={"Content-Type": "application/json"},
                    json_body={},
                    timeout=4.0,
                )
            )
            body = reply.json if isinstance(reply.json, dict) else {}
            out["actions"][action] = {
                "http": reply.status,
                "ms": int((time.time() - t0) * 1000),
                "status": body.get("status"),
                "retcode": body.get("retcode"),
                "hint": str(body.get("data") or body.get("message") or reply.text)[:160],
            }
        except Exception as e:
            out["actions"][action] = {"http": 0, "ms": int((time.time() - t0) * 1000), "err": f"{type(e).__name__}: {e}"[:160]}
    return out


async def probe_onebot_ws(lane: DockLane, url: str) -> dict:
    t0 = time.time()
    try:
        await lane.open()
        async with lane.session.ws_connect(url, heartbeat=8, timeout=4) as ws:
            msg = await asyncio.wait_for(ws.receive(), timeout=4)
            data = msg.data
            if isinstance(data, bytes):
                data = data.decode("utf-8", "replace")
            parsed = None
            try:
                parsed = json.loads(data) if isinstance(data, str) else None
            except Exception:
                parsed = None
            await ws.send_json({"action": "get_login_info", "params": {}, "echo": "harbor-tide"})
            try:
                reply = await asyncio.wait_for(ws.receive(), timeout=4)
                rdata = reply.data
            except Exception:
                rdata = None
            return {
                "ok": True,
                "ms": int((time.time() - t0) * 1000),
                "first": str(parsed or data)[:180],
                "reply": str(rdata)[:180],
            }
    except Exception as e:
        return {"ok": False, "ms": int((time.time() - t0) * 1000), "err": f"{type(e).__name__}: {e}"[:180]}


async def scan_local_onebot(lane: DockLane) -> dict:
    open_ports = [p for p in ONEBOT_PORTS if tcp_open("127.0.0.1", p)]
    http_hits = []
    ws_hits = []
    for p in open_ports:
        for base in (f"http://127.0.0.1:{p}", f"http://127.0.0.1:{p}/"):
            hit = await probe_onebot_http(lane, base.rstrip("/"))
            acts = hit.get("actions") or {}
            useful = any(
                (v.get("http") in (200, 401, 403)) or ("retcode" in v)
                for v in acts.values()
            )
            if useful:
                http_hits.append(hit)
                break
        for wsurl in (f"ws://127.0.0.1:{p}/", f"ws://127.0.0.1:{p}/event"):
            ws = await probe_onebot_ws(lane, wsurl)
            if ws.get("ok"):
                ws["url"] = wsurl
                ws_hits.append(ws)
                break
    return {"open_ports": open_ports, "http": http_hits, "ws": ws_hits}


async def probe_public_im(lane: DockLane) -> list[dict]:
    cases = [
        ("telegram", "GET", "https://api.telegram.org/bot0/getMe", None, None),
        ("discord", "GET", "https://discord.com/api/v10/gateway", None, None),
        ("facebook_graph", "GET", "https://graph.facebook.com/v21.0/me?access_token=none", None, None),
        ("instagram_graph", "GET", "https://graph.facebook.com/v21.0/me?access_token=none&fields=id,username", None, None),
        ("line", "GET", "https://api.line.me/v2/bot/info", {"Authorization": "Bearer none"}, None),
        ("slack", "GET", "https://slack.com/api/auth.test", None, {"token": "none"}),
        ("kook", "GET", "https://www.kookapp.cn/api/v3/gateway/index", {"Authorization": "Bot none"}, None),
        ("lark", "POST", "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", None, {"app_id": "none", "app_secret": "none"}),
        ("dingtalk", "GET", "https://oapi.dingtalk.com/gettoken?appkey=none&appsecret=none", None, None),
        ("qq_official_token", "POST", "https://bots.qq.com/app/getAppAccessToken", None, {"appId": "none", "clientSecret": "none"}),
        ("weixin_ilink_qr", "POST", "https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode", {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token"}, {"base_info": {"channel_version": "aetherpack"}}),
        ("onebot_spec_doc", "GET", "https://raw.githubusercontent.com/botuniverse/onebot-11/master/README.md", None, None),
        ("napcat_repo", "GET", "https://api.github.com/repos/NapNeko/NapCatQQ", {"User-Agent": "AetherPackBot-Harbor/1.0", "Accept": "application/vnd.github+json"}, None),
        ("snowluma_repo", "GET", "https://api.github.com/repos/SnowLuma/SnowLuma", {"User-Agent": "AetherPackBot-Harbor/1.0", "Accept": "application/vnd.github+json"}, None),
        ("llonebot_repo", "GET", "https://api.github.com/repos/LLOneBot/LuckyLilliaBot", {"User-Agent": "AetherPackBot-Harbor/1.0", "Accept": "application/vnd.github+json"}, None),
        ("lagrange_repo", "GET", "https://api.github.com/repos/LagrangeDev/Lagrange.Core", {"User-Agent": "AetherPackBot-Harbor/1.0", "Accept": "application/vnd.github+json"}, None),
        ("gocq_repo", "GET", "https://api.github.com/repos/Mrs4s/go-cqhttp", {"User-Agent": "AetherPackBot-Harbor/1.0", "Accept": "application/vnd.github+json"}, None),
    ]
    out = []
    for name, method, url, headers, body in cases:
        t0 = time.time()
        try:
            reply = await lane.request(
                TideCall(method=method, url=url, headers=headers or {}, json_body=body, timeout=12.0)
            )
            hint = (reply.text or "")[:160]
            if isinstance(reply.json, dict):
                hint = str({k: reply.json.get(k) for k in list(reply.json)[:6]})[:160]
            out.append({
                "name": name,
                "ok_http": reply.ok,
                "status": reply.status,
                "ms": int((time.time() - t0) * 1000),
                "hint": hint,
                "reachable": reply.status > 0,
            })
        except Exception as e:
            out.append({
                "name": name,
                "ok_http": False,
                "status": 0,
                "ms": int((time.time() - t0) * 1000),
                "hint": f"{type(e).__name__}: {e}"[:160],
                "reachable": False,
            })
    return out


async def probe_weixin(lane: DockLane) -> dict:
    creds = weixin_creds()
    berth = resolve_berth("weixin_ilink")
    call = berth.ping_call(creds, {})
    t0 = time.time()
    try:
        reply = await lane.request(call)
        tide = berth.read_tide(reply, creds)
        return {
            "ok": tide.ok,
            "reachable": tide.reachable,
            "status": tide.status,
            "ms": int((time.time() - t0) * 1000),
            "hint": tide.hint[:180],
            "extra": {k: tide.extra.get(k) for k in ("ret", "errcode", "has_msgs") if k in tide.extra},
            "account": creds.get("account_id"),
            "ping": call.url,
        }
    except Exception as e:
        return {
            "ok": False,
            "reachable": False,
            "status": 0,
            "ms": int((time.time() - t0) * 1000),
            "hint": f"{type(e).__name__}: {e}"[:180],
            "account": creds.get("account_id"),
            "ping": getattr(call, "url", ""),
        }


async def ppo_comment(summary: str) -> dict:
    cfg = load_cfg()
    ppo = next(p for p in cfg["providers"] if p["id"] == "ppo")
    lane = HttpLane()
    await lane.open()
    try:
        node = CortexNode(
            ProviderConfig(
                provider_id="ppo",
                provider_type=ProviderType.LLM,
                provider_name="ppo",
                api_key=ppo["api_key"],
                api_base_url=ppo["api_base_url"],
                model=ppo["model"],
                extra={"timeout": 40, "dialect": "openai_compat"},
            ),
            resolve_dialect("openai_compat"),
            classify_lane(ppo["api_base_url"], "cloud"),
        )
        node._lane = lane  # type: ignore[attr-defined]
        # dialect uses global? check cortex - dialect.chat likely uses own lane
        from aetherpackbot.providers import dialects as dmod
        if hasattr(dmod, "LANE"):
            pass
        resp = await node.chat(
            LLMRequest(
                messages=[LLMMessage(role="user", content="用不超过40字中文总结这段Harbor探测结果，只说通不通：\n" + summary[:1200])],
                max_tokens=128,
                temperature=0,
            )
        )
        return {"ok": bool(resp.content), "content": (resp.content or "")[:200], "model": resp.model}
    except Exception as e:
        return {"ok": False, "content": "", "err": str(e)[:240]}
    finally:
        await lane.close()


async def main() -> None:
    lane = DockLane()
    await lane.open()
    result = {
        "berths": sorted(set(b.name for b in BERTHS.values())),
        "github_protocol_sides": [
            {"name": "NapCatQQ", "repo": "https://github.com/NapNeko/NapCatQQ", "dialect": "onebot-v11"},
            {"name": "SnowLuma", "repo": "https://github.com/SnowLuma/SnowLuma", "dialect": "onebot-v11"},
            {"name": "LuckyLilliaBot/LLOneBot", "repo": "https://github.com/LLOneBot/LuckyLilliaBot", "dialect": "onebot-v11/satori/milky"},
            {"name": "Lagrange.Core", "repo": "https://github.com/LagrangeDev/Lagrange.Core", "dialect": "onebot-v11"},
            {"name": "go-cqhttp", "repo": "https://github.com/Mrs4s/go-cqhttp", "dialect": "onebot-v11"},
        ],
    }
    try:
        result["local_onebot"] = await scan_local_onebot(lane)
        result["public_im"] = await probe_public_im(lane)
        result["weixin"] = await probe_weixin(lane)
    finally:
        await lane.close()

    lines = []
    loc = result["local_onebot"]
    lines.append(f"本机OneBot开端口:{loc.get('open_ports')}")
    lines.append(f"HTTP命中:{len(loc.get('http') or [])} WS命中:{len(loc.get('ws') or [])}")
    wx = result["weixin"]
    lines.append(f"微信ilink ok={wx.get('ok')} status={wx.get('status')} hint={wx.get('hint')}")
    for item in result["public_im"]:
        lines.append(f"{item['name']} http={item['status']} reachable={item['reachable']}")
    result["ppo"] = await ppo_comment("\n".join(lines))
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:8000])


if __name__ == "__main__":
    asyncio.run(main())
