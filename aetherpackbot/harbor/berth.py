"""Berth: one IM dialect on the dock lane.

Vendors only describe how they talk. HarborMaster picks a live berth.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from aetherpackbot.harbor.wire import DockLane, HarborWireError, TideCall, TideReply, join_url
from aetherpackbot.kernel.logging import get_logger
from aetherpackbot.protocols.messages import Message, MessageChain, MessageSession
from aetherpackbot.protocols.platforms import (
    BasePlatformAdapter,
    PlatformCapabilities,
    PlatformConfig,
    PlatformStatus,
)

logger = get_logger("harbor.berth")


@dataclass
class Tide:
    ok: bool = False
    reachable: bool = False
    status: int = 0
    latency_ms: int = 0
    hint: str = ""
    checked_at: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class Berth:
    """A vendor dialect that can ping, listen, and send."""

    name = "berth"
    capabilities = PlatformCapabilities()

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        return None

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        hint = (reply.text or "")[:160]
        ok = reply.ok
        return Tide(
            ok=ok,
            reachable=reply.status > 0,
            status=reply.status,
            hint=hint,
            extra={"json": reply.json} if isinstance(reply.json, dict) else {},
        )

    async def send(
        self,
        lane: DockLane,
        creds: dict[str, Any],
        settings: dict[str, Any],
        session: MessageSession,
        chain: MessageChain,
        reply_to: str | None = None,
    ) -> str | None:
        raise NotImplementedError

    async def listen(
        self,
        lane: DockLane,
        creds: dict[str, Any],
        settings: dict[str, Any],
        on_message: Callable[[Message], Awaitable[None]],
        stop_event,
    ) -> None:
        raise NotImplementedError


class WeixinIlinkBerth(Berth):
    """Personal WeChat via ilink bot HTTP long-poll. Direct HTTP, no SDK."""

    name = "weixin_ilink"
    capabilities = PlatformCapabilities(
        supports_text=True,
        supports_images=True,
        supports_audio=True,
        supports_video=True,
        supports_files=True,
        max_message_length=4000,
    )

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall:
        base = (creds.get("base_url") or "https://ilinkai.weixin.qq.com").rstrip("/")
        token = creds.get("token") or ""
        ctx_map = creds.get("context_tokens") or {}
        user_id = next(iter(ctx_map.keys()), "") if isinstance(ctx_map, dict) else ""
        context_token = (ctx_map.get(user_id) if isinstance(ctx_map, dict) else "") or ""
        # getupdates is a long-poll; ping uses getconfig so the tide returns immediately.
        if user_id and context_token:
            return TideCall(
                method="POST",
                url=join_url(base, "ilink/bot/getconfig"),
                headers={
                    "Content-Type": "application/json",
                    "AuthorizationType": "ilink_bot_token",
                    "Authorization": f"Bearer {token}",
                },
                json_body={
                    "ilink_user_id": user_id,
                    "context_token": context_token,
                    "base_info": {"channel_version": "aetherpack"},
                },
                timeout=12.0,
            )
        return TideCall(
            method="POST",
            url=join_url(base, "ilink/bot/get_bot_qrcode"),
            headers={
                "Content-Type": "application/json",
                "AuthorizationType": "ilink_bot_token",
                "Authorization": f"Bearer {token}",
            },
            json_body={"base_info": {"channel_version": "aetherpack"}},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ret = int(body.get("ret") or 0)
        errcode = int(body.get("errcode") or 0)
        errmsg = str(body.get("errmsg") or "")
        ok = reply.ok and ret == 0 and errcode == 0
        hint = errmsg or ((reply.text or "")[:160])
        extra = {"ret": ret, "errcode": errcode, "has_msgs": bool(body.get("msgs"))}
        if body.get("get_updates_buf"):
            extra["sync_buf"] = str(body.get("get_updates_buf"))
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra=extra)

    async def send(
        self,
        lane: DockLane,
        creds: dict[str, Any],
        settings: dict[str, Any],
        session: MessageSession,
        chain: MessageChain,
        reply_to: str | None = None,
    ) -> str | None:
        import uuid

        base = (creds.get("base_url") or "https://ilinkai.weixin.qq.com").rstrip("/")
        token = creds.get("token") or ""
        user_id = session.user_id or session.session_id
        ctx_map = creds.get("context_tokens") or {}
        context_token = ctx_map.get(user_id) or session.extra.get("context_token") or ""
        if not token or not context_token:
            raise HarborWireError("weixin_ilink missing token or context_token")
        text = chain.plain_text
        reply = await lane.request(
            TideCall(
                method="POST",
                url=join_url(base, "ilink/bot/sendmessage"),
                headers={
                    "Content-Type": "application/json",
                    "AuthorizationType": "ilink_bot_token",
                    "Authorization": f"Bearer {token}",
                },
                json_body={
                    "base_info": {"channel_version": "aetherpack"},
                    "msg": {
                        "from_user_id": "",
                        "to_user_id": user_id,
                        "client_id": uuid.uuid4().hex,
                        "message_type": 2,
                        "message_state": 2,
                        "context_token": context_token,
                        "item_list": [{"type": 1, "text_item": {"text": text}}],
                    },
                },
                timeout=30.0,
            )
        )
        body = reply.json if isinstance(reply.json, dict) else {}
        if not reply.ok or int(body.get("ret") or 0) != 0:
            raise HarborWireError(
                f"weixin send failed {reply.status} {body.get('errmsg') or reply.text[:160]}",
                reply.status,
                reply.text,
            )
        return str(body.get("msg_id") or body.get("message_id") or "")


class OneBotBerth(Berth):
    """OneBot v11 reverse/forward. NapCat / SnowLuna speak this dialect."""

    name = "onebot"
    capabilities = PlatformCapabilities(
        supports_text=True,
        supports_images=True,
        supports_audio=True,
        supports_files=True,
        supports_mentions=True,
        max_message_length=4500,
    )

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        http = (creds.get("http_url") or settings.get("http_url") or "").rstrip("/")
        token = creds.get("access_token") or creds.get("token") or ""
        if not http:
            return None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return TideCall(
            method="POST",
            url=join_url(http, "get_login_info"),
            headers=headers,
            json_body={},
            timeout=8.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        status = str(body.get("status") or "")
        ok = reply.ok and (status in ("ok", "success") or body.get("retcode") == 0 or "user_id" in (body.get("data") or {}))
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        hint = f"qq={data.get('user_id') or ''} nick={data.get('nickname') or ''}".strip() or (reply.text or "")[:160]
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra={"data": data})

    async def send(
        self,
        lane: DockLane,
        creds: dict[str, Any],
        settings: dict[str, Any],
        session: MessageSession,
        chain: MessageChain,
        reply_to: str | None = None,
    ) -> str | None:
        http = (creds.get("http_url") or settings.get("http_url") or "").rstrip("/")
        token = creds.get("access_token") or creds.get("token") or ""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload: dict[str, Any] = {"message": chain.plain_text}
        if session.is_group:
            payload["group_id"] = int(session.group_id or 0)
            action = "send_group_msg"
        else:
            payload["user_id"] = int(session.user_id or 0)
            action = "send_private_msg"
        reply = await lane.request(
            TideCall(
                method="POST",
                url=join_url(http, action),
                headers=headers,
                json_body=payload,
                timeout=15.0,
            )
        )
        body = reply.json if isinstance(reply.json, dict) else {}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        if not reply.ok:
            raise HarborWireError(f"onebot send {reply.status} {reply.text[:160]}", reply.status, reply.text)
        return str(data.get("message_id") or "")


class TelegramBerth(Berth):
    name = "telegram"
    capabilities = PlatformCapabilities(
        supports_text=True,
        supports_images=True,
        supports_audio=True,
        supports_files=True,
        supports_mentions=True,
        max_message_length=4096,
    )

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        token = creds.get("bot_token") or creds.get("token") or ""
        if not token:
            return None
        api = (creds.get("api_base") or "https://api.telegram.org").rstrip("/")
        return TideCall(method="GET", url=f"{api}/bot{token}/getMe", timeout=12.0)

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and bool(body.get("ok"))
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        hint = f"@{result.get('username') or ''} id={result.get('id') or ''}".strip() or str(body.get("description") or reply.text[:160])
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra={"result": result})

    async def send(
        self,
        lane: DockLane,
        creds: dict[str, Any],
        settings: dict[str, Any],
        session: MessageSession,
        chain: MessageChain,
        reply_to: str | None = None,
    ) -> str | None:
        token = creds.get("bot_token") or creds.get("token") or ""
        api = (creds.get("api_base") or "https://api.telegram.org").rstrip("/")
        chat_id = session.group_id if session.is_group else session.user_id
        body_in: dict[str, Any] = {"chat_id": chat_id, "text": chain.plain_text}
        if reply_to:
            body_in["reply_to_message_id"] = int(reply_to)
        reply = await lane.request(
            TideCall(
                method="POST",
                url=f"{api}/bot{token}/sendMessage",
                json_body=body_in,
                timeout=20.0,
            )
        )
        body = reply.json if isinstance(reply.json, dict) else {}
        if not (reply.ok and body.get("ok")):
            raise HarborWireError(f"telegram send {reply.status} {reply.text[:160]}", reply.status, reply.text)
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        return str(result.get("message_id") or "")


class DiscordBerth(Berth):
    name = "discord"
    capabilities = PlatformCapabilities(
        supports_text=True,
        supports_images=True,
        supports_files=True,
        supports_mentions=True,
        max_message_length=2000,
    )

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        token = creds.get("bot_token") or creds.get("token") or ""
        if not token:
            return None
        api = (creds.get("api_base") or "https://discord.com/api/v10").rstrip("/")
        return TideCall(
            method="GET",
            url=f"{api}/users/@me",
            headers={"Authorization": f"Bot {token}"},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and bool(body.get("id"))
        hint = f"{body.get('username') or ''}#{body.get('discriminator') or ''} id={body.get('id') or ''}".strip() or (reply.text or "")[:160]
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra={"user": body if ok else {}})

    async def send(
        self,
        lane: DockLane,
        creds: dict[str, Any],
        settings: dict[str, Any],
        session: MessageSession,
        chain: MessageChain,
        reply_to: str | None = None,
    ) -> str | None:
        token = creds.get("bot_token") or creds.get("token") or ""
        api = (creds.get("api_base") or "https://discord.com/api/v10").rstrip("/")
        channel_id = session.group_id or session.user_id
        reply = await lane.request(
            TideCall(
                method="POST",
                url=f"{api}/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json_body={"content": chain.plain_text},
                timeout=20.0,
            )
        )
        body = reply.json if isinstance(reply.json, dict) else {}
        if not reply.ok:
            raise HarborWireError(f"discord send {reply.status} {reply.text[:160]}", reply.status, reply.text)
        return str(body.get("id") or "")


class QQOfficialBerth(Berth):
    name = "qq_official"
    capabilities = PlatformCapabilities(
        supports_text=True,
        supports_images=True,
        supports_mentions=True,
        max_message_length=2000,
    )

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        app_id = creds.get("app_id") or creds.get("appid") or ""
        secret = creds.get("secret") or creds.get("client_secret") or creds.get("app_secret") or ""
        if not app_id or not secret:
            return None
        api = (creds.get("api_base") or "https://bots.qq.com").rstrip("/")
        sandbox = bool(creds.get("sandbox") or settings.get("sandbox"))
        token_host = "https://bots.qq.com"
        return TideCall(
            method="POST",
            url=f"{token_host}/app/getAppAccessToken",
            json_body={"appId": str(app_id), "clientSecret": str(secret)},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        token = body.get("access_token") or ""
        ok = reply.ok and bool(token)
        hint = "token ok" if ok else (str(body.get("message") or body.get("msg") or reply.text[:160]))
        extra = {"access_token": token, "expires_in": body.get("expires_in")} if token else body
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra=extra)


class FacebookBerth(Berth):
    name = "facebook"
    capabilities = PlatformCapabilities(supports_text=True, supports_images=True, max_message_length=2000)

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        token = creds.get("page_token") or creds.get("access_token") or creds.get("token") or ""
        if not token:
            return None
        api = (creds.get("api_base") or "https://graph.facebook.com/v21.0").rstrip("/")
        return TideCall(method="GET", url=f"{api}/me", params={"access_token": token, "fields": "id,name"}, timeout=12.0)

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and bool(body.get("id"))
        hint = f"{body.get('name') or ''} id={body.get('id') or ''}".strip() or str((body.get("error") or {}).get("message") or reply.text[:160])
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra=body if isinstance(body, dict) else {})


class InstagramBerth(Berth):
    name = "instagram"
    capabilities = PlatformCapabilities(supports_text=True, supports_images=True, max_message_length=1000)

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        token = creds.get("access_token") or creds.get("page_token") or creds.get("token") or ""
        if not token:
            return None
        api = (creds.get("api_base") or "https://graph.facebook.com/v21.0").rstrip("/")
        ig_id = creds.get("ig_user_id") or "me"
        return TideCall(
            method="GET",
            url=f"{api}/{ig_id}",
            params={"access_token": token, "fields": "id,username"},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and bool(body.get("id"))
        hint = f"@{body.get('username') or ''} id={body.get('id') or ''}".strip() or str((body.get("error") or {}).get("message") or reply.text[:160])
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra=body if isinstance(body, dict) else {})


class LineBerth(Berth):
    name = "line"
    capabilities = PlatformCapabilities(supports_text=True, supports_images=True, max_message_length=5000)

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        token = creds.get("channel_access_token") or creds.get("token") or ""
        if not token:
            return None
        return TideCall(
            method="GET",
            url="https://api.line.me/v2/bot/info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and bool(body.get("userId") or body.get("displayName"))
        hint = f"{body.get('displayName') or ''} id={body.get('userId') or ''}".strip() or (reply.text or "")[:160]
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra=body if isinstance(body, dict) else {})


class SlackBerth(Berth):
    name = "slack"
    capabilities = PlatformCapabilities(supports_text=True, supports_images=True, max_message_length=4000)

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        token = creds.get("bot_token") or creds.get("token") or ""
        if not token:
            return None
        return TideCall(
            method="POST",
            url="https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and bool(body.get("ok"))
        hint = f"{body.get('user') or ''} team={body.get('team') or ''}".strip() or str(body.get("error") or reply.text[:160])
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra=body if isinstance(body, dict) else {})


class KookBerth(Berth):
    name = "kook"
    capabilities = PlatformCapabilities(supports_text=True, supports_images=True, max_message_length=8000)

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        token = creds.get("token") or creds.get("bot_token") or ""
        if not token:
            return None
        return TideCall(
            method="GET",
            url="https://www.kookapp.cn/api/v3/user/me",
            headers={"Authorization": f"Bot {token}"},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        ok = reply.ok and int(body.get("code") or 1) == 0
        hint = f"{data.get('username') or ''} id={data.get('id') or ''}".strip() or str(body.get("message") or reply.text[:160])
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra=data)


class LarkBerth(Berth):
    name = "lark"
    capabilities = PlatformCapabilities(supports_text=True, supports_images=True, max_message_length=4000)

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        app_id = creds.get("app_id") or ""
        secret = creds.get("app_secret") or creds.get("secret") or ""
        if not app_id or not secret:
            return None
        return TideCall(
            method="POST",
            url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json_body={"app_id": app_id, "app_secret": secret},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and int(body.get("code") or 1) == 0 and bool(body.get("tenant_access_token"))
        hint = "token ok" if ok else str(body.get("msg") or reply.text[:160])
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra={"code": body.get("code")})


class DingTalkBerth(Berth):
    name = "dingtalk"
    capabilities = PlatformCapabilities(supports_text=True, max_message_length=2000)

    def ping_call(self, creds: dict[str, Any], settings: dict[str, Any]) -> TideCall | None:
        app_key = creds.get("app_key") or creds.get("app_id") or ""
        secret = creds.get("app_secret") or creds.get("secret") or ""
        if not app_key or not secret:
            return None
        return TideCall(
            method="GET",
            url="https://oapi.dingtalk.com/gettoken",
            params={"appkey": app_key, "appsecret": secret},
            timeout=12.0,
        )

    def read_tide(self, reply: TideReply, creds: dict[str, Any]) -> Tide:
        body = reply.json if isinstance(reply.json, dict) else {}
        ok = reply.ok and int(body.get("errcode") or 1) == 0 and bool(body.get("access_token"))
        hint = "token ok" if ok else str(body.get("errmsg") or reply.text[:160])
        return Tide(ok=ok, reachable=reply.status > 0, status=reply.status, hint=hint, extra={"errcode": body.get("errcode")})


BERTHS: dict[str, Berth] = {
    "weixin_ilink": WeixinIlinkBerth(),
    "weixin_oc": WeixinIlinkBerth(),
    "onebot": OneBotBerth(),
    "aiocqhttp": OneBotBerth(),
    "napcat": OneBotBerth(),
    "snowluna": OneBotBerth(),
    "snowluma": OneBotBerth(),
    "llonebot": OneBotBerth(),
    "lagrange": OneBotBerth(),
    "gocqhttp": OneBotBerth(),
    "telegram": TelegramBerth(),
    "discord": DiscordBerth(),
    "qq_official": QQOfficialBerth(),
    "qqofficial": QQOfficialBerth(),
    "facebook": FacebookBerth(),
    "instagram": InstagramBerth(),
    "line": LineBerth(),
    "slack": SlackBerth(),
    "kook": KookBerth(),
    "lark": LarkBerth(),
    "feishu": LarkBerth(),
    "dingtalk": DingTalkBerth(),
}


def resolve_berth(kind: str) -> Berth:
    key = (kind or "").strip().lower()
    if key not in BERTHS:
        raise ValueError(f"unknown berth: {kind}")
    return BERTHS[key]
