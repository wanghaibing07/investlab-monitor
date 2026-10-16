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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

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
    response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
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


UI_ROOT = Path(__file__).resolve().parent / "assets"
app.mount("/assets", StaticFiles(directory=UI_ROOT), name="assets")


@app.get("/", include_in_schema=False)
@app.get("/setup", include_in_schema=False)
async def dashboard():
    """Human-readable private investment workspace; raw JSON remains API only."""
    return FileResponse(UI_ROOT / "index.html", media_type="text/html")


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



@app.get("/api/account")
async def private_account():
    """Read current confirmed valuation; protected by Vercel Authentication."""
    if not _configured():
        raise HTTPException(503, "Private Blob storage unavailable")
    try:
        return await cloud.read_private_account()
    except Exception as exc:
        return JSONResponse({"status":"STORAGE_ERROR",
                             "error_type":type(exc).__name__},status_code=503)


async def _confirmed_valuation(request: Request, *, update=False):
    # Vercel Authentication protects all project routes, including write APIs.
    # An additional user-entered administrator secret is deliberately not used.
    _private_origin(request)
    if not _configured():
        raise HTTPException(503, "Private Blob storage unavailable")
    if int(request.headers.get("content-length", "0")) > 8192:
        raise HTTPException(413, "Maximum request size exceeded")
    try:
        raw = await request.body()
        if len(raw) > 8192:
            raise HTTPException(413, "Maximum request size exceeded")
        data = json.loads(raw)
        expected = {"as_of", "values", "note", "confirmed"}
        if update:
            expected.add("expected_state_version")
        if not isinstance(data,dict) or set(data) != expected:
            raise ValueError("Unexpected valuation fields")
        if data["confirmed"] is not True:
            raise ValueError("Explicit confirmed valuation required")
        if not isinstance(data["as_of"],str) or date.fromisoformat(data["as_of"]) > date.today():
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
        if update:
            version = data["expected_state_version"]
            if not isinstance(version,str) or not re.fullmatch(
                r"state/[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}\.zip", version
            ):
                raise ValueError("Missing or invalid previous account state version")
        return data
    except HTTPException:
        raise
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(422,str(exc)) from None


@app.post("/api/initialize")
async def initialize(request: Request):
    data = await _confirmed_valuation(request)
    try:
        version = await cloud.initialize_private_account(
            data["values"], data["as_of"], data["note"]
        )
        readback = await cloud.verify_private_valuation(data["values"],data["as_of"])
        return {"status":"INITIALIZED", "state_version":version,
                "readback":readback,"order_sent":False,
                "next_step":"Independent online quote verification"}
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None
    except Exception as exc:
        raise HTTPException(503, "Initialization unavailable: "+type(exc).__name__) from None


@app.post("/api/valuation")
async def append_valuation(request: Request):
    data = await _confirmed_valuation(request,update=True)
    try:
        version = await cloud.append_private_valuation(
            data["values"],data["as_of"],data["note"],
            data["expected_state_version"]
        )
        readback = await cloud.verify_private_valuation(data["values"],data["as_of"])
        return {"status":"UPDATED","state_version":version,
                "readback":readback,"order_sent":False,
                "next_step":"Daily verification pending"}
    except ValueError as exc:
        # Missing/stale state, or out-of-order dated valuation.
        raise HTTPException(409,str(exc)) from None
    except Exception as exc:
        raise HTTPException(503, "Valuation update unavailable: "+type(exc).__name__) from None


@app.post("/api/run")
async def manual_run(request: Request):
    """Explicit, read-only investment monitor run from the protected browser."""
    _private_origin(request)
    if not _configured():
        raise HTTPException(503, "Private storage unavailable")
    try:
        if int(request.headers.get("content-length", "0")) > 1024:
            raise HTTPException(413, "Maximum request size exceeded")
        raw = await request.body()
        if len(raw) > 1024:
            raise HTTPException(413, "Maximum request size exceeded")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"confirmed", "expected_state_version"}:
            raise ValueError("Unexpected run request fields")
        if payload["confirmed"] is not True:
            raise ValueError("Explicit confirmation required")
        version = payload["expected_state_version"]
        if not isinstance(version, str) or not re.fullmatch(
            r"state/[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}\.zip", version
        ):
            raise ValueError("Invalid private account version")
    except HTTPException:
        raise
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(422, "Invalid manual run request") from None
    try:
        account = await cloud.read_private_account()
    except Exception as exc:
        return JSONResponse({"status": "STORAGE_ERROR",
                             "failure_type": type(exc).__name__}, status_code=503)
    if not account.get("account_initialized"):
        raise HTTPException(409, "Confirm and save an account first")
    if account.get("state_version") != version:
        raise HTTPException(409, "Account changed; refresh before running")
    try:
        result = await cloud.run_private_daily(expected_version=version)
    except Exception as exc:
        return JSONResponse({"status": "FAILED",
                             "failure_type": type(exc).__name__,
                             "trading_enabled": False}, status_code=503)
    return JSONResponse(result, status_code=200 if result.get("status") == "SUCCEEDED" else 503)


@app.get("/api/cron/daily")
async def daily_run(request: Request):
    bearer = request.headers.get("authorization", "")
    secret = bearer[7:] if bearer.startswith("Bearer ") else None
    _require_secret(secret, "CRON_SECRET")
    if not _configured():
        raise HTTPException(503,"Private storage not configured")
    result = await cloud.run_private_daily()
    return JSONResponse(result,status_code=200 if result["status"]=="SUCCEEDED" else 503)
