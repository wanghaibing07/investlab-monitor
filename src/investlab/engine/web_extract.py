"""Import TinyFish fetch evidence, never a new market-data vendor or price history.

The task orchestrator calls the connected fetch tool. Standalone Python consumes
its saved JSON response; no API key, paid browser agent, or second scheduler.
"""
import datetime as dt
import json
import math
from pathlib import Path
import monitor as m

URLS = {f'https://stockanalysis.com/etf/{s.lower()}/history/':(s,'STOCKANALYSIS') for s in m.SYMBOLS}
URLS.update({f'https://chartexchange.com/symbol/nasdaq-{s.lower()}/historical/':(s,'CHARTEXCHANGE') for s in m.SYMBOLS})


def cells(line): return [x.strip() for x in line.strip().strip('|').split('|')]


def parse_page(page, expected):
    url = page['url']; final = page.get('final_url',url)
    if url not in URLS or final != url: raise ValueError('Unapproved or redirected history URL')
    text = page.get('text',''); headers = None; found = []
    for line in text.splitlines():
        if not line.strip().startswith('|'): continue
        row = cells(line); lower = [x.casefold() for x in row]
        if lower and lower[0].startswith('date') and 'close' in lower:
            headers = lower; continue
        if headers is None or len(row) != len(headers): continue
        raw_date = row[0]
        try:
            try: date = dt.date.fromisoformat(raw_date)
            except ValueError: date = dt.datetime.strptime(raw_date,'%b %d, %Y').date()
        except ValueError: continue
        if date != expected: continue
        # Exact Close column: not Adj. Close, after-hours, bid, or header quote.
        price = float(row[headers.index('close')].replace(',','').removeprefix('$'))
        if not math.isfinite(price) or not 0 < price < 1e8: raise ValueError('Invalid daily-table close')
        found.append(price)
    if len(found) != 1: raise ValueError('Exactly one completed-session daily Close row required')
    symbol, source = URLS[url]
    return {'symbol':symbol,'source':source,'date':expected.isoformat(),'raw_close':found[0],
            'url':url,'quote_kind':'REGULAR_SESSION_DAILY_TABLE_CLOSE','collector':'TINYFISH_FETCH'}


def ensure_schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS web_fetch_evidence (
        evidence_sha256 TEXT PRIMARY KEY, collected_at TEXT NOT NULL,
        collector TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS web_table_closes (
        observation_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,trade_date TEXT NOT NULL,
        source TEXT NOT NULL,raw_close REAL NOT NULL CHECK(raw_close>0),source_url TEXT NOT NULL,
        quote_kind TEXT NOT NULL,evidence_sha256 TEXT NOT NULL REFERENCES web_fetch_evidence(evidence_sha256));''')


def import_tinyfish(payload, db=m.DB, now=None):
    now = now or m.utc_now(); expected = m.expected_close_session(now)
    if not isinstance(payload,dict) or not isinstance(payload.get('results'),list):
        raise ValueError('Expected the saved TinyFish fetch results object')
    quotes = []; errors = list(payload.get('errors') or []); seen = set()
    for page in payload['results']:
        if not isinstance(page,dict):
            errors.append({'error':'Invalid page result'}); continue
        try:
            quote = parse_page(page,expected); key = (quote['symbol'],quote['source'])
            if key in seen: raise ValueError('Duplicate website is not an independent source')
            seen.add(key); quotes.append(quote)
        except (KeyError,ValueError,TypeError) as exc:
            errors.append({'url':page.get('url'),'error':str(exc)})
    # Reject materially conflicting values before publishing any new quote.
    with m.conn(db) as c:
        for quote in quotes:
            ref = c.execute('SELECT raw_close FROM daily_prices WHERE symbol=? AND trade_date=?',
                            (quote['symbol'],expected.isoformat())).fetchone()
            if ref and abs(quote['raw_close']/ref[0]-1) > .005:
                errors.append({'url':quote['url'],'error':'CONFLICT_WITH_ADJUSTED_SERIES_RAW_CLOSE'})
                quotes = []; break
        for symbol in m.SYMBOLS:
            current=dict(c.execute('SELECT source,raw_close FROM web_closes WHERE symbol=? AND trade_date=?',
                                   (symbol,expected.isoformat())).fetchall())
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='web_table_closes'").fetchone():
                for source, price in c.execute('''SELECT w.source,w.raw_close FROM web_table_closes w
                    JOIN web_fetch_evidence e ON e.evidence_sha256=w.evidence_sha256
                    WHERE w.symbol=? AND w.trade_date=? ORDER BY e.collected_at,w.observation_id''',
                    (symbol,expected.isoformat())).fetchall(): current[source]=price
            current.update({q['source']:q['raw_close'] for q in quotes if q['symbol']==symbol})
            if len(current)>=2 and max(current.values())/min(current.values())-1 > .005:
                errors.append({'symbol':symbol,'error':'CROSS_SITE_CLOSE_CONFLICT'}); quotes=[]; break
    status = 'COMPLETE_6_OF_6' if len(quotes)==6 else ('PARTIAL' if quotes else 'FAILED')
    evidence_sha = m.sha(m.canonical(payload))
    with m.conn(db) as c:
        ensure_schema(c)
        c.execute('INSERT OR IGNORE INTO web_fetch_evidence VALUES(?,?,?,?,?)',
                  (evidence_sha,m.ztime(now),'TINYFISH_FETCH',status,m.canonical(payload)))
        for quote in quotes:
            identity = m.sha(m.canonical({'evidence':evidence_sha,'quote':quote}))[:24]
            c.execute('INSERT OR IGNORE INTO web_table_closes VALUES(?,?,?,?,?,?,?,?)',
                      (identity,quote['symbol'],quote['date'],quote['source'],quote['raw_close'],
                       quote['url'],quote['quote_kind'],evidence_sha))
    return {'status':status,'accepted_table_quotes':len(quotes),'requested_url_count':len(URLS),
            'trade_date':expected.isoformat(),'evidence_sha256':evidence_sha,'errors':errors,
            'data_role':'RAW_CLOSE_CORROBORATION_ONLY_NOT_INDEPENDENT_ADJUSTED_HISTORY',
            'quotes':quotes}


def audit(db):
    with m.conn(db) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='web_fetch_evidence'").fetchone():
            return {'attempts':0,'evidence_hash_errors':0}
        rows = c.execute('SELECT evidence_sha256,payload_json FROM web_fetch_evidence').fetchall()
    return {'attempts':len(rows),'evidence_hash_errors':sum(m.sha(payload)!=sha for sha,payload in rows)}
