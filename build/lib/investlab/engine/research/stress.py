from .leverage import ideal_path,growth

def synthetic():
    paths={'ROUND_TRIP_OSCILLATION_100_PAIRS':[.1,-1/11]*100,
           'TREND_UP_100_SESSIONS':[.01]*100,
           'PROLONGED_BEAR_100_SESSIONS':[-.015]*100,
           'OVERNIGHT_DROP_AND_REBOUND':[-.2,.25],
           'THEORETICAL_LIQUIDATION':[-.34]}
    out={}
    for name,rs in paths.items():
        q=ideal_path(rs,1);t=ideal_path(rs)
        out[name]={'label':'SYNTHETIC_NOT_HISTORICAL_TQQQ','qqq_like':q,'ideal_tqqq':t,
                   'assumptions':{'expense_rate':0,'financing':0,'slippage':0},
                   'warning':'STOPS_CANNOT_AVOID_ALREADY_REALIZED_OVERNIGHT_GAPS'}
    financing=[growth(.10,s,3,r,.005,.0097) for s in (.15,.25,.35) for r in (0,.04,.05)]
    return {'scenarios':out,'growth_assumption_sensitivity':financing,
            'pre_2010_history_status':'NOT_RUN_WITHOUT_VERIFIED_NDX_HISTORY'}
