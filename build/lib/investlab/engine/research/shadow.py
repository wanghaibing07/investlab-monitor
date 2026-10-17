"""Immutable observations, never forecasts retroactively claimed as live."""
import datetime as dt
import json
import sqlite3
from contextlib import closing
from pathlib import Path
import monitor as m
from .common import digest,read_protocol,code_hash,code_sources
from .dataset import from_candles,features
from . import snapshots
from .policies import trend,portfolio_vol,weights,flexible_target

def decision_identity(signal,p):
    """A changed fetch or sub-tick revision is evidence, not a new allocation/risk decision."""
    if signal['status']!='SHADOW_RESEARCH_OBSERVATION':
        return digest({k:v for k,v in signal.items() if k not in ('asof_available_at','data_vintage_sha256')})[:24]
    decimals=p['signal_identity']['weight_rounding_decimals']
    targets={name:{k:round(v,decimals) for k,v in (signal.get(name) or {}).items()}
             for name in ('hypothetical_target','flexible_floor_paper_target')}
    plan=signal.get('proposed_plan_risk',{})
    return digest({'session':signal['session_date'],'code':signal['model_sha256'],
                   'protocol':signal['protocol_sha256'],'status':signal['status'],
                   'risk_level':signal['risk_level'],'direction_regime':signal['direction_regime'],
                   'quality':signal.get('quality'),'targets':targets,
                   'plan_exceeds_budget':plan.get('exceeds_paper_vol_budget'),
                   'plan_rule_violations':plan.get('existing_rule_violations'),
                   'identity_basis':'DECISION_FINGERPRINT_V2'})[:24]


def observe(report,candles):
    p=read_protocol();cutoff=report['as_of_expected_session']
    out={'scope':'PAPER_RESEARCH_ONLY','is_paper':True,'orders':[],
         'session_date':cutoff,'data_identity_basis':'SEMANTIC_PRICES_V1','asof_available_at':report['created_at_bjt'],
         'protocol_sha256':digest(p),'model_sha256':code_hash(),'hypothetical_target':None,
         'risk_probability':None,'live_predictive_evidence':'INSUFFICIENT',
         'status':'DATA_GATE_BLOCKED','risk_level':'UNKNOWN','data_sha256':None}
    try:
        if report['strategy_observation']['status']=='DATA_GATE_BLOCKED':
            raise ValueError(';'.join(report['strategy_observation']['data_blockers']))
        # Cache replays may explain a historical state, never create a new qualified signal.
        if report['mode'] not in ('ONLINE_2_OF_2','ONLINE_3_OF_3'):raise ValueError('NOT_A_FRESH_ONLINE_RUN')
        if report['data_evidence_grade']=='SOURCE_CONFLICT':raise ValueError('SOURCE_CONFLICT')
        data=from_candles(candles,cutoff);fs=features(data,p)
        if data['quality']=='CACHE_ONLY_STALE':raise ValueError('STALE_ADJUSTED_HISTORY')
        state={}
        for f in fs[251:]:trend(f,state,p)
        f=fs[-1];active=state['trend'];safe=f['ewma_vol']<p['ewma']['entry_vol_max']
        high=f['ewma_vol']>=p['ewma']['high_vol']
        q=.5 if high or not active else .7;t=p['risk']['tqqq_entry'] if active and safe else 0
        out.update(status='SHADOW_RESEARCH_OBSERVATION',quality=data['quality'],data_sha256=data['data_sha256'],
                   data_vintage_sha256=data['data_vintage_sha256'],
                   direction_regime='TREND_ON' if active else 'TREND_OFF',
                   risk_level='HIGH' if high else ('ELEVATED' if not safe else 'NORMAL'),
                   ewma_predicted_annual_vol=f['ewma_vol'],hypothetical_target=weights(q,t),
                   covariance_estimated_portfolio_vol=portfolio_vol(f,q,t),
                   proposed_70_20_10_daily_exposure=1.3,
                   risk_level_scope='QQQ_BASE_INDEX_VOLATILITY_NOT_PLAN_SAFETY',
                   flexible_floor_paper_target=flexible_target(f,q,t,p),
                   proposed_plan_risk={
                       'plan_status':'PROPOSED_NOT_EXECUTED',
                       'estimated_annual_vol':portfolio_vol(f,.7,.2),
                       'paper_target_vol':p['paper_flexible_risk']['target_vol'],
                       'exceeds_paper_vol_budget':portfolio_vol(f,.7,.2)>p['paper_flexible_risk']['target_vol'],
                       'existing_rule_violations':['TQQQ_ABOVE_10_PERCENT','CASH_BELOW_15_PERCENT','DAILY_NDX_EXPOSURE_ABOVE_100_PERCENT']})
    except (ValueError,KeyError) as e:out['blocker']=str(e)
    out['signal_identity_basis']='DECISION_FINGERPRINT_V2'
    out['signal_id']=decision_identity(out,p)
    return out

