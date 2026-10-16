"""Explicit vendor contracts. Validation never silently repairs or overwrites bars."""
from dataclasses import dataclass
from datetime import date,datetime
from zoneinfo import ZoneInfo
import math
import re


@dataclass(frozen=True)
class QualifiedDailyBar:
    symbol: str
    exchange_session: str
    source: str
    feed: str
    adjustment: str
    raw_close: float
    adjusted_close: float | None
    retrieved_at: str
    original_payload_sha: str | None
    corporate_actions: tuple | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None


def validate(bars, completed_session, is_session, *, timeframe='1Day', next_page_token=None,
             expected_sessions=None):
    if timeframe not in ('1Day','1D'): raise ValueError('NOT_DAILY_BARS')
    if next_page_token: raise ValueError('INCOMPLETE_PAGINATION')
    seen={}; previous={}; limits=set()
    for b in bars:
        d=date.fromisoformat(b.exchange_session)
        if d.isoformat()>completed_session or not is_session(d): raise ValueError('UNCOMPLETED_OR_INVALID_SESSION')
        if b.symbol not in ('QQQ','TQQQ'): raise ValueError('UNEXPECTED_SYMBOL')
        key=(b.symbol,b.source,b.feed,b.adjustment)
        if key in previous and b.exchange_session<=previous[key].exchange_session: raise ValueError('DUPLICATE_OR_UNSORTED')
        valid=lambda v:isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0
        if not valid(b.raw_close): raise ValueError('INVALID_RAW_CLOSE')
        if b.adjusted_close is not None and not valid(b.adjusted_close): raise ValueError('INVALID_ADJUSTED_CLOSE')
        if b.adjusted_close is None: limits.add('ADJUSTED_CLOSE_MISSING')
        if b.feed.lower()=='iex': limits.add('IEX_NOT_CONSOLIDATED_CLOSE')
        if b.corporate_actions is None: limits.add('CORPORATE_ACTIONS_UNVERIFIED')
        if not b.original_payload_sha or not re.fullmatch('[0-9a-f]{64}',b.original_payload_sha): limits.add('ORIGINAL_PAYLOAD_HASH_MISSING')
        fetched=datetime.fromisoformat(b.retrieved_at.replace('Z','+00:00'))
        if fetched.tzinfo is None:raise ValueError('RETRIEVAL_TIME_REQUIRES_TIMEZONE')
        local=fetched.astimezone(ZoneInfo('America/New_York'))
        if local.date()<d or local.date()==d and (local.hour,local.minute)<(18,30):
            raise ValueError('BAR_RETRIEVED_BEFORE_PUBLICATION_BUFFER')
        ohlc=[v for v in (b.open,b.high,b.low) if v is not None]
        if any(not valid(v) for v in ohlc):raise ValueError('INVALID_OHLC')
        if len(ohlc)==3 and not b.low<=min(b.open,b.raw_close)<=max(b.open,b.raw_close)<=b.high:
            raise ValueError('INCONSISTENT_OHLC')
        prev=previous.get(key)
        if prev and b.adjusted_close and prev.adjusted_close:
            ratio=(b.adjusted_close/b.raw_close)/(prev.adjusted_close/prev.raw_close)
            jump=b.adjusted_close/prev.adjusted_close-1
            if (abs(ratio-1)>.05 or abs(jump)>.5) and not b.corporate_actions:
                raise ValueError('UNEXPLAINED_ACTION_OR_JUMP')
        previous[key]=b; seen.setdefault(key,set()).add(b.exchange_session)
    if not bars: raise ValueError('EMPTY_BARS')
    if expected_sessions is not None and any(set(expected_sessions)!=ds for ds in seen.values()):
        raise ValueError('MISSING_OR_MISALIGNED_SESSIONS')
    return {'status':'DATA_LIMITED' if limits else 'SOURCE_CONTRACT_VALID',
            'limits':sorted(limits),'bars':len(bars),'independent_history_verified':False}


def compare_sources(left,right,tolerance=.005):
    a={(b.symbol,b.exchange_session):b for b in left};b={(x.symbol,x.exchange_session):x for x in right}
    common=sorted(a.keys()&b.keys())
    conflicts=[{'symbol':k[0],'session':k[1],'reason':'RAW_CLOSE_CONFLICT'} for k in common
               if abs(a[k].raw_close/b[k].raw_close-1)>tolerance]
    same=all(a[k].source==b[k].source for k in common)
    complete=a.keys()==b.keys() and bool(common)
    # Raw agreement alone never verifies total-return adjustment or action history.
    return {'status':'DATA_BLOCKED' if conflicts else 'RAW_ONLY_CORROBORATION',
            'conflicts':conflicts,'overlap':len(common),'coverage_complete':complete,
            'independent_sources':bool(common) and not same,
            'adjusted_history_verified':False,'uncovered_left':len(a.keys()-b.keys())}


def source_failure(http_status):
    return {'status':'SOURCE_UNAVAILABLE','http_status':http_status,'independent_history_verified':False}
