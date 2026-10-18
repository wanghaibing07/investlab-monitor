"""One serialized operation: calculate -> persist -> verify -> expose -> back up."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from . import __version__
from .core import PACKAGE, ENGINE, atomic, canonical, code_identity, connection, digest, schema, utcnow
from .storage import backup


def worker(home, command, *flags, timeout=600):
    env = dict(os.environ, INVESTLAB_HOME=str(home), PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(PACKAGE / "worker.py"), command, *flags], env=env,
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError("计算进程失败: " + p.stderr[-1800:])
    return json.loads(p.stdout)


def init(home, demo=False):
    home = Path(home)
    if (home / "settings.json").exists() or (home / "data/monitor.sqlite3").exists(): raise ValueError("已有项目，拒绝重新初始化")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    worker(home, "bootstrap"); schema(home)
    atomic(home / "settings.json", {"schema_version": 1, "demo": demo,
            "target": {"QQQ": .6, "TQQQ": .4}, "execution": "MANUAL", "account": "default"})
    if demo:
        seed_demo(home)
    return {"home": str(home), "demo": demo, "needs_confirmed_valuation": not demo}


def seed_demo(home):
    """Reproducible synthetic market. Never redistributed real vendor history."""
    import math
    from datetime import date
    # Calendar imported only in this process for generating a fictional fixture.
    sys.path.insert(0, str(ENGINE))
    try:
        import monitor
        day = date(2023, 1, 3); end = date(2026, 10, 14); dates = []
        while day <= end:
            if monitor.is_regular_session(day): dates.append(day.isoformat())
            day += timedelta(days=1)
    finally:
        sys.path.remove(str(ENGINE))
    q, t = 100., 50.; now = utcnow(); rows = []
    for i, d in enumerate(dates):
        ret = .00045 + .008 * math.sin(i / 7) + .004 * math.cos(i / 23)
        if 320 <= i < 335: ret -= .018
        if 700 <= i < 715: ret -= .015
        q *= 1 + ret; t *= 1 + 3 * ret - .00008
        for s, p in (("QQQ", q), ("TQQQ", t)): rows.append((s, d, p, p, "SYNTHETIC_DEMO", now))
    with connection(home) as c:
        c.executemany("INSERT INTO daily_prices VALUES(?,?,?,?,?,?)", rows)
        c.execute("INSERT INTO portfolio_baselines(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,qld_value_cny,note) VALUES(?,?,?,?,?,?,?)", (now, "2026-10-14", 60000, 40000, 0, 0, "演示账户；虚构金额，不是用户持仓"))


def settings(home):
    p = Path(home) / "settings.json"
    if not p.exists(): raise ValueError("先运行init或migrate")
    value = json.loads(p.read_text())
    if value.get("target") != {"QQQ": .6, "TQQQ": .4} or value.get("execution") != "MANUAL":
        raise ValueError("目标配置与当前冻结规则不一致，请显式注册新策略版本")
    return value


def risk_summary(report):
    q = report.get("quant_analysis", {})
    risk = q.get("risk_contributions", {}).get("FULL_TARGET_REFERENCE", {})
    f = q.get("risk_forecast", {})
    return {"daily_exposure": 1.8, "annual_volatility": risk.get("annual_volatility"),
            "tqqq_variance_share": risk.get("variance_contribution_share", {}).get("TQQQ"),
            "downside_forecast": {k: f.get(k) for k in ("probability", "base_probability", "meaning", "calibration_status")},
            "forecast_use": "RESEARCH_ONLY", "macro_use": "SENSITIVITY_NOT_TIMING"}


def run(home, *, online=False, independent=False):
    cfg = settings(home)
    if cfg["demo"] and online: raise ValueError("演示账户不能联网混入真实市场数据，请在新目录初始化或迁移")
    schema(home)
    operation = uuid.uuid4().hex; started = utcnow(); source_at_start = code_identity()
    with connection(home) as c:
        # A crashed former operation is observable; don't call it a success.
        c.execute("UPDATE operations SET status='INTERRUPTED',completed_at=? WHERE status IN ('RUNNING','PERSISTED')", (started,))
        c.execute("INSERT INTO operations VALUES(?,?,NULL,'run','RUNNING',?)", (operation, started, "{}"))
    try:
        flags = (["--online"] if online else []) + (["--independent-check"] if independent else []) + (["--demo"] if cfg["demo"] else [])
        result = worker(home, "run", *flags)
        report = result["report"]
        with connection(home, readonly=True) as c:
            stored = c.execute("SELECT report_json,report_sha256 FROM monitor_runs WHERE run_id=?", (report["run_id"],)).fetchone()
            if not stored or digest(json.loads(stored[0])) != stored[1] or json.loads(stored[0]) != report:
                raise ValueError("报告未在事实账本中原样保存")
        if code_identity() != source_at_start:
            raise ValueError("运行期间源码发生改变，本轮不发布为合格结果")
        integrity = audit(home)
        if integrity["status"] != "PASS":
            raise ValueError("证据审计未通过: " + ";".join(integrity["errors"]))
        review = report["allocation_review"]
        qualified = not cfg["demo"] and report["mode"] == "ONLINE_2_OF_2" and review["status"] == "ALLOCATION_REVIEW" and all(x.get("quality") == "CURRENT" for x in report["market"].values()) and not any(k.endswith("persistence_error") for k in report)
        base = {"version": __version__, "operation_id": operation, "legacy_run_id": report["run_id"],
                "created_at": utcnow(), "session_date": report["as_of_expected_session"],
                "code_sha256": source_at_start, "demo": cfg["demo"], "qualified_online": qualified,
                "mode": report["mode"], "evidence_grade": report["data_evidence_grade"],
                "review": review, "market": report["market"], "portfolio": report["portfolio"],
                "risk": risk_summary(report), "mature_models": report.get("mature_models", {}),
                "alerts": report["alerts"], "trading_enabled": False,
                "persistence_errors": {k: v for k, v in report.items() if k.endswith("persistence_error")},
                "checks": {"database_report_readback": True, "evidence_audit": integrity["status"],
                    "independent_quotes": {s: report["fetch"][s].get("independent_status", "NOT_VERIFIED") for s in ("QQQ", "TQQQ")},
                    "strategy_effectiveness": "FORWARD_EVIDENCE_ACCUMULATING"}}
        rid = digest(base); base["review_id"] = rid
        with connection(home) as c:
            c.execute("INSERT INTO app_reviews VALUES(?,?,?,?,?,?)", (rid, operation, base["session_date"], base["created_at"], canonical(base), digest(base)))
            nid = digest({"signal_id": review["signal_id"], "session": base["session_date"], "demo": cfg["demo"]})
            body = plain_summary(base)
            c.execute("INSERT OR IGNORE INTO notifications VALUES(?,?,?,'LOCAL_ONLY',?)", (nid, rid, utcnow(), body))
            c.execute("UPDATE operations SET status='PERSISTED',details=? WHERE operation_id=?", (canonical({"review_id": rid}), operation))
        atomic(Path(home) / "data/app-latest.json", base)
        atomic(Path(home) / "data/notification.txt", body.encode())
        saved = backup(home)
        final = {"review_id": rid, "backup": saved, "checks": base["checks"], "qualified_online": qualified}
        with connection(home) as c:
            c.execute("UPDATE operations SET completed_at=?,status='SUCCEEDED',details=? WHERE operation_id=?", (utcnow(), canonical(final), operation))
        # This receipt is derived, and can be regenerated from the operations table.
        atomic(Path(home) / "data/last-operation.json", final)
        return {"summary": body, **final}
    except BaseException as exc:
        with connection(home) as c:
            c.execute("UPDATE operations SET completed_at=?,status='FAILED',details=? WHERE operation_id=?", (utcnow(), canonical({"error": str(exc)}), operation))
        raise


def plain_summary(value):
    review = value["review"]; target = review.get("next_review_weights")
    if value.get("latest_attempt", {}).get("status") not in (None, "SUCCEEDED"):
        headline = "今日：最近一轮失败或未完成；保留上一份报告，暂停新的调整建议。"
        target = None
    elif value["demo"]: headline = "演示：以下使用虚构行情和账户。"
    elif value.get("market_session_current") is False:
        headline = "今日：报告行情已落后于最新完整交易日，更新后再复核。"
        target = None
    elif review["status"] != "ALLOCATION_REVIEW": headline = "今日：缓存复算或数据不足，查看条件；暂无新的调整步骤。"
    else:
        labels = {"HOLD": "维持", "INCREASE_REVIEW": "增加至", "REDUCE_REVIEW": "减少至"}
        headline = "今日：" + "；".join(s + labels[review["actions"][s]] + (f'{target[s]:.0%}' if review["actions"][s] != "HOLD" else "") for s in ("QQQ", "TQQQ")) + "。"
    lines = [headline, "目标：QQQ 60%＋TQQQ 40%。"]
    if target: lines.append(f'本步：QQQ {target["QQQ"]:.0%}／TQQQ {target["TQQQ"]:.0%}／现金 {target["CASH"]:.0%}。')
    lines += ["行情截至 " + min(v.get("last_date", "未知") for v in value["market"].values()) + "；账户截至 " + value["portfolio"]["as_of"] + "。", "建议不会记成成交；策略效果继续检验。"]
    return "\n".join(lines)


def latest(home):
    # Read the database, not a possibly stale derived latest.json file after a crash.
    with connection(home, readonly=True) as c:
        row = c.execute("SELECT payload FROM app_reviews ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row: return None
        value = json.loads(row[0])
        ops = c.execute("SELECT status,completed_at,details FROM operations WHERE operation_id=?", (value["operation_id"],)).fetchone()
        value["operation"] = {**dict(ops), "details": json.loads(ops["details"])}
        attempt = c.execute("SELECT operation_id,status,started_at,completed_at FROM operations ORDER BY started_at DESC LIMIT 1").fetchone()
        value["latest_attempt"] = dict(attempt)
        value["distinct_verified_sessions"] = c.execute("SELECT count(DISTINCT session_date) FROM app_reviews r JOIN operations o ON o.operation_id=r.operation_id WHERE o.status='SUCCEEDED' AND json_extract(r.payload,'$.qualified_online')=1 AND json_extract(r.payload,'$.code_sha256')=?", (value["code_sha256"],)).fetchone()[0]
        value["stale_for_today"] = datetime.now(timezone.utc) - datetime.fromisoformat(value["created_at"]) > timedelta(hours=36)
        from .engine.monitor import expected_close_session
        value["market_session_current"] = value["session_date"] == expected_close_session().isoformat()
        value["is_actionable"] = bool(not value["demo"] and value["qualified_online"]
            and value["market_session_current"] and value["operation"]["status"] == "SUCCEEDED"
            and value["latest_attempt"]["operation_id"] == value["operation_id"]
            and value["latest_attempt"]["status"] == "SUCCEEDED")
        return value


def audit(home):
    legacy = worker(home, "audit")
    errors = []; warnings = []; count = 0
    with connection(home, readonly=True) as c:
        for table, column, hashcolumn in (("journal_events", "event_json", "event_sha256"), ("account_valuations", "payload", "payload_sha256"), ("app_reviews", "payload", "payload_sha256")):
            for row in c.execute(f"SELECT {column},{hashcolumn} FROM {table}"):
                count += 1
                if digest(json.loads(row[0])) != row[1]: errors.append(table + ":hash")
        running = c.execute("SELECT count(*) FROM operations WHERE status IN ('RUNNING','INTERRUPTED','FAILED')").fetchone()[0]
    def collect(value, path=""):
        if isinstance(value, dict):
            for k, v in value.items():
                if path == "research_evidence." and k == "signals_without_frozen_input_snapshot":
                    if v: warnings.append("早期研究记录缺少输入快照: " + str(v))
                    continue
                if ("error" in k or k.startswith("missing_") or k.startswith("qualified_reviews_missing") or k.startswith("signals_without_frozen") or k.startswith("qualified_signals_without_frozen")) and isinstance(v, (int, float)) and v != 0:
                    errors.append(path + k + "=" + str(v))
                collect(v, path + k + ".")
    collect(legacy)
    if legacy["sqlite_integrity"] != "ok": errors.append("sqlite_integrity")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "warnings": warnings, "hash_records_checked": count,
            "failed_or_interrupted_operations": running, "legacy": legacy}
