"""Risk forecasts, paired moving-block scenarios and decision economics.

Daily output is explanatory research. Probabilities of an explicit downside event
and frequencies inside a resampling model are different quantities.
"""
import datetime as dt
import json
import math
import random
import statistics as st
from pathlib import Path
from contextlib import closing
import sqlite3
import monitor as m
from .common import ROOT,DATA_ROOT, digest, write_json
from .dataset import from_candles, load, semantic_content, active_candles
from . import snapshots

PROTOCOL = ROOT / 'research/quant_protocol.json'


def config():
    return json.loads(PROTOCOL.read_text('utf8'))


def sources():
    return {name: (ROOT/name).read_text('utf8') for name in
            ('research/quant.py', 'research/quant_protocol.json', 'research/dataset.py', 'monitor.py')}


def model_hash():
    return digest(sources())


def sigmoid(z):
    return 1/(1+math.exp(-max(-35, min(35, z))))


def active_data(candles,cutoff):
    result=active_candles(candles,cutoff)
    result['data_vintage_sha256']=digest({s:result[s] for s in m.ACTIVE_SYMBOLS})
    return result


def load_active(db,cutoff=None):
    return active_data(m.price_data(db),cutoff or m.expected_close_session().isoformat())


def design(data):
    prices = [r['adjusted_close'] for r in data['QQQ']]
    returns = [0.0]+[math.log(b/a) for a,b in zip(prices, prices[1:])]
    out = [None]*len(prices)
    for i in range(251, len(prices)):
        vals = [(prices[i]/st.mean(prices[i-199:i+1])-1)/.20,
                st.stdev(returns[i-19:i+1])*math.sqrt(252)/.30,
                (prices[i]/prices[i-63]-1)/.20]
        # Fixed economic scales; clipping is fixed before fitting, not sample-fitted.
        out[i] = [1.0]+[max(-5.0, min(5.0, v)) for v in vals]
    return out


def samples(data, xs, boundary, p):
    """Only labels fully observable strictly BEFORE the forecast origin."""
    h=p['event']['horizon']; threshold=p['event']['threshold']
    q=[r['adjusted_close'] for r in data['QQQ']]
    out=[]
    for i in range(251, boundary-h, p['logistic']['stride']):
        if i+h >= len(q): continue
        label=int(min(q[i+1:i+h+1])/q[i]-1 <= threshold)
        out.append({'i':i, 'end_i':i+h, 'x':xs[i], 'y':label})
    return out


def fit(rows, p):
    cfg=p['logistic']; n=len(rows); positives=sum(r['y'] for r in rows)
    base=(positives+1)/(n+2)  # Beta(1,1) smoothing, fixed before evaluation.
    result={'samples':n, 'events':positives, 'base_probability':base,
            'training_sample_sha256':digest(rows), 'coefficients':None,
            'status':'BASE_RATE_FALLBACK'}
    if n<cfg['minimum_samples'] or min(positives, n-positives)<cfg['minimum_each_class']:
        return result
    beta=[math.log(base/(1-base)), 0., 0., 0.]
    # Bound the logistic-loss curvature to keep deterministic gradient steps stable.
    step=min(cfg['learning_rate'],1/(.25*max(sum(x*x for x in row['x']) for row in rows)+cfg['ridge']))
    for _ in range(cfg['iterations']):
        grad=[0.0]*len(beta)
        for row in rows:
            error=sigmoid(sum(b*x for b,x in zip(beta,row['x'])))-row['y']
            for k,x in enumerate(row['x']): grad[k]+=error*x/n
        for k in range(len(beta)):
            beta[k]-=step*(grad[k]+(cfg['ridge']*beta[k] if k else 0))
    result.update(status='REGULARIZED_LOGISTIC', coefficients=beta)
    return result


def predict(fitted, x):
    b=fitted['coefficients']
    return sigmoid(sum(a*v for a,v in zip(b,x))) if b else fitted['base_probability']


def forecast(data, p, xs=None):
    xs=xs or design(data); origin=len(data['dates'])-1
    rows=samples(data,xs,origin,p); fitted=fit(rows,p)
    probability=predict(fitted,xs[origin])
    return {**fitted, 'origin':data['dates'][origin], 'event':p['event'],
            'probability':probability, 'features':xs[origin],
            'latest_training_label_end':data['dates'][rows[-1]['end_i']] if rows else None,
            'training_label_end_before_origin':all(r['end_i']<origin for r in rows),
            'meaning':'QQQ_CLOSE_FALLS_10_PERCENT_FROM_ORIGIN_WITHIN_NEXT_20_SESSIONS',
            'calibration_status':'NOT_YET_FORWARD_VALIDATED',
            'not_tqqq_or_portfolio_loss_probability':True}


