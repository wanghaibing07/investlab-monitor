"""Read-only Alpaca PAPER account snapshot; explicitly separate from live accounts.

No order endpoints, shared API credentials, or implicit CNY account mutation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import urllib.error
import urllib.request

PAPER_BASE = "https://paper-api.alpaca.markets"
ALLOWED_PATHS = frozenset({"/v2/account", "/v2/positions"})
ASSETS = {"QQQ": Decimal("1"), "TQQQ": Decimal("3")}


def decimal(value, field):
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError()
        return number
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid Alpaca numerical field: " + field) from exc


def paper_get(path, *, opener=None):
    """Allowlist GET endpoints and an immutable paper-trading hostname."""
    if path not in ALLOWED_PATHS:
        raise ValueError("Forbidden Alpaca paper endpoint")
    key = os.getenv("APCA_API_KEY_ID", "").strip()
    secret = os.getenv("APCA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        raise ValueError("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY in the private process environment")
    request = urllib.request.Request(
        PAPER_BASE + path,
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                 "Accept": "application/json"},
        method="GET",
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=12) as response:
            body = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Alpaca paper API HTTP {exc.code} for {path}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Alpaca paper API connection failed for " + path) from None
    if len(body) > 2_000_000:
        raise ValueError("Alpaca paper response is too large")
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Alpaca paper response is not valid JSON") from None
    if not isinstance(parsed, (dict, list)):
        raise ValueError("Alpaca paper response has unexpected shape")
    return parsed


def normalize(account, positions):
    """Keep asset class/currency explicit. Never equate paper USD with CNY holdings."""
    if not isinstance(account, dict) or not isinstance(positions, list):
        raise ValueError("Unexpected Alpaca paper account payload")
    if account.get("currency") != "USD" or account.get("status") != "ACTIVE":
        raise ValueError("Alpaca paper account must be ACTIVE and denominated in USD")
    equity = decimal(account.get("equity"), "equity")
    cash = decimal(account.get("cash"), "cash")
    if equity <= 0:
        raise ValueError("Paper account equity must be positive")
    known = {symbol: Decimal("0") for symbol in ASSETS}
    unknown = {}
    seen = set()
    for pos in positions:
        if not isinstance(pos, dict):
            raise ValueError("Unexpected Alpaca position")
        symbol = pos.get("symbol")
        if not isinstance(symbol, str) or not symbol or symbol in seen:
            raise ValueError("Invalid/duplicate Alpaca position symbol")
        seen.add(symbol)
        amount = decimal(pos.get("market_value"), "position.market_value")
        if pos.get("side") not in (None, "long") or amount < 0:
            raise ValueError("Short or negative paper position is outside this long-only monitor")
        if symbol in known and pos.get("asset_class", "us_equity") == "us_equity":
            known[symbol] += amount
        else:
            unknown[symbol] = amount
    total_positions = sum(known.values()) + sum(unknown.values())
    # Broker values have small real-time price timing differences, hence a tolerance.
    if total_positions > equity * Decimal("1.02"):
        raise ValueError("Alpaca positions exceed reported paper equity")
    q = known["QQQ"] / equity
    t = known["TQQQ"] / equity
    exposure = q + Decimal("3") * t
    scenarios = {}
    for change in ("-0.10", "-0.05", "0.05", "0.10"):
        move = Decimal(change)
        scenarios[f"{int(move*100):+d}%"] = round(float(exposure * move * 100), 2)
    return {
        "source": "ALPACA_PAPER_READ_ONLY",
        "status": "PAPER_ACCOUNT_SNAPSHOT",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "currency": "USD",
        "equity_usd": str(equity),
        "cash_usd": str(cash),
        "positions_usd": {s: str(v) for s, v in known.items()},
        "other_symbols": sorted(unknown),
        "other_positions_value_usd": str(sum(unknown.values())),
        "known_weights": {s: round(float(v/equity), 6) for s, v in known.items()},
        "known_daily_index_exposure_proxy": round(float(exposure), 6),
        "simple_one_day_index_scenarios_pct": scenarios,
        "scenario_coverage": "PARTIAL_OTHER_HOLDINGS" if unknown else "QQQ_TQQQ_CASH_ONLY",
        "hypothetical_only": True,
        "execution_enabled": False,
        "account_ledger_mutated": False,
        "limitations": "Approximate one-day index sensitivity only; ignores tracking error, fees, path dependency and FX. Not a price forecast.",
    }


def snapshot(*, opener=None):
    account = paper_get("/v2/account", opener=opener)
    positions = paper_get("/v2/positions", opener=opener)
    return normalize(account, positions)
