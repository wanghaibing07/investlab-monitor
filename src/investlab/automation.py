"""Private, append-only daily research scheduler for the Vercel Hobby plan.

Cron computes on a restored, temporary copy of confirmed account state. A scheduled
run NEVER updates the account's state/ snapshots. Claims use Vercel Blob's atomic
allow_overwrite=False create, and retries have a separate bounded claim.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import json
import os
from pathlib import Path
import smtplib
import sys
import tempfile
from zoneinfo import ZoneInfo

from . import cloud


def nyse_session(utc_time=None):
    """At 00:00 UTC on Tue-Sat the completed US session is NY's local date."""
    from .core import ENGINE
    now = utc_time or datetime.now(timezone.utc)
    ny_day = now.astimezone(ZoneInfo("America/New_York")).date()
    sys.path.insert(0, str(ENGINE))
    try:
        import monitor
        return ny_day.isoformat() if monitor.is_regular_session(ny_day) else None
    finally:
        sys.path.pop(0)


async def _claim(session, attempt, account_version):
    """Durable single-winner claim for a given NYSE session and attempt."""
    from vercel.blob import put_blob
    if attempt not in ("primary", "retry"):
        raise ValueError("Unknown scheduled attempt")
    generation = hashlib.sha256(str(account_version).encode()).hexdigest()[:24]
    path = f"schedule-claims/{session}-{generation}-{attempt}.json"
    data = json.dumps({"session": session, "attempt": attempt,
                       "claimed_at": cloud.now()}, sort_keys=True).encode()
    try:
        await put_blob(path, data, access="private", add_random_suffix=False,
                       allow_overwrite=False, content_type="application/json")
        return True
    except Exception:
        # Never pretend a Blob authorization/network fault is a duplicate claim.
        names = {obj.pathname for obj in await cloud._list("schedule-claims/")}
        if path in names:
            return False
        raise


async def _last_receipt():
    return await cloud.latest_json("scheduled-receipts")


def _synthetic_free_result(session, source_state, computed_state, calculated, attempt):
    return {"status": "SUCCEEDED", "scheduled_session": session,
            "attempt": attempt, "started_at": cloud.now(),
            "account_state_version": source_state, "computed_version": computed_state,
            "qualified_online": calculated["qualified_online"],
            "audit": calculated["audit"],
            "research_verification": calculated["research_verification"],
            "review_id": calculated["review_id"],
            "trading_enabled": False}


async def _persist_receipt(report):
    """Reports are append-only, and scheduling receipt exists only after runs log."""
    report["completed_at"] = cloud.now()
    report_path = await cloud.save_private_report(report)
    # Distinct schedule journal cannot be hidden by a later manual run.
    await cloud._write("scheduled-receipts", json.dumps({
        **report, "report_version": report_path
    }, sort_keys=True).encode(), "json")
    return report


def _run_sync(home):
    return cloud._compute(home)