def percentile(values, level):
    a=sorted(values); x=(len(a)-1)*level; i=int(x); j=min(i+1,len(a)-1)
    return a[i]+(a[j]-a[i])*(x-i)


def validate_forecast(data, p):
    xs=design(data); dates=data['dates']; all_rows=samples(data,xs,len(dates),p)
    folds=[]; points=[]
    for year in range(p['first_test_year'],int(dates[-1][:4])+1):
        origin=next((i for i,d in enumerate(dates) if d>=f'{year}-01-01'),None)
        if origin is None or origin<251: continue
        train=samples(data,xs,origin,p); fitted=fit(train,p)
        test=[r for r in all_rows if dates[r['i']].startswith(str(year))]
        rows=[]
        for r in test:
            pr=predict(fitted,r['x']); base=fitted['base_probability']; y=r['y']
            rows.append({'date':dates[r['i']], 'label_end':dates[r['end_i']], 'y':y,
                         'probability':pr,'base':base, 'brier':(pr-y)**2,
                         'base_brier':(base-y)**2,
                         'log_loss':-y*math.log(max(pr,1e-12))-(1-y)*math.log(max(1-pr,1e-12))})
        if not rows: continue
        folds.append({'year':year,'train':fitted,'training_cutoff_exclusive':dates[origin],
                      'latest_label_end':dates[train[-1]['end_i']] if train else None,
                      'test_samples':len(rows), 'test_events':sum(r['y'] for r in rows),
                      'brier':st.mean(r['brier'] for r in rows),
                      'base_brier':st.mean(r['base_brier'] for r in rows),
                      'full_calendar_year':year<int(dates[-1][:4])})
        points.extend(rows)
    if not points: return {'status':'INSUFFICIENT_HISTORY','folds':folds}
    bs=st.mean(r['brier'] for r in points); bb=st.mean(r['base_brier'] for r in points)
    differences=[r['base_brier']-r['brier'] for r in points]
    rng=random.Random(p['simulation']['seed']); means=[]
    for _ in range(1000):
        idx=block_indices(len(points),len(points),3,rng)
        means.append(st.mean(differences[i] for i in idx))
    ci=[percentile(means,.025),percentile(means,.975)]
    calibration=[]
    edges=[0.,.05,.10,.20,.40,1.000001]
    for a,b in zip(edges,edges[1:]):
        rs=[r for r in points if a<=r['probability']<b]
        calibration.append({'range':[a,min(b,1.)], 'n':len(rs),
                            'mean_predicted':st.mean(r['probability'] for r in rs) if rs else None,
                            'observed_frequency':st.mean(r['y'] for r in rs) if rs else None})
    full=[f for f in folds if f['full_calendar_year']]
    fraction=st.mean(f['brier']<f['base_brier'] for f in full) if full else 0
    passed=len(full)>=5 and ci[0]>0 and fraction>=.6 and sum(r['y'] for r in points)>=5
    return {'status':'HISTORICAL_TIME_FORWARD_NOT_BLIND', 'folds':folds,'points':points,
            'samples':len(points),'events':sum(r['y'] for r in points),
            'brier':bs,'base_brier':bb,'brier_skill':1-bs/bb if bb else None,
            'log_loss':st.mean(r['log_loss'] for r in points),
            'paired_brier_improvement_95pct_block_interval':ci,
            'complete_year_fraction_beating_base':fraction,
            'calibration':calibration,
            'research_screen':'PASS_HISTORICAL_SCREEN_ONLY' if passed else 'NO_DEMONSTRATED_ADVANTAGE',
            'production_use':'EXPLANATORY_ONLY_NO_ALLOCATION_OVERRIDE',
            'limits':['HISTORY_ALREADY_SEEN','ONE_MODEL_NO_HYPERPARAMETER_SEARCH',
                      'NONOVERLAPPING_20_SESSION_ORIGINS_CAN_STILL_BE_DEPENDENT',
                      '95_PERCENT_INTERVAL_IS_POINTWISE_NOT_MULTI_MODEL_CORRECTED']}


