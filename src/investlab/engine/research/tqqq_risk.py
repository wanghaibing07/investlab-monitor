"""Causal, pure risk diagnostics. Fractions throughout; no account or order writes."""
import math
import statistics as st


def returns(prices):
    if len(prices) < 2 or any(not math.isfinite(p) or p <= 0 for p in prices):
        raise ValueError('INVALID_PRICE_SERIES')
    return [b / a - 1 for a, b in zip(prices, prices[1:])]


def annual_vol(values):
    return st.stdev(values) * math.sqrt(252) if len(values) >= 2 else None


def features(q, t, lam=.94):
    if len(q) != len(t):
        raise ValueError('UNALIGNED_SERIES')
    qr, tr = returns(q), returns(t)
    ewma = 0.; out = []
    for i in range(len(q)):
        if i:
            lr = math.log(q[i] / q[i-1])
            ewma = lam * ewma + (1-lam) * lr * lr
        if i < 199:
            out.append(None); continue
        qlog = [math.log(q[j]/q[j-1]) for j in range(i-19, i+1)]
        qs,ts=qr[i-60:i],tr[i-60:i]
        qm,tm=st.mean(qs),st.mean(ts)
        covariance=(st.variance(qs),st.variance(ts),sum((a-qm)*(b-tm) for a,b in zip(qs,ts))/(len(qs)-1))
        out.append({
            'close': q[i], 'sma20': st.mean(q[i-19:i+1]),
            'sma50': st.mean(q[i-49:i+1]), 'sma200': st.mean(q[i-199:i+1]),
            'momentum63': q[i]/q[i-63]-1,
            'three_down': all(q[j] < q[j-1] for j in range(i-2, i+1)),
            'return5': q[i]/q[i-5]-1, 'return10': q[i]/q[i-10]-1,
            'vol5': annual_vol(qr[i-5:i]), 'vol20': annual_vol(qlog),
            'ewma_vol': math.sqrt(252*ewma),
            'tqqq_vol20': annual_vol(tr[i-20:i]),
            'tqqq_drawdown252': t[i]/max(t[max(0,i-251):i+1])-1,
            'q_returns60': qs, 't_returns60': ts, 'covariance60':covariance})
    return out


def portfolio_risk(q_returns, t_returns, weights, target_vol=.25):
    if len(q_returns) != len(t_returns) or len(q_returns) < 20:
        raise ValueError('INSUFFICIENT_ALIGNED_RETURNS')
    wq, wt = weights['QQQ'], weights['TQQQ']
    if min(wq, wt) < 0 or wq + wt > 1 + 1e-10:
        raise ValueError('INVALID_WEIGHTS')
    pr = [wq*q+wt*t for q,t in zip(q_returns,t_returns)]
    qv, tv = st.variance(q_returns), st.variance(t_returns)
    qm, tm = st.mean(q_returns), st.mean(t_returns)
    cov = sum((q-qm)*(t-tm) for q,t in zip(q_returns,t_returns))/(len(pr)-1)
    var = wq*wq*qv + 2*wq*wt*cov + wt*wt*tv
    curve = [1.]
    for r in pr: curve.append(curve[-1]*(1+r))
    metrics = path_metrics(curve)
    windows = [annual_vol(pr[i-20:i]) for i in range(20,len(pr)+1)]
    return dict(metrics, window_sessions=len(pr), annual_vol=math.sqrt(max(0.,var)*252),
                approximate_daily_exposure=wq+3*wt,
                variance_contribution={'QQQ': wq*(wq*qv+wt*cov)/var if var else None,
                                       'TQQQ': wt*(wq*cov+wt*tv)/var if var else None},
                empirical_20d_vol_target_exceedance=sum(v>target_vol for v in windows)/len(windows),
                target_vol_scenario=target_vol, evidence='HISTORICAL_EMPIRICAL_NOT_FUTURE_PROBABILITY')


def path_metrics(curve):
    if len(curve)<2 or any(not math.isfinite(v) or v<=0 for v in curve):
        raise ValueError('INVALID_EQUITY_PATH')
    rs=returns(curve); peak=curve[0]; drawdowns=[]; longest=under=0
    for v in curve:
        peak=max(peak,v); dd=v/peak-1; drawdowns.append(dd)
        under=under+1 if dd < -1e-12 else 0; longest=max(longest,under)
    tail_n=max(1,math.ceil(.05*len(rs))); dd_n=max(1,math.ceil(.05*len(drawdowns)))
    vol=annual_vol(rs)
    return {'cagr':(curve[-1]/curve[0])**(252/len(rs))-1,
            'annual_vol':vol, 'sharpe_rf_zero':st.mean(rs)*252/vol if vol else None,
            'max_drawdown':min(drawdowns), 'cvar95_daily':st.mean(sorted(rs)[:tail_n]),
            'cdar95':st.mean(sorted(drawdowns)[:dd_n]), 'longest_underwater_sessions':longest,
            'worst20':min((curve[i]/curve[i-20]-1 for i in range(20,len(curve))),default=None),
            'tail_sample_sessions':tail_n, 'sessions':len(rs)}


def conflict(f, production, account_as_of, session):
    if not f:
        return {'status':'DATA_LIMITED','risk_conflict':False,'execution_ready':False}
    short=f['close']<f['sma20'] and f['three_down']
    add=production.get('actions',{}).get('TQQQ')=='INCREASE_REVIEW'
    return {'status':'PAPER', 'risk_conflict':bool(add and short),
            'long_trend':{'active':production.get('trend_active'),'source':'C0_UNCHANGED'},
            'medium_trend':{'below_sma50':f['close']<f['sma50'],'momentum63':f['momentum63']},
            'short_risk':{k:f[k] for k in ('close','sma20','three_down','return5','return10')},
            'volatility_risk':{k:f[k] for k in ('vol5','vol20','ewma_vol','tqqq_vol20','tqqq_drawdown252')},
            'research_observation':'PAUSE_NEW_ADDS' if short else 'NO_SHORT_FILTER',
            'execution_ready':False,'readiness':'NOT_IMPLEMENTATION_READY',
            'account_stale':account_as_of!=session,
            'missing_execution_inputs':['CURRENT_CONFIRMED_VALUATION','SHARES','COST','FX','PERSONAL_RISK_BUDGET'],
            'production_review_unchanged':True,'orders':[]}