def persist(signal,db):
    # Research observations occupy separate tables, never portfolio or transaction tables.
    with m.conn(db) as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS research_shadow_signals (
            signal_id TEXT PRIMARY KEY,session_date TEXT NOT NULL,created_at TEXT NOT NULL,
            signal_json TEXT NOT NULL,signal_sha256 TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_model_versions (
            model_sha256 TEXT PRIMARY KEY,registered_at TEXT NOT NULL,source_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_shadow_outcomes (
            signal_id TEXT NOT NULL REFERENCES research_shadow_signals(signal_id),
            horizon INTEGER NOT NULL,end_session TEXT NOT NULL,outcome_json TEXT NOT NULL,
            PRIMARY KEY(signal_id,horizon));''')
        snapshots.ensure_schema(c)
        snapshots.import_matching_legacy(c)
        # Do not insert blocked or backdated observations into the live signal collection.
        if signal['status']!='SHADOW_RESEARCH_OBSERVATION':return
        today=dt.datetime.fromisoformat(signal['asof_available_at']).astimezone(m.BEIJING).date().isoformat()
        if today<read_protocol()['shadow_start_date']:return
        if signal['model_sha256']!=code_hash():raise ValueError('Signal code version differs from source being archived')
        c.execute('INSERT OR IGNORE INTO research_model_versions VALUES(?,?,?)',
                  (signal['model_sha256'],signal['asof_available_at'],m.canonical(code_sources())))
        data=from_candles({s:[dict(r) for r in c.execute('SELECT * FROM daily_prices WHERE symbol=? ORDER BY trade_date',(s,))] for s in m.LEGACY_SYMBOLS},signal['session_date'])
        if data['data_sha256']!=signal['data_sha256']:raise ValueError('Dataset changed between observation and persistence')
        snapshots.archive(c,data,signal['asof_available_at'])
        existing=c.execute('SELECT signal_json FROM research_shadow_signals WHERE signal_id=?',(signal['signal_id'],)).fetchone()
        if not existing:
            c.execute('INSERT INTO research_shadow_signals VALUES(?,?,?,?,?)',
                      (signal['signal_id'],signal['session_date'],signal['asof_available_at'],m.canonical(signal),digest(signal)))
        observation={'signal_id':signal['signal_id'],'observed_at':signal['asof_available_at'],
                     'data_vintage_sha256':signal['data_vintage_sha256'],'data_sha256':signal['data_sha256']}
        c.execute('INSERT OR IGNORE INTO research_shadow_observations(observation_id,signal_id,observed_at,data_vintage_sha256,data_sha256) VALUES(?,?,?,?,?)',
                  (digest(observation)[:24],signal['signal_id'],signal['asof_available_at'],signal['data_vintage_sha256'],signal['data_sha256']))

def evaluate(db,cutoff=None):
    cutoff=cutoff or m.expected_close_session().isoformat();inserted=0
    with m.conn(db) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='research_shadow_signals'").fetchone():return {'new_outcomes':0}
        data={s:[dict(r) for r in c.execute('SELECT * FROM daily_prices WHERE symbol=? AND trade_date<=? ORDER BY trade_date',(s,cutoff))] for s in m.LEGACY_SYMBOLS}
        for row in c.execute('SELECT * FROM research_shadow_signals').fetchall():
            signal=json.loads(row['signal_json'])
            if signal['status']!='SHADOW_RESEARCH_OBSERVATION':continue
            model=c.execute('SELECT source_json FROM research_model_versions WHERE model_sha256=?',(signal['model_sha256'],)).fetchone()
            if not model:continue
            if snapshots.source_hash(json.loads(model[0]))!=signal['model_sha256']:raise ValueError('Archived model source hash mismatch')
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='research_data_snapshots'").fetchone():continue
            if snapshots.read(c,signal['data_sha256']) is None:continue
            for h in (7,30,90):
                outcomes={};end_dates=[]
                for sym,rs in data.items():
                    idx=next((i for i,r in enumerate(rs) if r['trade_date']==row['session_date']),None)
                    if idx is None or idx+h>=len(rs):break
                    window=rs[idx:idx+h+1];end=window[-1]['trade_date']
                    if m.missed_weekdays(window[0]['trade_date'],dt.date.fromisoformat(end))!=h:break
                    p0=window[0]['adjusted_close']
                    outcomes[sym]={'forward_etf_return_pct':(window[-1]['adjusted_close']/p0-1)*100,
                                   'adjusted_start_price':p0,'adjusted_end_price':window[-1]['adjusted_close'],
                                   'evaluation_window_sha256':digest(window),'evaluation_cutoff':cutoff}
                    end_dates.append(end)
                if len(outcomes)==2 and len(set(end_dates))==1:
                    outcomes['meaning']='ETF_LABEL_DIAGNOSTIC_NOT_STRATEGY_REALIZED_PNL'
                    inserted+=c.execute('INSERT OR IGNORE INTO research_shadow_outcomes VALUES(?,?,?,?)',
                                        (row['signal_id'],h,end_dates[0],m.canonical(outcomes))).rowcount
    return {'new_outcomes':inserted,'live_predictive_evidence':'INSUFFICIENT'}

def audit(db):
    with closing(sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='research_shadow_signals'").fetchone():
            return {'signals':0,'hash_errors':0,'model_hash_errors':0,'dataset_hash_errors':0}
        rs=c.execute('SELECT signal_json,signal_sha256 FROM research_shadow_signals').fetchall()
        versions=dict(c.execute('SELECT model_sha256,source_json FROM research_model_versions'))
        missing=sum(json.loads(a)['model_sha256'] not in versions for a,b in rs)
        model_errors=sum(snapshots.source_hash(json.loads(value))!=sha for sha,value in versions.items())
        data_missing=0;data_errors=0
        has_data=bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='research_data_snapshots'").fetchone())
        valid_data=set();corrupt_data=set()
        if has_data:
            for (data_sha,) in c.execute('SELECT data_sha256 FROM research_data_snapshots').fetchall():
                try:
                    snapshots.read(c,data_sha);valid_data.add(data_sha)
                except ValueError:corrupt_data.add(data_sha)
        data_errors=len(corrupt_data)
        data_missing=sum(json.loads(raw)['data_sha256'] not in valid_data|corrupt_data for raw,_ in rs)
        qualified_data_missing=sum(json.loads(raw)['model_sha256'] in versions and json.loads(raw)['data_sha256'] not in valid_data|corrupt_data for raw,_ in rs)
        observations=c.execute('SELECT COUNT(*) FROM research_shadow_observations').fetchone()[0] if has_data else 0
    return {'signals':len(rs),'hash_errors':sum(digest(json.loads(a))!=b for a,b in rs),
            'model_hash_errors':model_errors,'dataset_hash_errors':data_errors,
            'qualified_source_archived_signals':len(rs)-missing,
            'excluded_pre_release_prototypes_without_source_archive':missing,
            'signals_without_frozen_input_snapshot':data_missing,'qualified_signals_without_frozen_input_snapshot':qualified_data_missing,'observation_attempts':observations}
