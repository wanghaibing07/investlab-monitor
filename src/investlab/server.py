"""Loopback dashboard with explicit, CSRF-protected private valuation controls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import hmac
import secrets
import os
import sqlite3
from urllib.parse import urlsplit
from .core import PACKAGE, canonical, connection, lock
from .service import latest
from . import ledger, service


def handler(home, *, public_demo=False, public_hostname=None, local_edit=False, csrf_token=None):
    if local_edit and (public_demo or not csrf_token):
        raise ValueError("Private edit requires explicit local-only mode and a session token")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send_json(self, status, payload):
            body = canonical(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not local_edit or public_demo:
                self.send_error(405, "Read only")
                return
            route = urlsplit(self.path).path
            if route not in ("/api/valuation", "/api/recalculate"):
                self.send_error(404)
                return
            host_header = self.headers.get("Host", "")
            host = host_header.rsplit(":", 1)[0].lower()
            origin = self.headers.get("Origin", "")
            if host not in ("127.0.0.1", "localhost") or origin != "http://" + host_header:
                self.send_json(403, {"error": "本地同源验证失败"})
                return
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                self.send_json(403, {"error": "非同源请求被拒绝"})
                return
            supplied = self.headers.get("X-InvestLab-CSRF", "")
            if not supplied or not hmac.compare_digest(supplied, csrf_token):
                self.send_json(403, {"error": "缺少有效的页面会话令牌"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.send_json(415, {"error": "仅接受JSON"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if size < 2 or size > 8192 or self.headers.get("Transfer-Encoding"):
                self.send_json(413, {"error": "请求大小或传输格式无效"})
                return
            try:
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("请求必须是JSON对象")
                if route == "/api/valuation":
                    if set(data) != {"valuation_id", "account", "as_of", "currency", "values", "confirmed", "note"}:
                        raise ValueError("估值字段不完整或含未知字段")
                    if data["confirmed"] is not True:
                        raise ValueError("请先确认估值来自真实账户记录")
                    with lock(home):
                        result = ledger.valuation(home, data)
                    self.send_json(201, {"status": "SAVED", "valuation_id": data["valuation_id"], "duplicate": result["duplicate"], "trades_created": 0, "recalculate_required": True})
                else:
                    if set(data) != {"online"} or not isinstance(data["online"], bool):
                        raise ValueError("计算请求只接受布尔型online")
                    with lock(home):
                        result = service.run(home, online=data["online"], independent=data["online"])
                    self.send_json(200, {"status": "SUCCEEDED", "demo": service.settings(home)["demo"], "qualified_online": result["qualified_online"], "manual_execution_only": True})
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json(422, {"error": str(exc)})
            except (OSError, sqlite3.Error, RuntimeError, TimeoutError) as exc:
                self.send_json(503, {"error": "计算或保存失败，请在本地终端查看原因", "detail": type(exc).__name__})


        def do_GET(self):
            route = urlsplit(self.path).path
            allowed_hosts = {"localhost", "127.0.0.1", "[::1]"}
            if public_demo and public_hostname:
                allowed_hosts.add(public_hostname.lower())
            host = self.headers.get("Host", "").rsplit(":", 1)[0].lower()
            if host not in allowed_hosts:
                self.send_error(403, "Invalid Host"); return
            try:
                status = 200; kind = "application/json; charset=utf-8"
                if route == "/api/daily-status" and not public_demo:
                    from .daily import current_status
                    payload = current_status(home)
                elif route == "/api/local-session":
                    payload = {"local_edit": bool(local_edit), "read_only": not local_edit,
                               "csrf_token": csrf_token if local_edit else None}
                elif route == "/health/live": payload = {"status": "UP"}
                elif route == "/health/ready":
                    with connection(home, readonly=True) as c: c.execute("SELECT 1 FROM app_schema").fetchone()
                    value = latest(home)
                    ready = bool(value and value["operation"]["status"] == "SUCCEEDED"
                                 and value["latest_attempt"]["status"] == "SUCCEEDED"
                                 and (value["demo"] or value["market_session_current"]))
                    payload = {"status": "READY" if ready else "DEGRADED", "meaning": "APP_READY_NOT_STRATEGY_VALIDATED"}; status = 200 if ready else 503
                elif route == "/api/latest": payload = latest(home)
                elif route == "/api/history":
                    with connection(home, readonly=True) as c:
                        payload = [dict(r) for r in c.execute("SELECT operation_id,started_at,completed_at,command,status FROM operations ORDER BY started_at DESC LIMIT 100")]
                elif route == "/api/research":
                    p = Path(home) / "data/verification.json"
                    payload = json.loads(p.read_text()) if p.exists() else {"status": "NOT_RUN", "comparisons": []}
                elif route == "/api/journal":
                    with connection(home, readonly=True) as c:
                        payload = [json.loads(r[0]) for r in c.execute("SELECT event_json FROM journal_events ORDER BY occurred_at DESC,event_id DESC LIMIT 100")]
                elif route in ("/", "/app.js", "/style.css"):
                    name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[route]
                    payload = (PACKAGE / "web" / name).read_bytes()
                    kind = {"/": "text/html; charset=utf-8", "/app.js": "application/javascript; charset=utf-8", "/style.css": "text/css; charset=utf-8"}[route]
                else:
                    self.send_error(404); return
                body = payload if isinstance(payload, bytes) else canonical(payload).encode()
            except (OSError, ValueError, sqlite3.Error):
                status = 503; kind = "application/json"; body = b'{"status":"UNAVAILABLE"}'
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(body)
    return Handler


def serve(home, port=8765, *, public_demo=False, local_edit=False):
    if public_demo and local_edit:
        raise ValueError("Public demo can never enable local account editing")
    if public_demo:
        from .service import settings
        if settings(home).get("demo") is not True:
            raise ValueError("公网部署只允许使用虚构演示账户")
        public_hostname = os.environ.get("INVESTLAB_PUBLIC_HOSTNAME") or os.environ.get("RENDER_EXTERNAL_HOSTNAME")
        if not public_hostname:
            raise ValueError("公网演示缺少外部访问域名")
        if not all(ch.isalnum() or ch in ".-" for ch in public_hostname):
            raise ValueError("外部访问域名格式不正确")
    else:
        public_hostname = None
    bind_host = "0.0.0.0" if public_demo else "127.0.0.1"
    token = secrets.token_urlsafe(32) if local_edit else None
    server = ThreadingHTTPServer((bind_host, port), handler(
        home, public_demo=public_demo, public_hostname=public_hostname,
        local_edit=local_edit, csrf_token=token))
    print(f"看板：{bind_host}:{server.server_port}（{'本地估值编辑' if local_edit else '只读'}；{'虚构公网演示' if public_demo else '本地'}）", flush=True)
    try: server.serve_forever()
    finally: server.server_close()