def block_indices(n,horizon,block,rng):
    if n<block or block<1 or horizon<1: raise ValueError('Invalid block sample dimensions')
    out=[]
    while len(out)<horizon:
        start=rng.randrange(n-block+1)
        out.extend(range(start,start+block))
    return out[:horizon]


def check_weights(w):
    if set(w) not in (set(('QQQ','TQQQ','CASH')),set(('QQQ','QLD','TQQQ','CASH'))) or any(not math.isfinite(x) or x<0 for x in w.values()) or abs(sum(w.values())-1)>1e-8:
        raise ValueError('Invalid scenario weights')


def scenario_path(pairs,w):
    check_weights(w); values={s:w.get(s,0.) for s in m.SYMBOLS};c=w['CASH'];peak=1.;dd=0.
    for pair in pairs:
        symbols=m.SYMBOLS if len(pair)==3 else m.LEGACY_SYMBOLS
        if len(pair)!=len(symbols) or any(not math.isfinite(r) or r < -1 for r in pair):raise ValueError('Invalid scenario return')
        if 'QLD' not in symbols and values['QLD']>0:raise ValueError('QLD return path missing')
        for symbol,r in zip(symbols,pair):values[symbol]*=1+r
        value=sum(values.values())+c;peak=max(peak,value);dd=min(dd,value/peak-1)
    return {'terminal_return':sum(values.values())+c-1,'max_drawdown':dd}


def paths(data,portfolios,p,*,horizon=None,count=None,block=None,lookback=None):
    cfg=p['simulation']; horizon=horizon or cfg['daily_horizon']; count=count or cfg['daily_paths']; block=block or cfg['block_sessions']
    if not 1<=count<=10000: raise ValueError('Invalid path count')
    symbols=tuple(s for s in m.SYMBOLS if s in data)
    prices={s:[r['adjusted_close'] for r in data[s]] for s in symbols}
    pairs=[tuple(prices[s][i]/prices[s][i-1]-1 for s in symbols) for i in range(1,len(data['dates']))]
    if lookback: pairs=pairs[-lookback:]
    for w in portfolios.values(): check_weights(w)
    rng=random.Random(cfg['seed']); outcomes={name:[] for name in portfolios}; diffs={}
    for _ in range(count):
        indices=block_indices(len(pairs),horizon,block,rng); sample=[pairs[i] for i in indices]
        for name,w in portfolios.items(): outcomes[name].append(scenario_path(sample,w))
    summaries={}
    for name,rs in outcomes.items():
        returns=[r['terminal_return'] for r in rs]; dd=[r['max_drawdown'] for r in rs]
        tail=sorted(returns)[:max(1,math.ceil(.05*count))]
        summaries[name]={'initial_weights':portfolios[name],
            'terminal_return_p05_p50_p95':[percentile(returns,x) for x in (.05,.5,.95)],
            'loss_frequency':st.mean(x<0 for x in returns),
            'drawdown_20pct_frequency':st.mean(x<=-.2 for x in dd),
            'drawdown_p05':percentile(dd,.05), 'terminal_expected_shortfall_95':st.mean(tail),
            'loss_frequency_mc_standard_error':math.sqrt(st.mean(x<0 for x in returns)*(1-st.mean(x<0 for x in returns))/count)}
    base='CORE60_CASH40' if 'CORE60_CASH40' in outcomes else next(iter(outcomes))
    for name,rs in outcomes.items():
        delta=[a['terminal_return']-b['terminal_return'] for a,b in zip(rs,outcomes[base])]
        diffs[name]={'reference':base,'terminal_return_difference_p05_p50_p95':[percentile(delta,x) for x in (.05,.5,.95)],
                     'outperform_frequency_inside_model':st.mean(x>0 for x in delta)}
    return {'status':'PAIRED_MOVING_BLOCK_HISTORICAL_RESAMPLING','seed':cfg['seed'],
            'horizon':horizon,'paths':count,'block':block,'sample_return_sessions':len(pairs),
            'sample_start':data['dates'][-len(pairs)-1],'sample_end':data['dates'][-1],
            'portfolios':summaries,'paired_comparisons':diffs,
            'rebalance':'NONE_BUY_AND_HOLD_WEIGHTS_DRIFT',
            'cash':'ZERO_RETURN_IN_SCENARIO_NUMERAIRE_NOT_ACTUAL_CURRENCY_MAPPING',
            'limits':['FREQUENCIES_INSIDE_MODEL_NOT_CALIBRATED_MARKET_PROBABILITIES',
                      'POST_2010_SAMPLE_NO_2000_OR_2008','BLOCK_BOUNDARIES_BREAK_LONG_REGIMES',
                      'NO_STRATEGY_RESPONSE_ENTRY_FEES_TAX_OR_FX','ACTUAL_ETF_RETURNS_ALREADY_EMBED_FUND_DRAG']}


