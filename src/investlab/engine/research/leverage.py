"""Model arithmetic, not attribution of observed costs or an optimal bet estimate."""
import math

def ideal_path(returns, leverage=3, financing_rate=0, spread=0, expense=0):
    if not all(math.isfinite(x) for x in (leverage,financing_rate,spread,expense)):
        raise ValueError('Nonfinite model assumption')
    nav = 1.0; path = [nav]
    for r in returns:
        if not math.isfinite(r) or r <= -1:
            raise ValueError('Invalid underlying return')
        factor = 1 + leverage*r - (max(leverage-1,0)*(financing_rate+spread)+expense)/252
        if factor <= 0:
            return {'status':'THEORETICAL_NAV_NONPOSITIVE','path':path,'return_pct':None,
                    'failed_session_offset':len(path),'is_synthetic':True}
        nav *= factor; path.append(nav)
    return {'status':'SYNTHETIC_IDEAL_DAILY_RESET','path':path,'return_pct':(nav-1)*100,'is_synthetic':True}

def growth(mu, sigma, leverage=3, risk_free=0, spread=0, expense=0):
    if sigma < 0 or not all(math.isfinite(v) for v in (mu,sigma,leverage,risk_free,spread,expense)):
        raise ValueError('Invalid growth assumptions')
    g = leverage*mu - .5*leverage**2*sigma**2 - (leverage-1)*risk_free - max(leverage-1,0)*spread-expense
    return {'expected_log_growth':g,
            'relative_to_L_times_unlevered_log_growth_variance_drag':-.5*leverage*(leverage-1)*sigma**2,
            'extra_variance_drag_vs_one_unlevered_unit':-.5*(leverage**2-1)*sigma**2,
            'annual_geometric_factor_if_parameters_constant':math.exp(g)-1,
            'status':'ASSUMPTION_SENSITIVITY_NOT_FORECAST'}

def tracking(ndx, nav, compatible_basis=False):
    if not ndx or not nav or not compatible_basis:
        return {'status':'DATA_LIMITED_NO_COMPATIBLE_NDX_NAV_HISTORY','tracking_diff':None}
    if len(ndx)!=len(nav): raise ValueError('Unaligned NDX/NAV history')
    return {'status':'DIAGNOSTIC_NOT_COST_ATTRIBUTION',
            'tracking_diff':[nav[i]/nav[i-1]-1-3*(ndx[i]/ndx[i-1]-1) for i in range(1,len(ndx))]}
