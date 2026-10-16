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


def parse_alpaca_daily_evidence(pages, *, symbol, completed_session, is_session,
                               feed, adjustment, retrieved_at, expected_sessions=None):
    """Optional read-only adapter; never called by Yahoo or the production run.

    Each page is (original response bytes, query metadata). Raw and adjusted
    requests remain separate. A surviving next_page_token blocks certification.
    """
    from .engine.research.qualified_bars import QualifiedDailyBar, validate, source_failure
    if not pages:raise ValueError('EMPTY_PROVIDER_EVIDENCE')
    if feed not in ('sip','iex'):raise ValueError('UNSUPPORTED_EVIDENCE_FEED')
    bars=[];last_token=None;hashes=[];queries=[]
    for raw,query in pages:
        if not isinstance(raw,bytes):raise ValueError('ORIGINAL_RESPONSE_BYTES_REQUIRED')
        if query.get('feed')!=feed or query.get('adjustment')!=adjustment or query.get('timeframe') not in ('1Day','1D'):
            raise ValueError('PROVIDER_QUERY_CONTRACT_MISMATCH')
        if query.get('page_token')!=last_token:raise ValueError('PROVIDER_PAGE_CHAIN_MISMATCH')
        obj=json.loads(raw)
        if obj.get('http_status') in (401,403):return {'qualification':source_failure(obj['http_status']),'bars':[]}
        sha=hashlib.sha256(raw).hexdigest();hashes.append(sha);queries.append(query)
        obj=obj.get('data',obj);last_token=obj.get('next_page_token')
        for r in obj.get('bars',{}).get(symbol,[]):
            day=datetime.fromisoformat(r['t'].replace('Z','+00:00')).astimezone(NY).date().isoformat()
            # All-adjusted OHLC is not raw OHLC. Leave it separate and do not certify raw agreement.
            if adjustment!='raw':raise ValueError('ADJUSTED_ALPACA_REQUIRES_SEPARATE_RAW_JOIN')
            bars.append(QualifiedDailyBar(symbol,day,'ALPACA',feed,adjustment,r['c'],None,
                        retrieved_at,sha,None,r.get('o'),r.get('h'),r.get('l')))
    qualified=validate(bars,completed_session,is_session,next_page_token=last_token,expected_sessions=expected_sessions)
    return {'qualification':qualified,'bars':bars,'original_payload_hashes':hashes,'queries':queries,
            'data_role':'OPTIONAL_RAW_CORROBORATION_ONLY','production_grade_changed':False}


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