def risk_contributions(data,w,window=60):
    check_weights(w);symbols=tuple(s for s in m.SYMBOLS if s in data)
    if w.get('QLD',0)>0 and 'QLD' not in symbols:raise ValueError('QLD covariance data missing')
    prices={s:[r['adjusted_close'] for r in data[s]][-window-1:] for s in symbols}
    rs={s:[b/a-1 for a,b in zip(prices[s],prices[s][1:])] for s in symbols};n=len(rs['QQQ'])
    means={s:st.mean(rs[s]) for s in symbols}
    cov={s:{t:sum((a-means[s])*(b-means[t]) for a,b in zip(rs[s],rs[t]))/(n-1)*252 for t in symbols} for s in symbols}
    var=max(0.,sum(w.get(s,0)*w.get(t,0)*cov[s][t] for s in symbols for t in symbols))
    shares={s:w.get(s,0)*sum(cov[s][t]*w.get(t,0) for t in symbols)/var if var else 0 for s in symbols};shares['CASH']=0
    return {'window':n,'annual_volatility':math.sqrt(var),
            'approximate_single_day_ndx_exposure':w['QQQ']+2*w.get('QLD',0)+3*w['TQQQ'],
            'variance_contribution_share':shares,
            'qqq_tqqq_correlation':cov['QQQ']['TQQQ']/math.sqrt(cov['QQQ']['QQQ']*cov['TQQQ']['TQQQ']) if cov['QQQ']['QQQ']*cov['TQQQ']['TQQQ'] else None,
            'covariance':cov,'cash_and_fx_risk_omitted':True,'volatility_is_not_a_loss_limit':True}


def cost_hurdles(report,p):
    account=report['portfolio']; review=report.get('allocation_review',{})
    baseline=review.get('current_baseline_weights'); target=review.get('next_review_weights')
    result={'status':'ASSUMPTION_GRID_NOT_BROKER_QUOTE','account_as_of':account['as_of'],
            'actual_commission_fx_tax_fractional_share_rules':'UNKNOWN', 'tickets':[]}
    if not baseline or not target: return result
    for s in m.SYMBOLS:
        amount=abs(target.get(s,0)-baseline.get(s,0))*account['total_cny']
        if amount<.01: continue
        grid=[]
        for bps in p['cost_scenarios']['bps_per_side']:
            for fixed in p['cost_scenarios']['fixed_cny_per_ticket']:
                cost=amount*bps/10000+fixed
                grid.append({'bps':bps,'fixed_cny':fixed,'one_way_cny':cost,
                             'roundtrip_hurdle_on_traded_slice':2*cost/amount,
                             'roundtrip_hurdle_on_baseline_equity':2*cost/account['total_cny']})
        result['tickets'].append({'symbol':s,'hypothetical_notional_cny_at_old_baseline':amount,'grid':grid})
    return result


def fx_sensitivity(w):
    """Explicit assumed USD ETF sleeve, CNY cash. No actual FX or custody inferred."""
    check_weights(w); output=[]
    for asset_return in (-.30,0.,.30):
        for usd_cny_change in (-.10,0.,.10):
            sleeve=(1+asset_return)*(1+usd_cny_change)-1
            output.append({'usd_etf_sleeve_return':asset_return,'usd_cny_change':usd_cny_change,
                           'hypothetical_cny_portfolio_return':(w['QQQ']+w.get('QLD',0)+w['TQQQ'])*sleeve})
    return {'assumption':'ALL_ETFS_ARE_USD_DENOMINATED_AND_CASH_IS_CNY_NO_HEDGE','grid':output}


def portfolios_for(report):
    account=report['portfolio']; total=account['total_cny']
    result={'LAST_CONFIRMED_BASELINE':{'QQQ':account['qqq_value_cny']/total,'TQQQ':account['tqqq_value_cny']/total,'QLD':account.get('qld_value_cny',0)/total,'CASH':account['cash_cny']/total},
            'CORE60_CASH40':{'QQQ':.6,'TQQQ':0.,'CASH':.4},
            'FULL_TARGET_REFERENCE':report['allocation_review']['strategic_reference'],
            'QQQ100_REFERENCE':{'QQQ':1.,'TQQQ':0.,'CASH':0.}}
    next_w=report.get('allocation_review',{}).get('next_review_weights')
    if next_w: result['NEXT_REVIEW_REFERENCE']=next_w
    return result


