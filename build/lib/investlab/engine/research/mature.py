"""Conventional strategy families with causal, common-cost research execution."""
import bisect
import csv
import datetime as dt
import io
import json
import math
import statistics as st
import sqlite3
import urllib.request
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import monitor as m
from .common import ROOT,DATA_ROOT,digest,write_json
from .engine import metrics
from .dataset import active_candles

INPUT=DATA_ROOT/'quant53/mature_inputs'
PROTOCOL=ROOT/'research/mature_protocol.json'
ASSETS=m.ACTIVE_SYMBOLS


def config(): return json.loads(PROTOCOL.read_text())


def sources():
    return {n:(ROOT/n).read_text() for n in ('research/mature.py','research/mature_protocol.json','research/dataset.py','monitor.py')}


def source_hash():
    return digest(sources())


def refresh():
    INPUT.mkdir(parents=True,exist_ok=True)
    def macro(sid):
        url='https://fred.stlouisfed.org/graph/fredgraph.csv?id='+sid
        try:
            req=urllib.request.Request(url,headers={'User-Agent':m.UA})
            with urllib.request.urlopen(req,timeout=15) as f:raw=f.read(2_000_000)
            rows=list(csv.DictReader(io.StringIO(raw.decode())))
            if len(rows)<120 or sid not in rows[0]:raise ValueError('Invalid macro CSV')
            m.atomic_write(INPUT/(sid+'.csv'),raw)
            write_json(INPUT/(sid+'.source.json'),{'source':url,'fetched_at':m.ztime(),'point_in_time_vintages':False})
            return {'series':sid,'status':'OK','observations':len(rows)}
        except Exception as e:return {'series':sid,'status':'ERROR','error':str(e)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs=[pool.submit(macro,s) for s in config()['macro']['factors']]
        results=[job.result() for job in jobs]
    write_json(INPUT/'refresh_results.json',{'created_at':m.ztime(),'results':results})
    return results


def dataset(candles,cutoff):
    joint=active_candles(candles,cutoff);dates=joint['dates']
    if len(dates)<300:raise ValueError('Insufficient joint research history')
    prices={s:[r['adjusted_close'] for r in joint[s]] for s in ASSETS}
    semantic={'dates':dates,'prices':prices}
    return {**semantic,'data_sha256':digest(semantic),'quality':'CURRENT_SINGLE_PROVIDER' if dates[-1]==cutoff else 'STALE_RESEARCH_ASSETS'}


def covariance(returns,i,window,shrink):
    rs=[r[i-window+1:i+1] for r in returns]; means=[st.mean(v) for v in rs]
    return [[sum((a-means[j])*(b-means[k]) for a,b in zip(rs[j],rs[k]))/(window-1)*252*(1 if j==k else 1-shrink)
             for k in range(len(rs))] for j in range(len(rs))]


def variance(w,cov):return max(0.,sum(w[i]*cov[i][j]*w[j] for i in range(len(w)) for j in range(len(w))))


def equal_risk(cov):
    """Coordinate solution of .5*x'Sigma*x - sum(b_i*log(x_i))."""
    n=len(cov)
    if any(cov[i][i]<=0 for i in range(n)):raise ValueError('Nonpositive asset variance')
    x=[1/math.sqrt(cov[i][i]) for i in range(n)]
    for _ in range(400):
        previous=x[:]
        for i in range(n):
            a=cov[i][i];c=sum(cov[i][j]*x[j] for j in range(n) if j!=i);disc=math.sqrt(c*c+4*a/n)
            x[i]=(2/n)/(c+disc) if c>=0 else (-c+disc)/(2*a)
        if max(abs(a-b) for a,b in zip(x,previous))<1e-11:break
    w=[v/sum(x) for v in x];v=variance(w,cov)
    shares=[w[i]*sum(cov[i][j]*w[j] for j in range(n))/v for i in range(n)]
    if max(abs(s-1/n) for s in shares)>1e-6:raise ValueError('Risk parity solver failed equal-contribution check')
    return w


def features(data,p):
    prices=data['prices'];n=len(data['dates']);returns={s:[0.]+[b/a-1 for a,b in zip(prices[s],prices[s][1:])] for s in ASSETS}
    logs=[math.log(x) for x in prices['QQQ']];residual=[None]*n;z=[None]*n;out=[None]*n
    cfg=p['mean_reversion'];v=0.
    for i in range(n):
        if i:v=.94*v+.06*math.log(prices['QQQ'][i]/prices['QQQ'][i-1])**2
        if i>=cfg['z_window']:
            previous=logs[i-cfg['z_window']:i];sd=st.stdev(previous)
            residual[i]=logs[i]-st.mean(previous);z[i]=residual[i]/sd if sd else 0.
        if i<252:continue
        cov=covariance([returns[s] for s in ASSETS],i,p['covariance_sessions'],p['diagonal_shrinkage'])
        prior=residual[i-cfg['ar_window']:i];following=residual[i-cfg['ar_window']+1:i+1]
        mx=st.mean(prior);my=st.mean(following);den=sum((x-mx)**2 for x in prior)
        phi=sum((x-mx)*(y-my) for x,y in zip(prior,following))/den if den else None
        half=-math.log(2)/math.log(phi) if phi is not None and 0<phi<1 else None
        intercept=my-phi*mx if phi is not None else None
        eq_mean=intercept/(1-phi) if half is not None else None
        eq_sd=math.sqrt(st.variance(y-intercept-phi*x for x,y in zip(prior,following))/(1-phi*phi)) if half is not None else None
        ou_z=(residual[i]-eq_mean)/eq_sd if eq_sd else None
        out[i]={'cov':cov,'qqq_vol':max(math.sqrt(cov[0][0]),math.sqrt(v*252)),
                'momentum':{s:prices[s][i]/prices[s][i-252]-1 for s in ASSETS},
                'z':ou_z if ou_z is not None else z[i], 'z20_diagnostic':z[i],
                'ar_phi':phi,'ar_intercept':intercept,'ou_half_life':half,
                'ou_equilibrium_mean':eq_mean,'ou_equilibrium_sigma':eq_sd,
                'mr_trend_on':prices['QQQ'][i]>st.mean(prices['QQQ'][i-199:i+1])}
    return out


def target(name,f,p,state,index,monthly):
    w=[0.]*len(ASSETS);cap=p['risky_weight_cap'];vol=p['annual_vol_target'];cov=f['cov']
    if name=='MR_Z_OU_QQQ':
        cfg=p['mean_reversion'];held=state.get('entry_index') is not None
        if held and (f['z']>=cfg['exit_z'] or not f['mr_trend_on'] or index-state['entry_index']>=cfg['max_holding_sessions']):
            state['entry_index']=None
        elif not held and f['z']<=cfg['entry_z'] and f['mr_trend_on'] and f['ou_half_life'] is not None and f['ou_half_life']<=cfg['half_life_max']:
            state['entry_index']=index
        w[0]=cfg['maximum_sleeve'] if state.get('entry_index') is not None else 0.
    elif name in ('B_QQQ90','B_QQQ25','B_QQQ100'):w[0]={'B_QQQ90':cap,'B_QQQ25':.25,'B_QQQ100':1.}[name]
    elif name=='B_FIXED60_40':
        w[ASSETS.index('QQQ')]=.6;w[ASSETS.index('TQQQ')]=.4
    elif name in ('RP_QQQ_TQQQ','RP_VOL_TARGET_QQQ_TQQQ'):
        indices=list(range(len(ASSETS)))
        sub=[[cov[i][j] for j in indices] for i in indices]
        for j,a in zip(indices,equal_risk(sub)):w[j]=cap*a
        if name=='RP_VOL_TARGET_QQQ_TQQQ':
            scale=min(1.,vol/max(math.sqrt(variance(w,cov)),1e-8))
            w=[x*scale for x in w]
    elif name=='VOL_TARGET_QQQ':w[0]=min(cap,vol/max(f['qqq_vol'],1e-8))
    elif name=='TSMOM12_QQQ':w[0]=min(cap,vol/max(f['qqq_vol'],1e-8)) if f['momentum']['QQQ']>0 else 0.
    elif name=='TSMOM12_MULTI':
        positive=[j for j in range(len(ASSETS)) if f['momentum'][ASSETS[j]]>0]
        if positive:
            raw=[1/math.sqrt(cov[j][j]) for j in positive];total=sum(raw)
            for j,a in zip(positive,raw):w[j]=a/total
            scale=min(cap,vol/max(math.sqrt(variance(w,cov)),1e-8))
            w=[x*scale for x in w]
    else:raise ValueError('Unknown mature model '+name)
    if any(v<0 or not math.isfinite(v) for v in w) or sum(w)>1+1e-9:raise ValueError('Invalid mature target')
    if name not in ('MR_Z_OU_QQQ','VOL_TARGET_QQQ') and not monthly:return None
    return w+[1-sum(w)]


def rebalance(values,weights,bps):
    if not 0<=bps<=500:raise ValueError('Invalid cost')
    total=sum(values);rate=bps/10000;lo=0.;hi=total
    for _ in range(60):
        post=(lo+hi)/2;fee=rate*sum(abs(post*w-v) for w,v in zip(weights[:-1],values[:-1]))
        if post+fee>total:hi=post
        else:lo=post
    post=(lo+hi)/2;new=[post*w for w in weights];traded=sum(abs(a-b) for a,b in zip(new[:-1],values[:-1]))
    return new,total-post,traded


def simulate(data,fs,p,name,cost):
    dates=data['dates'];values=[0.]*len(ASSETS)+[1.];curve=[1.];events=[];state={};exposures=[];weights=[]
    for i in range(253,len(dates)):
        total=sum(values);before=[v/total for v in values];weights.append(before)
        exposures.append(sum(before[j]*(1 if symbol=='QQQ' else 3) for j,symbol in enumerate(ASSETS)))
        monthly=i==253 or dates[i][:7]!=dates[i-1][:7]
        desired=target(name,fs[i-1],p,state,i,monthly)
        for j,s in enumerate(ASSETS):values[j]*=data['prices'][s][i]/data['prices'][s][i-1]
        if desired is not None:
            drifted=[v/sum(values) for v in values]
            threshold=.05 if name=='VOL_TARGET_QQQ' else 1e-8
            if max(abs(a-b) for a,b in zip(desired,drifted))>=threshold:
                values,fee,traded=rebalance(values,desired,cost)
                events.append({'signal_session':dates[i-1],'execute_session':dates[i],
                               'target':dict(zip(ASSETS+('CASH',),desired)),'fee':fee,'traded':traded})
        curve.append(sum(values))
    summary=metrics(curve,dates[252:],events,exposures)
    summary.update(model_id=name,cost_bps=cost,average_cash_weight=st.mean(w[-1] for w in weights),
                   terminal_weights=dict(zip(ASSETS+('CASH',),[v/sum(values) for v in values])))
    yearly={}
    for year in sorted({d[:4] for d in dates[253:]}):
        idx=[j for j,d in enumerate(dates[252:]) if j and d.startswith(year)]
        yearly[year]=(curve[idx[-1]]/curve[idx[0]-1]-1)*100
    summary['yearly_return_pct']=yearly
    return {'summary':summary,'dates':dates[252:],'curve':curve,'trades':events}


def solve(a,b):
    a=[row[:]+[v] for row,v in zip(a,b)];n=len(b)
    for k in range(n):
        pivot=max(range(k,n),key=lambda i:abs(a[i][k]));a[k],a[pivot]=a[pivot],a[k]
        if abs(a[k][k])<1e-12:raise ValueError('Singular regression')
        scale=a[k][k];a[k]=[v/scale for v in a[k]]
        for i in range(n):
            if i!=k:
                scale=a[i][k];a[i]=[v-scale*w for v,w in zip(a[i],a[k])]
    return [row[-1] for row in a]


def macro_inputs(cutoff):
    result={}
    for sid in config()['macro']['factors']:
        path=INPUT/(sid+'.csv')
        if not path.exists():raise ValueError('Missing macro series '+sid)
        rows=list(csv.DictReader(io.StringIO(path.read_text('utf8'))));obs={}
        for row in rows:
            date=row.get('observation_date') or row.get('DATE')
            if not date or date>cutoff or row[sid] in ('','.'):continue
            value=float(row[sid])
            if not math.isfinite(value):raise ValueError('Nonfinite macro input')
            obs[date]=value
        if not obs:raise ValueError('Empty macro series '+sid)
        result[sid]=obs
    return result


def macro_regression(data,p,obs=None):
    if obs is None:obs=macro_inputs(data['dates'][-1])
    factors=p['macro']['factors']
    common=sorted(set.intersection(*(set(obs[s]) for s in factors)))
    q=dict(zip(data['dates'],data['prices']['QQQ']));rows=[]
    for a,b in zip(common,common[1:]):
        if a not in q or b not in q:continue
        # Returns span exactly the same two observed dates, including any holiday gap.
        x=[obs[s][b]-obs[s][a] if s!='DTWEXBGS' else math.log(obs[s][b]/obs[s][a]) for s in factors]
        rows.append({'start':a,'end':b,'x':x,'y':math.log(q[b]/q[a])})
    rows=rows[-p['macro']['regression_window']:]
    if len(rows)<p['macro']['minimum_observations']:raise ValueError('Insufficient macro regression overlap')
    means=[st.mean(r['x'][j] for r in rows) for j in range(4)]
    scales=[st.stdev(r['x'][j] for r in rows) or 1. for j in range(4)]
    xs=[[1.]+[(r['x'][j]-means[j])/scales[j] for j in range(4)] for r in rows];n=len(rows)
    matrix=[[sum(x[i]*x[j] for x in xs)/n+(p['macro']['ridge'] if i==j and i else 0) for j in range(5)] for i in range(5)]
    rhs=[sum(x[i]*r['y'] for x,r in zip(xs,rows))/n for i in range(5)];beta=solve(matrix,rhs)
    raw=[beta[j+1]/scales[j] for j in range(4)];alpha=beta[0]-sum(a*b for a,b in zip(raw,means))
    pred=[alpha+sum(a*b for a,b in zip(raw,r['x'])) for r in rows];ym=st.mean(r['y'] for r in rows)
    denominator=sum((r['y']-ym)**2 for r in rows);r2=1-sum((r['y']-v)**2 for r,v in zip(rows,pred))/denominator if denominator else None
    shocks={'REAL_YIELD_PLUS_50BP':[.5,0,0,0], 'BREAKEVEN_PLUS_50BP':[0,.5,0,0],
            'DOLLAR_PLUS_5PCT':[0,0,math.log(1.05),0], 'CREDIT_SPREAD_PLUS_100BP':[0,0,0,1.]}
    return {'status':'MACRO_FACTOR_ATTRIBUTION_CURRENT_VINTAGE', 'scope':'APT_INSPIRED_RISK_SENSITIVITY_NOT_FAIR_PRICE',
            'factors':factors,'observations':n,'start':rows[0]['start'],'end':rows[-1]['end'],
            'latest_each_factor':{s:max(obs[s]) for s in factors},'beta':dict(zip(factors,raw)),
            'intercept_log_return':alpha,'in_sample_r_squared':r2,
            'shock_log_return_sensitivity':{name:sum(a*b for a,b in zip(raw,x)) for name,x in shocks.items()},
            'expected_return_from_risk_premia':None,'factor_risk_premia_lambda':'UNKNOWN',
            'point_in_time_vintages':False,'historical_macro_trading_backtest':'BLOCKED_WITHOUT_RELEASE_VINTAGES',
            'limits':['CONDITIONAL_ASSOCIATION_NOT_CAUSATION','FACTOR_SHOCKS_MAY_BE_CORRELATED',
                      'CURRENT_VINTAGE_REVISIONS','OBSERVATION_DATE_IS_NOT_PUBLICATION_TIME',
                      'NOT_A_FORWARD_RETURN_FORECAST_OR_INTRINSIC_VALUE'], 'input_sha256':digest(obs)}


def context(report,candles):
    p=config();out={'status':'DATA_LIMITED','scope':'MATURE_STRATEGIES_RESEARCH_ONLY','model_sha256':source_hash(),
                    'protocol_sha256':digest(p),'orders':[],'allocation_override':False}
    if report.get('data_evidence_grade')=='SOURCE_CONFLICT':
        out.update(status='DATA_BLOCKED',blocker='PRICE_SOURCE_CONFLICT')
        return out
    try:
        data=dataset(candles,report['as_of_expected_session']);fs=features(data,p);f=fs[-1]
        targets={}
        for name in p['models']:
            if name=='MR_Z_OU_QQQ':continue
            w=target(name,f,p,{},len(data['dates']),True)
            targets[name]=dict(zip(ASSETS+('CASH',),w))
        # Mean-reversion depends on historical entry/exit state: replay causally.
        state={};w=None
        for i in range(253,len(data['dates'])+1):w=target('MR_Z_OU_QQQ',fs[i-1],p,state,i,True)
        targets['MR_Z_OU_QQQ']=dict(zip(ASSETS+('CASH',),w))
        out.update(status='RESEARCH_CONTEXT' if data['quality']=='CURRENT_SINGLE_PROVIDER' else 'STALE_RESEARCH_CONTEXT',
                   data_end=data['dates'][-1],data_sha256=data['data_sha256'],current_hypothetical_targets=targets,
                   qqq_zscore=f['z'],residual_ar1_phi=f['ar_phi'],estimated_half_life_sessions=f['ou_half_life'],
                   covariance_shrinkage=p['diagonal_shrinkage'],live_account_mutated=False)
        macro=None
        try:
            macro=macro_inputs(data['dates'][-1])
            out['macro']=macro_regression(data,p,obs=macro)
        except (ValueError,KeyError,OSError) as exc:
            out['macro']={'status':'DATA_LIMITED','reason':str(exc),
                          'input_sha256':digest(macro) if macro else None}
        out['input_snapshot_sha256']=digest({'data_sha256':data['data_sha256'],
             'macro_sha256':out['macro'].get('input_sha256'),'model_sha256':out['model_sha256']})
        rp=[targets['RP_QQQ_TQQQ'][s] for s in ASSETS]
        v=variance(rp,f['cov'])
        out['risk_parity_variance_shares']={s:rp[i]*sum(f['cov'][i][j]*rp[j] for j in range(len(ASSETS)))/v for i,s in enumerate(ASSETS)}
        for file in ('comparison.json',):
            path=DATA_ROOT/'quant53/mature'/file
            if path.exists():
                obj=json.loads(path.read_text())
                if obj['model_sha256']==out['model_sha256']:out['comparison_reference']={'data_end':obj['data_end'],'path':'data/quant53/mature/RESULTS.md'}
    except (ValueError,KeyError) as exc:out['blocker']=str(exc)
    return out


def persist(context,candles,db):
    if 'data_sha256' not in context:return
    data=dataset(candles,context['data_end'])
    if data['data_sha256']!=context['data_sha256']:raise ValueError('Mature strategy inputs changed')
    out=Path(db).parent/'quant53/mature_snapshots';out.mkdir(parents=True,exist_ok=True)
    try:macro=macro_inputs(data['dates'][-1])
    except (ValueError,KeyError,OSError):macro=None
    expected=digest({'data_sha256':data['data_sha256'],'macro_sha256':digest(macro) if macro else None,
                     'model_sha256':source_hash()})
    if expected!=context['input_snapshot_sha256']:raise ValueError('Macro/source inputs changed before snapshot')
    path=out/(expected+'.json')
    if not path.exists():write_json(path,{'dataset':data,'macro':macro,'snapshot_sha256':expected,
                        'source_bundle':sources()})


def audit(db):
    errors=0;paths=list((Path(db).parent/'quant53/mature_snapshots').glob('*.json'))
    for path in paths:
        try:
            obj=json.loads(path.read_text());d=obj['dataset']
            data_sha=digest({'dates':d['dates'],'prices':d['prices']})
            expected=digest({'data_sha256':data_sha,'macro_sha256':digest(obj['macro']) if obj['macro'] else None,
                             'model_sha256':digest(obj['source_bundle'])})
            errors+=expected!=obj['snapshot_sha256'] or path.stem!=expected or data_sha!=d['data_sha256']
        except (ValueError,KeyError):errors+=1
    with closing(sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)) as c:
        refs=[json.loads(row[0]).get('mature_models',{}).get('input_snapshot_sha256') for row in c.execute('SELECT report_json FROM monitor_runs')]
    existing={path.stem for path in paths}
    return {'input_snapshots':len(paths),'snapshot_hash_errors':errors,
            'missing_run_input_snapshots':sum(ref not in existing for ref in refs if ref)}


