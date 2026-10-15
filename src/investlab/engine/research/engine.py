"""Close-t intent, close-(t+1) execution; new holdings earn returns starting t+2.
Adjusted-price units are total-return accounting units, NOT executable share counts.
"""
import copy
import math
import statistics
import strategy
from .policies import decision

def metrics(curve,dates,trades=(),exposures=()):
    if len(curve)<2:raise ValueError('Need at least one return')
    ret=[curve[i]/curve[i-1]-1 for i in range(1,len(curve))]
    n=len(ret);sd=statistics.stdev(ret) if n>1 else 0
    peak=curve[0];dd=0;peak_idx=0;worst_peak=0;trough=0;longest=0;underwater=0
    for i,v in enumerate(curve):
        if v>=peak:peak=v;peak_idx=i;underwater=0
        else:underwater+=1;longest=max(longest,underwater)
        if v/peak-1<dd:dd=v/peak-1;worst_peak=peak_idx;trough=i
    recovery=next((i for i in range(trough+1,len(curve)) if curve[i]>=curve[worst_peak]),None)
    tail=sorted(ret)[:max(1,math.ceil(.05*n))]
    result={'sessions':n,'start':dates[0],'end':dates[-1],
            'total_return_pct':(curve[-1]/curve[0]-1)*100,
            'cagr_pct':((curve[-1]/curve[0])**(252/n)-1)*100,
            'annual_vol_pct':sd*math.sqrt(252)*100,
            'sharpe_rf_zero':statistics.mean(ret)/sd*math.sqrt(252) if sd else None,
            'max_drawdown_pct':dd*100,'historical_cvar95_daily_pct':statistics.mean(tail)*100,
            'tail_sample_sessions':len(tail),'max_underwater_sessions':longest,
            'worst_peak':dates[worst_peak],'worst_trough':dates[trough],
            'recovery_session':dates[recovery] if recovery is not None else None,
            'recovery_from_peak_sessions':recovery-worst_peak if recovery is not None else None,
            'recovery_censored':recovery is None,
            'rebalances':len(trades),'external_fees_normalized':sum(x['fee'] for x in trades),
            'turnover_normalized_initial_equity':sum(x['traded'] for x in trades),
            'average_daily_ndx_exposure':statistics.mean(exposures) if exposures else None}
    for h in (20,60):
        losses=sorted(((curve[i]/curve[i-h]-1)*100,dates[i-h],dates[i]) for i in range(h,len(curve)))
        result[f'worst_{h}_sessions_pct']=losses[0][0] if losses else None
        if h==20:result['worst_5_overlapping_20_session_windows']=[{'loss_pct':a,'start':b,'end':c} for a,b,c in losses[:5]]
    return result

def simulate(data,fs,p,name,cost_bps=15,blocked_execution_sessions=()):
    if not math.isfinite(cost_bps) or not 0<=cost_bps<=500:raise ValueError('Invalid external cost')
    dates=data['dates'];values=[0.,0.,1.];state={};curve=[1.];events=[];exposures=[];infeasible=[]
    q=[r['adjusted_close'] for r in data['QQQ']];t=[r['adjusted_close'] for r in data['TQQQ']]
    weights_history=[];blocked_events=[]
    # All models begin flat on warmup close, including buy-and-hold comparators.
    for i in range(252,len(dates)):
        old=sum(values);prev=list(values)
        state_before=copy.deepcopy(state)
        signal=decision(name,i-1,data,fs,prev,state,p)
        exposures.append(prev[0]/old+3*prev[1]/old)
        weights_history.append([v/old for v in prev])
        values[0]*=q[i]/q[i-1];values[1]*=t[i]/t[i-1]
        target=signal['target']
        if signal['risk_budget_infeasible']:infeasible.append(dates[i-1])
        if target and dates[i] in blocked_execution_sessions:
            blocked_events.append({'signal_session':dates[i-1],'execute_session':dates[i],'status':'UNFILLED_PAPER_EXECUTION','is_paper':True})
            state=state_before
            target=None
        if target:
            pre=list(values);v0=sum(values)
            values,fee,traded=strategy.rebalance(values,target['QQQ'],target['TQQQ'],cost_bps/10000)
            if any(x< -1e-10 or not math.isfinite(x) for x in values):raise ValueError('Invalid simulated cash/asset')
            if abs(sum(values)+fee-v0)>1e-8:raise ValueError('Self-financing conservation failed')
            if pre[1]==0 and values[1]>0:state['t_entry']=t[i];state['entry_index']=i
            if values[1]==0:state.pop('t_entry',None);state.pop('entry_index',None)
            if name=='R_VALUE_AVERAGE_STRESS':state['quarter_start_t_value']=values[1]
            events.append({'signal_session':dates[i-1],'execute_session':dates[i],
                           'target':target,'fee':fee,'traded':traded,'reason':signal['reason'],
                           'adjusted_accounting_price':{'QQQ':q[i],'TQQQ':t[i]},
                           'is_paper':True,'not_executable_share_units':True})
        curve.append(sum(values))
    report=metrics(curve,dates[251:],events,exposures)
    report.update(model_id=name,cost_bps_per_side=cost_bps,
                  risk_budget_infeasible_sessions=len(infeasible),
                  blocked_execution_count=len(blocked_events),
                  infeasible_first_sessions=infeasible[:5],
                  reserve_exhaustions=state.get('reserve_exhaustions',0),
                  value_average_paused_buys=state.get('paused_buys',0),
                  terminal_weights=dict(zip(('QQQ','TQQQ','CASH'),[v/sum(values) for v in values])))
    return {'summary':report,'dates':dates[251:],'curve':curve,'trades':events,
            'weights_earning_return':weights_history,'exposures':exposures,'blocked_executions':blocked_events}
