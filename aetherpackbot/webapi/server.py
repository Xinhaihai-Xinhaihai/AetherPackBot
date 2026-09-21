"""
Web Server - Quart-based async web server.

Provides REST API endpoints and serves the dashboard static files.
"""

from __future__ import annotations

import asyncio
import secrets
from functools import wraps
from pathlib import Path
from typing import Any, TYPE_CHECKING

import jwt
from quart import Quart, jsonify, request, send_from_directory, Response
from quart_cors import cors

from aetherpackbot.kernel.logging import get_logger

if TYPE_CHECKING:
    from aetherpackbot.kernel.container import ServiceContainer

logger = get_logger("webapi")


class WebServer:
    """
    Async web server based on Quart.
    
    Provides:
    - REST API for bot management
    - JWT-based authentication
    - Static file serving for dashboard
    - WebSocket endpoints for real-time updates
    """
    
    def __init__(
        self,
        container: ServiceContainer,
        webui_dir: str | None = None,
    ) -> None:
        self._container = container
        self._webui_dir = webui_dir
        
        self._app: Quart | None = None
        self._server_task: asyncio.Task | None = None
        
        # Auth settings
        self._jwt_secret = secrets.token_hex(32)
        self._admin_username = "aetherpackbot"
        self._admin_password = "aetherpackbot"
    
    async def start(self) -> None:
        """Start the web server."""
        from aetherpackbot.storage.config import ConfigurationManager
        
        try:
            config_manager = await self._container.resolve(ConfigurationManager)
            web_config = config_manager.web
            
            self._admin_username = web_config.admin_username
            self._admin_password = web_config.admin_password
            
            if web_config.jwt_secret:
                self._jwt_secret = web_config.jwt_secret
            
            host = web_config.host
            port = web_config.port
        except Exception:
            host = "0.0.0.0"
            port = 7619
        
        # Create Quart app
        self._app = Quart(
            __name__,
            static_folder=None,
        )
        
        # Enable CORS
        self._app = cors(self._app, allow_origin="*")
        
        # Register routes
        self._register_routes()
        
        # Start server
        self._server_task = asyncio.create_task(
            self._app.run_task(host=host, port=port)
        )
        
        logger.info(f"Web server started on http://{host}:{port}")
    
    async def stop(self) -> None:
        """Stop the web server."""
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Web server stopped")
    
    def _register_routes(self) -> None:
        """Register all API routes."""
        app = self._app
        if not app:
            return
        
        # Auth middleware
        def require_auth(f):
            @wraps(f)
            async def decorated(*args, **kwargs):
                token = request.headers.get("Authorization", "").replace("Bearer ", "")
                if not self._verify_token(token):
                    return jsonify({"error": "Unauthorized"}), 401
                return await f(*args, **kwargs)
            return decorated
        
        # Health check
        @app.route("/health")
        async def health():
            return jsonify({"status": "ok", "version": "1.0.0"})
        
        # Auth endpoints
        @app.route("/api/auth/login", methods=["POST"])
        async def login():
            data = await request.get_json()
            username = data.get("username", "")
            password = data.get("password", "")
            
            if username == self._admin_username and password == self._admin_password:
                token = self._create_token(username)
                return jsonify({"token": token, "username": username})
            
            return jsonify({"error": "Invalid credentials"}), 401
        
        @app.route("/api/auth/verify", methods=["GET"])
        @require_auth
        async def verify():
            return jsonify({"valid": True})
        
        # Status endpoints
        @app.route("/api/status")
        @require_auth
        async def get_status():
            from aetherpackbot.platforms.manager import PlatformManager
            from aetherpackbot.providers.manager import ProviderManager
            from aetherpackbot.plugins.manager import PluginManager
            
            status = {
                "platforms": {},
                "providers": [],
                "plugins": [],
            }
            
            try:
                platform_manager = await self._container.resolve(PlatformManager)
                raw = platform_manager.get_status()
                status["platforms"] = {
                    key: bool(value.get("running")) if isinstance(value, dict) else bool(value)
                    for key, value in raw.items()
                }
            except Exception:
                pass
            
            try:
                provider_manager = await self._container.resolve(ProviderManager)
                status["providers"] = provider_manager.list_provider_ids()
            except Exception:
                pass
            
            try:
                plugin_manager = await self._container.resolve(PluginManager)
                status["plugins"] = [
                    {
                        "name": p.name,
                        "version": p.metadata.version,
                        "status": p.status.name,
                    }
                    for p in plugin_manager.get_all_plugins()
                ]
            except Exception:
                pass
            
            return jsonify(status)
        
        # Config endpoints
        @app.route("/api/config", methods=["GET"])
        @require_auth
        async def get_config():
            from aetherpackbot.storage.config import ConfigurationManager
            
            try:
                config_manager = await self._container.resolve(ConfigurationManager)
                return jsonify(config_manager.to_dict())
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        @app.route("/api/config", methods=["PUT"])
        @require_auth
        async def update_config():
            from aetherpackbot.storage.config import ConfigurationManager
            
            try:
                config_manager = await self._container.resolve(ConfigurationManager)
                data = await request.get_json()
                
                for key, value in data.items():
                    config_manager.set(key, value)
                
                await config_manager.save()
                return jsonify({"success": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        # Brain / provider endpoints
        @app.route("/api/providers")
        @require_auth
        async def list_providers():
            from aetherpackbot.providers.manager import ProviderManager
            try:
                provider_manager = await self._container.resolve(ProviderManager)
                return jsonify(provider_manager.snapshots())
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/brains")
        @require_auth
        async def list_brains():
            from aetherpackbot.providers.manager import ProviderManager
            try:
                provider_manager = await self._container.resolve(ProviderManager)
                return jsonify(provider_manager.snapshots())
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/brains/dialects")
        @require_auth
        async def list_dialects():
            from aetherpackbot.providers.dialects import DIALECTS
            names = sorted(set(cls.name for cls in DIALECTS.values()))
            return jsonify({"dialects": names, "aliases": sorted(DIALECTS.keys())})

        @app.route("/api/brains/pulse", methods=["POST"])
        @require_auth
        async def pulse_brains():
            from aetherpackbot.providers.manager import ProviderManager
            try:
                provider_manager = await self._container.resolve(ProviderManager)
                pulses = await provider_manager.router.pulse_all()
                return jsonify({
                    pid: {
                        "ok": p.ok,
                        "status": p.status,
                        "latency_ms": p.latency_ms,
                        "lane": p.lane,
                        "hint": p.hint,
                    }
                    for pid, p in pulses.items()
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/brains/<provider_id>/config", methods=["GET", "PUT"])
        @require_auth
        async def brain_config(provider_id: str):
            from aetherpackbot.storage.config import ConfigurationManager
            from aetherpackbot.providers.manager import ProviderManager
            try:
                provider_manager = await self._container.resolve(ProviderManager)
                config_manager = await self._container.resolve(ConfigurationManager)
                node = provider_manager.get(provider_id)
                if not node:
                    return jsonify({"error": "provider not found"}), 404
                if request.method == "GET":
                    return jsonify(node.snapshot())
                data = await request.get_json() or {}
                snap = provider_manager.apply_capabilities(provider_id, data)
                providers = list(config_manager.get("providers") or [])
                for item in providers:
                    if item.get("id") == provider_id:
                        caps = snap.get("capabilities") or {}
                        item["capabilities"] = caps
                        for key in ("temperature", "enable_tools", "enable_vision", "enable_text", "max_tokens"):
                            if key in caps:
                                item[key] = caps[key]
                        break
                config_manager.set("providers", providers)
                await config_manager.save()
                return jsonify(snap)
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/mcp")
        @require_auth
        async def list_mcp():
            from aetherpackbot.mcp.client import McpManager
            try:
                mcp = await self._container.resolve(McpManager)
                return jsonify(mcp.snapshots())
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/mcp", methods=["POST"])
        @require_auth
        async def add_mcp():
            from aetherpackbot.mcp.client import McpManager
            from aetherpackbot.storage.config import ConfigurationManager
            try:
                mcp = await self._container.resolve(McpManager)
                config_manager = await self._container.resolve(ConfigurationManager)
                data = await request.get_json() or {}
                servers = list(config_manager.get("mcp.servers") or [])
                sid = str(data.get("id") or f"mcp_{len(servers)+1}")
                data["id"] = sid
                found = False
                for i, item in enumerate(servers):
                    if item.get("id") == sid:
                        servers[i] = data
                        found = True
                        break
                if not found:
                    servers.append(data)
                config_manager.set("mcp.servers", servers)
                await config_manager.save()
                await mcp.apply_config(servers)
                session = mcp.sessions.get(sid)
                return jsonify(session.snapshot() if session else data), 201
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/mcp/<server_id>", methods=["DELETE"])
        @require_auth
        async def delete_mcp(server_id: str):
            from aetherpackbot.mcp.client import McpManager
            from aetherpackbot.storage.config import ConfigurationManager
            try:
                mcp = await self._container.resolve(McpManager)
                config_manager = await self._container.resolve(ConfigurationManager)
                servers = [s for s in (config_manager.get("mcp.servers") or []) if s.get("id") != server_id]
                config_manager.set("mcp.servers", servers)
                await config_manager.save()
                await mcp.apply_config(servers)
                return jsonify({"success": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/mcp/<server_id>/bind", methods=["PUT"])
        @require_auth
        async def bind_mcp(server_id: str):
            from aetherpackbot.mcp.client import McpManager
            try:
                mcp = await self._container.resolve(McpManager)
                data = await request.get_json() or {}
                models = data.get("bind_models") or data.get("models") or []
                if isinstance(models, str):
                    models = [models]
                session = await mcp.bind_models(server_id, models)
                return jsonify(session.snapshot())
            except KeyError:
                return jsonify({"error": "mcp server not found"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/brains/chat", methods=["POST"])
        @require_auth
        async def brain_chat():
            from aetherpackbot.protocols.providers import LLMMessage, LLMRequest
            from aetherpackbot.providers.manager import ProviderManager
            try:
                data = await request.get_json() or {}
                provider_manager = await self._container.resolve(ProviderManager)
                text = data.get("prompt") or data.get("text") or ""
                if not text:
                    return jsonify({"error": "prompt required"}), 400
                req = LLMRequest(
                    messages=[LLMMessage(role="user", content=text)],
                    model=data.get("model"),
                    temperature=float(data.get("temperature") or 0.7),
                    max_tokens=data.get("max_tokens"),
                )
                resp = await provider_manager.router.chat(req, data.get("provider_id"))
                return jsonify({
                    "content": resp.content,
                    "model": resp.model,
                    "usage": resp.usage,
                    "finish_reason": resp.finish_reason,
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        # Platform endpoints
        @app.route("/api/platforms")
        @require_auth
        async def list_platforms():
            from aetherpackbot.platforms.manager import PlatformManager
            
            try:
                platform_manager = await self._container.resolve(PlatformManager)
                return jsonify(platform_manager.list_snapshots())
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/platforms", methods=["POST"])
        @require_auth
        async def add_platform():
            from aetherpackbot.platforms.manager import PlatformManager
            try:
                platform_manager = await self._container.resolve(PlatformManager)
                data = await request.get_json() or {}
                snap = await platform_manager.add_platform(data)
                return jsonify(snap), 201
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/platforms/<platform_id>/start", methods=["POST"])
        @require_auth
        async def start_platform(platform_id: str):
            from aetherpackbot.platforms.manager import PlatformManager
            try:
                platform_manager = await self._container.resolve(PlatformManager)
                return jsonify(await platform_manager.start_platform(platform_id))
            except KeyError:
                return jsonify({"error": "platform not found"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/platforms/<platform_id>/stop", methods=["POST"])
        @require_auth
        async def stop_platform(platform_id: str):
            from aetherpackbot.platforms.manager import PlatformManager
            try:
                platform_manager = await self._container.resolve(PlatformManager)
                return jsonify(await platform_manager.stop_platform(platform_id))
            except KeyError:
                return jsonify({"error": "platform not found"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/platforms/<platform_id>", methods=["DELETE"])
        @require_auth
        async def delete_platform(platform_id: str):
            from aetherpackbot.platforms.manager import PlatformManager
            try:
                platform_manager = await self._container.resolve(PlatformManager)
                await platform_manager.delete_platform(platform_id)
                return jsonify({"success": True})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        # Plugin endpoints
        @app.route("/api/plugins")
        @require_auth
        async def list_plugins():
            from aetherpackbot.plugins.manager import PluginManager
            
            try:
                plugin_manager = await self._container.resolve(PluginManager)
                plugins = []
                
                for p in plugin_manager.get_all_plugins():
                    plugins.append({
                        "name": p.name,
                        "version": p.metadata.version,
                        "author": p.metadata.author,
                        "description": p.metadata.description,
                        "status": p.status.name,
                        "is_builtin": p.is_builtin,
                    })
                
                return jsonify(plugins)
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        @app.route("/api/plugins/<plugin_name>/reload", methods=["POST"])
        @require_auth
        async def reload_plugin(plugin_name: str):
            from aetherpackbot.plugins.manager import PluginManager
            
            try:
                plugin_manager = await self._container.resolve(PluginManager)
                success = await plugin_manager.reload_plugin(plugin_name)
                
                if success:
                    return jsonify({"success": True})
                return jsonify({"error": "Plugin not found"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/plugins/<plugin_name>", methods=["DELETE"])
        @require_auth
        async def uninstall_plugin(plugin_name: str):
            from aetherpackbot.plugins.manager import PluginManager
            try:
                plugin_manager = await self._container.resolve(PluginManager)
                ok = await plugin_manager.uninstall_plugin(plugin_name)
                if ok:
                    return jsonify({"success": True})
                return jsonify({"error": "Plugin not found"}), 404
            except PermissionError as e:
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        # Tools endpoints
        @app.route("/api/tools")
        @require_auth
        async def list_tools():
            from aetherpackbot.agents.orchestrator import AgentOrchestrator
            
            try:
                orchestrator = await self._container.resolve(AgentOrchestrator)
                tools = []
                
                for tool in orchestrator.get_all_tools():
                    tools.append({
                        "name": tool.name,
                        "description": tool.description,
                        "enabled": tool.enabled,
                        "parameters": [
                            {
                                "name": p.name,
                                "type": p.type,
                                "description": p.description,
                                "required": p.required,
                            }
                            for p in tool.parameters
                        ],
                    })
                
                return jsonify(tools)
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        # Logs endpoint
        @app.route("/api/logs")
        @require_auth
        async def get_logs():
            from aetherpackbot.kernel.logging import get_log_manager
            
            try:
                count = request.args.get("count", 100, type=int)
                log_manager = get_log_manager()
                logs = log_manager.broker.get_recent(count)
                
                return jsonify([
                    {
                        "timestamp": log.timestamp.isoformat(),
                        "level": log.level,
                        "logger": log.logger_name,
                        "message": log.message,
                    }
                    for log in logs
                ])
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        # Static files (dashboard)
        @app.route("/")
        @app.route("/<path:path>")
        async def serve_static(path: str = "index.html"):
            static_dir = self._get_static_dir()
            if not static_dir:
                # Return a simple status page when dashboard is not built
                return Response(
                    self._get_fallback_html(),
                    content_type="text/html; charset=utf-8",
                )
            
            file_path = static_dir / path
            
            if file_path.is_file():
                return await send_from_directory(str(static_dir), path)
            
            # Fallback to index.html for SPA routing
            if (static_dir / "index.html").exists():
                return await send_from_directory(str(static_dir), "index.html")
            
            return jsonify({"error": "Not found"}), 404
    
    def _get_static_dir(self) -> Path | None:
        """Get the static files directory."""
        if self._webui_dir:
            path = Path(self._webui_dir)
            if path.exists():
                return path
        
        # Check data/dist first, then the dashboard build output
        for candidate in (Path("data/dist"), Path("dashboard/dist")):
            if (candidate / "index.html").exists():
                return candidate
        
        return None
    
    def _get_fallback_html(self) -> str:
        """Get fallback HTML when dashboard is not built."""
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AetherPackBot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .card {
            background: white;
            border-radius: 16px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
        }
        .logo {
            width: 64px;
            height: 64px;
            background: linear-gradient(135deg, #3b82f6, #1d4ed8);
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 24px;
        }
        .logo span { color: white; font-size: 32px; font-weight: bold; }
        h1 { text-align: center; color: #1f2937; margin-bottom: 8px; }
        .subtitle { text-align: center; color: #6b7280; margin-bottom: 32px; }
        .status { 
            background: #ecfdf5; 
            border: 1px solid #a7f3d0;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 24px;
        }
        .status-title { 
            color: #065f46; 
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-title::before {
            content: '';
            width: 8px;
            height: 8px;
            background: #10b981;
            border-radius: 50%;
        }
        .info {
            background: #f3f4f6;
            border-radius: 8px;
            padding: 16px;
        }
        .info p { color: #4b5563; font-size: 14px; line-height: 1.6; }
        .code {
            background: #1f2937;
            color: #10b981;
            padding: 12px 16px;
            border-radius: 6px;
            font-family: monospace;
            font-size: 13px;
            margin-top: 12px;
            overflow-x: auto;
        }
        .api-info {
            margin-top: 24px;
            padding-top: 24px;
            border-top: 1px solid #e5e7eb;
        }
        .api-info h3 { color: #374151; font-size: 14px; margin-bottom: 12px; }
        .endpoint {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 0;
            font-size: 13px;
        }
        .method {
            background: #dbeafe;
            color: #1d4ed8;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
            font-size: 11px;
        }
        .path { color: #6b7280; font-family: monospace; }
    </style>
</head>
<body>
    <div class="card">
        <div class="logo"><span>A</span></div>
        <h1>AetherPackBot</h1>
        <p class="subtitle">v1.0.0 - LLM Chatbot Framework</p>
        
        <div class="status">
            <div class="status-title">服务运行中</div>
        </div>
        
        <div class="info">
            <p>Dashboard 尚未构建。请运行以下命令构建前端：</p>
            <div class="code">cd dashboard && npm install && npm run build</div>
            <p style="margin-top: 12px;">构建完成后，将 dist 目录复制到 data/dist</p>
        </div>
        
        <div class="api-info">
            <h3>API 端点</h3>
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="path">/health</span>
            </div>
            <div class="endpoint">
                <span class="method">POST</span>
                <span class="path">/api/auth/login</span>
            </div>
            <div class="endpoint">
                <span class="method">GET</span>
                <span class="path">/api/status</span>
            </div>
        </div>
    </div>
</body>
</html>"""
    
    def _create_token(self, username: str) -> str:
        """Create a JWT token."""
        import time
        
        payload = {
            "sub": username,
            "iat": int(time.time()),
            "exp": int(time.time()) + 86400 * 7,  # 7 days
        }
        
        return jwt.encode(payload, self._jwt_secret, algorithm="HS256")
    
    def _verify_token(self, token: str) -> bool:
        """Verify a JWT token."""
        if not token:
            return False
        
        try:
            jwt.decode(token, self._jwt_secret, algorithms=["HS256"])
            return True
        except jwt.PyJWTError:
            return False
