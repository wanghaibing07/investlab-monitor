"""Loopback-only read-only dashboard; no ledger mutation endpoints."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
import sqlite3
from urllib.parse import urlsplit
from .core import PACKAGE, canonical, connection
from .service import latest


def handler(home, *, public_demo=False, public_hostname=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            self.send_error(405, "Read only")

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
                if route == "/health/live": payload = {"status": "UP"}
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


def serve(home, port=8765, *, public_demo=False):
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
    server = ThreadingHTTPServer((bind_host, port), handler(home, public_demo=public_demo, public_hostname=public_hostname))
    print(f"看板：{bind_host}:{server.server_port}（只读；{'虚构公网演示' if public_demo else '本地'}）", flush=True)
    try: server.serve_forever()
    finally: server.server_close()