def observe(report,candles):
    p=config(); result={'status':'DATA_BLOCKED','scope':'QUANT_EXPLANATORY_RESEARCH',
            'session_date':report['as_of_expected_session'],'model_sha256':model_hash(),
            'protocol_sha256':digest(p),'orders':[],'allocation_override':False}
    try:
        review=report.get('allocation_review',{})
        if review.get('status')=='DATA_BLOCKED' or report.get('data_evidence_grade')=='SOURCE_CONFLICT': raise ValueError('PRICE_DATA_GATE')
        data=active_data(candles,report['as_of_expected_session'])
        if data['quality']=='CACHE_ONLY_STALE': raise ValueError('STALE_ALIGNED_HISTORY')
        portfolios=portfolios_for(report)
        result.update(status='ONLINE_RESEARCH_CONTEXT' if review.get('status')=='ALLOCATION_REVIEW' else 'CACHE_REPLAY_ONLY',
            data_sha256=data['data_sha256'], account_as_of=report['portfolio']['as_of'],
            risk_forecast=forecast(data,p), path_simulation=paths(data,portfolios,p),
            risk_contributions={n:risk_contributions(data,w,p['covariance_sessions']) for n,w in portfolios.items()},
            cost_hurdles=cost_hurdles(report,p), fx_sensitivity=fx_sensitivity(portfolios['FULL_TARGET_REFERENCE']))
        validation_file=DATA_ROOT/'quant53/validation.json'
        if validation_file.exists():
            validation=json.loads(validation_file.read_text())
            if validation['model_sha256']==result['model_sha256']:
                result['historical_validation']={k:validation[k] for k in ('research_screen','brier_skill','samples','events','data_end')}
        result['unknown_inputs']=['CURRENT_ACCOUNT_VALUATION','ACTUAL_BROKER_FEES_AND_CURRENCY',
                                  'PERSONAL_CASH_RESERVE_AND_LOSS_BUDGET','INDEPENDENT_ADJUSTED_HISTORY']
    except (ValueError,KeyError,ZeroDivisionError) as exc: result['blocker']=str(exc)
    result['analysis_id']=digest(result)[:24]
    return result


def report_lines(result):
    lines=['## 量化模型与路径推演','状态：'+result['status']]
    if 'risk_forecast' not in result: return lines+['原因：'+result.get('blocker','计算失败')]
    f=result['risk_forecast']; lines.append(f"模型估计：未来20个交易日内，QQQ某日收盘较{f['origin']}收盘低至少10%的概率为 {f['probability']:.1%}；训练历史频率基准 {f['base_probability']:.1%}。这是待验证预测，不是TQQQ或全账户亏损概率。")
    v=result.get('historical_validation')
    if v: lines.append(f"历史按年向前验证：Brier技能分 {v['brier_skill']:.3f}（大于0才优于历史频率）；{v['samples']}个不重叠窗口、{v['events']}次事件。结论 {v['research_screen']}；截至{v['data_end']}。")
    sim=result['path_simulation']; full=sim['portfolios']['FULL_TARGET_REFERENCE']; a,b,c=full['terminal_return_p05_p50_p95']
    lines.append(f"60% QQQ / 40% TQQQ目标组合：{sim['paths']}条联合区块模拟、每条{sim['horizon']}交易日，期末收益5%/50%/95%分位为 {a:.1%}/{b:.1%}/{c:.1%}。这些是模型内分布，不能当作市场承诺。")
    rc=result['risk_contributions']['FULL_TARGET_REFERENCE']
    lines.append(f"模型参考中的TQQQ占近{rc['window']}日组合方差约 {rc['variance_contribution_share']['TQQQ']:.1%}；组合估计年化波动 {rc['annual_volatility']:.1%}。")
    lines.append('费用门槛与汇率情景已计算；金额按最后确认基线推演。实际佣金、兑换费和当前估值待补齐，详细值见JSON。')
    return lines


