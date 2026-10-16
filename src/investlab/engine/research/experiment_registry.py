"""Exclusive, immutable research registration and results. No SQLite migration."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def write_once(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(value,f,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def register(directory,source_commit,code_hash,input_hash,session_date,policy):
    params={'ewma_lambda':.94,'fast_vol_floor':.20,'fast_to_slow_ratio':1.5,
            'portfolio_vol_target':.25,'portfolio_vol_scenarios':[.15,.20,.25],
            'warmup':252,'fees_bps':[15,50],'slippage_bps':[0,10,30],
            'execution':['NEXT_CLOSE','ASSUMED_NEXT_OPEN','ADVERSE_GAP','DELAY_ONE_SESSION','UNFILLED_STRESS'],
            'assumed_open_gap':.01,'blocked_every_nth_signal':20,
            'cvar_risk_improvement_min':.10,'cagr_loss_max':.03,
            'annual_diagnostic_fold_sessions':252}
    spec={'schema_version':1,'scope':'PAPER','source_commit':source_commit,'code_hash':code_hash,
          'input_hash':input_hash,'session_date':session_date,'parameters':params,
          'parameter_hash':digest(params),'production_policy':policy,'policy_hash':digest(policy),
          'models':['C0_ORIGINAL','C1_SHORT_TERM_FILTER','C2_FAST_VOL_FILTER','C3_PORTFOLIO_RISK_BUDGET','C4_COMBINED'],
          'historical_label':'HISTORIC_DIAGNOSTIC_ALREADY_SEEN','parameter_search_trials':0,
          'primary_trials':30,'execution_sensitivity_trials':60,'portfolio_budget_trials':15,
          'normalized_risk_trials':5,'total_registered_trials':110,
          'acceptance':'NO_LEAKAGE_AND_CVAR_IMPROVEMENT_WITH_DISCLOSED_CAGR_COST',
          'production_approved':False,'registered_at':datetime.now(timezone.utc).isoformat()}
    spec['experiment_id']=digest({k:v for k,v in spec.items() if k!='registered_at'})
    write_once(Path(directory)/'experiment_registry.json',spec)
    return spec
