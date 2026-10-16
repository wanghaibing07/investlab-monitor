"""Conservative, explainable *manual review* brief derived from verified InvestLab facts.

No automatic trading. Technical PASS does not by itself authorize a position
change. The current confirmed account must match the report's original account
baseline, and a report must still be actionable for today's completed session.
"""
from __future__ import annotations

import math
from typing import Any

TICKERS = ("QQQ", "TQQQ", "QLD", "CASH")
PORTFOLIO_KEYS = {
    "QQQ": "qqq_value_cny",
    "TQQQ": "tqqq_value_cny",
    "QLD": "qld_value_cny",
    "CASH": "cash_cny",
}
ACTION_LABELS = {
    "HOLD": "维持",
    "INCREASE_REVIEW": "评估增加",
    "REDUCE_REVIEW": "评估减少",
}
REASONS = {
    "TREND_ENTRY_STEP": ("趋势允许分步复核", "QQQ 趋势开启，且波动符合当前策略的增配条件；仍需核对账户、费用和承受能力。"),
    "TREND_EXIT": ("长期趋势转弱，复核杠杆风险", "策略趋势条件已关闭，优先检查 TQQQ 战术仓的降档方案。"),
    "VOLATILITY_EXIT": ("波动达到退出条件，复核降杠杆", "QQQ 的短期波动达到策略退出阈值，先处理风险，再考虑收益机会。"),
    "VOLATILITY_PAUSE_ADDITIONS": ("波动偏高，暂停增加杠杆", "策略暂不支持继续增加 TQQQ，观察波动回落及趋势变化。"),
    "TRIM_ABOVE_REFERENCE": ("仓位高于参考上限，检查超额部分", "当前战术仓超过策略参考权重，先核对是否需要降低敞口。"),
    "WITHIN_TACTICAL_BAND": ("配置处于容忍范围，维持观察", "当前权重处于策略允许偏差范围内，不因每天运行而重复加仓。"),
}


