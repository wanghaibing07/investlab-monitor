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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

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
    response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'"
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
            "storage_connected": _configured(), "storage_credentials_only": True,
            "execution_enabled": False,
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
<p><a href="/setup">初始化真实账户（需要管理令牌）</a></p>
<p>接口：<a href="/health">运行健康</a> · <a href="/api/status">私有运行状态</a> ·
<a href="/api/latest">最新私有报告</a></p>
<small>默认无自动下单 · 不会读取 ChatGPT 插件凭据 · 不使用公开 Blob 存储</small></article>
</body></html>"""



@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    """Browser-only setup form: never embed any secret or private holdings in source."""
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>InvestLab · 初始化私有账户</title>
<style>body{background:#101a29;color:#edf3f9;max-width:640px;margin:4vh auto;padding:0 20px;font:16px/1.65 system-ui}
main{background:#19283a;border:1px solid #33475e;border-radius:15px;padding:24px}
label{display:block;margin:14px 0 4px}input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #576a80;border-radius:8px;background:#fff;color:#111}
button{display:block;margin-top:20px;width:100%;padding:14px;background:#80d4cb;border:0;border-radius:9px;font-size:17px;font-weight:700;cursor:pointer}
button:disabled{opacity:.55}p{color:#b9cee1}a{color:#8ed2ed}#result{white-space:pre-wrap;overflow-wrap:anywhere}
.small{font-size:13px;color:#bdd0e2}.check{display:flex;align-items:center;gap:9px}.check input{width:auto}</style></head><body><main>
<h1>初始化私有账户</h1>
<p>请从券商账户核对这一天的人民币估值。这里只记录已确认的估值，不创建交易，不自动下单。</p>
<p id="current">正在检查是否已存在账户…</p>
<form id="setup-form" autocomplete="off">
<label for="day">估值日期</label><input id="day" type="date" required>
<label for="qqq">QQQ 人民币估值（整数元）</label><input id="qqq" type="number" min="0" max="999999999999" step="1" required>
<label for="tqqq">TQQQ 人民币估值（整数元）</label><input id="tqqq" type="number" min="0" max="999999999999" step="1" required>
<label for="qld">QLD 人民币估值（整数元）</label><input id="qld" type="number" min="0" max="999999999999" step="1" required>
<label for="cash">现金人民币估值（整数元）</label><input id="cash" type="number" min="0" max="999999999999" step="1" required>
<label for="note">估值来源说明（5 至 160 字）</label><input id="note" maxlength="160" minlength="5" required placeholder="持有人根据账户明细确认估值">
<label for="token">管理令牌（INVESTLAB_ADMIN_TOKEN）</label>
<input id="token" type="password" required autocomplete="off" spellcheck="false">
<p class="small">令牌仅随此网页的 HTTPS 初始化请求发送，不写入报告、浏览器本地存储或网页地址。请从 Vercel 项目私有环境变量中获取，不要发到聊天中。</p>
<label class="check"><input id="confirmed" type="checkbox" required>我已核实以上金额及日期，确认一次性创建真实账户</label>
<button id="submit" type="submit" disabled>核对并初始化</button></form>
<pre id="result" role="status" aria-live="polite"></pre>
<p><a href="/api/status">查看私有账户状态</a> · <a href="/">返回首页</a></p>
</main><script src="/setup.js" defer></script></body></html>"""


