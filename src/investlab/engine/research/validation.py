"""Time-forward diagnostics. No parameter fitting, hidden test selection, or blind claim."""
import math
import statistics
from .engine import metrics

def purged_indices(dates, start, end, boundary, horizon):
    return [i for i,d in enumerate(dates) if start<=d<=end and
            i+horizon<len(dates) and dates[i+horizon]<boundary]

def folds(data,p):
    dates=data['dates'];last=int(dates[-1][:4]);cfg=p['walk_forward'];out=[]
    first_eligible=dates[251]
    for year in range(cfg['first_test_year'],last+1):
        valid_start=f'{year-1}-01-01';test_start=f'{year}-01-01';test_end=min(f'{year}-12-31',dates[-1])
        train_end=f'{year-2}-12-31';valid_end=f'{year-1}-12-31'
        train=purged_indices(dates,first_eligible,train_end,valid_start,cfg['purge_sessions'])
        valid=purged_indices(dates,valid_start,valid_end,test_start,cfg['purge_sessions'])
        test=[i for i,d in enumerate(dates) if test_start<=d<=test_end]
        if not test:continue
        out.append({'year':year,'train_start':first_eligible,'train_end':dates[train[-1]] if train else None,
                    'validation_start':valid_start,'validation_end':dates[valid[-1]] if valid else None,
                    'test_start':dates[test[0]],'test_end':dates[test[-1]],
                    'train_sessions_after_purge':len(train),'validation_sessions_after_purge':len(valid),
                    'test_sessions':len(test),'purge_horizon':cfg['purge_sessions'],
                    'training_minimum_sessions_met':len(train)>=3*252,
                    'test_year_complete':year<last or dates[-1]>=f'{year}-12-30',
                    'model_fit':False,'label':'TIME_FORWARD_FIXED_RULE_REPLAY_NOT_BLIND'})
    return out

def fold_metrics(run,fold):
    dates=run['dates'];idx=[i for i,d in enumerate(dates) if fold['test_start']<=d<=fold['test_end']]
    if not idx:return None
    a,b=idx[0],idx[-1];a=max(a,1)
    events=[t for t in run['trades'] if dates[a]<=t['execute_session']<=dates[b]]
    return metrics(run['curve'][a-1:b+1],dates[a-1:b+1],events,run['exposures'][a-1:b])

def forecast_quality(data,fs,p,start='2015-01-01'):
    q=[r['adjusted_close'] for r in data['QQQ']]
    ret=[0]+[math.log(q[i]/q[i-1]) for i in range(1,len(q))]
    out=[]
    for h in (1,5,20):
        samples=[]
        for i in range(251,len(q)-h):
            if data['dates'][i]<start:continue
            # qlike proxy is future uncentered mean squared log-return, not ex-post std dev.
            realized=statistics.mean(x*x for x in ret[i+1:i+h+1])
            samples.append((max(realized,1e-14),max(fs[i]['ewma_daily_var'],1e-14),
                            max(fs[i]['rv20_daily_var'],1e-14)))
        if not samples:continue
        scores={}
        for j,name in [(1,'EWMA94'),(2,'RV20')]:
            scores[name]={'qlike':statistics.mean(math.log(x[j])+x[0]/x[j] for x in samples),
                          'mae_annualized_rms_vol':statistics.mean(abs(math.sqrt(x[j]*252)-math.sqrt(x[0]*252)) for x in samples)}
        out.append({'horizon_sessions':h,'matured_samples':len(samples),'scores':scores,
                    'target':'FUTURE_MEAN_SQUARED_LOG_RETURN','overlapping_samples':h>1,
                    'statistical_significance_claim':False})
    return {'status':'HISTORICAL_FIXED_FORECAST_COMPARISON_NOT_LIVE_VALIDATION','results':out}

def choose(comparisons,p):
    """Candidate must beat risk baseline consistently at all nonzero costs."""
    result={};cfg=p['selection']
    for name in ('M1_TREND_EWMA','M2_COVARIANCE_BUDGET','R_RSI2_SWING','M2_FLEXIBLE_FLOOR_PAPER'):
        cases=[]
        for cost in (15,50):
            windows=comparisons[str(cost)]['windows'];positive=0;valid=0;tail_ok=True;vol_ratio=[]
            for window in windows:
                if not window['fold']['test_year_complete']:continue
                a=window['models'][name];b=window['models']['B_MATCHED_COV_VOL_PAPER' if name=='M2_FLEXIBLE_FLOOR_PAPER' else cfg['baseline']]
                if a['sharpe_rf_zero'] is None or b['sharpe_rf_zero'] is None:continue
                valid+=1;positive+=a['sharpe_rf_zero']-b['sharpe_rf_zero']>=cfg['sharpe_delta_min']
                tail_ok &= abs(a['historical_cvar95_daily_pct'])<=cfg['max_tail_loss_ratio']*abs(b['historical_cvar95_daily_pct'])
                vol_ratio.append(a['annual_vol_pct']/max(b['annual_vol_pct'],1e-12))
            fraction=positive/max(valid,1)
            cases.append({'cost_bps':cost,'complete_windows':valid,'positive_windows':positive,
                          'positive_fraction':fraction,'tail_gate':tail_ok,
                          'mean_realized_vol_ratio_vs_baseline':statistics.mean(vol_ratio) if vol_ratio else None,
                          'pass':valid>=5 and fraction>=cfg['positive_window_fraction_min'] and tail_ok})
        passed=all(x['pass'] for x in cases)
        # Even if screening passes, unequal realized risk and previously viewed data preclude promotion.
        result[name]={'screen':'PASS_SCREEN_ONLY' if passed else 'NO_EVIDENCE_OF_ADVANTAGE',
                      'decision':'KEEP_PRODUCTION_V4_1','cases':cases,
                      'reason':'RISK_NOT_EXACTLY_MATCHED_AND_NO_UNSEEN_FORWARD_EVIDENCE'}
    return result
