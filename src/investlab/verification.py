"""Independent accounting oracle and chronological historical diagnostics.

Does not call the production rebalance solver or tune strategy parameters.
"""
from pathlib import Path
import json
import math
import sys
from .core import ENGINE, atomic, canonical, code_identity, connection, digest, utcnow


def piecewise_rebalance(values, weights, bps):
    """Solve the self-financing fee equation analytically on sign intervals."""
    total = sum(values); rate = bps / 10000
    breaks = sorted({0., total, *(v / w for v, w in zip(values[:-1], weights[:-1]) if w > 0 and 0 < v / w < total)})
    for left, right in zip(breaks, breaks[1:]):
        mid = (left + right) / 2
        signs = [1 if mid * w >= v else -1 for v, w in zip(values[:-1], weights[:-1])]
        capital = (total + rate * sum(s * v for s, v in zip(signs, values[:-1]))) / (1 + rate * sum(s * w for s, w in zip(signs, weights[:-1])))
        if left - 1e-10 <= capital <= right + 1e-10:
            new = [capital * w for w in weights]
            return new, total - capital
    if total == 0: return [0.] * len(values), 0.
    raise ValueError("Independent fee equation has no solution")


def replay_trade_schedule(data, production, bps):
    """Independently apply saved targets after that day's old holdings return."""
    dates = production["dates"]; maps = {s: dict(zip(data["dates"], data["prices"][s])) for s in ("QQQ", "TQQQ")}
    targets = {e["execute_session"]: e for e in production["trades"]}
    values = [0., 0., 1.]; curve = [1.]
    for previous, day in zip(dates, dates[1:]):
        for j, s in enumerate(("QQQ", "TQQQ")): values[j] *= maps[s][day] / maps[s][previous]
        if day in targets:
            event = targets[day]
            if event["signal_session"] >= day: raise ValueError("Same-session or future signal leakage")
            w = [event["target"][s] for s in ("QQQ", "TQQQ", "CASH")]
            values, _ = piecewise_rebalance(values, w, bps)
        if min(values) < -1e-10: raise ValueError("Negative simulated balance")
        curve.append(sum(values))
    return curve


def historical_folds(result, length=252):
    curve, dates = result["curve"], result["dates"]
    folds = []
    for start in range(0, len(curve) - 1, length):
        end = min(start + length, len(curve) - 1)
        segment = curve[start:end + 1]; peak = segment[0]; worst = 0.
        for v in segment: peak = max(peak, v); worst = min(worst, v / peak - 1)
        folds.append({"start": dates[start], "end": dates[end], "sessions": end-start,
                      "return_pct": (segment[-1] / segment[0] - 1) * 100,
                      "max_drawdown_pct": worst * 100,
                      "evidence": "CHRONOLOGICAL_DIAGNOSTIC_ALREADY_SEEN_HISTORY"})
    return folds


def verify(home):
    """Ten families, both fee assumptions, all equity points; no account writes."""
    sys.path.insert(0, str(ENGINE))
    try:
        import monitor as m
        from research import mature
        candles = m.price_data(Path(home) / "data/monitor.sqlite3")
        cutoff = min(candles[s][-1]["trade_date"] for s in m.ACTIVE_SYMBOLS)
        data = mature.dataset(candles, cutoff); p = mature.config(); fs = mature.features(data, p)
        rows = []; failures = []
        for bps in p["cost_bps_per_side"]:
            for name in p["models"]:
                result = mature.simulate(data, fs, p, name, bps)
                independent = replay_trade_schedule(data, result, bps)
                error = max(abs(a-b) / max(abs(a), 1e-15) for a,b in zip(result["curve"], independent))
                if len(independent) != len(result["curve"]) or error > 1e-9: failures.append(name + ":accounting")
                rows.append({"model_id": name, "cost_bps": bps, "max_relative_equity_error": error,
                             "summary": result["summary"], "folds": historical_folds(result)})
        # For two assets with equal risk contributions, w1*sigma1=w2*sigma2.
        cov = fs[-1]["cov"]; expected = math.sqrt(cov[1][1]) / (math.sqrt(cov[0][0]) + math.sqrt(cov[1][1]))
        actual = mature.equal_risk(cov)[0]; parity_error = abs(actual - expected)
        if parity_error > 1e-7: failures.append("risk_parity_analytic")
        # Future prices must not alter earlier features or targets.
        prefix = {"dates": data["dates"][:-20], "prices": {s: v[:-20] for s, v in data["prices"].items()}}
        prefix_fs = mature.features(prefix, p)
        if fs[:-20] != prefix_fs: failures.append("future_feature_leakage")
        for name in p["models"]:
            a = mature.simulate(data, fs, p, name, 15)
            b = mature.simulate(prefix, prefix_fs, p, name, 15)
            if a["curve"][:len(b["curve"])] != b["curve"]: failures.append(name + ":future_signal_leakage")
        # Export curves for visual comparison, explicitly hypothetical research.
        charts = {}
        for name in ("B_QQQ100", "B_FIXED60_40", "VOL_TARGET_QQQ", "TSMOM12_QQQ", "RP_VOL_TARGET_QQQ_TQQQ"):
            r = mature.simulate(data, fs, p, name, 15)
            charts[name] = {"dates": r["dates"], "equity": r["curve"]}
        result = {"status": "PASS" if not failures else "FAIL", "failures": failures,
                  "checked_at": utcnow(), "data_sha256": data["data_sha256"], "data_end": cutoff,
                  "model_sha256": mature.source_hash(), "app_code_sha256": code_identity(),
                  "risk_parity_analytic_error": parity_error, "comparisons": rows, "curves": charts,
                  "independent_verification_scope": "ACCOUNTING_PLUS_PREFIX_CAUSALITY_NOT_MARKET_DATA_OR_STRATEGY_ALPHA",
                  "forward_validation": "NOT_ESTABLISHED_BY_HISTORICAL_TESTS",
                  "assumptions": {"signal": "close_t", "execution": "close_t_plus_1", "new_holdings_returns": "t_plus_2",
                                  "cash_yield": 0, "taxes": "EXCLUDED", "fx": "USD_RESEARCH_NOT_CNY_ACCOUNT_PNL"}}
        atomic(Path(home) / "data/verification.json", result)
        return result
    finally:
        sys.path.remove(str(ENGINE))


def freeze(home):
    with connection(home) as c:
        last = c.execute("SELECT max(trade_date) FROM daily_prices WHERE symbol='QQQ'").fetchone()[0]
        specification = {"target": {"QQQ": .6, "TQQQ": .4}, "step": .05,
                         "scope": "DAILY_MANUAL_ALLOCATION_AND_20_SESSION_DOWNSIDE_FORECAST",
                         "changes_require_new_version": True, "history_already_seen": True}
        code = code_identity(); key = digest({"code": code, "data_end": last, "spec": specification})
        c.execute("INSERT OR IGNORE INTO experiments VALUES(?,?,?,?,?)", (key, utcnow(), last, code, canonical(specification)))
    return {"experiment_id": key, "future_evidence_begins_after": last, "code_sha256": code}
