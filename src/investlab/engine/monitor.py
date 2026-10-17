"""Read-only QQQ/TQQQ investment monitor. Python stdlib only, SQLite is source of truth.

Financial values supplied by the user are RMB mark-to-market estimates, not shares or trade lots.
Signals represent conditions for manual review; this software NEVER places orders.
"""
from __future__ import annotations
import argparse
import calendar
from contextlib import contextmanager, closing
import csv
import datetime as dt
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
DATA_ROOT=Path(os.environ.get('INVESTLAB_HOME',str(ROOT))).expanduser().resolve()/'data'
DB=DATA_ROOT/'monitor.sqlite3'
LEGACY_SYMBOLS=('QQQ','TQQQ')
SYMBOLS=('QQQ','QLD','TQQQ')
ACTIVE_SYMBOLS=('QQQ','TQQQ')
BEIJING=ZoneInfo('Asia/Shanghai')
NEW_YORK=ZoneInfo('America/New_York')
UA='Mozilla/5.0 QQQ-TQQQ-read-only-monitor/5.5'

def utc_now():return dt.datetime.now(dt.timezone.utc)
def ztime(t=None):return (t or utc_now()).astimezone(BEIJING).isoformat(timespec='seconds')
def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def sha(x):return hashlib.sha256(x.encode('utf8')).hexdigest()
def atomic_write(p:Path,b:bytes):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.tmp')
    with open(tmp,'wb') as f:
        f.write(b);f.flush();os.fsync(f.fileno())
    os.replace(tmp,p)

@contextmanager
def conn(db=DB):
    db=Path(db);db.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(db,timeout=10)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL')
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()

def init_db(db=DB):
    with conn(db) as c:
        c.executescript('''
            CREATE TABLE IF NOT EXISTS portfolio_baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                as_of TEXT NOT NULL,
                qqq_value_cny INTEGER NOT NULL CHECK(qqq_value_cny>=0),
                cash_cny INTEGER NOT NULL CHECK(cash_cny>=0),
                tqqq_value_cny INTEGER NOT NULL DEFAULT 0 CHECK(tqqq_value_cny>=0),
                detail_level TEXT NOT NULL DEFAULT 'aggregate_value_no_shares',
                note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS daily_prices (
                symbol TEXT NOT NULL CHECK(symbol IN ('QQQ','QLD','TQQQ')),
                trade_date TEXT NOT NULL,
                adjusted_close REAL NOT NULL CHECK(adjusted_close>0),
                raw_close REAL NOT NULL CHECK(raw_close>0),
                source TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY(symbol,trade_date));
            CREATE TABLE IF NOT EXISTS price_imports (
                id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                source TEXT NOT NULL, downloaded_at TEXT NOT NULL,
                first_date TEXT NOT NULL, last_date TEXT NOT NULL,
                raw_checksum TEXT NOT NULL, observations INTEGER NOT NULL,
                result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS web_closes (
                symbol TEXT NOT NULL CHECK(symbol IN ('QQQ','QLD','TQQQ')),
                trade_date TEXT NOT NULL,
                source TEXT NOT NULL,
                raw_close REAL NOT NULL CHECK(raw_close>0),
                source_url TEXT NOT NULL,
                verified_at TEXT NOT NULL,
                PRIMARY KEY(symbol,trade_date,source));
            CREATE TABLE IF NOT EXISTS monitor_runs (
                run_id TEXT PRIMARY KEY, run_at TEXT NOT NULL,
                mode TEXT NOT NULL, data_status TEXT NOT NULL,
                report_sha256 TEXT NOT NULL, report_json TEXT NOT NULL);
        ''')
        # Preserve all historical baselines while allowing a future user-confirmed
        # TQQQ valuation. Earlier schemas accidentally prohibited any TQQQ holding.
        sql=c.execute("SELECT sql FROM sqlite_master WHERE name='portfolio_baselines'").fetchone()[0]
        if 'CHECK(tqqq_value_cny=0)' in sql.replace(' ',''):
            c.execute('''CREATE TABLE portfolio_baselines_v52 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,recorded_at TEXT NOT NULL,as_of TEXT NOT NULL,
                qqq_value_cny INTEGER NOT NULL CHECK(qqq_value_cny>=0),
                cash_cny INTEGER NOT NULL CHECK(cash_cny>=0),
                tqqq_value_cny INTEGER NOT NULL DEFAULT 0 CHECK(tqqq_value_cny>=0),
                detail_level TEXT NOT NULL DEFAULT 'aggregate_value_no_shares',note TEXT NOT NULL)''')
            c.execute('INSERT INTO portfolio_baselines_v52 SELECT * FROM portfolio_baselines')
            c.execute('DROP TABLE portfolio_baselines')
            c.execute('ALTER TABLE portfolio_baselines_v52 RENAME TO portfolio_baselines')
        if 'qld_value_cny' not in {r[1] for r in c.execute('PRAGMA table_info(portfolio_baselines)')}:
            c.execute('ALTER TABLE portfolio_baselines ADD COLUMN qld_value_cny INTEGER NOT NULL DEFAULT 0 CHECK(qld_value_cny>=0)')
        # Expand only price-table constraints; preserve every row and primary key.
        for table in ('daily_prices','web_closes'):
            original=c.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
            if "'QLD'" not in original:
                temporary=table+'_v54'
                statement=original.replace('CREATE TABLE '+table,'CREATE TABLE '+temporary).replace("('QQQ','TQQQ')","('QQQ','QLD','TQQQ')")
                c.execute(statement)
                c.execute('INSERT INTO '+temporary+' SELECT * FROM '+table)
                c.execute('DROP TABLE '+table)
                c.execute('ALTER TABLE '+temporary+' RENAME TO '+table)

