"""One durable daily observation cycle and failure outbox for a private InvestLab home.

No order endpoints or external communications are called by run_cycle.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
import json
import os
import smtplib
import uuid

from . import service, verification
from .core import atomic, connection, digest, utcnow

STEPS = ("macro", "online", "audit", "verify", "evaluate")
ALERT_STATES = frozenset({"FAILED", "DEGRADED", "INTERRUPTED"})


class DailyGateError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def status_file(home):
    return Path(home) / "data" / "daily-status.json"


def outbox(home):
    return Path(home) / "data" / "daily-alerts"


def record_alert(home, report):
    """Stable event ID prevents duplicate notifications for a stage/day/code."""
    identity = digest({"date": report["started_at"][:10], "stage": report["stage"],
                       "issue_code": report["issue_code"], "status": report["status"]})
    path = outbox(home) / (identity + ".json")
    if not path.exists():
        atomic(path, {"alert_id": identity, "state": "PENDING",
                      "issued_at": utcnow(), "cycle_id": report["cycle_id"],
                      "cycle_date": report["started_at"][:10],
                      "status": report["status"], "stage": report["stage"],
                      "issue_code": report["issue_code"],
                      "delivery_attempts": 0})
    return identity


def run_cycle(home, *, update_macro=True, evaluate=True):
    """Caller owns the shared OS writer lock. Returns without hiding degraded runs."""
    home = Path(home)
    now = utcnow()
    report = {
        "schema_version": 1, "cycle_id": uuid.uuid4().hex, "started_at": now,
        "completed_at": None, "status": "RUNNING", "stage": "preflight",
        "issue_code": None, "steps": {name: "PENDING" for name in STEPS},
        "report_review_id": None, "qualified_online": False,
        "trading_enabled": False, "notification_transport": "LOCAL_OUTBOX"
    }
    atomic(status_file(home), report)
    optional_errors = []
    try:
        if service.settings(home).get("demo") is True:
            raise DailyGateError("SYNTHETIC_DEMO_NOT_ELIGIBLE")
        with connection(home, readonly=True) as conn:
            if not conn.execute("SELECT 1 FROM portfolio_baselines LIMIT 1").fetchone():
                raise DailyGateError("CONFIRMED_ACCOUNT_REQUIRED")

        report["stage"] = "macro"
        if update_macro:
            try:
                service.worker(home, "refresh", timeout=240)
                report["steps"]["macro"] = "SUCCEEDED"
            except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
                report["steps"]["macro"] = "FAILED_OPTIONAL"
                optional_errors.append("MACRO_REFRESH_UNAVAILABLE")
        else:
            report["steps"]["macro"] = "SKIPPED"

        report["stage"] = "online"
        result = service.run(home, online=True, independent=True)
        report["steps"]["online"] = "SUCCEEDED"
        report["report_review_id"] = result["review_id"]
        report["qualified_online"] = bool(result["qualified_online"])
        if not result["qualified_online"]:
            raise DailyGateError("ONLINE_DATA_NOT_QUALIFIED")

        report["stage"] = "audit"
        audit = service.audit(home)
        if audit["status"] != "PASS":
            raise DailyGateError("PERSISTED_AUDIT_NOT_PASS")
        report["steps"]["audit"] = "SUCCEEDED"

        report["stage"] = "verify"
        verified = verification.verify(home)
        if verified.get("status") != "PASS":
            raise DailyGateError("INDEPENDENT_RESEARCH_CHECK_NOT_PASS")
        report["steps"]["verify"] = "SUCCEEDED"
        report["verification_comparisons"] = len(verified.get("comparisons", []))

        report["stage"] = "evaluate"
        if evaluate:
            evaluated = service.worker(home, "evaluate", timeout=300)
            if not isinstance(evaluated, dict):
                raise DailyGateError("FORWARD_EVALUATION_INVALID")
            report["steps"]["evaluate"] = "SUCCEEDED"
            report["forward_evaluation"] = "ATTEMPTED_NOT_AUTOMATIC_PROOF"
        else:
            report["steps"]["evaluate"] = "SKIPPED"

        report["stage"] = "complete"
        if optional_errors:
            report["status"] = "DEGRADED"
            report["issue_code"] = optional_errors[0]
        else:
            report["status"] = "SUCCEEDED"
    except Exception as exc:
        report["status"] = "FAILED"
        report["issue_code"] = exc.code if isinstance(exc, DailyGateError) else {
            "preflight": "PREFLIGHT_ERROR", "macro": "MACRO_ERROR",
            "online": "ONLINE_RUN_FAILED", "audit": "AUDIT_FAILED",
            "verify": "RESEARCH_VERIFY_FAILED",
            "evaluate": "FORWARD_EVALUATION_FAILED"
        }.get(report["stage"], "DAILY_CYCLE_FAILED")
        if report["stage"] in report["steps"] and report["steps"][report["stage"]] == "PENDING":
            report["steps"][report["stage"]] = "FAILED"
        report["error_type"] = type(exc).__name__  # no raw exception, URLs or credentials
    except BaseException as exc:
        report["status"] = "INTERRUPTED"
        report["issue_code"] = "DAILY_PROCESS_INTERRUPTED"
        report["error_type"] = type(exc).__name__
        raise
    finally:
        report["completed_at"] = utcnow()
        if report["status"] in ALERT_STATES and report["issue_code"] != "SYNTHETIC_DEMO_NOT_ELIGIBLE":
            report["alert_id"] = record_alert(home, report)
        atomic(status_file(home), report)
        atomic(home / "data" / "daily-history" / (report["cycle_id"] + ".json"), report)
    return report


def current_status(home):
    path = status_file(home)
    if not path.exists():
        return {"status": "NOT_RUN", "trading_enabled": False, "meaning": "No private daily cycle has run"}
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("status") not in {"RUNNING", "FAILED", "DEGRADED", "SUCCEEDED", "INTERRUPTED"}:
        raise ValueError("Invalid daily status document")
    if report["status"] == "RUNNING":
        try:
            started = datetime.fromisoformat(report["started_at"])
            if started.tzinfo is not None and datetime.now(timezone.utc) - started > timedelta(minutes=45):
                return {**report, "status": "INTERRUPTED",
                        "issue_code": "PREVIOUS_CYCLE_STILL_RUNNING_AFTER_TIMEOUT",
                        "meaning": "Daily cycle has not completed within its expected timeout"}
        except (ValueError, TypeError, KeyError):
            raise ValueError("Invalid daily status timestamp") from None
    return report


def _email_settings(env):
    required = ("INVESTLAB_SMTP_HOST", "INVESTLAB_SMTP_USER",
                "INVESTLAB_SMTP_PASSWORD", "INVESTLAB_ALERT_TO")
    if not all(env.get(key) for key in required):
        return None
    port = int(env.get("INVESTLAB_SMTP_PORT", "465"))
    if not (1 <= port <= 65535):
        raise ValueError("SMTP port out of range")
    return {"host": env["INVESTLAB_SMTP_HOST"], "port": port,
            "user": env["INVESTLAB_SMTP_USER"], "password": env["INVESTLAB_SMTP_PASSWORD"],
            "to": env["INVESTLAB_ALERT_TO"]}


def dispatch_pending(home, *, env=None, smtp_factory=None):
    """Opt-in SMTP SSL dispatch, with at-least-once retry and local receipts."""
    env = os.environ if env is None else env
    cfg = _email_settings(env)
    if cfg is None:
        return {"status": "NOT_CONFIGURED", "sent": 0,
                "pending": sum(1 for p in outbox(home).glob("*.json")
                    if json.loads(p.read_text()).get("state") == "PENDING")}
    paths = sorted(outbox(home).glob("*.json"))
    pending = [p for p in paths if json.loads(p.read_text()).get("state") == "PENDING"]
    sent = 0
    for path in pending:
        alert = json.loads(path.read_text(encoding="utf-8"))
        msg = EmailMessage()
        msg["From"] = cfg["user"]
        msg["To"] = cfg["to"]
        msg["Subject"] = f'InvestLab daily monitor: {alert["status"]} ({alert["issue_code"]})'
        msg.set_content(
            "InvestLab private daily monitoring result.\n"
            f'Date (UTC): {alert["cycle_date"]}\n'
            f'Outcome: {alert["status"]}\n'
            f'Stage: {alert["stage"]}\n'
            f'Code: {alert["issue_code"]}\n'
            "No portfolio balances, tokens, prices, or account data are included.\n"
            "Check your private InvestLab daily-status for details.\n"
        )
        try:
            with (smtp_factory or smtplib.SMTP_SSL)(cfg["host"], cfg["port"], timeout=15) as smtp:
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            alert["delivery_attempts"] = int(alert.get("delivery_attempts", 0)) + 1
            alert["last_delivery_error_type"] = type(exc).__name__
            atomic(path, alert)
            return {"status": "DELIVERY_FAILED", "sent": sent,
                    "pending": len(pending)-sent, "error_type": type(exc).__name__}
        alert["state"] = "SENT"
        alert["sent_at"] = utcnow()
        alert["delivery_attempts"] = int(alert.get("delivery_attempts", 0)) + 1
        atomic(path, alert)
        sent += 1
    return {"status": "OK", "sent": sent, "pending": 0}
