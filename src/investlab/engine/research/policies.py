"""Frozen policies share one information boundary and portfolio budget."""
import math
import strategy

def weights(q,t):
    if not all(math.isfinite(x) and x>=-1e-12 for x in (q,t)) or q+t>1+1e-12:
        raise ValueError('Invalid nonnegative self-financing weights')
    return {'QQQ':q,'TQQQ':t,'CASH':max(0,1-q-t)}

def portfolio_vol(f,q,t):
    return math.sqrt(max(0,q*q*f['qqq_var']+t*t*f['tqqq_var']+2*q*t*f['cov']))

def flexible_target(f,q,t,p):
    cap=p['paper_flexible_risk']['target_vol']
    scale=min(1,cap/max(portfolio_vol(f,q,t),1e-12))
    return weights(q*scale,t*scale)


def trend(f,state,p):
    active=state.get('trend',False);cfg=p['trend']
    if f['close']>f['sma200']*(1+cfg['enter_buffer']):active=True
    elif f['close']<f['sma200']*(1-cfg['exit_buffer']):active=False
    state['trend']=active
    return active

def decision(name, i, data, fs, values, state, p):
    """Called only with information through close i. Return target or hold."""
    if name not in p['models']:raise ValueError('Unregistered model: '+name)
    f=fs[i];dates=data['dates'];equity=sum(values)
    qprev,tprev=values[0]/equity,values[1]/equity
    target=None;reason='HOLD';due=False;infeasible=False
    monthly=i+1<len(dates) and dates[i][:7]!=dates[i+1][:7]
    quarter=i+1<len(dates) and (int(dates[i][5:7])-1)//3!=(int(dates[i+1][5:7])-1)//3
    first=not state.get('initialized',False)
    initial={'B_QQQ':(1,0),'B_QQQ80':(.8,0),'B_USER70_20_10_STRESS':(.7,.2),'B_TQQQ_STRESS':(0,1)}
    if name in initial:
        target=weights(*initial[name]);due=first or (monthly and name not in ('B_QQQ','B_TQQQ_STRESS'));reason='INITIAL_OR_MONTH_END'
    elif name in ('C0_CORE_ANCHORED','C0_TACTICAL_ANCHORED'):
        cfg=strategy.config()
        elapsed=strategy.elapsed_sessions(dates[:i+1],dates[251])
        x=strategy.targets(f,cfg,elapsed);q=x['qqq'];t=0
        if name=='C0_TACTICAL_ANCHORED':
            entry=state.get('t_entry')
            if entry is not None:
                stop=(f['close']<f['sma200'] or f['vol20_pct']>=cfg['tqqq']['qqq_vol20_exit'] or
                      data['TQQQ'][i]['adjusted_close']/entry-1<=-.2 or tprev>cfg['tqqq']['hard_max_weight'])
                if not stop:t=.05 if tprev>.075 else tprev
            else:t=x['tqqq']
            q=min(q,1-p['risk']['cash_min']-t,p['risk']['daily_exposure_max']-3*t)
        target=weights(q,t);due=first or abs(q-qprev)>=p['turnover_band']-1e-12 or abs(t-tprev)>=.005
        reason='C0_STATEFUL_ACCOUNT_INDEPENDENT_CLOCK'
    elif name=='R_VALUE_AVERAGE_STRESS':
        # A dollar target fixed at prior quarter execution. No deposits or imaginary bonds.
        if first:target=weights(0,p['value_average']['initial_tqqq']);due=True
        elif quarter:
            goal=state['quarter_start_t_value']*(1+p['value_average']['quarter_target'])
            wt=min(1,max(0,goal/equity))
            if p['value_average']['trend_buy_lock'] and f['close']<f['sma200'] and wt>tprev:
                wt=tprev;state['paused_buys']=state.get('paused_buys',0)+1
            if goal>equity:state['reserve_exhaustions']=state.get('reserve_exhaustions',0)+1
            target=weights(0,wt);due=True
        reason='SIMPLIFIED_QUARTERLY_VALUE_AVERAGING_NOT_9SIG'
    elif name=='R_RSI2_SWING':
        cfg=p['swing'];t=tprev
        if tprev>0:
            holding=i-state['entry_index']
            if (f['close']<f['sma200'] or f['rsi2']>cfg['exit_above'] or
                f['close']>f['prior_high5'] or holding>=cfg['max_holding_sessions']-1):t=0
        elif f['close']>f['sma200'] and f['rsi2']<cfg['entry_below']:t=cfg['weight']
        target=weights(.7,t);due=first or abs(t-tprev)>.005 or monthly;reason='QQQ_RSI2_NO_IBS_CLAIM'
    else:
        active=trend(f,state,p)
        safe=f['ewma_vol']<p['ewma']['entry_vol_max']
        high=f['ewma_vol']>=p['ewma']['high_vol']
        if name=='R_LRS_FULL_TQQQ_STRESS':
            target=weights(0,1 if active and safe else (.5 if active and not high else 0))
            due=first or abs(target['TQQQ']-tprev)>.05;reason='FULL_LEVERAGE_RISK_ONLY'
        else:
            risk=p['risk'];q=.7 if active else .5
            if name=='M1_EWMA_ONLY':q=.7;t=risk['tqqq_entry'] if safe else 0
            elif name=='M1_TREND_ONLY':t=risk['tqqq_entry'] if active else 0
            else:t=risk['tqqq_entry'] if active and safe else 0
            if high and name!='M1_TREND_ONLY':q=.5;t=0
            if name in ('M2_COVARIANCE_BUDGET','B_MATCHED_DAILY_EXPOSURE'):
                # First reduce leverage, then QQQ, with no hidden override of old floor.
                cap=risk['target_vol']
                if portfolio_vol(f,q,t)>cap:
                    lo,hi=0,t
                    for _ in range(35):
                        mid=(lo+hi)/2
                        if portfolio_vol(f,q,mid)<=cap:lo=mid
                        else:hi=mid
                    t=lo
                    if portfolio_vol(f,q,t)>cap:
                        q=max(risk['qqq_min'],min(q,cap/max(math.sqrt(f['qqq_var']),1e-12)))
                infeasible=portfolio_vol(f,q,t)>cap+1e-8
                if name=='B_MATCHED_DAILY_EXPOSURE':q,t=q+3*t,0
            elif name in ('M2_FLEXIBLE_FLOOR_PAPER','B_MATCHED_COV_VOL_PAPER'):
                # Explicit paper-only policy version; the legacy 50% floor is not overwritten.
                cap=p['paper_flexible_risk']['target_vol']
                flex=flexible_target(f,q,t,p);q,t=flex['QQQ'],flex['TQQQ']
                if name=='B_MATCHED_COV_VOL_PAPER':
                    matched=portfolio_vol(f,q,t)
                    q,t=matched/max(math.sqrt(f['qqq_var']),1e-12),0
                    q=min(q,.85)
                infeasible=portfolio_vol(f,q,t)>cap+1e-8
            elif name=='B_QQQ_VOL12':q,t=min(.85,risk['target_vol']/max(f['ewma_vol'],1e-12)),0
            target=weights(q,t);due=first or abs(q-qprev)>=p['turnover_band']-1e-12 or abs(t-tprev)>=.005
            if name in ('M2_FLEXIBLE_FLOOR_PAPER','B_MATCHED_COV_VOL_PAPER') and portfolio_vol(f,qprev,tprev)>p['paper_flexible_risk']['target_vol']+1e-8:
                due=True
            reason='TREND_EWMA_COVARIANCE_RESEARCH'
    if target and name.startswith(('C0_','M1_','M2_','R_RSI')):
        risk=p['risk'];t=min(target['TQQQ'],risk['tqqq_max'])
        q=min(target['QQQ'],risk['qqq_max'],1-risk['cash_min']-t,risk['daily_exposure_max']-3*t)
        target=weights(q,t)
    state['initialized']=True
    if not due:return {'target':None,'reason':reason,'risk_budget_infeasible':infeasible}
    return {'target':target,'reason':reason,'risk_budget_infeasible':infeasible}