def set_portfolio(qqq:int,cash:int,asof=None,note='用户明确确认的账户聚合价值',db=DB,*,tqqq=None,qld=None):
    if not (isinstance(qqq,int) and isinstance(cash,int) and qqq>=0 and cash>=0):
        raise ValueError("Cash and QQQ value must be nonnegative integer RMB amounts")
    asof=asof or utc_now().astimezone(BEIJING).date().isoformat()
    dt.date.fromisoformat(asof)
    init_db(db)
    with conn(db) as c:
        latest=c.execute('SELECT * FROM portfolio_baselines ORDER BY id DESC LIMIT 1').fetchone()
        tqqq=(latest['tqqq_value_cny'] if latest else 0) if tqqq is None else tqqq
        if not isinstance(tqqq,int) or tqqq<0:raise ValueError('TQQQ value must be nonnegative integer RMB')
        qld=(latest['qld_value_cny'] if latest else 0) if qld is None else qld
        if not isinstance(qld,int) or qld<0:raise ValueError('QLD value must be nonnegative integer RMB')
        if latest and (latest['qqq_value_cny'],latest['cash_cny'],latest['tqqq_value_cny'],latest['qld_value_cny'],latest['as_of'])==(qqq,cash,tqqq,qld,asof):
            return latest['id']
        cur=c.execute('INSERT INTO portfolio_baselines(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,qld_value_cny,note) VALUES (?,?,?,?,?,?,?)',
                      (ztime(),asof,qqq,cash,tqqq,qld,note))
        return cur.lastrowid

def portfolio(db=DB):
    with conn(db) as c:
        r=c.execute('SELECT * FROM portfolio_baselines ORDER BY id DESC LIMIT 1').fetchone()
        return dict(r) if r else None

def validate(rows):
    clean=[];seen={}
    for r in rows:
        try:
            date=dt.date.fromisoformat(str(r['date']))
            adj=float(r['adjusted_close']);raw=float(r.get('raw_close',adj))
            if not (math.isfinite(adj) and math.isfinite(raw) and 0<adj<1e8 and 0<raw<1e8):continue
            if date>dt.date.today()+dt.timedelta(days=2):continue
            item={'date':date.isoformat(),'adjusted_close':adj,'raw_close':raw}
            if date.isoformat() in seen and seen[date.isoformat()] != item:
                raise RuntimeError('Conflicting duplicate price row: '+date.isoformat())
            seen[date.isoformat()]=item
        except (TypeError,ValueError,KeyError,OverflowError):continue
    for d in sorted(seen):clean.append(seen[d])
    if not clean:raise ValueError('No valid daily price rows')
    return clean

def ingest(sym,rows,source,downloaded_at=None,db=DB):
    if sym not in SYMBOLS:raise ValueError('Unsupported ticker: '+sym)
    if source not in ('YAHOO_QUERY1','YAHOO_QUERY2','LEGACY_YAHOO_CACHE','MANUAL_VERIFIED'):
        raise ValueError('Unapproved adjusted series source')
    cleaned=validate(rows)
    downloaded_at=downloaded_at or ztime()
    identity=sha(canonical({'symbol':sym,'source':source,'rows':cleaned}))[:24]
    # Never delete older history if an API returns a truncated window.
    with conn(db) as c:
        existing=c.execute('SELECT trade_date,adjusted_close,raw_close FROM daily_prices WHERE symbol=?',(sym,)).fetchall()
        old={r['trade_date'] for r in existing}
        # keep older latest-provenance on same-date if data is a legacy cache;
        # online official history can replace adjusted values after split changes.
        for r in cleaned:
            if source=='LEGACY_YAHOO_CACHE':
                c.execute('INSERT OR IGNORE INTO daily_prices VALUES(?,?,?,?,?,?)',
                          (sym,r['date'],r['adjusted_close'],r['raw_close'],source,downloaded_at))
            else:
                c.execute('''INSERT INTO daily_prices VALUES(?,?,?,?,?,?)
                    ON CONFLICT(symbol,trade_date) DO UPDATE SET
                    adjusted_close=excluded.adjusted_close,raw_close=excluded.raw_close,
                    source=excluded.source,fetched_at=excluded.fetched_at''',
                    (sym,r['date'],r['adjusted_close'],r['raw_close'],source,downloaded_at))
        after=c.execute('SELECT COUNT(*) AS n FROM daily_prices WHERE symbol=?',(sym,)).fetchone()['n']
        if after<len(old):raise RuntimeError('History truncated: rollback')
        c.execute('INSERT OR IGNORE INTO price_imports VALUES(?,?,?,?,?,?,?, ?,?)',
                  (identity,sym,source,downloaded_at,cleaned[0]['date'],cleaned[-1]['date'],
                   sha(canonical(cleaned)),len(cleaned),'OK'))
    return {'symbol':sym,'source':source,'received':len(cleaned),'total':after,'last':cleaned[-1]['date']}

