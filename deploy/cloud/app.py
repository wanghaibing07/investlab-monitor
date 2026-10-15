"""InvestLab private Vercel FastAPI control plane (protected by Vercel Authentication)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import hmac
import json
import os
import re
import tempfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from investlab import cloud, service
from investlab.core import utcnow

app = FastAPI(title="InvestLab private cloud", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    return response


def _configured():
    return bool(os.environ.get("BLOB_READ_WRITE_TOKEN"))


def _require_secret(provided: str | None, env_name: str):
    expected = os.environ.get(env_name, "")
    if not expected or len(expected) < 32:
        raise HTTPException(503, detail="Private administrator setting unavailable")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(401, detail="Unauthorized")
    return True


def _private_origin(request: Request):
    origin = request.headers.get("origin", "")
    host = request.headers.get("host", "")
    if not origin or not host or origin != "https://" + host:
        raise HTTPException(403, detail="Same-origin HTTPS confirmation required")
    if request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}:
        raise HTTPException(403, detail="Cross-origin write rejected")
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
        raise HTTPException(415, detail="JSON only")


@app.get("/health")
async def health():
    return {"service": "InvestLab private cloud", "status": "UP",
            "storage_connected": _configured(), "execution_enabled": False,
            "browser_auth": "VERCEL_AUTH_REQUIRED_AT_PLATFORM"}


@app.get("/", response_class=HTMLResponse)
async def home():
    return """<!doctype html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InvestLab 私有云端监控</title>
<style>body{background:#101a29;color:#edf3f9;max-width:760px;margin:7vh auto;padding:0 22px;font:16px/1.8 system-ui}
article{border:1px solid #33475e;border-radius:16px;padding:26px;background:#19283a}
p{color:#b9cee1}code{background:#24384d;padding:3px 7px;border-radius:5px}
a{color:#8ed2ed}h1{font-size:30px}small{color:#98afc4}</style></head><body>
<article><h1>InvestLab · 私有云端</h1><p>这里与公开的虚构演示完全隔离。Vercel 身份登录负责保护访问。</p>
<p><strong>云端存储已预留；真实账户不会自动导入。</strong> 首次录入需再次通过管理令牌确认。
运行结果只在数据质量与独立验证通过后标记成功。</p>
<p>接口：<a href="/health">运行健康</a> · <a href="/api/status">私有运行状态</a> ·
<a href="/api/latest">最新私有报告</a></p>
<small>默认无自动下单 · 不会读取 ChatGPT 插件凭据 · 不使用公开 Blob 存储</small></article>
</body></html>"""


@app.get("/api/status")
async def status():
    if not _configured():
        return JSONResponse({"status": "STORAGE_UNAVAILABLE", "account_initialized": False},status_code=503)
    try:
        report = await cloud.latest_json("runs")
        return report or {"status":"SETUP_REQUIRED", "account_initialized":False,
                          "meaning":"No private daily run has completed; confirm your account first"}
    except Exception as exc:
        return JSONResponse({"status":"STORAGE_ERROR", "error_type":type(exc).__name__},status_code=503)


@app.get("/api/latest")
async def latest():
    if not _configured():
        raise HTTPException(503,"Private storage unavailable")
    with tempfile.TemporaryDirectory(prefix="investlab-cloud-read-") as tmp:
        home_dir = Path(tmp)/"private"
        if not await cloud.load_private_home(home_dir):
            return JSONResponse({"status":"SETUP_REQUIRED", "account_initialized":False},status_code=404)
        try:
            report = service.latest(home_dir)
            if report is None:
                return JSONResponse({"status":"NEEDS_FIRST_ONLINE_RUN"},status_code=404)
            if report.get("demo") is not False:
                raise RuntimeError("Synthetic data in private account store")
            return report
        except Exception as exc:
            return JSONResponse({"status":"READ_ERROR", "error_type":type(exc).__name__},status_code=503)


@app.post("/api/initialize")
async def initialize(request: Request):
    _private_origin(request)
    _require_secret(request.headers.get("x-investlab-admin-token"), "INVESTLAB_ADMIN_TOKEN")
    if not _configured():
        raise HTTPException(503,"Private Blob storage unavailable")
    if int(request.headers.get("content-length", "0")) > 8192:
        raise HTTPException(413, "Maximum request size exceeded")
    try:
        data = await request.json()
        if not isinstance(data,dict) or set(data) != {"as_of","values","note","confirmed"}:
            raise ValueError("Unexpected account fields")
        if data["confirmed"] is not True:
            raise ValueError("Explicit confirmed valuation required")
        if not isinstance(data["as_of"],str) or date.fromisoformat(data["as_of"])>date.today():
            raise ValueError("Account valuation date is invalid")
        if not isinstance(data["note"],str) or not 5 <= len(data["note"]) <= 160:
            raise ValueError("Provide valuation source note")
        values = data["values"]
        if not isinstance(values,dict) or set(values) != {"QQQ","TQQQ","QLD","CASH"}:
            raise ValueError("Missing QQQ/TQQQ/QLD/CASH CNY valuation")
        if not all(isinstance(v,str) and re.fullmatch(r"\d{1,12}",v) for v in values.values()):
            raise ValueError("CNY valuations must be nonnegative integer strings")
        if sum(int(v) for v in values.values())<=0:
            raise ValueError("Total portfolio valuation must be positive")
        version = await cloud.initialize_private_account(values,data["as_of"],data["note"])
        return {"status":"INITIALIZED", "state_version":version,
                "order_sent":False, "next_step":"Independent online quote verification"}
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    except Exception as exc:
        raise HTTPException(503, "Initialization unavailable: "+type(exc).__name__) from None


@app.get("/api/cron/daily")
async def daily_run(request: Request):
    bearer = request.headers.get("authorization", "")
    secret = bearer[7:] if bearer.startswith("Bearer ") else None
    _require_secret(secret, "CRON_SECRET")
    if not _configured():
        raise HTTPException(503,"Private storage not configured")
    result = await cloud.run_private_daily()
    return JSONResponse(result,status_code=200 if result["status"]=="SUCCEEDED" else 503)