def ensure_schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS quant53_models (
      model_sha256 TEXT PRIMARY KEY,source_json TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS quant53_analyses (
      analysis_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,session_date TEXT NOT NULL,
      model_sha256 TEXT NOT NULL REFERENCES quant53_models(model_sha256),
      data_sha256 TEXT NOT NULL,analysis_json TEXT NOT NULL,analysis_sha256 TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS quant53_outcomes (
      analysis_id TEXT PRIMARY KEY REFERENCES quant53_analyses(analysis_id),
      outcome_json TEXT NOT NULL,outcome_sha256 TEXT NOT NULL);''')


def persist(result,created_at,db):
    if result['status']!='ONLINE_RESEARCH_CONTEXT': return
    if result['model_sha256']!=model_hash(): raise ValueError('Quant source changed before persistence')
    data=load_active(db,result['session_date'])
    if result['data_sha256']!=data['data_sha256']: raise ValueError('Quant input changed before persistence')
    with m.conn(db) as c:
        ensure_schema(c); snapshots.ensure_schema(c); snapshots.archive(c,data,created_at)
        c.execute('INSERT OR IGNORE INTO quant53_models VALUES(?,?)',(model_hash(),m.canonical(sources())))
        c.execute('INSERT OR IGNORE INTO quant53_analyses VALUES(?,?,?,?,?,?,?)',
                  (result['analysis_id'],created_at,result['session_date'],model_hash(),data['data_sha256'],m.canonical(result),digest(result)))


def evaluate(db,cutoff=None):
    cutoff=cutoff or m.expected_close_session().isoformat(); inserted=0
    with m.conn(db) as c:
        ensure_schema(c)
        prices=c.execute('SELECT trade_date,adjusted_close FROM daily_prices WHERE symbol=? AND trade_date<=? ORDER BY trade_date',('QQQ',cutoff)).fetchall()
        dates=[r[0] for r in prices]; values=[r[1] for r in prices]
        existing={r[0] for r in c.execute('SELECT analysis_id FROM quant53_outcomes')}
        seen=set()
        for aid,raw in c.execute('SELECT analysis_id,analysis_json FROM quant53_analyses ORDER BY created_at,analysis_id').fetchall():
            obj=json.loads(raw); f=obj['risk_forecast']; h=f['event']['horizon']
            key=(f['origin'],obj['model_sha256'])
            if key in seen: continue
            seen.add(key)
            if aid in existing: continue
            if f['origin'] not in dates: continue
            i=dates.index(f['origin'])
            if i+h>=len(dates): continue
            if m.missed_weekdays(dates[i],dt.date.fromisoformat(dates[i+h]))!=h: continue
            loss=min(values[i+1:i+h+1])/values[i]-1; y=int(loss<=f['event']['threshold'])
            out={'origin':dates[i],'end':dates[i+h],'event':y,'minimum_forward_close_return':loss,
                 'probability':f['probability'],'base_probability':f['base_probability'],
                 'brier':(f['probability']-y)**2,'base_brier':(f['base_probability']-y)**2,
                 'evaluation_price_sha256':digest([(r[0],r[1]) for r in prices[i:i+h+1]]),
                 'meaning':'FORECAST_CALIBRATION_NOT_ACCOUNT_PNL'}
            c.execute('INSERT INTO quant53_outcomes VALUES(?,?,?)',(aid,m.canonical(out),digest(out))); inserted+=1
        n=c.execute('SELECT COUNT(*) FROM quant53_outcomes').fetchone()[0]
        distinct=c.execute('SELECT COUNT(DISTINCT session_date) FROM quant53_analyses JOIN quant53_outcomes USING(analysis_id)').fetchone()[0]
    return {'new_outcomes':inserted,'matured_forecasts':n,'distinct_forecast_sessions':distinct,
            'same_session_revision_policy':'EVALUATE_FIRST_QUALIFIED_ANALYSIS_PER_MODEL_VERSION',
            'daily_forecasts_overlap':True,
            'forward_efficacy':'PENDING' if distinct<20 else 'REQUIRES_DEPENDENCE_AWARE_REVIEW'}


def audit(db):
    with closing(sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='quant53_analyses'").fetchone(): return {'analyses':0,'analysis_hash_errors':0,'model_hash_errors':0,'outcome_hash_errors':0,'missing_input_snapshots':0}
        rows=c.execute('SELECT analysis_json,analysis_sha256,data_sha256 FROM quant53_analyses').fetchall()
        models=c.execute('SELECT source_json,model_sha256 FROM quant53_models').fetchall()
        outs=c.execute('SELECT outcome_json,outcome_sha256 FROM quant53_outcomes').fetchall()
        missing=0; corrupt=0
        for _,_,sha in rows:
            try:
                if snapshots.read(c,sha) is None: missing+=1
            except ValueError: corrupt+=1
    return {'analyses':len(rows),'analysis_hash_errors':sum(digest(json.loads(a))!=b for a,b,_ in rows),
            'model_hash_errors':sum(digest(json.loads(a))!=b for a,b in models),
            'outcome_hash_errors':sum(digest(json.loads(a))!=b for a,b in outs),
            'missing_input_snapshots':missing,'input_snapshot_hash_errors':corrupt}


def run(db=m.DB,output=None):
    p=config(); output=Path(output or DATA_ROOT/'quant53'); output.mkdir(parents=True,exist_ok=True)
    identity={'model_sha256':model_hash(),'protocol_sha256':digest(p),'sources':sources(),
              'registered_before_fitting':True,'parameter_search_trials':0}
    write_json(output/'registered_experiment.json',identity)
    data=load_active(db); validation={**validate_forecast(data,p), 'model_sha256':model_hash(),
          'protocol_sha256':digest(p),'data_sha256':data['data_sha256'],'data_end':data['dates'][-1]}
    write_json(output/'validation.json',validation)
    report=m.build_report(db=db); portfolios=portfolios_for(report)
    sensitivity={}
    for lookback in (None,1260):
        for block in p['simulation']['sensitivity_blocks']:
            sensitivity[f"{'FULL_HISTORY' if lookback is None else 'LAST_5Y'}_BLOCK{block}"]=paths(data,portfolios,p,horizon=p['simulation']['research_horizon'],count=p['simulation']['research_paths'],block=block,lookback=lookback)
    write_json(output/'scenario_sensitivity.json',{'data_sha256':data['data_sha256'],'model_sha256':model_hash(),'cases':sensitivity})
    write_json(output/'current_analysis.json',report['quant_analysis'])
    from .leverage import growth
    growth_scenarios=[{'mu':mu,'sigma':vol,'leverage':leverage,'financing_rate':rate,
                       **growth(mu,vol,leverage,rate,.005,.0082)} for mu in (.05,.10,.15)
                      for vol in (.15,.25,.35) for rate in (0.,.04,.06) for leverage in (1,2,3)]
    write_json(output/'growth_assumptions.json',{'scope':'ASSUMPTION_SENSITIVITY_NOT_RETURN_FORECAST_OR_LEVERAGE_OPTIMIZATION',
            'net_expense_assumption':.0082,'financing_spread_assumption':.005,
            'same_expense_for_all_leverage_cases_for_isolation':True,'cases':growth_scenarios})
    lines=['# QQQ 60% / TQQQ 40% 量化风险研究结果','',f"行情截至 {data['dates'][-1]}；一个固定逻辑回归模型，没有参数寻优。",'',
           f"历史向前检验：{validation.get('samples',0)}个非重叠窗口、{validation.get('events',0)}次10%下跌事件。",
           f"Brier技能分 {validation.get('brier_skill',0):.4f}；结论 {validation.get('research_screen','INSUFFICIENT_HISTORY')}。",'',
           '概率模型继续作为解释层；现有配置复核仍单独运行。未来验证从真实在线保存的概率开始，到期后自动计算Brier分数。','',
           '已运行6组联合区块情景：5/20/60日区块 × 全部可用历史/近5年。每组600条252交易日路径，同一路径比较各仓位。',
           '情景采用初始持仓后自然漂移，现金零收益，没有假设再平衡或策略止损；不是交易策略预期收益。','',
           '| 情景 | 60/40目标收益5%分位 | 中位 | 95%分位 | 路径内20%回撤频率 |','|---|---:|---:|---:|---:|']
    for name,obj in sensitivity.items():
        s=obj['portfolios']['FULL_TARGET_REFERENCE']; a,b,c=s['terminal_return_p05_p50_p95']
        lines.append(f"| {name} | {a:.1%} | {b:.1%} | {c:.1%} | {s['drawdown_20pct_frequency']:.1%} |")
    (output/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return {'data_end':data['dates'][-1],'screen':validation.get('research_screen'),
            'brier_skill':validation.get('brier_skill'),'scenario_cases':len(sensitivity),'output':str(output)}