WEB_SOURCES={
    'STOCKANALYSIS':'stockanalysis.com',
    'CHARTEXCHANGE':'chartexchange.com',
    'YCHARTS':'ycharts.com',
}

def import_web_closes(payload, db=DB, now=None):
    """Insert only dates corroborated across two sites. Keeps raw web closes
    separate from the adjusted daily series, which needs full corporate actions.
    This is not proof that the sites use independent underlying exchange feeds.
    """
    now=now or utc_now()
    date=dt.date.fromisoformat(payload['trade_date'])
    if date>expected_close_session(now) or not is_regular_session(date):raise ValueError('Web quote is not from a completed market session')
    quotes=payload.get('quotes')
    if not quotes or not set(quotes).issubset(SYMBOLS):raise ValueError('Unsupported or empty quote symbol set')
    normalized={}
    for symbol in quotes:
        seen=set();items=[]
        for entry in quotes[symbol]:
            source=entry['source'].upper()
            if source not in WEB_SOURCES or source in seen:raise ValueError('Unknown or duplicate quote website')
            url=entry['url'];u=urlsplit(url)
            if u.scheme!='https' or u.hostname!=WEB_SOURCES[source]:raise ValueError('Unapproved source hostname')
            price=float(entry['raw_close'])
            if not math.isfinite(price) or not 0<price<1e8:raise ValueError('Invalid quote')
            seen.add(source);items.append((source,round(price,4),url))
        if len(items)<2:raise ValueError('At least two distinct websites per ETF')
        v=[x[1] for x in items];spread=100*(max(v)/min(v)-1)
        if spread>0.5:raise ValueError(f'{symbol} cross-site raw close conflict: {spread:.3f}%')
        normalized[symbol]=items
    # Validate all before writing; reject same-site revised values to retain immutability.
    with conn(db) as c:
        for symbol,items in normalized.items():
            for source,price,url in items:
                old=c.execute('SELECT raw_close,source_url FROM web_closes WHERE symbol=? AND trade_date=? AND source=?',
                              (symbol,date.isoformat(),source)).fetchone()
                if old and (abs(old['raw_close']-price)>0.00001 or old['source_url']!=url):
                    raise ValueError('Existing quote provenance conflict; no overwrite')
        for symbol,items in normalized.items():
            for source,price,url in items:
                c.execute('INSERT OR IGNORE INTO web_closes VALUES(?,?,?,?,?,?)',
                          (symbol,date.isoformat(),source,price,url,ztime(now)))
    return {'trade_date':date.isoformat(),'sites':{s:len(normalized[s]) for s in normalized},
            'type':'CORROBORATED_WEB_RAW_CLOSE_NOT_ADJUSTED_SERIES'}

def web_close_snapshot(db=DB):
    with conn(db) as c:
        out={}
        for symbol in SYMBOLS:
            rows=c.execute('SELECT trade_date,source,raw_close,source_url FROM web_closes WHERE symbol=? ORDER BY trade_date DESC',
                           (symbol,)).fetchall()
            selected={(r['trade_date'],r['source']):dict(r) for r in rows}
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='web_table_closes'").fetchone():
                verified=c.execute('''SELECT w.trade_date,w.source,w.raw_close,w.source_url,w.quote_kind,e.collector
                    FROM web_table_closes w JOIN web_fetch_evidence e ON e.evidence_sha256=w.evidence_sha256
                    WHERE w.symbol=? ORDER BY e.collected_at,w.observation_id''',(symbol,)).fetchall()
                for row in verified:selected[(row['trade_date'],row['source'])]=dict(row)
            rows=sorted(selected.values(),key=lambda r:r['trade_date'],reverse=True)
            if not rows:out[symbol]=None;continue
            latest=rows[0]['trade_date'];group=[dict(r) for r in rows if r['trade_date']==latest]
            prices=[r['raw_close'] for r in group]
            out[symbol]={'date':latest,'raw_close':round(statistics.median(prices),4),
                         'websites':len(group),'spread_pct':round((max(prices)/min(prices)-1)*100,4),
                         'source_urls':{r['source']:r['source_url'] for r in group},
                         'verified_daily_table_websites':sum(r.get('quote_kind')=='REGULAR_SESSION_DAILY_TABLE_CLOSE' for r in group),
                         'collectors':sorted({r.get('collector','LEGACY_WEB_QUOTE') for r in group}),
                         'meaning':'cross-site checked raw daily close; not a downloaded adjusted-price series'}
        return out

