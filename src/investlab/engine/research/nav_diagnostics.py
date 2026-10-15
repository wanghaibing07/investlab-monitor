"""Official NAV file validation; no false total-return or financing-cost attribution."""
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path
from .leverage import tracking,ideal_path

def official_nav(path):
    raw=Path(path).read_bytes();rows=list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    required={'Date','Ticker','NAV','Prior NAV','NAV Change (%)'}
    if not rows or not required<=set(rows[0]):raise ValueError('Official NAV format invalid')
    cleaned=[];seen=set()
    for row in rows:
        date=dt.datetime.strptime(row['Date'],'%m/%d/%Y').date().isoformat()
        nav=float(row['NAV']);prior=float(row['Prior NAV']);pct=float(row['NAV Change (%)'])
        if row['Ticker']!='TQQQ' or date in seen or min(nav,prior)<=0 or not all(math.isfinite(x) for x in (nav,prior,pct)):
            raise ValueError('Official NAV malformed/duplicate')
        if abs((nav/prior-1)*100-pct)>.00002:raise ValueError('NAV percent arithmetic inconsistent')
        cleaned.append({'date':date,'nav':nav,'prior_nav':prior,'reported_change_pct':pct});seen.add(date)
    return {'rows':sorted(cleaned,key=lambda r:r['date']),'raw_sha256':hashlib.sha256(raw).hexdigest(),
            'source':'PROSHARES_OFFICIAL','url':'https://accounts.profunds.com/etfdata/ByFund/TQQQ-historical_nav.csv',
            'basis':'ISSUER_HISTORICAL_NAV_LEVEL_SPLIT_NORMALIZED_NOT_CONFIRMED_DISTRIBUTION_TOTAL_RETURN'}

def diagnose(data,nav,index=None):
    nmap={r['date']:r for r in nav['rows']};last=data['dates'][-1]
    aligned=[(r,nmap[r['trade_date']]) for r in data['TQQQ'] if r['trade_date'] in nmap]
    gaps=[{'date':r['trade_date'],'market_close':r['raw_close'],'official_nav':n['nav'],
           'premium_discount_pct':(r['raw_close']/n['nav']-1)*100} for r,n in aligned]
    out={'status':'OFFICIAL_NAV_HISTORY_VALIDATED_PRICE_BASIS_ONLY',
         'source':nav['source'],'raw_sha256':nav['raw_sha256'],'url':nav['url'],
         'basis':nav['basis'],'official_sessions':len(nav['rows']),'aligned_market_sessions':len(aligned),
         'first':nav['rows'][0]['date'],'last':nav['rows'][-1]['date'],
         'last_session':next((r for r in gaps if r['date']==last),None),
         'median_absolute_market_nav_deviation_pct':statistics.median(abs(r['premium_discount_pct']) for r in gaps),
         'largest_5_market_nav_deviations':sorted(gaps,key=lambda r:abs(r['premium_discount_pct']),reverse=True)[:5],
         'no_independent_full_adjusted_market_validation':True,'no_cost_attribution':True}
    if not index:
        out['tracking']=tracking(None,None);return out
    imap={r['date']:r['raw_close'] for r in index};dates=sorted(nmap.keys() & imap.keys() & set(data['dates']))
    nr=[];xr=[];daily=[]
    for a,b in zip(dates,dates[1:]):
        # Do not compress gaps into a pseudo-one-day return.
        import monitor as m
        if m.missed_weekdays(a,dt.date.fromisoformat(b))!=1:continue
        rn=nmap[b]['nav']/nmap[b]['prior_nav']-1;rx=imap[b]/imap[a]-1
        nr.append(rn);xr.append(rx);daily.append({'date':b,'nav_price_return':rn,'ndx_price_return':rx,'tracking_diff':rn-3*rx})
    out['tracking']={'status':'NAV_PRICE_RETURN_VS_NDX_PRICE_INDEX_DIAGNOSTIC_WITH_DISTRIBUTION_LIMIT',
             'ndx_provider':'YAHOO_NOT_INDEPENDENT_INDEX_PROVIDER','aligned_daily_returns':len(daily),
             'mean_diff_bps':statistics.mean(r['tracking_diff'] for r in daily)*10000 if daily else None,
             'daily':daily,'ideal_index_path':ideal_path(xr),
             'warning':'DISTRIBUTIONS_FINANCING_FEES_TIMING_TRACKING_CANNOT_BE_SEPARATELY_IDENTIFIED'}
    return out