_SETUP_JS = r"""
"use strict";
const $ = id => document.getElementById(id);
const status = $("current"), output = $("result"), button = $("submit");
let initialized = false;
async function refresh() {
  const r = await fetch("/api/status", {cache:"no-store", credentials:"same-origin"});
  const x = await r.json();
  initialized = x.account_initialized === true || x.latest_run_exists === true;
  button.disabled = initialized || x.status !== "SETUP_REQUIRED" || x.storage_verified !== true;
  status.textContent = initialized ? "已存在确认账户，禁止重复初始化。" :
    x.status === "SETUP_REQUIRED" && x.storage_verified === true ?
      "云端已确认暂无账户快照，可以初始化。" :
      "存储状态未通过检查：" + x.status + "。暂不允许写入。";
  return x;
}
refresh().catch(() => { status.textContent="无法检查云端账户状态，写入已阻止。"; });
$("setup-form").addEventListener("submit", async function (event) {
  event.preventDefault();
  if (button.disabled || initialized) return;
  const raw = {};
  for (const key of ["qqq","tqqq","qld","cash"]) {
    const value = $(key).value;
    if (!/^(0|[1-9][0-9]{0,11})$/.test(value)) {
      output.textContent="请输入每项非负整数人民币金额。"; return;
    }
    raw[key.toUpperCase()] = value;
  }
  if (Object.values(raw).reduce((a,b)=>a+Number(b),0) <= 0) {
    output.textContent="资产总额必须大于零。"; return;
  }
  if (!$("confirmed").checked) {
    output.textContent="请先确认估值与日期。"; return;
  }
  const token = $("token").value;
  const payload = {
    as_of:$("day").value, values:raw, note:$("note").value, confirmed:true
  };
  if (!token || !payload.as_of || payload.note.length<5) return;
  button.disabled = true;
  output.textContent="正在安全写入，并重新读取私有 Blob 与 SQLite 核验…";
  try {
    const res = await fetch("/api/initialize", {
      method:"POST", credentials:"same-origin", cache:"no-store",
      headers:{"Content-Type":"application/json", "X-Investlab-Admin-Token":token},
      body:JSON.stringify(payload)
    });
    $("token").value="";
    const data = await res.json();
    if (!res.ok || data.status !== "INITIALIZED" || data.readback?.verified !== true) {
      output.textContent="初始化未验收成功。HTTP "+res.status+"；"+(data.detail||data.status||"未知错误")+
        "。请先刷新账户状态，勿重复提交。"; await refresh(); return;
    }
    const check = data.readback;
    if (check.as_of !== payload.as_of || Object.keys(raw).some(k=>check.values[k]!==raw[k])) {
      output.textContent="写入返回数据与确认估值不一致，禁止继续。";return;
    }
    const fresh = await refresh();
    if (fresh.account_initialized !== true || fresh.storage_verified !== true) {
      output.textContent="写入已返回成功，但独立状态读取未确认；请人工检查。";return;
    }
    output.textContent="持久化验证成功：\n日期 "+check.as_of+
      "\nQQQ ¥"+check.values.QQQ+"，TQQQ ¥"+check.values.TQQQ+
      "，QLD ¥"+check.values.QLD+"，现金 ¥"+check.values.CASH+
      "\n合计 ¥"+check.total_value_cny+
      "\n未创建任何交易；每日自动监控尚未启用。";
  } catch (_) {
    $("token").value="";
    output.textContent="请求或回读失败，请先打开 /api/status 查状态，勿直接重试。";
    try { await refresh(); } catch (_) {}
  } finally { $("token").value=""; }
});
"""

@app.get("/setup.js", response_class=PlainTextResponse)
async def setup_script():
    return PlainTextResponse(_SETUP_JS, media_type="text/javascript", headers={
        "Cache-Control": "private, no-store"
    })


@app.get("/api/status")
async def status():
    if not _configured():
        return JSONResponse({
            "status": "STORAGE_UNAVAILABLE",
            "account_initialized": None,
            "storage_verified": False,
            "latest_run_exists": None,
        }, status_code=503)
    try:
        # A missing run is not evidence that the account is uninitialized.
        # Verify private Blob contents, ZIP checksums and SQLite confirmed valuation.
        account_initialized = await cloud.private_account_verified()
        report = await cloud.latest_json("runs")
        if report is None:
            return {
                "status": "READY_FOR_FIRST_RUN" if account_initialized else "SETUP_REQUIRED",
                "account_initialized": account_initialized,
                "storage_verified": True,
                "latest_run_exists": False,
                "execution_enabled": False,
                "meaning": (
                    "Confirmed private account found; first verified online run pending"
                    if account_initialized else
                    "Private Blob was read successfully; no confirmed account or daily report exists"
                ),
            }
        if not account_initialized:
            return JSONResponse({
                "status": "STATE_INCONSISTENT",
                "account_initialized": False,
                "latest_run_exists": True,
                "storage_verified": True,
                "issue_code": "RUN_REPORT_WITHOUT_CONFIRMED_ACCOUNT",
                "execution_enabled": False,
            }, status_code=503)
        return {
            **report,
            "account_initialized": True,
            "storage_verified": True,
            "latest_run_exists": True,
            "execution_enabled": False,
        }
    except Exception as exc:
        return JSONResponse({
            "status": "STORAGE_ERROR",
            "account_initialized": None,
            "storage_verified": False,
            "error_type": type(exc).__name__,
        }, status_code=503)


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
        readback = await cloud.verify_private_valuation(values, data["as_of"])
        return {"status":"INITIALIZED", "state_version":version,
                "readback":readback,
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