def yahoo_download(sym,domain='query1.finance.yahoo.com',timeout=9,now=None):
    now=now or utc_now()
    # range=max may silently return monthly bars despite interval=1d.
    start=int(dt.datetime(2010,2,9,tzinfo=dt.timezone.utc).timestamp())
    end=int(now.timestamp())
    url=f'https://{domain}/v8/finance/chart/{sym}?period1={start}&period2={end}&interval=1d&events=div%2Csplits'
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as rsp:
        if rsp.status!=200:raise ValueError('HTTP '+str(rsp.status))
        buf=rsp.read(6_000_000)
    data=json.loads(buf)
    chart=data.get('chart',{})
    if chart.get('error'):raise ValueError(str(chart['error'])[:300])
    results=chart.get('result') or []
    if not results:raise ValueError('Empty result')
    item=results[0]
    granularity=item.get('meta',{}).get('dataGranularity')
    if granularity is not None and granularity!='1d':raise ValueError('Expected daily bars; received '+granularity)
    ind=item['indicators'];q=ind['quote'][0];adj=ind.get('adjclose') or []
    a=adj[0].get('adjclose',[]) if adj else []
    if not a:raise ValueError('Missing Yahoo adjusted closing prices: refusing to mix raw/adjusted history')
    now=now or utc_now()
    ny=now.astimezone(NEW_YORK)
    cutoff=expected_close_session(now)
    rows=[]
    for i,ts in enumerate(item.get('timestamp') or []):
        market_date=dt.datetime.fromtimestamp(ts,NEW_YORK).date()
        # A daily bar from the current session is NOT a completed close before 18:30 NY.
        if market_date>cutoff or not is_regular_session(market_date):continue
        try:
            raw=q['close'][i]
            av=a[i] if i<len(a) else None
            if raw is None or av is None:continue
            rows.append({'date':market_date.isoformat(),'adjusted_close':av,'raw_close':raw})
        except (IndexError,TypeError,KeyError):continue
    return validate(rows)

def stooq_last_raw(sym,timeout=6):
    start=(dt.datetime.now(NEW_YORK).date()-dt.timedelta(days=20)).strftime('%Y%m%d')
    url=f'https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d&d1={start}'
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'text/csv'})
    with urllib.request.urlopen(req,timeout=timeout) as res:
        s=res.read(200_000).decode('utf-8','replace')
    records=list(csv.DictReader(io.StringIO(s)))
    if not records or not {'Date','Close'}<=set(records[0]):raise ValueError('Stooq unexpected csv response')
    r=records[-1]
    return {'date':r['Date'],'raw_close':float(r['Close']),'provider':'Stooq','adjustments_unverified':True}

def price_data(db=DB):
    with conn(db) as c:
        return {s:[dict(x) for x in c.execute('SELECT * FROM daily_prices WHERE symbol=? ORDER BY trade_date',(s,))]
                for s in SYMBOLS}

def nth_weekday(year,month,weekday,n):
    first=dt.date(year,month,1)
    delta=(weekday-first.weekday())%7
    return first+dt.timedelta(days=delta+7*(n-1))

def last_weekday(year,month,weekday):
    d=dt.date(year,month,calendar.monthrange(year,month)[1])
    return d-dt.timedelta(days=(d.weekday()-weekday)%7)

def easter(year):
    # Gregorian computus: for NYSE Good Friday holiday determination.
    a=year%19;b=year//100;c=year%100;d=b//4;e=b%4;f=(b+8)//25
    g=(b-f+1)//3;h=(19*a+b-d-g+15)%30;i=c//4;k=c%4
    l=(32+2*e+2*i-h-k)%7;m=(a+11*h+22*l)//451
    month=(h+l-7*m+114)//31;day=(h+l-7*m+114)%31+1
    return dt.date(year,month,day)

def market_holidays(year):
    # Regular US stock-market holidays, standard calendar only; unscheduled closures require exchange alerts.
    newyear=dt.date(year,1,1)
    xmas=dt.date(year,12,25)
    jun=dt.date(year,6,19)
    independence=dt.date(year,7,4)
    def observed(day):
        return day+dt.timedelta(days=1) if day.weekday()==6 else (day-dt.timedelta(days=1) if day.weekday()==5 else day)
    h={newyear if newyear.weekday()!=6 else newyear+dt.timedelta(days=1),
       nth_weekday(year,1,0,3),nth_weekday(year,2,0,3),easter(year)-dt.timedelta(days=2),
       last_weekday(year,5,0),observed(independence),nth_weekday(year,9,0,1),
       nth_weekday(year,11,3,4),observed(xmas)}
    if year>=2022:h.add(observed(jun))
    # Exchange-announced extraordinary full-day closures, not missing data.
    extraordinary={2012:{dt.date(2012,10,29),dt.date(2012,10,30)},
                   2018:{dt.date(2018,12,5)},2025:{dt.date(2025,1,9)}}
    h.update(extraordinary.get(year,set()))
    # NYSE does not close on Friday Dec 31 when next Jan 1 is Saturday.
    return h

def is_regular_session(day):
    return day.weekday()<5 and day not in market_holidays(day.year)

def expected_close_session(now=None):
    now=now or utc_now()
    ny=now.astimezone(NEW_YORK)
    day=ny.date()
    if (ny.hour,ny.minute)<(18,30):day-=dt.timedelta(days=1)
    while not is_regular_session(day):day-=dt.timedelta(days=1)
    return day

def missed_weekdays(last,expected):
    last=dt.date.fromisoformat(last)
    if last>=expected:return 0
    n=0
    while last<expected:
        last+=dt.timedelta(days=1)
        if is_regular_session(last):n+=1
    return n

