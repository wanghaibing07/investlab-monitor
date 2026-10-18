"""Deterministic research observations, never orders or a personal profit estimate."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / 'strategy_config.json'


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def config():
    return json.loads(CONFIG_PATH.read_text('utf8'))


def indicators(rows):
    if len(rows) < 252:
        return None
    p = [r['adjusted_close'] for r in rows]
    sma200 = statistics.mean(p[-200:])
    return {'close': p[-1], 'sma20': statistics.mean(p[-20:]),
            'sma50': statistics.mean(p[-50:]), 'sma200': sma200,
            'sma200_slope20_pct': (sma200 / statistics.mean(p[-220:-20]) - 1) * 100,
            'momentum63_pct': (p[-1] / p[-64] - 1) * 100,
            'drawdown252_pct': (p[-1] / max(p[-252:]) - 1) * 100,
            'vol20_pct': statistics.stdev([math.log(p[i] / p[i-1])
                                         for i in range(len(p)-20, len(p))]) * math.sqrt(252) * 100,
            'two_closes_above_sma20': (p[-1] > statistics.mean(p[-20:]) and
                                      p[-2] > statistics.mean(p[-21:-1]))}


def classify(m):
    if m['vol20_pct'] >= 45 or m['drawdown252_pct'] <= -25:
        return 'CRISIS'
    if m['close'] < m['sma200'] * .97 and m['sma200_slope20_pct'] < 0:
        return 'RISK_OFF'
    if (m['close'] > m['sma200'] and m['sma50'] > m['sma200'] and
            m['sma200_slope20_pct'] > 0 and m['momentum63_pct'] > 0 and m['vol20_pct'] < 30):
        return 'BULL'
    return 'NEUTRAL'


def elapsed_sessions(session_dates, anchor_date):
    """Explicit policy clock shared by observer and historical simulation."""
    dt.date.fromisoformat(anchor_date)
    return sum(date > anchor_date for date in session_dates)


def targets(m, cfg, elapsed_sessions=0):
    """Hypothetical weights. Time counter is anchored, never reset each daily run."""
    regime = classify(m)
    q = cfg['qqq']
    dd = m['drawdown252_pct']
    if regime == 'BULL':
        key = 'dd_over_15' if dd <= -15 else ('dd_10_to_15' if dd <= -10 else
                   ('dd_5_to_10' if dd <= -5 else 'dd_0_to_5'))
        weight = q['bull_targets'][key]
        clock = q['time_deployment']
        timed = min(clock['max_without_drawdown'], q['bull_targets']['dd_0_to_5'] +
                    (max(0, elapsed_sessions) // clock['every_sessions']) * clock['step'])
        weight = max(weight, timed)
    else:
        weight = q[{'CRISIS': 'crisis_target', 'RISK_OFF': 'risk_off_target',
                    'NEUTRAL': 'neutral_target'}[regime]]
        if regime == 'NEUTRAL':
            clock = q['time_deployment']
            weight = min(clock['max_without_drawdown'], weight +
                         (max(0, elapsed_sessions)//clock['every_sessions'])*clock['step'])
    t = cfg['tqqq']
    eligible = (regime == 'BULL' and t['qqq_drawdown_range'][0] <= dd <= t['qqq_drawdown_range'][1]
                and m['vol20_pct'] < t['qqq_vol20_entry_max'] and m['momentum63_pct'] > 0
                and m['two_closes_above_sma20'])
    tactical = t['entry_weight'] if eligible else 0.0
    # Both cash reserve and approximate daily Nasdaq exposure constrain the scenario.
    weight = min(weight, q['hard_max_weight'], 1-cfg['portfolio']['cash_min_weight']-tactical,
                 cfg['portfolio']['effective_ndx_exposure_max']-3*tactical)
    return {'regime': regime, 'qqq': weight, 'tqqq': tactical,
            'cash': 1-weight-tactical, 'tqqq_entry_condition_met': eligible}


def schema(db):
    import monitor as m
    with m.conn(db) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS strategy_versions (
          sha256 TEXT PRIMARY KEY, config_json TEXT NOT NULL, registered_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS strategy_signals (
          signal_id TEXT PRIMARY KEY, session_date TEXT, created_at TEXT NOT NULL,
          strategy_sha256 TEXT NOT NULL REFERENCES strategy_versions(sha256),
          data_sha256 TEXT NOT NULL, status TEXT NOT NULL, signal_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS signal_outcomes (
          signal_id TEXT NOT NULL REFERENCES strategy_signals(signal_id),
          horizon_sessions INTEGER NOT NULL, end_session TEXT NOT NULL,
          outcome_json TEXT NOT NULL, PRIMARY KEY(signal_id,horizon_sessions));
        CREATE TABLE IF NOT EXISTS backtest_runs (
          run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, result_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_receipts (
          receipt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, channel TEXT NOT NULL,
          provider_reference TEXT NOT NULL, status TEXT NOT NULL, recorded_at TEXT NOT NULL);
        ''')


def observe(report, candles):
    import monitor as m
    cfg = config()
    cutoff = report['as_of_expected_session']
    rows = {s: [r for r in candles[s] if r['trade_date'] <= cutoff] for s in m.LEGACY_SYMBOLS}
    prices = {s: [{'date': r['trade_date'], 'adj': r['adjusted_close'], 'raw': r['raw_close'],
                   'source': r['source']} for r in rows[s]] for s in m.LEGACY_SYMBOLS}
    reasons = []
    for sym in m.LEGACY_SYMBOLS:
        series = rows[sym]
        if len(series) < 252:
            reasons.append(sym + ':INSUFFICIENT_HISTORY')
            continue
        if series[-1]['trade_date'] != cutoff:
            reasons.append(sym + ':STALE_ADJUSTED_HISTORY')
        window = series[-252:]
        dates = {r['trade_date'] for r in window}
        day = dt.date.fromisoformat(window[0]['trade_date'])
        end = dt.date.fromisoformat(cutoff)
        while day <= end:
            if m.is_regular_session(day) and day.isoformat() not in dates:
                reasons.append(sym + ':MISSING_SESSION:' + day.isoformat())
            day += dt.timedelta(days=1)
        if any(not m.is_regular_session(dt.date.fromisoformat(d)) for d in dates):
            reasons.append(sym + ':NON_SESSION_DATA')
    if report['data_evidence_grade'] == 'SOURCE_CONFLICT':
        reasons.append('SOURCE_CONFLICT')
    # A fresh single-source series permits observation, but remains explicitly uncorroborated.
    status = 'DATA_GATE_BLOCKED' if reasons else 'RESEARCH_OBSERVATION_ONLY'
    data_hash = digest(prices)
    out = {'status': status, 'strategy_sha256': digest(cfg), 'data_sha256': data_hash,
           'session_date': cutoff, 'baseline_as_of': report['portfolio']['as_of'],
           'data_blockers': reasons, 'validation': 'EXPERIMENTAL_NOT_LONG_TERM_VALIDATED',
           'orders': [], 'trading_enabled': False, 'tqqq_scope': 'MONITOR_ONLY',
           'scenario_targets': None, 'executable_delta_cny': None,
           'current_valuation_is_not_live': report['portfolio']['as_of'] != cutoff,
           'independent_check': report['data_evidence_grade']}
    metrics = indicators(rows['QQQ'])
    out['indicators_as_of'] = rows['QQQ'][-1]['trade_date'] if rows['QQQ'] else None
    out['qqq_indicators'] = metrics
    out['historical_regime'] = classify(metrics) if metrics else 'UNKNOWN'
    if not reasons:
        elapsed = elapsed_sessions([r['trade_date'] for r in rows['QQQ']], report['portfolio']['as_of'])
        out['scenario_targets'] = targets(metrics, cfg, elapsed)
        out['time_deployment_elapsed_sessions'] = elapsed
    out['signal_id'] = digest({'config': digest(cfg), 'prices': data_hash,
                              'cutoff': cutoff, 'portfolio': report['portfolio'],
                              'status': status, 'independent_check': out['independent_check']})[:24]
    return out


def persist(signal, created_at, db):
    import monitor as m
    schema(db)
    cfg = config()
    with m.conn(db) as c:
        c.execute('INSERT OR IGNORE INTO strategy_versions VALUES(?,?,?)',
                  (digest(cfg), canonical(cfg), created_at))
        c.execute('INSERT OR IGNORE INTO strategy_signals VALUES(?,?,?,?,?,?,?)',
                  (signal['signal_id'], signal['session_date'], created_at, signal['strategy_sha256'],
                   signal['data_sha256'], signal['status'], canonical(signal)))


def evaluate(db):
    """Forward ETF returns, not personal account performance; never use incomplete sessions."""
    import monitor as m
    schema(db)
    cutoff = m.expected_close_session().isoformat()
    data = {s: [r for r in v if r['trade_date'] <= cutoff] for s, v in m.price_data(db).items() if s in m.LEGACY_SYMBOLS}
    inserted = 0
    with m.conn(db) as c:
        signals = c.execute("SELECT * FROM strategy_signals WHERE status='RESEARCH_OBSERVATION_ONLY'").fetchall()
        for signal in signals:
            for horizon in (7, 30, 90):
                result = {}
                end_dates = []
                for sym, series in data.items():
                    index = next((i for i, r in enumerate(series) if r['trade_date'] == signal['session_date']), None)
                    if index is None or index + horizon >= len(series):
                        break
                    window = series[index:index+horizon+1]
                    expected = m.missed_weekdays(window[0]['trade_date'], dt.date.fromisoformat(window[-1]['trade_date']))
                    if expected != horizon:
                        break
                    p0 = window[0]['adjusted_close']
                    result[sym] = {'forward_return_pct': (window[-1]['adjusted_close']/p0-1)*100,
                                   'max_adverse_excursion_pct': min(0, min(r['adjusted_close']/p0-1 for r in window))*100}
                    end_dates.append(window[-1]['trade_date'])
                if len(result) == 2 and len(set(end_dates)) == 1:
                    result['meaning'] = 'ETF_FORWARD_RETURNS_NOT_ACTUAL_ACCOUNT_PNL'
                    cur = c.execute('INSERT OR IGNORE INTO signal_outcomes VALUES(?,?,?,?)',
                                    (signal['signal_id'], horizon, end_dates[0], canonical(result)))
                    inserted += cur.rowcount
    return {'new_outcomes': inserted, 'horizons_trading_sessions': [7, 30, 90]}


def rebalance(values, q, t, cost):
    """Solve post-fee equity before setting target amounts; buy and sell both incur fees."""
    equity = sum(values)
    net = equity
    for _ in range(40):
        traded = abs(q*net-values[0]) + abs(t*net-values[1])
        new_net = equity-cost*traded
        if abs(new_net-net) < 1e-12:
            break
        net = new_net
    traded = abs(q*new_net-values[0]) + abs(t*new_net-values[1])
    return [q*new_net, t*new_net, (1-q-t)*new_net], cost*traded, traded


def backtest(db, cost_bps=15):
    import monitor as m
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 500:
        raise ValueError('Cost must be 0..500 bps per side')
    data = m.price_data(db)
    cutoff = m.expected_close_session().isoformat()
    qmap = {r['trade_date']: r for r in data['QQQ'] if r['trade_date'] <= cutoff}
    tmap = {r['trade_date']: r for r in data['TQQQ'] if r['trade_date'] <= cutoff}
    dates = sorted(qmap.keys() & tmap.keys())
    if len(dates) < 254:
        raise ValueError('Need at least 254 aligned trading sessions including warmup')
    start, end = dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1])
    if any(not m.is_regular_session(dt.date.fromisoformat(d)) for d in dates):
        raise ValueError('Non-trading session in history')
    day = start
    while day <= end:
        if m.is_regular_session(day) and day.isoformat() not in qmap.keys() & tmap.keys():
            raise ValueError('Historical gap: ' + day.isoformat())
        day += dt.timedelta(days=1)
    cfg = config()
    metrics = [None]*251 + [indicators([qmap[d] for d in dates[:i+1]]) for i in range(251,len(dates))]
    cost = cost_bps/10000
    results = {}
    names=('QQQ_BUY_HOLD','QQQ60_CASH40_MONTHLY','QQQ80_CASH20_MONTHLY',
           'TQQQ_BUY_HOLD_STRESS','QQQ95_TQQQ5_MONTHLY_RESEARCH','QQQ_SMA200_FILTER',
           'QQQ_VOL12_MAX80','RESEARCH_QQQ_CORE_ONLY','RESEARCH_TQQQ_TACTICAL',
           'USER_PLAN_QQQ70_TQQQ20_CASH10_MONTHLY')
    for name in names:
        q0 = 1.0 if name in ('QQQ_BUY_HOLD','QQQ_SMA200_FILTER') else (
            .95 if name=='QQQ95_TQQQ5_MONTHLY_RESEARCH' else (
            .8 if name in ('QQQ80_CASH20_MONTHLY','QQQ_VOL12_MAX80') else .6))
        t0=1.0 if name=='TQQQ_BUY_HOLD_STRESS' else (.05 if name=='QQQ95_TQQQ5_MONTHLY_RESEARCH' else 0)
        if name=='USER_PLAN_QQQ70_TQQQ20_CASH10_MONTHLY':q0,t0=.7,.2
        if name=='TQQQ_BUY_HOLD_STRESS':q0=0
        if name in ('QQQ_SMA200_FILTER','QQQ_VOL12_MAX80'):
            # No pre-warmup signal: remain cash until the first delayed execution.
            q0=0
        values, fees, turnover = rebalance([0,0,1], q0, t0, cost)
        curve = [sum(values)];returns=[];rebalances=1
        tactical_entry=None
        for i in range(252,len(dates)):
            # Position held during day i was decided before its price became known.
            old=sum(values)
            values[0] *= qmap[dates[i]]['adjusted_close']/qmap[dates[i-1]]['adjusted_close']
            values[1] *= tmap[dates[i]]['adjusted_close']/tmap[dates[i-1]]['adjusted_close']
            should = False
            tactical_target=0
            signal_metrics=metrics[i-1]
            if name in ('RESEARCH_QQQ_CORE_ONLY','RESEARCH_TQQQ_TACTICAL'):
                # Signal at i-1, execute at i close. No open prices are available.
                scenario=targets(signal_metrics,cfg,elapsed_sessions(dates[:i],dates[251]))
                target=scenario['qqq']
                if name=='RESEARCH_TQQQ_TACTICAL':
                    if tactical_entry is not None:
                        prev_equity=curve[-1]
                        prev_t_weight=(values[1]/(tmap[dates[i]]['adjusted_close']/tmap[dates[i-1]]['adjusted_close']))/prev_equity
                        should_exit=(signal_metrics['close'] < signal_metrics['sma200'] or
                            signal_metrics['vol20_pct'] >= cfg['tqqq']['qqq_vol20_exit'] or
                            tmap[dates[i-1]]['adjusted_close']/tactical_entry-1 <= -.2 or
                            prev_t_weight > cfg['tqqq']['hard_max_weight'])
                        if not should_exit:
                            tactical_target=(.05 if prev_t_weight>.075 else prev_t_weight)
                    else:
                        tactical_target=scenario['tqqq']
                    target=min(target,1-cfg['portfolio']['cash_min_weight']-tactical_target,
                               cfg['portfolio']['effective_ndx_exposure_max']-3*tactical_target)
                should = (abs(values[0]/sum(values)-target) >= .05-1e-12 or
                          (name=='RESEARCH_TQQQ_TACTICAL' and
                           abs(tactical_target-values[1]/sum(values)) >= .005))
            elif name=='QQQ_SMA200_FILTER':
                target=1.0 if signal_metrics['close']>signal_metrics['sma200'] else 0.0
                should=(target==0 and values[0]>0) or (target==1 and values[2]>0)
            elif name=='QQQ_VOL12_MAX80':
                target=min(.8,12/max(signal_metrics['vol20_pct'],.01))
                should=abs(values[0]/sum(values)-target)>=.05
            else:
                target = q0
                tactical_target=t0
                should = name not in ('QQQ_BUY_HOLD','TQQQ_BUY_HOLD_STRESS') and dates[i][:7] != dates[i-1][:7]
            if should:
                previous_t=values[1]
                values, fee, traded = rebalance(values,target,tactical_target,cost)
                if name=='RESEARCH_TQQQ_TACTICAL':
                    if previous_t==0 and values[1]>0:tactical_entry=tmap[dates[i]]['adjusted_close']
                    elif values[1]==0:tactical_entry=None
                fees+=fee;turnover+=traded;rebalances+=1
            equity=sum(values);curve.append(equity);returns.append(equity/old-1)
        peak=1.0;mdd=0;peak_index=0;worst_peak=0;worst_trough=0
        for index,value in enumerate(curve):
            if value>peak:peak=value;peak_index=index
            drawdown=value/peak-1
            if drawdown<mdd:mdd=drawdown;worst_peak=peak_index;worst_trough=index
        recovery=next((j for j in range(worst_trough+1,len(curve)) if curve[j]>=curve[worst_peak]),None)
        n=len(returns);sigma=statistics.stdev(returns) if n>1 else 0
        results[name]={'total_return_pct':(curve[-1]-1)*100,
                       'cagr_pct':(curve[-1]**(252/n)-1)*100,
                       'max_drawdown_pct':mdd*100,
                       'sharpe_rf_zero':statistics.mean(returns)/sigma*math.sqrt(252) if sigma else None,
                       'external_cost_fraction_of_initial_capital':fees,
                       'turnover_fraction_of_initial_capital':turnover,
                       'rebalances':rebalances,
                       'worst_drawdown_peak_session':dates[251+worst_peak],
                       'worst_drawdown_trough_session':dates[251+worst_trough],
                       'recovery_session':dates[251+recovery] if recovery is not None else None,
                       'recovery_trading_sessions_from_peak':recovery-worst_peak if recovery is not None else None,
                       'terminal_hypothetical_weights':{'QQQ':values[0]/sum(values),'TQQQ':values[1]/sum(values),'CASH':values[2]/sum(values)},
                       'year_returns_pct':{}}
        for year in sorted({d[:4] for d in dates[251:]}):
            indices=[j for j,d in enumerate(dates[251:]) if d.startswith(year)]
            begin=max(0,indices[0]-1);finish=indices[-1]
            results[name]['year_returns_pct'][year]=(curve[finish]/curve[begin]-1)*100
    out={'first_execution_session':dates[251],'last_session':dates[-1],
         'evaluation_sessions':len(dates)-252,'warmup_sessions':252,
         'data_sha256':digest({'QQQ':[qmap[d] for d in dates],'TQQQ':[tmap[d] for d in dates]}),
         'strategy_sha256':digest(cfg),'cost_bps_per_side':cost_bps,'cash_interest':0,
         'currency':'USD_NORMALIZED_NOT_CNY_ACCOUNT','execution':'signal_close_t_execute_close_t_plus_1',
         'strategy_inception_date':dates[251],
         'time_anchor_scope':'HISTORICAL_STRATEGY_INCEPTION_NOT_USER_ACCOUNT_DATE',
         'tqqq_backtest_scope':'HYPOTHETICAL_RESEARCH_ONLY_NO_ACCOUNT_TRANSACTION','results':results,
         'limits':['NO_TAX_FX_OR_CASH_YIELD','NO_OUT_OF_SAMPLE_VALIDATION',
                   'POST_2010_SAMPLE_EXCLUDES_DOTCOM_CRASH',
                   'NEXT_CLOSE_EXECUTION_NOT_OPEN_EXECUTION',
                   'FIRST_252_SESSIONS_ARE_WARMUP_NOT_EVALUATED',
                   'RULES_ARE_EXPERIMENTAL_NOT_A_PROVEN_OPTIMUM']}
    out['run_id']=digest(out)[:24]
    schema(db)
    with m.conn(db) as c:
        c.execute('INSERT OR IGNORE INTO backtest_runs VALUES(?,?,?)',(out['run_id'],m.ztime(),canonical(out)))
    return out
