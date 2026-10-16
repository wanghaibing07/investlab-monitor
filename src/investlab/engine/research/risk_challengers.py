"""Frozen shadow filters; C0 delegates to the original review function."""
import math

MODELS=('C0_ORIGINAL','C1_SHORT_TERM_FILTER','C2_FAST_VOL_FILTER','C3_PORTFOLIO_RISK_BUDGET','C4_COMBINED')


def target(model, current, trend, f, policy, parameters, original_review):
    if model not in MODELS:
        raise ValueError('UNKNOWN_CHALLENGER')
    desired, reason=original_review(current,trend,f['vol20']*100,policy)
    if model=='C0_ORIGINAL': return desired,reason,[]
    blocks=[]
    if model in ('C1_SHORT_TERM_FILTER','C4_COMBINED') and f['close']<f['sma20'] and f['three_down']:
        blocks.append('BELOW_SMA20_AND_THREE_DOWN')
    if model in ('C2_FAST_VOL_FILTER','C4_COMBINED'):
        fast=max(f['ewma_vol'],f['vol5'])
        if fast>parameters['fast_vol_floor'] and fast>parameters['fast_to_slow_ratio']*f['vol20']:
            blocks.append('FAST_VOL_ACCELERATION')
    # C1/C2 only cancel incremental buys, preserving exits and reductions.
    if blocks and desired['TQQQ']>current['TQQQ']:
        desired=dict(desired,TQQQ=current['TQQQ'])
        desired['CASH']=1-desired['QQQ']-desired['TQQQ']
    if model in ('C3_PORTFOLIO_RISK_BUDGET','C4_COMBINED'):
        qv,tv,cov=f['covariance60'];wq,wt=desired['QQQ'],desired['TQQQ']
        risk=math.sqrt(max(0.,wq*wq*qv+2*wq*wt*cov+wt*wt*tv)*252)
        scale=min(1.,parameters['portfolio_vol_target']/risk) if risk else 1.
        if scale<1:
            desired={k:desired[k]*scale for k in ('QQQ','TQQQ')}
            desired['CASH']=1-sum(desired.values());blocks.append('PAPER_PORTFOLIO_BUDGET_SCALE')
    return desired,reason,blocks
