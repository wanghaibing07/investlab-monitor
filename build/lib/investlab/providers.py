"""Provider boundary: retained raw evidence -> strict completed daily bars.

Yahoo query1/query2 are two endpoints of ONE vendor, never independent sources.
"""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import urllib.request
from zoneinfo import ZoneInfo
from .core import atomic, canonical, digest, utcnow

NY = ZoneInfo("America/New_York")


def parse_yahoo(payload, symbol, cutoff, is_session):
    chart = payload.get("chart", {})
    if chart.get("error"): raise ValueError("Yahoo returned an error")
    results = chart.get("result")
    if not isinstance(results, list) or len(results) != 1: raise ValueError("Unexpected chart result count")
    item = results[0]; meta = item.get("meta", {})
    if meta.get("symbol", "").upper() != symbol or meta.get("dataGranularity") != "1d":
        raise ValueError("Symbol or daily interval mismatch")
    stamps = item.get("timestamp") or []
    ind = item.get("indicators", {}); quotes = ind.get("quote") or []; adjusted = ind.get("adjclose") or []
    if len(quotes) != 1 or len(adjusted) != 1: raise ValueError("Missing raw/adjusted quote series")
    raw = quotes[0].get("close") or []; adj = adjusted[0].get("adjclose") or []
    if not stamps or len(stamps) != len(raw) or len(raw) != len(adj): raise ValueError("Quote array lengths differ")
    rows = []; seen = set(); previous = None
    for stamp, a, b in zip(stamps, adj, raw):
        day = datetime.fromtimestamp(stamp, NY).date()
        if day > cutoff: continue  # Intraday unfinished bar is deliberately excluded.
        if not is_session(day): raise ValueError("Non-session daily quote")
        if day in seen or previous is not None and day <= previous: raise ValueError("Duplicate/unsorted vendor dates")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 < v < 1e8 for v in (a, b)):
            raise ValueError("Invalid completed-session price")
        seen.add(day); previous = day
        rows.append({"date": day.isoformat(), "adjusted_close": float(a), "raw_close": float(b)})
    if not rows or rows[-1]["date"] != cutoff.isoformat(): raise ValueError("Latest completed session missing")
    return rows


def yahoo(symbol, domain="query1.finance.yahoo.com", timeout=9, now=None):
    import monitor as m
    if symbol not in ("QQQ", "TQQQ") or domain not in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        raise ValueError("Unsupported provider request")
    now = now or m.utc_now(); cutoff = m.expected_close_session(now)
    end = int(now.timestamp()); start = 1265673600
    url = f"https://{domain}/v8/finance/chart/{symbol}?period1={start}&period2={end}&interval=1d&events=div%2Csplits"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 InvestLab/6.0", "Accept": "application/json"})
    limit = 6_000_000
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(limit + 1)
    if len(raw) > limit: raise ValueError("Provider response exceeds size limit")
    payload = json.loads(raw)
    identity = hashlib.sha256(raw).hexdigest()
    root = Path(os.environ["INVESTLAB_HOME"]) / "data/provider-evidence"
    atomic(root / (identity + ".json"), raw)
    metadata = {"provider": "YAHOO", "endpoint": domain, "url": url, "fetched_at": utcnow(),
                "symbol": symbol, "cutoff": cutoff.isoformat(), "raw_sha256": identity}
    try:
        rows = parse_yahoo(payload, symbol, cutoff, m.is_regular_session)
        metadata.update(status="VALIDATED", rows=len(rows), semantic_sha256=digest(rows))
    except Exception as exc:
        metadata.update(status="REJECTED", error=str(exc)); atomic(root / (identity + ".meta.json"), metadata); raise
    atomic(root / (identity + ".meta.json"), metadata)
    return rows
