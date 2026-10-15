"""Strict aligned, completed-session adjusted market-price snapshot."""
import datetime as dt
import math
import sqlite3
import statistics
from contextlib import closing
import monitor as m
import strategy
from .common import digest

def semantic_content(data):
    """Only prices/dates affect model identity; fetch metadata remains separate evidence."""
    symbols=data.get('asset_universe',m.LEGACY_SYMBOLS)
    result={'dates':data['dates'], **{symbol:[{'trade_date':r['trade_date'],
            'adjusted_close':r['adjusted_close'],'raw_close':r['raw_close']} for r in data[symbol]]
            for symbol in symbols}}
    if 'asset_universe' in data:result['asset_universe']=data['asset_universe']
    return result


def from_candles(candles, cutoff, *, symbols=None):
    symbols = tuple(symbols or m.LEGACY_SYMBOLS)
    maps = {}
    for symbol in symbols:
        selected = [dict(r) for r in candles[symbol] if r['trade_date'] <= cutoff]
        dates = [r['trade_date'] for r in selected]
        if dates != sorted(set(dates)): raise ValueError('Unsorted/duplicate sessions: '+symbol)
        for r in selected:
            if not m.is_regular_session(dt.date.fromisoformat(r['trade_date'])):
                raise ValueError('Non-session observation')
            if any(not math.isfinite(r[k]) or r[k] <= 0 for k in ('adjusted_close','raw_close')):
                raise ValueError('Invalid price')
        maps[symbol] = {r['trade_date']:r for r in selected}
    dates = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    if len(dates)<254: raise ValueError('Insufficient aligned history')
    # Check complete common coverage, no hidden intersection gaps.
    day = dt.date.fromisoformat(dates[0]); end = dt.date.fromisoformat(dates[-1])
    while day<=end:
        if m.is_regular_session(day) and day.isoformat() not in dates:
            raise ValueError('Missing aligned session: '+day.isoformat())
        day += dt.timedelta(days=1)
    aligned = {symbol:[maps[symbol][d] for d in dates] for symbol in symbols}
    # Extreme adjusted jumps or adjustment-factor discontinuity must be investigated.
    anomalies = []
    for symbol, rows in aligned.items():
        for a,b in zip(rows,rows[1:]):
            factor_a=a['adjusted_close']/a['raw_close']; factor_b=b['adjusted_close']/b['raw_close']
            if abs(b['adjusted_close']/a['adjusted_close']-1)>.5 or abs(factor_b/factor_a-1)>.05:
                anomalies.append({'symbol':symbol,'session':b['trade_date'],'reason':'UNVERIFIED_CORPORATE_ACTION_OR_EXTREME_MOVE'})
    if anomalies: raise ValueError('Quarantined price anomalies: '+str(anomalies[:5]))
    content = {'dates':dates, **aligned}
    if symbols != m.LEGACY_SYMBOLS:content['asset_universe']=list(symbols)
    return {**content,'data_sha256':digest(semantic_content(content)),
            'data_identity_basis':'SEMANTIC_PRICES_V1',
            'data_vintage_sha256':digest(content),'cutoff':cutoff,
            'quality':'CURRENT_SINGLE_PROVIDER_ADJUSTED' if dates[-1]==cutoff else 'CACHE_ONLY_STALE',
            'basis':'ADJUSTED_MARKET_CLOSE_TOTAL_RETURN_PROXY_NOT_NAV',
            'independent_nav_verified':False}


def triad_candles(candles, cutoff):
    """Apply identical price gates; QLD must cover the full legacy window."""
    legacy=from_candles(candles,cutoff)
    joint=from_candles(candles,cutoff,symbols=m.SYMBOLS)
    if joint['dates']!=legacy['dates']:raise ValueError('QLD_ALIGNED_HISTORY_MISSING')
    return joint


def active_candles(candles, cutoff):
    """Current strategy inputs; excluded assets cannot block active holdings."""
    return from_candles(candles,cutoff,symbols=m.ACTIVE_SYMBOLS)

def load(db, cutoff=None):
    cutoff = cutoff or m.expected_close_session().isoformat()
    # True read-only connection: research cannot change SQLite or create WAL files.
    with closing(sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        candles = {s:[dict(r) for r in c.execute('SELECT * FROM daily_prices WHERE symbol=? ORDER BY trade_date',(s,))] for s in m.LEGACY_SYMBOLS}
    return from_candles(candles,cutoff)

def rsi(prices, period=2):
    out=[None]*len(prices)
    if len(prices)<=period:return out
    changes=[prices[i]-prices[i-1] for i in range(1,len(prices))]
    up=statistics.mean(max(x,0) for x in changes[:period]);dn=statistics.mean(max(-x,0) for x in changes[:period])
    for i in range(period,len(prices)):
        if i>period:
            x=changes[i-1];up=(up*(period-1)+max(x,0))/period;dn=(dn*(period-1)+max(-x,0))/period
        out[i]=100*up/(up+dn) if up+dn else 50.0
    return out

def features(data, protocol):
    q=[r['adjusted_close'] for r in data['QQQ']]; t=[r['adjusted_close'] for r in data['TQQQ']]
    qr=[0]+[math.log(q[i]/q[i-1]) for i in range(1,len(q))]
    tr=[0]+[math.log(t[i]/t[i-1]) for i in range(1,len(t))]
    rsi2=rsi(q,protocol['swing']['qqq_rsi_days'])
    out=[];v=0;lam=protocol['ewma']['lambda'];window=protocol['risk']['covariance_sessions']
    for i in range(len(q)):
        if i: v=lam*v+(1-lam)*qr[i]**2
        if i<251:out.append(None);continue
        metric=strategy.indicators(data['QQQ'][i-251:i+1])
        qs=qr[i-window+1:i+1];ts=tr[i-window+1:i+1]
        qm=statistics.mean(qs);tm=statistics.mean(ts)
        cov=statistics.mean((x-qm)*(y-tm) for x,y in zip(qs,ts))*252
        out.append({**metric,'ewma_vol':math.sqrt(v*252),'ewma_daily_var':v,
                    'rv20_daily_var':statistics.mean(x*x for x in qr[i-19:i+1]),
                    'qqq_var':statistics.pvariance(qs)*252,'tqqq_var':statistics.pvariance(ts)*252,
                    'cov':cov,'rsi2':rsi2[i], 'prior_high5':max(q[i-5:i])})
    return out
