"""Explicit confirmed events with Decimal arithmetic. No signal can write trades."""
from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from .core import canonical, connection, digest, schema, utcnow

KINDS = {"DEPOSIT", "WITHDRAWAL", "BUY", "SELL", "DIVIDEND", "FEE", "SPLIT", "OPENING_POSITION", "VOID", "REPORTED_BUY"}
CURRENCIES = {"USD", "CNY", "HKD"}
SYMBOLS = {"QQQ", "QLD", "TQQQ"}


def number(value, *, positive=False):
    if isinstance(value, (float, bool)):
        raise ValueError("账本数字请使用十进制字符串，例如 '10.25'")
    try:
        v = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("无效账本数字") from exc
    if not v.is_finite() or v < 0 or (positive and v <= 0):
        raise ValueError("金额或数量必须是有限非负数")
    if len(v.as_tuple().digits) > 28 or abs(v.as_tuple().exponent) > 12:
        raise ValueError("数字精度过大")
    return v


def normalize(event):
    if set(event) - {"event_id", "account", "occurred_at", "kind", "currency", "symbol", "amount", "quantity", "price", "fee", "ratio", "confirmed", "note", "reverses_event_id", "evidence_level", "source", "amount_is_approximate"}:
        raise ValueError("未知交易字段")
    if event.get("confirmed") is not True:
        raise ValueError("只接收已确认的真实流水")
    e = dict(event)
    for k in ("event_id", "account", "occurred_at"):
        if not isinstance(e.get(k), str) or not e[k] or len(e[k]) > 160:
            raise ValueError("缺少或无效字段: " + k)
    if e.get("kind") == "REPORTED_BUY":
        allowed = {"event_id", "account", "occurred_at", "kind", "currency", "symbol", "amount", "confirmed", "note", "evidence_level", "source", "amount_is_approximate"}
        if set(e) - allowed or e.get("symbol") not in SYMBOLS or e.get("currency") not in CURRENCIES:
            raise ValueError("买入事实报告不能补造成交份额、价格或费用")
        if e.get("evidence_level") != "USER_REPORTED" or not e.get("source") or not e.get("note"):
            raise ValueError("买入事实报告需要用户来源和未知项说明")
        # Date precision is preserved; no invented execution time or FX conversion.
        if len(e["occurred_at"]) != 10 or date.fromisoformat(e["occurred_at"]) > date.today():
            raise ValueError("买入事实报告只接收非未来的明确日期")
        if not isinstance(e.get("amount_is_approximate"), bool):
            raise ValueError("需明确报告金额是否近似")
        e["amount"] = str(number(e.get("amount"), positive=True))
        return e
    if set(e) & {"evidence_level", "source", "amount_is_approximate"}:
        raise ValueError("事实报告字段只能用于REPORTED_BUY")
    stamp = datetime.fromisoformat(e["occurred_at"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("流水时间必须带时区")
    if stamp > datetime.fromisoformat(utcnow()):
        raise ValueError("未来流水不能作为已成交记录")
    e["occurred_at"] = stamp.astimezone(__import__('datetime').timezone.utc).isoformat()
    if e.get("kind") not in KINDS or e.get("currency") not in CURRENCIES:
        raise ValueError("不支持的流水类型或币种")
    kind = e["kind"]
    if kind in {"BUY", "SELL", "SPLIT", "OPENING_POSITION", "DIVIDEND"} and e.get("symbol") not in SYMBOLS:
        raise ValueError("无效证券代码")
    fields = {"BUY": ("quantity", "price"), "SELL": ("quantity", "price"),
              "OPENING_POSITION": ("quantity",), "SPLIT": ("ratio",), "VOID": ()}.get(kind, ("amount",))
    for k in fields:
        e[k] = str(number(e.get(k), positive=True))
    e["fee"] = str(number(e.get("fee", "0")))
    if kind not in ("BUY", "SELL") and number(e["fee"]) != 0:
        raise ValueError("非买卖费用请独立记录FEE流水")
    if kind == "VOID" and (not isinstance(e.get("reverses_event_id"), str) or not e["reverses_event_id"] or not e.get("note")):
        raise ValueError("纠正流水必须引用原ID并说明原因")
    return e


def replay(events):
    cash = {}; holdings = {}; basis = {}; realized = {}; dividends = {}
    D = Decimal
    by_id = {e["event_id"]: e for e in events}; voided = set()
    for e in events:
        if e["kind"] != "VOID": continue
        original = by_id.get(e["reverses_event_id"])
        if not original or original["kind"] == "VOID" or original["account"] != e["account"] or original["currency"] != e["currency"]:
            raise ValueError("纠正引用必须是同账户同币种的原始流水")
        if original["occurred_at"] > e["occurred_at"] or original["event_id"] in voided:
            raise ValueError("纠正不能先于原流水，也不能重复作废")
        voided.add(original["event_id"])
    for e in sorted((e for e in events if e["kind"] != "VOID" and e["event_id"] not in voided), key=lambda x: (x["occurred_at"], x["event_id"])):
        if e["kind"] == "REPORTED_BUY":
            continue  # Evidence of activity; never an inferred cash debit or share lot.
        currency = e["currency"]; kind = e["kind"]; symbol = e.get("symbol")
        cash.setdefault(currency, D(0))
        key = (symbol, currency)
        if kind == "DEPOSIT": cash[currency] += D(e["amount"])
        elif kind in ("WITHDRAWAL", "FEE"): cash[currency] -= D(e["amount"])
        elif kind == "DIVIDEND":
            cash[currency] += D(e["amount"])
            dividends[currency] = dividends.get(currency, D(0)) + D(e["amount"])
        elif kind == "OPENING_POSITION":
            holdings[key] = holdings.get(key, D(0)) + D(e["quantity"])
            # Cost cannot be inferred from an opening quantity.
            basis[key] = None
        elif kind == "SPLIT":
            if holdings.get(key, D(0)) <= 0: raise ValueError("拆股前缺少持仓")
            holdings[key] *= D(e["ratio"])
        else:
            qty, price, fee = D(e["quantity"]), D(e["price"]), D(e["fee"])
            old = holdings.get(key, D(0))
            if kind == "BUY":
                cash[currency] -= qty * price + fee
                holdings[key] = old + qty
                basis[key] = ((D(0) if old == 0 else basis.get(key, D(0))) + qty * price + fee) if old == 0 or basis.get(key, D(0)) is not None else None
            else:
                if qty > old: raise ValueError("卖出数量超过已确认持仓")
                cash[currency] += qty * price - fee
                sold_cost = basis[key] * qty / old if basis.get(key) is not None else None
                realized[currency] = (realized.get(currency, D(0)) + qty * price - fee - sold_cost) if sold_cost is not None and realized.get(currency, D(0)) is not None else None
                holdings[key] = old - qty
                basis[key] = basis[key] - sold_cost if sold_cost is not None else None
        if cash[currency] < 0:
            raise ValueError("流水会导致负现金，请补齐入金/成交先后顺序")
    reports = [e for e in events if e["kind"] == "REPORTED_BUY" and e["event_id"] not in voided]
    return {"cash": {k: str(v) for k, v in cash.items()},
            "positions": [{"symbol": s, "currency": c, "quantity": str(q),
                           "cost_basis": str(basis[(s, c)]) if basis.get((s, c)) is not None else None}
                          for (s, c), q in sorted(holdings.items())],
            "realized_pnl": {k: str(v) if v is not None else None for k, v in realized.items()},
            "dividends": {k: str(v) for k, v in dividends.items()},
            "voided_event_ids": sorted(voided), "reported_activity": reports,
            "position_detail_complete": not reports,
            "cost_method": "WEIGHTED_AVERAGE_NOT_TAX_ACCOUNTING"}


def import_events(home, incoming):
    """Atomic batch, stable broker IDs, reject changed duplicate IDs."""
    if not isinstance(incoming, list) or not incoming:
        raise ValueError("流水必须是非空JSON数组")
    normalized = [normalize(e) for e in incoming]
    schema(home)
    with connection(home) as c:
        c.execute("BEGIN IMMEDIATE")
        existing = {r["event_id"]: json.loads(r["event_json"]) for r in c.execute("SELECT * FROM journal_events")}
        inserted = 0
        for e in normalized:
            if e["event_id"] in existing:
                if digest(existing[e["event_id"]]) != digest(e): raise ValueError("同一流水ID内容冲突")
                continue
            existing[e["event_id"]] = e
            c.execute("INSERT INTO journal_events VALUES(?,?,?,?,?,?)", (e["event_id"], e["account"], e["occurred_at"], utcnow(), canonical(e), digest(e)))
            inserted += 1
        for account in {e["account"] for e in normalized}:
            replay([e for e in existing.values() if e["account"] == account])
    return {"inserted": inserted, "duplicate": len(normalized) - inserted,
            "reported_activity_count": sum(e["kind"] == "REPORTED_BUY" for e in normalized),
            "accounts": sorted({e["account"] for e in normalized})}


def account(home, name):
    with connection(home, readonly=True) as c:
        events = [json.loads(r[0]) for r in c.execute("SELECT event_json FROM journal_events WHERE account=? ORDER BY occurred_at,event_id", (name,))]
    return {"account": name, "event_count": len(events), **replay(events)}


def valuation(home, value):
    """User-provided complete valuation, not a trade or an inferred share count."""
    required = {"valuation_id", "account", "as_of", "currency", "values", "confirmed", "note"}
    if not required <= set(value) or set(value) - required - {"reconciles_event_ids"}:
        raise ValueError("估值需提供valuation_id/account/as_of/currency/values/confirmed/note")
    if value["confirmed"] is not True or value["currency"] != "CNY":
        raise ValueError("当前账户估值入口接收明确确认的人民币估值")
    if date.fromisoformat(value["as_of"]) > date.today(): raise ValueError("不能确认未来估值")
    if not all(isinstance(value[k], str) and value[k] for k in ("valuation_id", "account", "note")):
        raise ValueError("缺少估值身份或来源说明")
    if set(value["values"]) != {"QQQ", "QLD", "TQQQ", "CASH"}: raise ValueError("需明确四项估值，零持仓填写0")
    values = {k: number(v) for k, v in value["values"].items()}
    if sum(values.values()) <= 0: raise ValueError("总资产必须大于0")
    reconciles = value.get("reconciles_event_ids", [])
    if not isinstance(reconciles, list) or any(not isinstance(x, str) or not x for x in reconciles) or len(reconciles) != len(set(reconciles)):
        raise ValueError("估值核对事件ID必须为不重复的字符串列表")
    # Legacy baseline is integer CNY, so refuse to silently lose cents.
    if any(v != v.to_integral_value() for v in values.values()):
        raise ValueError("聚合估值兼容接口目前使用整数人民币，请显式取整后确认")
    schema(home)
    with connection(home) as c:
        c.execute("BEGIN IMMEDIATE")
        for event_id in reconciles:
            event = c.execute("SELECT account,occurred_at FROM journal_events WHERE event_id=?", (event_id,)).fetchone()
            if not event or event["account"] != value["account"] or event["occurred_at"][:10] > value["as_of"]:
                raise ValueError("估值只能核对同账户且不晚于估值日的真实事件")
        old = c.execute("SELECT payload FROM account_valuations WHERE valuation_id=?", (value["valuation_id"],)).fetchone()
        if old:
            if digest(json.loads(old[0])) != digest(value): raise ValueError("同一估值ID内容冲突")
            return {"duplicate": True}
        prior = c.execute("SELECT max(as_of) FROM account_valuations WHERE account=?", (value["account"],)).fetchone()[0]
        if value["account"] == "default":
            legacy_date = c.execute("SELECT max(as_of) FROM portfolio_baselines").fetchone()[0]
            prior = max(x for x in (prior, legacy_date) if x) if prior or legacy_date else None
        if prior and value["as_of"] < prior: raise ValueError("历史估值不可替换最新账户基线")
        c.execute("INSERT INTO account_valuations VALUES(?,?,?,?,?,?)", (value["valuation_id"], value["account"], value["as_of"], utcnow(), canonical(value), digest(value)))
        if value["account"] == "default":
            c.execute("INSERT INTO portfolio_baselines(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,qld_value_cny,note) VALUES(?,?,?,?,?,?,?)", (utcnow(), value["as_of"], int(values["QQQ"]), int(values["CASH"]), int(values["TQQQ"]), int(values["QLD"]), value["note"]))
    return {"duplicate": False, "valuation_id": value["valuation_id"], "trades_created": 0}
