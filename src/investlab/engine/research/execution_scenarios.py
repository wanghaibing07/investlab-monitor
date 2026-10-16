"""Self-financing paper fills, including explicit open assumptions and non-fills."""
import math
import statistics as st
from .risk_challengers import target
from .tqqq_risk import path_metrics, returns


def simulate(data,fs,trends,policy,parameters,original_review,rebalance,model,
             fee_bps=15,slippage_bps=0,execution='NEXT_CLOSE',fixed_weights=None):
    if execution not in parameters['execution']: raise ValueError('UNKNOWN_EXECUTION_MODEL')
    if not all(math.isfinite(x) and 0<=x<=500 for x in (fee_bps,slippage_bps)):
        raise ValueError('INVALID_COST')
    dates=data['dates'];q=data['prices']['QQQ'];t=data['prices']['TQQQ']
    start=parameters['warmup']-1
    values=[0.,0.,1.];curve=[1.];trades=[];blocked=[];filters=[];exposures=[]
    holdings=[];pending=None;attempts=0;external_fee=slip_cost=0.
    for i in range(start+1,len(dates)):
        total=sum(values); current=dict(zip(('QQQ','TQQQ','CASH'),[v/total for v in values]))
        holdings.append(current); exposures.append(current['QQQ']+3*current['TQQQ'])
        if fixed_weights is None:
            desired,reason,flags=target(model,current,trends[i-1]['active'],fs[i-1],policy,parameters,original_review)
        else:
            desired=fixed_weights; reason='FIXED_RESEARCH_REFERENCE';flags=[]
        if flags: filters.append({'session':dates[i-1],'flags':flags})
        changed=any(abs(desired[k]-current[k])>1e-9 for k in ('QQQ','TQQQ'))
        if fixed_weights is not None:
            changed=changed and (i==start+1 or dates[i][:7]!=dates[i-1][:7])
        signal_date=dates[i-1]
        if execution=='DELAY_ONE_SESSION':
            if pending is None and changed: pending=(i+1,desired,signal_date,reason)
            if pending is not None and pending[0]==i:
                _,desired,signal_date,reason=pending;pending=None;changed=True
            else: changed=False
        overnight=[1.,1.]
        if execution=='ADVERSE_GAP' and changed:
            overnight=[1+(parameters['assumed_open_gap']*factor)*(1 if desired[k]>current[k] else -1)
                       for k,factor in (('QQQ',1),('TQQQ',3))]
        at_open=execution in ('ASSUMED_NEXT_OPEN','ADVERSE_GAP')
        multipliers=[q[i]/q[i-1],t[i]/t[i-1]]
        for j in (0,1): values[j]*=overnight[j] if at_open else multipliers[j]
        if changed:
            attempts+=1
            if execution=='UNFILLED_STRESS' and attempts%parameters['blocked_every_nth_signal']==0:
                blocked.append({'signal_session':signal_date,'execute_session':dates[i],
                                'status':'UNFILLED_PAPER','reason':'REGISTERED_LIQUIDITY_STRESS'})
            else:
                if signal_date>=dates[i]: raise ValueError('FUTURE_SIGNAL_LEAKAGE')
                before=sum(values)
                values,cost,traded=rebalance(values,desired['QQQ'],desired['TQQQ'],(fee_bps+slippage_bps)/10000)
                if abs(sum(values)+cost-before)>1e-8 or min(values)<-1e-10:
                    raise ValueError('SELF_FINANCING_FAILED')
                rate=fee_bps+slippage_bps
                fee=cost if not slippage_bps else (cost*fee_bps/rate if rate else 0.)
                slip=cost-fee
                external_fee+=fee;slip_cost+=slip
                trades.append({'signal_session':signal_date,'execute_session':dates[i],
                               'target':desired,'fee':fee,'slippage':slip,'traded':traded,
                               'reason':reason,'paper':True,'execution':execution})
        if at_open:
            for j in (0,1):values[j]*=multipliers[j]/overnight[j]
        curve.append(sum(values))
    summary=path_metrics(curve)
    summary.update(model_id=model,cost_bps=fee_bps,slippage_bps=slippage_bps,execution=execution,
                   rebalances=len(trades),unfilled=len(blocked),fees_initial_equity=external_fee,
                   slippage_initial_equity=slip_cost,turnover_initial_equity=sum(x['traded'] for x in trades),
                   average_daily_exposure=st.mean(exposures),filtered_sessions=len(filters),
                   evidence='HISTORIC_DIAGNOSTIC_ALREADY_SEEN',hypothetical=True,
                   pending_at_end=pending is not None)
    # Up capture uses equal daily intervals, preserving the opening execution assumption.
    own=returns(curve); bench=returns(q[start:]);up=[i for i,r in enumerate(bench) if r>0]
    summary['up_capture']=sum(own[i] for i in up)/sum(bench[i] for i in up) if up else None
    folds=[]
    for left in range(0,len(curve)-1,252):
        right=min(left+252,len(curve)-1)
        folds.append({'start':dates[start+left],'end':dates[start+right],
                      **path_metrics(curve[left:right+1]),'label':'ALREADY_SEEN_CHRONOLOGICAL_DIAGNOSTIC'})
    summary['folds']=folds
    worst=sorted(range(len(own)),key=lambda j:own[j])[:5]
    summary['worst_days']=[{'session':dates[start+j+1],'return':own[j]} for j in worst]
    return {'summary':summary,'curve':curve,'dates':dates[start:],'trades':trades,
            'blocked_executions':blocked,'filter_events':filters,'holdings':holdings}


def rebound_counterexamples(data,fs,paths):
    baseline=paths['C0_ORIGINAL']; dates=baseline['dates']; start=len(data['dates'])-len(dates)
    q=data['prices']['QQQ']; rows=[]
    for j in range(1,len(dates)-5):
        f=fs[start+j]
        if f['close']<f['sma20'] and f['three_down']:
            delta={name:(p['curve'][j+5]/p['curve'][j]-1)-(baseline['curve'][j+5]/baseline['curve'][j]-1)
                   for name,p in paths.items() if name!='C0_ORIGINAL'}
            rows.append({'session':dates[j],'qqq_next5':q[start+j+5]/q[start+j]-1,
                         'challenger_minus_c0_next5':delta})
    return {'horizon':5,'overlapping_windows':True,'events':len(rows),
            'missed_rebounds':sorted((r for r in rows if r['qqq_next5']>0),key=lambda r:r['challenger_minus_c0_next5'].get('C1_SHORT_TERM_FILTER',0))[:10],
            'avoided_losses':sorted((r for r in rows if r['qqq_next5']<0),key=lambda r:-r['challenger_minus_c0_next5'].get('C1_SHORT_TERM_FILTER',0))[:10],
            'all_event_results':rows}