def calc_metrics(rows,expected):
    if not rows:return {'quality':'MISSING','observations':0,'signals':[]}
    closes=[r['adjusted_close'] for r in rows];n=len(closes)
    nowval=closes[-1];last=rows[-1]['trade_date']
    missed=missed_weekdays(last,expected)
    quality='CURRENT' if missed==0 else ('DELAYED' if missed==1 else 'STALE')
    latest={'last_date':last,'adjusted_close':round(nowval,4),'raw_close':round(rows[-1]['raw_close'],4),'observations':n,'quality':quality,'missing_weekdays':missed}
    for window in (20,50,200):
        latest[f'sma_{window}']=round(statistics.mean(closes[-window:]),4) if n>=window else None
    if n>=2:
        latest['change_1d_pct']=round((closes[-1]/closes[-2]-1)*100,3)
    for window in (20,60,252):
        latest[f'return_{window}d_pct']=round((nowval/closes[-window-1]-1)*100,3) if n>window else None
    if n>=252:
        highest=max(closes[-252:]);latest['drawdown_252d_pct']=round((nowval/highest-1)*100,3)
    if n>=21:
        daily=[math.log(closes[i]/closes[i-1]) for i in range(n-20,n)]
        latest['volatility_20d_annualized_pct']=round(statistics.stdev(daily)*math.sqrt(252)*100,2)
    signals=[]
    dd=latest.get('drawdown_252d_pct')
    if dd is not None:
        for threshold in (5,10,15,20):
            if dd<=-threshold:signals.append(f'从252日高点回撤达到{threshold}%：人工复核')
    for window in (50,200):
        key=f'sma_{window}'
        if latest.get(key) and nowval<latest[key]:signals.append(f'收盘低于{window}日均线：趋势风险提醒')
    if latest.get('volatility_20d_annualized_pct',0)>40:signals.append('20日年化波动超过40%：波动风险提醒')
    latest['signals']=signals
    latest['signals_actionable']=quality=='CURRENT'  # never order/action; only recency of reminders
    return latest