def report_lines(obj):
    lines=['## 成熟量化策略对照','状态：'+obj['status']]
    targets=obj.get('current_hypothetical_targets')
    if not targets:return lines+['原因：'+obj.get('blocker','数据不齐')]
    rp=targets['RP_QQQ_TQQQ'];vt=targets['VOL_TARGET_QQQ'];tm=targets['TSMOM12_QQQ']
    lines.append(f"风险平价研究配置：QQQ {rp['QQQ']:.1%} / TQQQ {rp['TQQQ']:.1%} / 现金 {rp['CASH']:.1%}。")
    lines.append(f"12%波动目标对照：QQQ {vt['QQQ']:.1%}；12个月动量对照：QQQ {tm['QQQ']:.1%}；其余为现金。这是不同规则的研究配置，不是同时叠加。")
    phi=obj.get('residual_ar1_phi');half=obj.get('estimated_half_life_sessions')
    phi_text=f'{phi:.3f}' if phi is not None else '无法估计'
    lines.append(f"均值回归：当前标准化偏离 {obj['qqq_zscore']:.2f}，AR(1)系数 {phi_text}，估计恢复一半的时间 "+(f'{half:.1f}交易日。' if half is not None else '不满足0<phi<1。'))
    macro=obj.get('macro',{})
    if 'in_sample_r_squared' in macro:lines.append(f"宏观因子已估计实际利率、通胀预期、美元、信用利差敏感度；共同数据截至{macro['end']}。公布历史版本未齐，宏观回测不作为已验证交易信号。")
    else:lines.append('宏观数据状态：'+macro.get('status','缺失'))
    return lines