def _number(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


def _iso_date(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        return value
    return None


def _historical_signal(report: dict, run: dict) -> dict | None:
    """Prior *research observation*, never a current action or trading approval."""
    if run.get("status") != "SUCCEEDED" or run.get("qualified_online") is not True:
        return None
    if report.get("demo") is not False or report.get("qualified_online") is not True:
        return None
    review = report.get("review")
    if not isinstance(review, dict) or review.get("status") != "ALLOCATION_REVIEW":
        return None
    reason = review.get("tactical_reason")
    if reason not in REASONS:
        return None
    title, explanation = REASONS[reason]
    return {
        "session": _iso_date(report.get("session_date")),
        "headline": title,
        "explanation": explanation,
        "trend_active": review.get("trend_active")
            if type(review.get("trend_active")) is bool else None,
        "qqq_vol20_pct": _number(review.get("qqq_vol20_pct")),
        "not_current_advice": True,
        "label": "历史模型观察（不可直接交易）",
    }


def _base(account: dict | None, run: dict | None, report: dict | None) -> dict:
    account = account if isinstance(account, dict) else {}
    run = run if isinstance(run, dict) else {}
    report = report if isinstance(report, dict) else {}
    has_account = account.get("account_initialized") is True
    return {
        "status": "WAIT", "actionable": False, "priority": "CHECK",
        "headline": "正在等待可信数据", "explanation": "",
        "next_step": "先保存真实账户估值。",
        "manual_only": True, "trading_enabled": False,
        "account_as_of": account.get("as_of") if has_account else None,
        "report_session": _iso_date(report.get("session_date")),
        "report_created_at": report.get("created_at"),
        "report_review_id": report.get("review_id"),
        "verified_run": run.get("status") == "SUCCEEDED" and run.get("qualified_online") is True
            and run.get("audit") == "PASS" and run.get("research_verification") == "PASS",
        "current_weights": None, "reference_weights": {"QQQ": .6, "TQQQ": .4, "QLD": 0.0, "CASH": 0.0},
        "step_weights": None, "steps": [], "conditions": [], "metrics": {},
        "evidence": [], "warnings": [],
        "historical_signal": _historical_signal(report, run),
        "portfolio_total_cny": None, "cash_current_cny": None,
        "limitations": "配置复核供人工研究，不等于下单指令、成交股数或个人风险承受能力评估。",
    }


def _wait(out: dict, status: str, headline: str, explanation: str, next_step: str) -> dict:
    out.update(status=status, actionable=False, priority="CHECK", headline=headline,
               explanation=explanation, next_step=next_step,
               steps=[], step_weights=None)
    return out


def decision_brief(account: dict | None, run: dict | None, report: dict | None) -> dict:
    """Return one safe, user-first decision with evidence, or explicit blockers."""
    out = _base(account, run, report)
    account = account if isinstance(account, dict) else {}
    run = run if isinstance(run, dict) else {}
    report = report if isinstance(report, dict) else {}

    if account.get("account_initialized") is not True:
        return _wait(out, "NEEDS_ACCOUNT", "还没有确认真实持仓",
                     "无法用演示账户或目标配置代替你实际拥有的资产。",
                     "进入「账户与设置」，保存真实人民币估值。")

    if run.get("status") == "FAILED":
        return _wait(out, "LAST_RUN_FAILED", "上一次运行没有通过",
                     "不能把旧报告当成今天的有效操作建议。",
                     "查看「运行报告」中的失败类型，修复后手动重跑。")
    if not out["verified_run"]:
        return _wait(out, "NEEDS_VERIFIED_RUN", "账户已保存，等待可信监控结论",
                     "账户数据可以读取，但尚无同时通过在线行情、账本审计和研究验证的最新运行。",
                     "打开「运行报告」执行一次在线核验；核验成功后才会生成配置复核。")

    if not report or not report.get("qualified_online") or report.get("demo") is not False:
        return _wait(out, "REPORT_UNAVAILABLE", "技术检查通过，但完整研究报告缺失",
                     "未能将通过的运行状态与相同账户版本的研究报告核对。",
                     "检查报告存储是否完整，重新运行并核对。")

    if not isinstance(report.get("review"), dict):
        return _wait(out, "REVIEW_UNAVAILABLE", "没有可核对的配置研究结论",
                     "这次运行没有提供策略复核的原始数据。",
                     "查看研究日志和行情有效性，不要从 PASS 推断应该买卖。")

    portfolio = report.get("portfolio")
    if not isinstance(portfolio, dict):
        return _wait(out, "ACCOUNT_MISMATCH", "账户与监控报告无法对应",
                     "报告缺少创建时的实际持仓快照。",
                     "刷新账户与行情后重新运行，不沿用上一次操作意见。")

    if portfolio.get("as_of") != account.get("as_of"):
        return _wait(out, "ACCOUNT_MISMATCH", "持仓估值已经更新，请重新分析",
                     "监控报告使用的估值日期与当前私有账户不同。",
                     "基于刚保存的持仓重新运行监控。")
    values = account.get("values")
    if not isinstance(values, dict):
        return _wait(out, "ACCOUNT_MISMATCH", "账户持仓数据不完整",
                     "当前无法逐项确认 QQQ、TQQQ、QLD 与现金的人民币估值。",
                     "核对真实持仓后重新运行。")
    for symbol in TICKERS:
        raw = values.get(symbol)
        expected = portfolio.get(PORTFOLIO_KEYS[symbol], None)
        if not isinstance(raw, str) or not raw.isdecimal() or type(expected) not in (int, float) or int(raw) != expected:
            return _wait(out, "ACCOUNT_MISMATCH", "持仓金额已变化，先更新结论",
                         "报告对应的资产金额与当前保存的账户不一致，旧建议不可继续使用。",
                         "重新运行监控，以最新真实账户生成研究结论。")

    if report.get("operation", {}).get("status") != "SUCCEEDED" or report.get("latest_attempt", {}).get("status") != "SUCCEEDED":
        return _wait(out, "REPORT_NOT_FINAL", "报告不是最新一次已完成的成功运行",
                     "验证通过属于过去某次记录，最新执行未形成可用结果。",
                     "检查最近一次运行状态和报告版本。")
    if report.get("is_actionable") is not True or report.get("market_session_current") is not True:
        return _wait(out, "MARKET_STALE", "行情曾通过验证，但已不是最新完整交易日",
                     "技术 PASS 只说明当时的数据一致，不代表此刻可以照旧调整。",
                     "更新至最新完整交易日行情，再复核配置。")
    if report.get("review", {}).get("status") != "ALLOCATION_REVIEW":
        return _wait(out, "MODEL_BLOCKED", "行情校验通过，但策略尚未形成配置意见",
                     "模型仍有条件未满足或仅能提供缓存复算。",
                     "查看策略条件；没有完整参考权重前维持人工观察。")

    review = report["review"]
    weights = review.get("next_review_weights")
    if not isinstance(weights, dict) or any(_number(weights.get(x)) is None for x in TICKERS):
        return _wait(out, "MODEL_BLOCKED", "本步配置数据不完整",
                     "缺少可审核的目标权重，不能凭文字猜测应如何调整。",
                     "重新核对策略报告和权重计算。")

    if any(not 0 <= float(weights[x]) <= 1 for x in TICKERS) or abs(sum(float(weights[x]) for x in TICKERS) - 1) > 1e-7:
        return _wait(out, "MODEL_BLOCKED", "模型权重未通过自检",
                     "本步所有资产占比必须在 0% 到 100% 之间，合计等于 100%。",
                     "检查策略权重计算，不使用异常结果。")

    reference = review.get("strategic_reference") or out["reference_weights"]
    if isinstance(reference, dict) and all(_number(reference.get(x)) is not None for x in TICKERS):
        out["reference_weights"] = {x: float(reference[x]) for x in TICKERS}
    total_cny = sum(int(values[x]) for x in TICKERS)
    if total_cny <= 0:
        return _wait(out, "ACCOUNT_MISMATCH", "账户资产总额异常",
                     "未确认正数资产总额，不能计算配置差异。",
                     "核对账户估值，再重新运行监控。")
    out["portfolio_total_cny"] = total_cny
    out["cash_current_cny"] = int(values["CASH"])
    out["current_weights"] = {x: int(values[x]) / total_cny for x in TICKERS}
    out["step_weights"] = {x: float(weights[x]) for x in TICKERS}
    actions = review.get("actions") or {}
    if not isinstance(actions, dict) or any(actions.get(x) not in ACTION_LABELS for x in ("QQQ", "TQQQ")):
        return _wait(out, "MODEL_BLOCKED", "模型操作字段不完整",
                     "暂时无法核对股票及杠杆 ETF 的具体复核动作。",
                     "查看原始模型结果。")

    for symbol in ("QQQ", "TQQQ"):
        current_weight = out["current_weights"][symbol]
        next_weight = out["step_weights"][symbol]
        expected_action = ("INCREASE_REVIEW" if next_weight > current_weight + 1e-9
                           else "REDUCE_REVIEW" if next_weight < current_weight - 1e-9
                           else "HOLD")
        if actions[symbol] != expected_action:
            return _wait(out, "MODEL_BLOCKED", "模型动作与配置权重不一致",
                         "文字中的增减动作不能和实际目标比例互相矛盾。",
                         "暂停配置复核，检查策略规则计算。")

    reason = review.get("tactical_reason")
    title, why = REASONS.get(reason, ("本轮仓位复核已生成", "参考模型给出了下一步权重，但还需要你人工核对账户和风险。"))
    steps = []
    for symbol in ("QQQ", "TQQQ"):
        current = out["current_weights"][symbol]
        future = out["step_weights"][symbol]
        code = actions[symbol]
        steps.append({
            "symbol": symbol,
            "action": code,
            "label": ACTION_LABELS[code],
            "current_weight": round(current, 6),
            "reference_weight": round(future, 6),
            "change_pp": round((future - current) * 100, 2),
            "current_value_cny": int(values[symbol]),
            "step_reference_value_cny": int(round(total_cny * future)),
            "estimated_difference_cny": int(round(total_cny * future)) - int(values[symbol]),
            "text": (f"{symbol}：{ACTION_LABELS[code]}（当前 {current:.1%} → 本步参考 {future:.1%}）"),
        })

    out.update(status="ACTION_REVIEW", actionable=True,
               priority="REVIEW" if any(s["action"] != "HOLD" for s in steps) else "HOLD",
               headline=title, explanation=why,
               next_step=("先核对真实估值、个人可承受回撤和交易成本；如认可策略，再由本人决定是否交易。"
                          if any(s["action"] != "HOLD" for s in steps)
                          else "维持当前持仓并观察下一交易日行情，不重复产生新交易。"),
               steps=steps, metrics={
                   "trend_active": review.get("trend_active") if type(review.get("trend_active")) is bool else None,
                   "qqq_vol20_pct": _number(review.get("qqq_vol20_pct")),
                   "full_reference_daily_exposure": _number(review.get("full_reference_daily_exposure")),
                   "next_review_daily_exposure": _number(review.get("next_review_daily_exposure")),
                   "risk_annual_volatility": _number((report.get("risk") or {}).get("annual_volatility")),
                   "risk_tqqq_variance_share": _number((report.get("risk") or {}).get("tqqq_variance_share")),
               })
    conditions = review.get("entry_conditions") or []
    out["cash_step_reference_cny"] = int(round(total_cny * out["step_weights"]["CASH"]))
    out["estimated_cash_change_cny"] = (
        out["cash_step_reference_cny"] - out["cash_current_cny"]
    )
    # Reference CNY differences are not order quantities: they ignore price drift,
    # fees, spreads, tax, lot sizes, and current currency conversion.
    out["amounts_are_illustrative"] = True
    out["conditions"] = [
        {"label": str(x.get("rule", ""))[:160], "met": x.get("met")}
        for x in conditions if isinstance(x, dict) and type(x.get("met")) is bool
    ][:5]
    out["evidence"] = [
        {"label": "行情时点", "value": report.get("session_date")},
        {"label": "账户估值", "value": account.get("as_of")},
        {"label": "行情交叉校验", "value": run.get("qualified_online")},
        {"label": "账本校验", "value": run.get("audit")},
        {"label": "研究独立验证", "value": run.get("research_verification")},
    ]
    out["warnings"] = [
        "QQQ/TQQQ 配置复核是研究意见，尚未证明择时优于长期持有。",
        "TQQQ 追踪单日 3 倍波动，多日复利可能产生路径依赖和较大回撤。",
        "所有比例均为估值权重，不提供可执行股数、即时汇率或自动交易。",
    ]
    if review.get("account_valuation_current") is False:
        out["warnings"].append("账户估值日与模型使用的美股收盘日不同，交易前须再次核对报价与估值。")
    return out