def build_report(now=None,online=False,independent_check=False,db=DB):
    init_db(db);now=now or utc_now();expected=expected_close_session(now)
    fetch_log={}
    if online:
        for sym in ACTIVE_SYMBOLS:
            attempts=[];got=False
            for domain,source in (('query1.finance.yahoo.com','YAHOO_QUERY1'),('query2.finance.yahoo.com','YAHOO_QUERY2')):
                try:
                    r=yahoo_download(sym,domain=domain,now=now)
                    info=ingest(sym,r,source,db=db);attempts.append({'source':source,'status':'OK','records':info['received']});got=True;break
                except Exception as ex:
                    attempts.append({'source':source,'status':'ERROR','reason':str(ex)[:160]})
            fetch_log[sym]={'online_success':got,'attempts':attempts}
    else:
        fetch_log={s:{'online_success':False,'attempts':[],'mode':'OFFLINE_CACHE'} for s in ACTIVE_SYMBOLS}
    if independent_check and online:
        for sym in ACTIVE_SYMBOLS:
            try:fetch_log[sym]['independent_quote']=stooq_last_raw(sym)
            except Exception as e:fetch_log[sym]['independent_quote_error']=str(e)[:160]
    p=portfolio(db)
    if not p:raise RuntimeError('Portfolio baseline not initialized')
    candles=price_data(db)
    metrics={s:calc_metrics(candles[s],expected) for s in ACTIVE_SYMBOLS}
    web_quotes={s:v for s,v in web_close_snapshot(db).items() if s in ACTIVE_SYMBOLS}
    for symbol in ACTIVE_SYMBOLS:
        observation=web_quotes.get(symbol)
        if observation:
            observation['fresh_for_expected_session']=observation['date']==expected.isoformat()
            m=metrics[symbol]
            if m.get('last_date')==observation['date']:
                observation['diff_vs_historical_raw_pct']=round(abs(observation['raw_close']/m['raw_close']-1)*100,3)
                observation['historical_raw_agrees']=observation['diff_vs_historical_raw_pct']<=0.5
            else:
                observation['historical_raw_agrees']=None
            m['web_cross_checked_raw_close']=observation
    # Compare Stooq raw close only if exact same market session. Never cross-check adjusted series.
    for sym in ACTIVE_SYMBOLS:
        check=fetch_log[sym].get('independent_quote');m=metrics[sym]
        if check and m.get('last_date')==check.get('date'):
            err=abs(check['raw_close']/m['raw_close']-1)*100
            fetch_log[sym]['independent_same_session_diff_pct']=round(err,3)
            fetch_log[sym]['independent_status']='MATCH' if err<=1.5 else 'CONFLICT'
        elif check:fetch_log[sym]['independent_status']='DATE_MISMATCH'
        else:fetch_log[sym]['independent_status']='NOT_VERIFIED'
    # Don't upgrade cache to LIVE because date appears recent; successful HTTP required.
    success=sum(bool(fetch_log[s]['online_success']) for s in ACTIVE_SYMBOLS)
    if not online:mode='OFFLINE_CACHE'
    elif success==len(ACTIVE_SYMBOLS):mode=f'ONLINE_{len(ACTIVE_SYMBOLS)}_OF_{len(ACTIVE_SYMBOLS)}'
    elif success:mode=f'ONLINE_PARTIAL_{success}_OF_{len(ACTIVE_SYMBOLS)}'
    else:mode='ONLINE_FAILED_CACHE'
    has_stale=any(m['quality'] in ('MISSING','STALE') for m in metrics.values())
    disagreement=any(fetch_log[s].get('independent_status')=='CONFLICT' for s in ACTIVE_SYMBOLS)
    evidence_grade='CURRENT_SINGLE_SOURCE' if success==len(ACTIVE_SYMBOLS) and all(m['quality']=='CURRENT' for m in metrics.values()) else 'LIMITED'
    if disagreement:evidence_grade='SOURCE_CONFLICT'
    if any(q and q.get('historical_raw_agrees') is False for q in web_quotes.values()):
        evidence_grade='SOURCE_CONFLICT'
    if evidence_grade=='LIMITED' and all(q and q.get('fresh_for_expected_session') and q['websites']>=2 for q in web_quotes.values()):
        evidence_grade='WEB_CROSS_CHECKED_RAW_ONLY'
    if evidence_grade!='SOURCE_CONFLICT' and all(
        metrics[s]['quality']=='CURRENT' and web_quotes[s] and
        web_quotes[s].get('fresh_for_expected_session') and
        web_quotes[s].get('historical_raw_agrees') is True for s in ACTIVE_SYMBOLS):
        evidence_grade='CURRENT_ADJUSTED_WITH_WEB_RAW_CORROBORATION'

    run={'created_at_bjt':ztime(now),'as_of_expected_session':expected.isoformat(),
         'mode':mode,'data_evidence_grade':evidence_grade,
         'market':metrics,'fetch':fetch_log,
         'portfolio':{'as_of':p['as_of'],'cash_cny':p['cash_cny'],'qqq_value_cny':p['qqq_value_cny'],
                      'tqqq_value_cny':p['tqqq_value_cny'],'qld_value_cny':p['qld_value_cny'],'total_cny':p['qqq_value_cny']+p['cash_cny']+p['tqqq_value_cny']+p['qld_value_cny'],
                      'qqq_weight_pct':round(p['qqq_value_cny']/(p['cash_cny']+p['qqq_value_cny']+p['tqqq_value_cny']+p['qld_value_cny'])*100,2) if (p['cash_cny']+p['qqq_value_cny']+p['tqqq_value_cny']+p['qld_value_cny']) else 0,
                      'share_count':'UNKNOWN','cost_basis':'UNKNOWN','profit_loss':'UNKNOWN',
                      'valuation_source':'USER_REPORTED_AGGREGATE', 'no_automatic_mark_to_market':True},
         'alerts':[], 'trading_enabled':False,'old_decisions_imported':False}
    if has_stale:run['alerts'].append('部分收盘行情过期或缺失；禁止把风险监测读作实时信号。')
    if success<len(ACTIVE_SYMBOLS) and online:run['alerts'].append('在线行情未全部获取成功；已保留明确缓存来源。')
    if disagreement:run['alerts'].append('独立报价与主来源发生冲突；需要人工核对。')
    if not online:run['alerts'].append('本次为离线缓存报告，不是今日联网获取成功。')
    if evidence_grade=='WEB_CROSS_CHECKED_RAW_ONLY':
        run['alerts'].append('两只ETF的最新原始收盘价已有跨网站核对；复权均线依然按历史缓存日期判断，不能视为完整联网历史更新。')
    if evidence_grade=='SOURCE_CONFLICT':
        run['alerts'].append('检测到价格来源冲突，请人工复核，不能据此下判断。')
    import strategy
    run['strategy_observation']=strategy.observe(run,candles)
    from research import shadow
    try:
        run['research_shadow']=shadow.observe(run,candles)
    except Exception as exc:
        run['research_shadow']={'status':'RESEARCH_MODULE_ERROR','blocker':str(exc)[:200],
                                'hypothetical_target':None,'orders':[],'is_paper':True}
    import advisory
    run['allocation_review']=advisory.observe(run,candles)
    from research import quant
    try:
        run['quant_analysis']=quant.observe(run,candles)
    except Exception as exc:
        run['quant_analysis']={'status':'QUANT_MODULE_ERROR','blocker':str(exc)[:200],
                               'orders':[],'allocation_override':False}
    from research import mature
    try:
        run['mature_models']=mature.context(run,candles)
    except Exception as exc:
        run['mature_models']={'status':'MODEL_MODULE_ERROR','blocker':str(exc)[:200],
                              'orders':[],'allocation_override':False}
    run_id=sha(canonical({'now':run['created_at_bjt'],'market':metrics,'mode':mode,
                          'portfolio':run['portfolio'],'strategy_id':run['strategy_observation']['signal_id'],
                          'research_id':run['research_shadow'].get('signal_id'),
                          'allocation_id':run['allocation_review']['signal_id'],
                          'quant_id':run['quant_analysis'].get('analysis_id')}))[:20]
    run['run_id']=run_id
    return run

def text_report(run):
    from daily_summary import build_summary,research_lines
    health_path=DATA_ROOT/'automation_health.json'
    health=json.loads(health_path.read_text()) if health_path.exists() else {}
    out=['# QQQ / TQQQ 每日监控',build_summary(run,health),'',*research_lines(run)]
    return '\n\n'.join(out)+'\n'