async def execute_once(attempt="primary", *, current_session=None):
    """Run one scheduled attempt, preserving live portfolio state/ unchanged."""
    session = current_session if current_session is not None else nyse_session()
    if session is None:
        return {"status": "SKIPPED_CLOSED_SESSION", "trading_enabled": False}
    if attempt not in ("primary", "retry"):
        raise ValueError("Unknown scheduled attempt")
    account = await cloud.read_private_account()
    source_version = account.get("state_version") or "no-confirmed-account"
    previous = await _last_receipt()
    if previous and previous.get("scheduled_session") == session and \
            previous.get("status") == "SUCCEEDED" and \
            previous.get("account_state_version") == source_version:
        return {"status": "ALREADY_VERIFIED", "scheduled_session": session,
                "trading_enabled": False}

    claimed = await _claim(session, attempt, source_version)
    if not claimed:
        return {"status": "DUPLICATE_SUPPRESSED", "scheduled_session": session,
                "trading_enabled": False}
    report = {"status": "RUNNING", "scheduled_session": session,
              "attempt": attempt, "started_at": cloud.now(), "trading_enabled": False}
    try:
        if account.get("account_initialized") is not True:
            raise ValueError("Missing confirmed private account")
        source_version = account["state_version"]
        with tempfile.TemporaryDirectory(prefix="investlab-scheduled-") as temp:
            home = Path(temp) / "private"
            if not await cloud.load_private_home(home, expected_version=source_version):
                raise ValueError("Missing original private snapshot")
            result = await asyncio.to_thread(_run_sync, home)
            # A concurrent valuation update never gets overwritten by cron.
            latest = await cloud._list("state/")
            versions = sorted(x.pathname for x in latest if x.pathname.endswith(".zip"))
            if not versions or versions[-1] != source_version:
                raise ValueError("Account snapshot changed; scheduled result not published")
            calculated_archive = await asyncio.to_thread(cloud._make_archive, home)
            calc_version = await cloud._write("computed", calculated_archive, "zip")
        report.update(_synthetic_free_result(
            session, source_version, calc_version, result, attempt))
        report["started_at"] = report.get("started_at", cloud.now())
    except Exception as exc:
        report.update(status="FAILED", issue_code="SCHEDULED_RESEARCH_FAILED",
                      failure_type=type(exc).__name__, qualified_online=False)
    try:
        return await _persist_receipt(report)
    except Exception as exc:
        return {"status": "FAILED", "scheduled_session": session, "attempt": attempt,
                "issue_code": "SCHEDULED_RECEIPT_PERSIST_FAILED",
                "failure_type": type(exc).__name__, "trading_enabled": False}


def _send_failure_email(report):
    """Optional private SMTP delivery; never report success without a send."""
    keys = ("INVESTLAB_SMTP_HOST", "INVESTLAB_SMTP_USER",
            "INVESTLAB_SMTP_PASSWORD", "INVESTLAB_ALERT_TO")
    if not all(os.environ.get(k) for k in keys):
        return "NOT_CONFIGURED"
    host = os.environ["INVESTLAB_SMTP_HOST"]
    user = os.environ["INVESTLAB_SMTP_USER"]
    password = os.environ["INVESTLAB_SMTP_PASSWORD"]
    receiver = os.environ["INVESTLAB_ALERT_TO"]
    port = int(os.environ.get("INVESTLAB_SMTP_PORT", "465"))
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = receiver
    msg["Subject"] = "InvestLab 每日监控失败"
    msg.set_content(
        "InvestLab 未能生成今日合格监控报告。\n"
        f"美股交易日：{report.get('scheduled_session','unknown')}\n"
        f"失败类型：{report.get('issue_code','MISSING_RECEIPT')}\n"
        "请在已登录的 InvestLab 查看运行报告。系统未自动下单。\n")
    with smtplib.SMTP_SSL(host, port, timeout=12) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    return "SENT"


async def daily_primary():
    return await execute_once("primary")


async def daily_watchdog():
    """Independent later invocation retries once and alerts on final failure."""
    session = nyse_session()
    if session is None:
        return {"status": "SKIPPED_CLOSED_SESSION", "trading_enabled": False}
    try:
        receipt = await _last_receipt()
        account = await cloud.read_private_account()
        if receipt and receipt.get("scheduled_session") == session and \
                receipt.get("status") == "SUCCEEDED" and \
                receipt.get("account_state_version") == account.get("state_version"):
            return {"status": "VERIFIED", "scheduled_session": session,
                    "trading_enabled": False}
        result = await execute_once("retry", current_session=session)
    except Exception as exc:
        result = {"status": "FAILED", "scheduled_session": session,
                  "issue_code": "WATCHDOG_OR_STORAGE_FAILED",
                  "failure_type": type(exc).__name__, "trading_enabled": False}
    if result.get("status") in ("SUCCEEDED", "ALREADY_VERIFIED", "DUPLICATE_SUPPRESSED"):
        return result
    try:
        email_status = await asyncio.to_thread(_send_failure_email, result)
    except Exception:
        email_status = "DELIVERY_FAILED"
    # Do not claim alert is sent if SMTP is missing or failed.
    result["alert_delivery"] = email_status
    return result
