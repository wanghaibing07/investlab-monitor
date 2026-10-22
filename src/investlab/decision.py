"""One final manual-review decision from market evidence and reconciled account facts.

The numerical C0 model is retained as a reference. It cannot turn an outdated
valuation, a partial trade report, or an unconfirmed risk budget into an order.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import math
import sqlite3

from .core import digest

VERSION = "decision-contract-v1"
AMOUNT_FIELDS = ("emergency_reserve_cny", "investable_capital_cny",
                 "max_acceptable_loss_cny", "minimum_cash_cny")


def account_evidence(db, baseline, session, account="default"):
    """Read the existing journal; preserve reported amounts without inventing fills."""
    c = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        events = ([json.loads(r[0]) for r in c.execute(
            "SELECT event_json FROM journal_events WHERE account=? ORDER BY occurred_at,event_id",
            (account,))] if "journal_events" in tables else [])
        row = (c.execute("SELECT payload FROM account_valuations WHERE account=? "
                         "ORDER BY as_of DESC,recorded_at DESC,rowid DESC LIMIT 1", (account,)).fetchone()
               if "account_valuations" in tables else None)
        valuation = json.loads(row[0]) if row else None
    finally:
        c.close()
    voided = {e["reverses_event_id"] for e in events if e["kind"] == "VOID"}
    active = [e for e in events if e["kind"] != "VOID" and e["event_id"] not in voided]
    covered = set((valuation or {}).get("reconciles_event_ids", []))
    reports = [e for e in active if e["kind"] == "REPORTED_BUY"]
    unresolved = [e["event_id"] for e in reports if e["event_id"] not in covered]
    asof = baseline.get("as_of")
    changes = [e["event_id"] for e in active
               if e["event_id"] not in covered and
               (e["occurred_at"][:10] > (asof or "") or
                e["occurred_at"][:10] == asof and e["kind"] != "REPORTED_BUY")]
    blockers = []
    if asof != session:
        blockers.append("ACCOUNT_VALUATION_NOT_CURRENT")
    if unresolved or changes:
        blockers.append("ACCOUNT_ACTIVITY_NOT_RECONCILED")
    values = ({"QQQ": baseline.get("qqq_value_cny"), "TQQQ": baseline.get("tqqq_value_cny"),
               "QLD": baseline.get("qld_value_cny", 0), "CASH": baseline.get("cash_cny")}
              if not blockers else None)
    out = {"account": account, "valuation_as_of": asof,
           "valuation_id": (valuation or {}).get("valuation_id"),
           "baseline_scope": "HISTORICAL_AGGREGATE_NOT_CURRENT_HOLDINGS" if blockers else "CURRENT_CONFIRMED_AGGREGATE",
           "reported_activity": reports, "unreconciled_event_ids": sorted(set(unresolved + changes)),
           "reconciliation_required": bool(unresolved or changes),
           "current_values_cny": values, "blockers": blockers,
           "shares": None, "cost_basis": None, "actual_pnl": None}
    out["evidence_id"] = digest(out)
    return out


def risk_budget_status(budget, policy):
    """A target allocation or prior loss is never substituted for a user budget."""
    if not isinstance(budget, dict) or budget.get("confirmed") is not True:
        return {"status": "NOT_CONFIRMED", "limits": None}
    try:
        if not budget.get("source") or not isinstance(budget.get("confirmed_at"), str):
            raise ValueError("missing source")
        if date.fromisoformat(budget["confirmed_at"]) > date.today():
            raise ValueError("future confirmation")
        amounts = {}
        for k in AMOUNT_FIELDS:
            v = budget[k]
            if not isinstance(v, str):
                raise ValueError("use decimal strings")
            amounts[k] = Decimal(v)
            if not amounts[k].is_finite() or amounts[k] < 0:
                raise ValueError("invalid amount")
        if amounts["investable_capital_cny"] <= 0 or amounts["max_acceptable_loss_cny"] > amounts["investable_capital_cny"]:
            raise ValueError("invalid capital")
        if budget.get("reserve_location") not in ("IN_ACCOUNT", "OUTSIDE_ACCOUNT"):
            raise ValueError("reserve location unknown")
        exposure = budget["maximum_daily_ndx_exposure"]
        weight = budget["maximum_tqqq_weight"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (exposure, weight)) or exposure < 0 or not 0 <= weight <= 1:
            raise ValueError("invalid envelope")
        floor = amounts["minimum_cash_cny"]
        if budget["reserve_location"] == "IN_ACCOUNT":
            floor = max(floor, amounts["emergency_reserve_cny"])
        limits = {"minimum_cash_cny": float(floor),
                  "investable_capital_cny": float(amounts["investable_capital_cny"]),
                  "maximum_daily_ndx_exposure": min(exposure, policy["maximum_daily_ndx_exposure"]),
                  "maximum_tqqq_weight": min(weight, policy["strategic_reference"]["TQQQ"])}
        if not all(math.isfinite(v) for v in limits.values()):
            raise ValueError("non-finite limits")
        return {"status": "CONFIRMED_ENVELOPE", "limits": limits,
                "source": budget["source"], "confirmed_at": budget["confirmed_at"],
                "loss_budget_use": "SCENARIO_REVIEW_NOT_A_GUARANTEED_LOSS_CAP"}
    except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
        return {"status": "INVALID_OR_INCOMPLETE", "limits": None}


def decide(report, account, budget, policy):
    """Pure precedence: data eligibility, protective review, then additions."""
    ref = report.get("allocation_review", {})
    session = report.get("as_of_expected_session")
    rb = risk_budget_status(budget, policy)
    blockers = list(account["blockers"])
    market = report.get("market", {})
    reference_valid = (
        ref.get("status") in ("ALLOCATION_REVIEW", "CACHE_REPLAY_ONLY")
        and report.get("data_evidence_grade") != "SOURCE_CONFLICT"
        and set(market) == {"QQQ", "TQQQ"}
        and all(v.get("quality") == "CURRENT" and v.get("last_date") == session for v in market.values())
        and isinstance(ref.get("trend_active"), bool)
        and isinstance(ref.get("qqq_vol20_pct"), (int, float))
        and not isinstance(ref.get("qqq_vol20_pct"), bool)
        and math.isfinite(ref["qqq_vol20_pct"]) and ref["qqq_vol20_pct"] >= 0)
    market_ready = bool(reference_valid and report.get("mode") == "ONLINE_2_OF_2"
                        and ref.get("status") == "ALLOCATION_REVIEW")
    if not market_ready:
        blockers.append("MARKET_NOT_FRESH_OR_NOT_ONLINE")
    risk_reason = None
    if reference_valid:
        if not ref["trend_active"]:
            risk_reason = "TREND_EXIT"
        elif ref["qqq_vol20_pct"] >= policy["volatility"]["exit_at_pct"]:
            risk_reason = "VOLATILITY_EXIT"
    out = {"version": VERSION, "session_date": session,
           "status": "DATA_BLOCKED", "actions": {"QQQ": "DATA_BLOCKED", "TQQQ": "DATA_BLOCKED"},
           "review_ready": False, "execution_ready": False, "orders": [],
           "executable_delta_cny": None, "executable_shares": None,
           "target_weights": None, "blockers": blockers,
           "account_evidence_id": account["evidence_id"], "risk_budget": rb,
           "market_reference": {"scope": "C0_REFERENCE_NOT_FINAL_ACCOUNT_ACTION",
               "trend_active": ref.get("trend_active") if reference_valid else None,
               "qqq_vol20_pct": ref.get("qqq_vol20_pct") if reference_valid else None,
               "risk_reason": risk_reason, "fresh_online": market_ready},
           "reasons": [], "next_condition": "核对账户事实并取得本轮合格收盘行情。",
           "short_indicators": "EXPLANATION_ONLY_NO_RSI_EXIT_OR_ENTRY_OVERRIDE"}
    values = account["current_values_cny"]
    current = None
    if values and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                      and math.isfinite(v) and v >= 0 for v in values.values()):
        total = sum(values.values())
        if total > 0:
            current = {k: v / total for k, v in values.items()}
    if current is None:
        if "ACCOUNT_VALUES_INCOMPLETE" not in blockers:
            blockers.append("ACCOUNT_VALUES_INCOMPLETE")
    # A verified market exit remains visible even when the amount cannot be sized.
    if market_ready and risk_reason:
        out.update(status="REDUCE_REVIEW",
                   actions={"QQQ": "SEPARATE_CORE_REVIEW", "TQQQ": "REDUCE_REVIEW"},
                   reasons=["长期趋势关闭。" if risk_reason == "TREND_EXIT" else "波动达到既有退出门槛。"],
                   next_condition="先核查TQQQ实际持仓，再人工复核减仓或退出；QQQ核心仓单独判断。")
        if current:
            out["target_weights"] = {"QQQ": current["QQQ"], "QLD": current["QLD"],
                                    "TQQQ": 0., "CASH": current["CASH"] + current["TQQQ"]}
            out["actions"]["TQQQ"] = "REDUCE_REVIEW" if current["TQQQ"] > 0 else "HOLD"
            out["review_ready"] = True
            if not current["TQQQ"]:
                out["status"] = "HOLD"
        else:
            out["reasons"].append("账户待核对，不能给出精确卖出金额或股数。")
    elif not market_ready or current is None:
        out["reasons"] = (["买入事实尚未与最新账户估值核对。"] if account["reconciliation_required"]
                          else ["账户估值或本轮行情不足以支持新的仓位调整。"])
    else:
        limits = rb["limits"]
        if limits:
            limits = dict(limits)
            limits["minimum_cash_cny"] = max(limits["minimum_cash_cny"], total - limits["investable_capital_cny"])
            cap = limits["maximum_daily_ndx_exposure"]
            q, t, l = current["QQQ"], current["TQQQ"], current["QLD"]
            t_limit = min(limits["maximum_tqqq_weight"],
                          max(0., (cap - q - 2 * l) / 3),
                          max(0., 1 - q - l - limits["minimum_cash_cny"] / total))
            exposure = q + 2 * l + 3 * t
            if t > t_limit + 1e-9 or exposure > cap + 1e-9 or values["CASH"] < limits["minimum_cash_cny"]:
                t_next = min(t, t_limit)
                q_next = min(q, max(0., cap - 2 * l - 3 * t_next),
                             max(0., 1 - l - t_next - limits["minimum_cash_cny"] / total))
                out.update(status="REDUCE_REVIEW", review_ready=True,
                           actions={"QQQ": "REDUCE_REVIEW" if q_next < q - 1e-9 else "HOLD",
                                    "TQQQ": "REDUCE_REVIEW" if t_next < t - 1e-9 else "HOLD"},
                           target_weights={"QQQ": q_next, "QLD": l, "TQQQ": t_next,
                                           "CASH": 1 - q_next - l - t_next},
                           reasons=["当前组合超出已确认的现金或杠杆约束。"],
                           next_condition="人工复核恢复风险约束所需的减仓，不同时生成新增建议。")
        if out["status"] != "REDUCE_REVIEW":
            vol = ref["qqq_vol20_pct"]
            if vol >= policy["volatility"]["entry_max_pct"]:
                out.update(status="PAUSE_ADD", actions={"QQQ": "HOLD", "TQQQ": "PAUSE_ADD"},
                           reasons=["波动处于暂停新增区间。"],
                           next_condition="波动回到新增门槛以下，且账户与风险预算齐备后再复核。")
            elif not limits:
                blockers.append("PERSONAL_RISK_BUDGET_NOT_CONFIRMED")
                out.update(status="PAUSE_ADD", actions={"QQQ": "NO_NEW_REVIEW", "TQQQ": "PAUSE_ADD"},
                           reasons=["配置目标尚不能替代个人资金与风险约束。"],
                           next_condition="确认备用金、可投资资金、可接受损失及现金要求后再复核新增。")
            else:
                candidate = ref.get("next_review_weights")
                if not candidate or current["QLD"] != 0:
                    blockers.append("C0_REFERENCE_OR_ASSET_SCOPE_INCOMPLETE")
                else:
                    t = current["TQQQ"]
                    q = max(0., min(candidate["QQQ"], limits["maximum_daily_ndx_exposure"],
                                   1 - limits["minimum_cash_cny"] / total))
                    cap_t = max(0., min(limits["maximum_tqqq_weight"],
                                      (limits["maximum_daily_ndx_exposure"] - q) / 3,
                                      1 - q - limits["minimum_cash_cny"] / total))
                    gap = min(policy["strategic_reference"]["TQQQ"], cap_t) - t
                    t_next = min(cap_t, t + min(policy["tactical_add_step"], gap)) if gap >= policy["tactical_drift_band"] - 1e-10 else min(t, cap_t)
                    target = {"QQQ": q, "QLD": 0., "TQQQ": t_next, "CASH": 1 - q - t_next}
                    actions = {k: ("INCREASE_REVIEW" if target[k] > current[k] + 1e-9 else
                                   "REDUCE_REVIEW" if target[k] < current[k] - 1e-9 else "HOLD")
                               for k in ("QQQ", "TQQQ")}
                    status = ("REDUCE_REVIEW" if "REDUCE_REVIEW" in actions.values() else
                              "ADD_REVIEW" if "INCREASE_REVIEW" in actions.values() else "HOLD")
                    if status == "REDUCE_REVIEW":
                        # No asset is added while another is being reduced by an envelope.
                        for k in actions:
                            if actions[k] == "INCREASE_REVIEW":
                                target[k] = current[k]; actions[k] = "HOLD"
                        target["CASH"] = 1 - target["QQQ"] - target["TQQQ"]
                    out.update(status=status, actions=actions, target_weights=target, review_ready=True,
                               reasons=["已按真实估值、既有趋势和已确认的风险约束复核。"],
                               next_condition="本建议保持待复核；收到执行、取消或新的账户事实后才重新评估下一步。")
    # Session changes and repeated runs are not new account or execution events.
    if out["status"] == "DATA_BLOCKED" and rb["status"] != "CONFIRMED_ENVELOPE":
        out["reasons"].append("个人资金与风险预算也尚未确认。")
        out["next_condition"] = "核对最新账户估值及买入事实，确认资金和风险要求；合格收盘行情更新后再复核。"
    out["proposal_id"] = digest({"version": VERSION, "policy_sha256": digest(policy), "account": account["evidence_id"],
        "budget": rb, "status": out["status"], "actions": out["actions"],
        "target": {k: round(v, 8) for k, v in (out["target_weights"] or {}).items()},
        "trigger": risk_reason or out["status"]})[:24]
    out["lifecycle"] = "MANUAL_REVIEW_ONLY_NOT_A_FILL"
    return out


def attach(report, home, policy):
    cfg = json.loads((Path(home) / "settings.json").read_text())
    account = account_evidence(Path(home) / "data/monitor.sqlite3", report["portfolio"],
                               report["as_of_expected_session"], cfg.get("account", "default"))
    report["account_state"] = account
    report["decision"] = decide(report, account, cfg.get("risk_budget"), policy)
    report["allocation_review_scope"] = "HISTORICAL_BASELINE_C0_REFERENCE_USE_DECISION_FOR_FINAL_ACTION"
    return report


def summary_lines(decision, account):
    status = decision["status"]
    headlines = {"DATA_BLOCKED": "今日：资料不足，暂停生成新的仓位调整。",
                 "PAUSE_ADD": "今日：暂停新增TQQQ。",
                 "REDUCE_REVIEW": "今日：复核降低仓位，先处理风险。",
                 "ADD_REVIEW": "今日：具备新增复核条件，等待人工确认。",
                 "HOLD": "今日：本轮无需调整仓位。"}
    lines = [headlines[status]]
    for event in account.get("reported_activity", []):
        if event["event_id"] in account.get("unreconciled_event_ids", []):
            amount = "约" if event["amount_is_approximate"] else ""
            currency = {"CNY": "元人民币", "USD": "美元", "HKD": "港元"}[event["currency"]]
            lines.append(f'已确认：{event["occurred_at"]}买入{amount}{event["amount"]}{currency}的{event["symbol"]}；成交细节待补，不按零持仓判断。')
    lines += ["原因：" + "；".join(decision["reasons"][:2]),
              "下次条件：" + decision["next_condition"],
              "长期目标：QQQ 60%／TQQQ 40%，须服从已确认的风险约束。"]
    if decision.get("target_weights"):
        t = decision["target_weights"]
        lines.append(f'待复核比例：QQQ {t["QQQ"]:.1%}／TQQQ {t["TQQQ"]:.1%}／现金 {t["CASH"]:.1%}；不是成交。')
    return lines

