"""Explicit research batch, isolated from everyday monitor execution."""
import json
import math
import statistics
import sqlite3
from contextlib import closing
from pathlib import Path
import monitor as m
from .common import ROOT,DATA_ROOT,read_protocol,write_json,digest,code_hash
from .dataset import load,features
from .engine import simulate
from .validation import folds,fold_metrics,forecast_quality,choose
from .stress import synthetic
from .nav_diagnostics import official_nav,diagnose
from .leverage import tracking

def run(db=m.DB,output=None):
    p=read_protocol();output=Path(output or DATA_ROOT/'research');output.mkdir(parents=True,exist_ok=True)
    data=load(db);fs=features(data,p)
    ident={'protocol_sha256':digest(p),'data_sha256':data['data_sha256'],'model_sha256':code_hash()}
    vintage={'data_vintage_sha256':data['data_vintage_sha256'],'data_identity_basis':data['data_identity_basis']}
    nav_path=DATA_ROOT/'research/PROSHARES_NAV_HISTORY.raw'
    index_path=DATA_ROOT/'research/ndx_yahoo.json'
    nav=official_nav(nav_path) if nav_path.exists() else None
    index=json.loads(index_path.read_text()) if index_path.exists() else None
    nav_report=diagnose(data,nav,index) if nav else tracking(None,None)
    with closing(sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True)) as c:
        corroboration={}
        for symbol in m.LEGACY_SYMBOLS:
            quotes=c.execute('SELECT source,raw_close,source_url FROM web_closes WHERE symbol=? AND trade_date=?',(symbol,data['dates'][-1])).fetchall()
            reference=data[symbol][-1]['raw_close']
            corroboration[symbol]={'sites':len(quotes),'same_session_verified':len(quotes)>=2 and all(abs(price/reference-1)<=.005 for _,price,_ in quotes)}
    corroborated=all(item['same_session_verified'] for item in corroboration.values())
    grade='B_LAST_CLOSE_CORROBORATED_SINGLE_ADJUSTED_PROVIDER' if corroborated and data['quality']!='CACHE_ONLY_STALE' else 'C_CACHE_OR_UNCORROBORATED_ADJUSTED_PROVIDER'
    registry={'dataset':{'source_group':'YAHOO_QUERY1_QUERY2_SAME_PROVIDER','last_session':data['dates'][-1],
                        'first_session':data['dates'][0],'sessions':len(data['dates']),
                        'price_basis':data['basis'],'data_vintage':'CURRENT_DOWNLOAD_NOT_POINT_IN_TIME_ARCHIVE',
                        'raw_close_semantics':'YAHOO_CLOSE_SPLIT_ADJUSTED_NOT_DIVIDEND_ADJUSTED_NOT_ORIGINAL_PRE_SPLIT_EXECUTION_PRICE'},
              'official_nav_history':{'status':nav_report['status'],'source_sha256':nav.get('raw_sha256') if nav else None},
              'ndx_history':'YAHOO_PRICE_INDEX_NOT_INDEPENDENT_PROVIDER' if index else 'NOT_VERIFIED',
              'web_quotes':corroboration,
              'grade':grade,**ident,**vintage}
    write_json(output/'source_registry.json',registry)
    write_json(output/'historical_dataset.json',data)
    write_json(output/'data_quality_report.json',{'status':data['quality'],'freshness_cutoff':data['cutoff'],
              'no_independent_adjusted_history':True,'no_independent_nav_history':nav is None,
              'strict_calendar_and_finite_values':True,**ident,**vintage})
    all_runs={};comparisons={};trial_rows=[];fold_list=folds(data,p)
    for cost in p['cost_bps_per_side']:
        runs={name:simulate(data,fs,p,name,cost) for name in p['models']}
        all_runs[str(cost)]=runs
        comparisons[str(cost)]={'full_sample':{n:r['summary'] for n,r in runs.items()},
            'windows':[{'fold':fold,'models':{n:fold_metrics(r,fold) for n,r in runs.items()}} for fold in fold_list]}
        for name,r in runs.items():
            trial_rows.append({**ident,'model_id':name,'cost_bps_per_side':cost,'parameters':p,
                'timestamp':m.ztime(),'summary':r['summary'],'retained':True,
                'label':'PRE_REGISTERED_FIXED_RULE_NO_PARAMETER_SEARCH'})
    if len(trial_rows)>p['max_trial_evaluations']:raise ValueError('Registered trial cap exceeded')
    decision=choose(comparisons,p)
    base=all_runs['15'];risk={}
    q=[r['adjusted_close'] for r in data['QQQ']][251:]
    qr=[q[i]/q[i-1]-1 for i in range(1,len(q))]
    topdays=sorted(range(len(qr)),key=lambda i:qr[i],reverse=True)[:10]
    for name,r in base.items():
        summary=r['summary'];missed=[{'date':r['dates'][i+1],'qqq_return_pct':qr[i]*100,
                 'earning_daily_exposure':r['exposures'][i],
                 'exposure_gap_to_one':1-r['exposures'][i]} for i in topdays]
        risk[name]={'cvar95':summary['historical_cvar95_daily_pct'],'worst_windows':summary['worst_5_overlapping_20_session_windows'],
                    'missed_top_10_qqq_days':missed,'risk_budget_infeasible_sessions':summary['risk_budget_infeasible_sessions']}
    daily={name:{'dates':r['dates'],'equity':r['curve'],'weights_earning_return':r['weights_earning_return'],
                 'trades':r['trades']} for name,r in base.items()}
    write_json(output/'model_comparison_oos.json',{'identity':ident,'comparisons':comparisons,
               'decision':decision,'limits':['HISTORICAL_DATA_ALREADY_SEEN','FIXED_RULES_NOT_FITTED_ML',
               'NOT_EXACTLY_RISK_MATCHED','CASH_ZERO_YIELD_TAX_FX_OMITTED','ADJUSTED_ACCOUNTING_UNITS_NOT_TRADABLE_SHARES']})
    matched={}
    for cost,runs in all_runs.items():
        a=runs['M2_FLEXIBLE_FLOOR_PAPER'];b=runs['B_MATCHED_COV_VOL_PAPER']
        gaps=[]
        for j,wa in enumerate(a['weights_earning_return']):
            f=fs[251+j];wb=b['weights_earning_return'][j]
            from .policies import portfolio_vol
            gaps.append(portfolio_vol(f,wa[0],wa[1])-portfolio_vol(f,wb[0],wb[1]))
        matched[cost]={'comparison':'SAME_SIGNAL_TIME_COVARIANCE_FORECAST_BUDGET_NOT_IDENTICAL_REALIZED_RISK',
                      'mean_absolute_forecast_vol_gap':statistics.mean(abs(x) for x in gaps),
                      'maximum_absolute_forecast_vol_gap':max(abs(x) for x in gaps),
                      'realized_annual_vol_gap_pct':a['summary']['annual_vol_pct']-b['summary']['annual_vol_pct'],
                      'candidate_risk_budget_infeasible_sessions':a['summary']['risk_budget_infeasible_sessions']}
    write_json(output/'risk_matched_comparison.json',matched)
    write_json(output/'simulation_paths_15bps.json',daily)
    write_json(output/'official_nav_diagnostics.json',nav_report)
    halted=simulate(data,fs,p,'M1_TREND_EWMA',50,[t['execute_session'] for t in base['M1_TREND_EWMA']['trades'][:5]])
    write_json(output/'execution_halt_stress.json',{'status':'HYPOTHETICAL_MISSED_EXECUTIONS_ON_REAL_PRICE_HISTORY','summary':halted['summary'],'blocked':halted['blocked_executions']})
    write_json(output/'forecast_validation.json',forecast_quality(data,fs,p))
    write_json(output/'risk_report.json',{'historical':risk,'synthetic':synthetic(),'official_tracking':{'status':nav_report.get('tracking',nav_report)['status'],'see':'official_nav_diagnostics.json'}})
    # Avoid duplicate trials on replay. Keep separate files for each identity; no abandoned model disappears.
    trial_id=digest(ident)[:16];trial_path=output/f'trials_{trial_id}.jsonl'
    if not trial_path.exists():m.atomic_write(trial_path,''.join(m.canonical(x)+'\n' for x in trial_rows).encode())
    write_json(output/'latest_trial_index.json',{'file':trial_path.name,'trial_evaluations':len(trial_rows),**ident})
    write_json(output/'failures.json',{'model_decisions':decision,
               'ML':'SKIPPED_WITH_REASON_CORE_INDEPENDENT_DATA_GATE_PARTIAL_AND_NO_PROVEN_NEED',
               'HFEA_OPTIONS':p['excluded'],'failed_risk_windows':risk})
    # 70/20/10 risk contributions, from observed covariance; no diversification assumption.
    f=fs[-1];qv,tv,cov=f['qqq_var'],f['tqqq_var'],f['cov'];q0,t0=.7,.2
    variance=q0*q0*qv+t0*t0*tv+2*q0*t0*cov
    write_json(output/'current_diagnostics.json',{'session':data['dates'][-1],
         'qqq_raw_close':data['QQQ'][-1]['raw_close'],'tqqq_raw_close':data['TQQQ'][-1]['raw_close'],
         'qqq_sma200_adjusted':f['sma200'],'qqq_vol20_pct':f['vol20_pct'],
         'ewma_vol_pct':f['ewma_vol']*100,'qqq_rsi2':f['rsi2'],
         'tqqq_sma200_adjusted':statistics.mean(r['adjusted_close'] for r in data['TQQQ'][-200:]),
         'tqqq_sma50_adjusted':statistics.mean(r['adjusted_close'] for r in data['TQQQ'][-50:]),
         'plan_status':'UNEXECUTED_70_20_10_STRESS_ONLY','plan_daily_exposure':1.3,
         'plan_estimated_annual_vol_pct':math.sqrt(variance)*100,
         'plan_tqqq_variance_contribution_fraction':t0*(q0*cov+t0*tv)/variance if variance else None,
         'current_buy_signal':'NOT_GENERATED_BY_RESEARCH_BATCH',**ident})
    rows=['# v5.1 修复研究结果','',f"数据截至 {data['dates'][-1]}；固定规则历史逐年检验，历史已经被看过，不是盲测。",'',
          '| 模型 | 年化% | 最大回撤% | 波动% | 夏普 | 2022年% |', '|---|---:|---:|---:|---:|---:|']
    win2022=next(w for w in comparisons['15']['windows'] if w['fold']['year']==2022)
    for n,r in base.items():
        x=r['summary'];y=win2022['models'][n]
        rows.append(f"|{n}|{x['cagr_pct']:.2f}|{x['max_drawdown_pct']:.2f}|{x['annual_vol_pct']:.2f}|{x['sharpe_rf_zero']:.3f}|{y['total_return_pct']:.2f}|")
    rows+=['','全部模型采用收盘信号、次日收盘模拟成交，每边15bp外部成本；基金内在费用没有重复扣。',
           '新引擎从热身结束时全现金起步，基准也延迟一天建仓；旧结果作为v4.1档案保存，不能直接替换旧数字。',
           'M2原模型保持50%下限；新M2_FLEXIBLE_FLOOR_PAPER明确允许降低核心模拟仓位，B_MATCHED_COV_VOL_PAPER按相同协方差估计风险作对照；未改变生产规则。',
           'B_MATCHED_DAILY_EXPOSURE只匹配目标近似单日方向风险，不等于精确匹配实现波动或长期收益。',
           'R_VALUE_AVERAGE_STRESS是简化季度价值平均，未实现官方完整9-Sig规则；不能引用其官方成绩。',
           '全仓TQQQ、全杠杆LRS、60%季度补仓仅为风险对照，不自动成为账户配置。','',
           '候选决策：'+json.dumps(decision,ensure_ascii=False),
           '已验证发行商NAV历史及Yahoo NDX价格指数；NAV分红总回报口径、独立复权历史仍缺，不能把追踪差全算作融资成本。',
           '没有未见未来样本证据，不更换v4.1生产策略；机器学习、期权及跨资产对冲暂不加入。']
    (output/'RESULTS.md').write_text('\n'.join(rows)+'\n',encoding='utf8')
    return {'status':'RESEARCH_COMPLETE_WITH_DATA_LIMITATIONS','models':len(p['models']),
            'trial_evaluations':len(trial_rows),'year_windows':len(fold_list),**ident,'decision':decision}

if __name__=='__main__':print(json.dumps(run(),indent=2,ensure_ascii=False))
