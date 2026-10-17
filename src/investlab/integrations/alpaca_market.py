"""Independent *contextual* Alpaca IEX historical-bar comparison.

It never changes model prices, validations, portfolio allocation or trading.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo
from ..core import connection, utcnow

DATA_BASE = "https://data.alpaca.markets/v2/stocks/bars"
SYMBOLS = ("QQQ", "TQQQ")
NEW_YORK = ZoneInfo("America/New_York")


def fetch_iex(date_iso, *, opener=None):
    trading_day = date.fromisoformat(date_iso)
    key = os.environ.get("APCA_API_KEY_ID", "").strip()
    secret = os.environ.get("APCA_API_SECRET_KEY", "").strip()
    if not key or not secret:
        raise ValueError("Alpaca paper market comparison requires private APCA_API_KEY_ID and APCA_API_SECRET_KEY")
    args = urllib.parse.urlencode({
        "symbols": ",".join(SYMBOLS), "timeframe": "1Day",
        "start": trading_day.isoformat(),
        "end": (trading_day + timedelta(days=1)).isoformat(),
        "adjustment": "all", "feed": "iex", "limit": "100"
    })
    req = urllib.request.Request(
        DATA_BASE + "?" + args,
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                 "Accept": "application/json"}, method="GET")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=15) as response:
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Alpaca IEX market API HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Alpaca IEX market API unavailable") from None
    if len(raw) > 1_000_000:
        raise ValueError("Alpaca bar response exceeds maximum size")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Alpaca bar response is invalid JSON") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("bars"), dict) or doc.get("next_page_token"):
        raise ValueError("Alpaca bar response incomplete or unexpected")
    result = {}
    for symbol in SYMBOLS:
        candles = doc["bars"].get(symbol, [])
        if not isinstance(candles, list):
            raise ValueError("Invalid Alpaca bar list")
        matches = []
        for candle in candles:
            if not isinstance(candle, dict):
                raise ValueError("Invalid Alpaca bar")
            stamp = datetime.fromisoformat(str(candle.get("t", "")).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Alpaca daily bar lacks timezone")
            if stamp.astimezone(NEW_YORK).date() == trading_day:
                try:
                    close = Decimal(str(candle.get("c")))
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError("Invalid Alpaca close") from exc
                if not close.is_finite() or close <= 0:
                    raise ValueError("Alpaca close must be positive and finite")
                matches.append(close)
        if len(matches) > 1:
            raise ValueError("Duplicate Alpaca daily bars")
        result[symbol] = matches[0] if matches else None
    return result


def check(home, *, opener=None):
    """A second provider's single-exchange observations are NOT a validated SIP close."""
    from ..service import settings
    if settings(home).get("demo") is True:
        raise ValueError("Cannot compare real IEX prices with synthetic demo data")
    local = {}
    with connection(home, readonly=True) as conn:
        for symbol in SYMBOLS:
            row = conn.execute(
                "SELECT trade_date, adjusted_close FROM daily_prices "
                "WHERE symbol=? ORDER BY trade_date DESC LIMIT 1", (symbol,)).fetchone()
            if row is None:
                raise ValueError(f"Local completed historical prices missing for {symbol}")
            local[symbol] = (row["trade_date"], Decimal(str(row["adjusted_close"])))
    session = local["QQQ"][0]
    if any(x[0] != session for x in local.values()):
        raise ValueError("QQQ/TQQQ local session mismatch")
    external = fetch_iex(session, opener=opener)
    comparisons = {}
    for symbol in SYMBOLS:
        local_close = local[symbol][1]
        if not local_close.is_finite() or local_close <= 0:
            raise ValueError("Invalid local adjusted price")
        vendor_close = external[symbol]
        pct = abs((vendor_close/local_close - 1) * 100) if vendor_close is not None else None
        comparisons[symbol] = {
            "local_adjusted_close": str(local_close),
            "alpaca_iex_adjusted_close": str(vendor_close) if vendor_close is not None else None,
            "relative_difference_pct": round(float(pct), 4) if pct is not None else None,
            "within_context_tolerance_1pct": pct is not None and pct <= 1
        }
    available = all(v["relative_difference_pct"] is not None for v in comparisons.values())
    agrees = available and all(v["within_context_tolerance_1pct"] for v in comparisons.values())
    return {
        "status": "CONTEXT_AGREEMENT" if agrees else ("SOURCE_DISAGREEMENT" if available else "INCOMPLETE"),
        "checked_at": utcnow(), "session_date": session,
        "local_source": "YAHOO_OR_PREVIOUSLY_IMPORTED_ADJUSTED_PRICES",
        "external_source": "ALPACA_IEX_SINGLE_EXCHANGE",
        "feed": "iex", "adjustment": "all",
        "comparisons": comparisons,
        "used_for_trading": False, "changes_strategy_signal": False,
        "meaning": "A single-exchange IEX close and Yahoo-adjusted close may differ. Context agreement is not SIP or official closing price verification."
    }