def html_report(run):
    text=text_report(run)
    paragraphs=[]
    for line in text.splitlines():
        if line.startswith('# '):paragraphs.append('<h1>'+html.escape(line[2:])+'</h1>')
        elif line.startswith('## '):paragraphs.append('<h2>'+html.escape(line[3:])+'</h2>')
        elif line:paragraphs.append('<p>'+html.escape(line)+'</p>')
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>QQQ / TQQQ 每日监控</title><style>body{font:17px system-ui,sans-serif;max-width:820px;margin:32px auto;padding:20px;background:#0b1220;color:#eaf0fc}p{line-height:1.7}h1{font-size:26px}h2{font-size:20px;margin-top:34px;color:#b1d3ff}</style><main>'+''.join(paragraphs)+'</main></html>'


def save_report(run,db=DB,output_dir=None):
    import strategy
    if run.get('mature_models'):
        from research import mature
        try:mature.persist(run['mature_models'],price_data(db),db)
        except Exception as exc:
            run['mature_persistence_error']=str(exc)[:200]
            run['alerts'].append('成熟策略输入快照保存失败；本轮研究归档不完整。')
    if run.get('quant_analysis'):
        from research import quant
        try:
            quant.persist(run['quant_analysis'],run['created_at_bjt'],db)
        except Exception as exc:
            run['quant_persistence_error']=str(exc)[:200]
            run['alerts'].append('量化预测归档失败，本次不计入前瞻验证。')
            run['run_id']=sha(canonical({'original_run_id':run['run_id'],
                                       'quant_persistence_error':run['quant_persistence_error']}))[:20]
    if run.get('allocation_review'):
        import advisory
        advisory.persist(run['allocation_review'],run['created_at_bjt'],db)
    if run.get('strategy_observation'):
        strategy.persist(run['strategy_observation'],run['created_at_bjt'],db)
    from research import shadow
    if run.get('research_shadow') and run['research_shadow']['status']=='SHADOW_RESEARCH_OBSERVATION':
        try:
            shadow.persist(run['research_shadow'],db)
        except Exception as exc:
            # Research evidence failure must remain visible while the core report still saves.
            run['research_persistence_error']=str(exc)[:200]
            run['alerts'].append('影子研究证据保存失败；本轮研究信号未计入合格前瞻记录。')
            run['run_id']=sha(canonical({'original_run_id':run['run_id'],
                                       'research_persistence_error':run['research_persistence_error']}))[:20]
    # Hash the complete final payload; fetch/research evidence can differ even
    # when a fixed test clock and the allocation decision are identical.
    run['run_id']=sha(canonical({k:v for k,v in run.items() if k!='run_id'}))[:20]
    output_dir=Path(output_dir or Path(db).parent)
    if run['mode']!='OFFLINE_CACHE':
        atomic_write(output_dir/'last_online_attempt.json',json.dumps(
            {'created_at_bjt':run['created_at_bjt'],'run_id':run['run_id'],
             'expected_session':run['as_of_expected_session'],'mode':run['mode'],
             'fetch':run['fetch'],'market_dates':{s:v.get('last_date') for s,v in run['market'].items()}},
             ensure_ascii=False,indent=2).encode('utf8'))
    for filename,content in [('latest.json',json.dumps(run,indent=2,ensure_ascii=False)),('latest.md',text_report(run)),('dashboard.html',html_report(run))]:
        atomic_write(output_dir/filename,content.encode('utf8'))
    report_sha=sha(canonical(run));runfile=output_dir/'runs'/f'{run["run_id"]}.json'
    if runfile.exists() and json.loads(runfile.read_text('utf-8'))!=run:raise ValueError('Run hash collision / non-immutable run')
    atomic_write(runfile,json.dumps(run,ensure_ascii=False,indent=2).encode('utf8'))
    with conn(db) as c:
        c.execute('INSERT OR IGNORE INTO monitor_runs VALUES(?,?,?,?,?,?)',
                  (run['run_id'],run['created_at_bjt'],run['mode'],run['data_evidence_grade'],report_sha,canonical(run)))
    outcomes=strategy.evaluate(db)
    outcomes['research_shadow']=shadow.evaluate(db)
    from research import quant
    outcomes['quant53']=quant.evaluate(db)
    backup=backup_database(db,output_dir/'backups'/f'{run["run_id"]}.sqlite3')
    from daily_summary import build_summary
    health_path=DATA_ROOT/'automation_health.json'
    health=json.loads(health_path.read_text()) if health_path.exists() else {}
    atomic_write(output_dir/'notification.txt',build_summary(run,health).encode('utf8'))
    return {'report_sha256':report_sha,'run_id':run['run_id'],'report_path':str(output_dir/'latest.md'),
            'outcomes':outcomes,'database_backup':str(backup)}

def backup_database(db=DB,target=None):
    target=Path(target or Path(db).parent/'backups'/'latest.sqlite3')
    target.parent.mkdir(parents=True,exist_ok=True)
    tmp=target.with_suffix('.tmp')
    with closing(sqlite3.connect(db)) as source, closing(sqlite3.connect(tmp)) as dest:
        source.backup(dest)
        if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise RuntimeError('Backup database integrity failed')
        if dest.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Backup foreign key check failed')
    os.replace(tmp,target)
    return target

def audit(db=DB):
    with conn(db) as c:
        result=c.execute('PRAGMA integrity_check').fetchone()[0]
        baseline=c.execute('SELECT COUNT(*) FROM portfolio_baselines').fetchone()[0]
        prices={s:c.execute('SELECT COUNT(*) FROM daily_prices WHERE symbol=?',(s,)).fetchone()[0] for s in SYMBOLS}
        runs=c.execute('SELECT COUNT(*) FROM monitor_runs').fetchone()[0]
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        foreign_keys=len(c.execute('PRAGMA foreign_key_check').fetchall())
        invalid_hashes=sum(sha(r['report_json'])!=r['report_sha256'] for r in
                           c.execute('SELECT report_sha256,report_json FROM monitor_runs'))
        strategy_counts={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in
                         ('strategy_versions','strategy_signals','signal_outcomes','backtest_runs') if t in tables}
    return {'sqlite_integrity':result,'baselines':baseline,'price_records':prices,'runs':runs,
      'foreign_key_errors':foreign_keys,'run_hash_errors':invalid_hashes,'strategy_records':strategy_counts,
      'legacy_trade_tables_present':any(x in tables for x in ('transactions','decisions','pending_events')),
      'read_only_no_trade_interface':True,
      'research_evidence':__import__('research.shadow',fromlist=['audit']).audit(db),
      'allocation_reviews':__import__('advisory').audit(db),
      'web_fetch_evidence':__import__('web_extract').audit(db),
      'quant53':__import__('research.quant',fromlist=['audit']).audit(db),
      'mature53':__import__('research.mature',fromlist=['audit']).audit(db)}

def main(argv=None):
    par=argparse.ArgumentParser(description='QQQ 60% / TQQQ 40% 只读监控')
    par.add_argument('command',choices=('init','run','portfolio','audit','import-web','import-tinyfish','backtest','evaluate','research','quant-research','mature-research','mature-refresh'))
    par.add_argument('--cost-bps',type=float,default=15,help='回测每边交易成本（基点）')
    par.add_argument('--online',action='store_true',help='尝试下载新行情，默认使用缓存')
    par.add_argument('--independent-check',action='store_true',help='在线时检查Stooq独立原始收盘价')
    par.add_argument('--require-current',action='store_true',help='保存报告后，行情未完整在线更新时返回非零退出码')
    par.add_argument('--cash',type=int)
    par.add_argument('--qqq-value',type=int)
    par.add_argument('--qld-value',type=int,help='仅在明确确认QLD持仓估值后填写')
    par.add_argument('--tqqq-value',type=int,help='仅在用户明确确认持仓估值后填写；省略则保留原值')
    par.add_argument('--date')
    par.add_argument('--file',help='包含两只ETF真实收盘价格及两个网页证据的JSON文件')
    args=par.parse_args(argv)
    init_db()
    if args.command=='init':
        if portfolio():raise RuntimeError('Existing portfolio; init cannot reset history')
        set_portfolio(12000,8000,'2026-10-08')
        for s in SYMBOLS:
            file=DATA_ROOT/'seed'/f'{s}.json'
            if file.exists():
                o=json.loads(file.read_text('utf8'));print(ingest(s,o['rows'],'LEGACY_YAHOO_CACHE',downloaded_at=o['downloaded_at']))
        print('初始化完成，空白决策历史。')
    elif args.command=='portfolio':
        if args.cash is not None and args.qqq_value is not None:
            set_portfolio(args.qqq_value,args.cash,args.date,'用户显式更新聚合估值，不记录交易',tqqq=args.tqqq_value,qld=args.qld_value)
        print(json.dumps(portfolio(),ensure_ascii=False,indent=2))
    elif args.command=='run':
        r=build_report(online=args.online,independent_check=args.independent_check)
        print(json.dumps({'mode':r['mode'],'market':{k:{'date':v.get('last_date'),'quality':v['quality']} for k,v in r['market'].items()},'saved':save_report(r)},ensure_ascii=False,indent=2))
        if args.require_current and (r['mode']!=f'ONLINE_{len(ACTIVE_SYMBOLS)}_OF_{len(ACTIVE_SYMBOLS)}' or
                r['strategy_observation']['status']=='DATA_GATE_BLOCKED'):
            raise SystemExit(2)
    elif args.command=='import-web':
        if not args.file:raise SystemExit('import-web requires --file')
        print(json.dumps(import_web_closes(json.loads(Path(args.file).read_text('utf8'))),ensure_ascii=False,indent=2))
    elif args.command=='import-tinyfish':
        if not args.file:raise SystemExit('import-tinyfish requires a saved TinyFish fetch JSON file')
        from web_extract import import_tinyfish
        print(json.dumps(import_tinyfish(json.loads(Path(args.file).read_text('utf8'))),ensure_ascii=False,indent=2))
    elif args.command=='audit':print(json.dumps(audit(),ensure_ascii=False,indent=2))
    elif args.command=='backtest':
        import strategy
        result=strategy.backtest(DB,args.cost_bps)
        atomic_write(DATA_ROOT/'backtest_latest.json',json.dumps(result,ensure_ascii=False,indent=2).encode())
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=='evaluate':
        import strategy
        from research import shadow,quant
        print(json.dumps({'legacy':strategy.evaluate(DB),'research':shadow.evaluate(DB),'quant53':quant.evaluate(DB)},ensure_ascii=False,indent=2))
    elif args.command=='quant-research':
        from research.quant import run
        print(json.dumps(run(DB),ensure_ascii=False,indent=2))
    elif args.command=='mature-research':
        from research.mature import run
        print(json.dumps(run(DB),ensure_ascii=False,indent=2))
    elif args.command=='mature-refresh':
        from research.mature import refresh
        print(json.dumps(refresh(),ensure_ascii=False,indent=2))
    elif args.command=='research':
        from research.run import run
        print(json.dumps(run(DB),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