def run(db=m.DB):
    p=config();output=DATA_ROOT/'quant53/mature';output.mkdir(parents=True,exist_ok=True)
    write_json(output/'registered_protocol.json',{'protocol':p,'protocol_sha256':digest(p),'model_sha256':source_hash(),'registered_before_comparison':True})
    data=dataset(m.price_data(db),m.expected_close_session().isoformat());fs=features(data,p)
    results={};paths={}
    for cost in p['cost_bps_per_side']:
        runs={name:simulate(data,fs,p,name,cost) for name in p['models']}
        results[str(cost)]={name:r['summary'] for name,r in runs.items()}
        if cost==15:paths={name:{'dates':r['dates'],'curve':r['curve'],'trades':r['trades']} for name,r in runs.items()}
    report={'model_sha256':source_hash(),'protocol_sha256':digest(p),'data_sha256':data['data_sha256'],
            'data_end':data['dates'][-1],'models':results,
            'limits':['HISTORY_ALREADY_SEEN_NOT_BLIND','SINGLE_ADJUSTED_PROVIDER',
                      'DIFFERENT_RISK_BUDGETS_NO_ALPHA_CLAIM','CASH_ZERO_YIELD_TAX_FX_OMITTED',
                      'LONG_ONLY_ADAPTATIONS_NOT_ORIGINAL_LEVERAGED_OR_LONG_SHORT_FUNDS'],
            'decision':'RESEARCH_COMPARISON_NO_AUTOMATIC_POLICY_REPLACEMENT'}
    write_json(output/'comparison.json',report);write_json(output/'paths_15bps.json',paths)
    current=context({'as_of_expected_session':data['dates'][-1]},m.price_data(db));write_json(output/'current_models.json',current)
    write_json(output/'macro_factor_model.json',current['macro'])
    persist(current,m.price_data(db),db)
    lines=['# 成熟量化方案对照','',f"行情截至{data['dates'][-1]}；10条固定规则、2档费用，参数没有寻优。",'',
           '| 模型 | 单边费用bp | 年化收益% | 最大回撤% | 年化波动% | 2022收益% |','|---|---:|---:|---:|---:|---:|']
    for cost,runs in results.items():
        for name,r in runs.items():lines.append(f"| {name} | {cost} | {r['cagr_pct']:.2f} | {r['max_drawdown_pct']:.2f} | {r['annual_vol_pct']:.2f} | {r['yearly_return_pct'].get('2022',0):.2f} |")
    lines+=['','60/40为用户指定的固定配置对照；风险平价和目标波动是独立研究规则，不覆盖该目标。',
            'QQQ和TQQQ共享纳指风险；风险平价分配同源杠杆风险，研究策略可以留现金调节总敞口。',
            '均值回归只有25%战术资金上限，需与B_QQQ25比较，不能直接用低收益判定优劣；也不能把较低资金占用造成的小回撤当作择时优势。',
            '动量按12个月正收益做多/转现金；没有复刻期货多空、融资和完整跨资产配置。',
            '宏观模型输出历史暴露与假设冲击，尚没有历史发布版本和可靠风险溢价lambda，不输出内在价格或已验证宏观择时收益。']
    (output/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    return {'data_end':data['dates'][-1],'models':len(p['models']),'cost_cases':len(results),'macro':current['macro']['status']}
