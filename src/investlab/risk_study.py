"""Isolated shadow study. Reads one ledger using mode=ro, writes a new output folder."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from .core import ENGINE,PACKAGE
from .engine.research.experiment_registry import digest,register,write_once
from .engine.research.tqqq_risk import features,portfolio_risk,conflict,returns,path_metrics
from .engine.research.risk_challengers import MODELS,target
from .engine.research.execution_scenarios import simulate,rebound_counterexamples


def study_code_identity():
    # Canonical paths and normalized UTF-8 newlines make identities portable.
    return digest({p.relative_to(PACKAGE).as_posix():hashlib.sha256(p.read_text(encoding='utf8').encode()).hexdigest()
                   for p in sorted(PACKAGE.rglob('*')) if p.is_file()
                   and p.suffix in ('.py','.json','.js','.html','.css') and '__pycache__' not in p.parts})


def read_inputs(home):
    home=Path(home).resolve();db=home/'data/monitor.sqlite3'
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        if c.execute('pragma integrity_check').fetchall()[0][0]!='ok' or c.execute('pragma foreign_key_check').fetchall():
            raise ValueError('LEDGER_INTEGRITY_FAILURE')
        candles={s:[dict(r) for r in c.execute('SELECT * FROM daily_prices WHERE symbol=? ORDER BY trade_date',(s,))] for s in ('QQQ','TQQQ')}
        stored=c.execute('SELECT report_json FROM monitor_runs ORDER BY run_at DESC LIMIT 1').fetchone()
        report=json.loads(stored[0]) if stored else None
    if not report:raise ValueError('NO_ARCHIVED_PRODUCTION_REPORT')
    return db,before,candles,report


def study(home,output,source_commit):
    output=Path(output).resolve();home=Path(home).resolve()
    # Research outputs must not sit anywhere in the source runtime tree.
    if output==home or home in output.parents or output.exists():
        raise ValueError('RESEARCH_OUTPUT_REQUIRES_NEW_ISOLATED_DIRECTORY')
    repo=Path(__file__).resolve().parents[2]
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    # --source-commit describes the actual checked out code, including the initial research parent.
    if head!=source_commit:raise ValueError('SOURCE_COMMIT_MISMATCH')
    db,before,candles,report=read_inputs(home)
    sys.path.insert(0,str(ENGINE))
    try:
        import advisory,advisory_compare,monitor,strategy
        from research.dataset import from_candles,features as original_features
        from research.common import read_protocol
        cutoff=report['as_of_expected_session']
        data0=from_candles(candles,cutoff)
        data={'dates':data0['dates'],'prices':{s:[r['adjusted_close'] for r in data0[s]] for s in ('QQQ','TQQQ')}}
        policy=advisory.config(); original=advisory.observe(report,candles)
        if original!=report['allocation_review']:raise ValueError('C0_ARCHIVED_REPORT_MISMATCH')
        registry=register(output,head,study_code_identity(),digest(data),cutoff,policy)
        par=registry['parameters'];fs=features(data['prices']['QQQ'],data['prices']['TQQQ'],par['ewma_lambda'])
        trends=advisory.trend_history(data0['QQQ'],policy)
        args=(data,fs,trends,policy,par,advisory.review_weights,strategy.rebalance)
        # Exact original historical algorithm is the oracle, at both original costs.
        golden=[]
        oldfs=original_features(data0,read_protocol())
        for fee in par['fees_bps']:
            old=advisory_compare.simulate_review(data0,oldfs,policy,fee)
            new=simulate(*args,'C0_ORIGINAL',fee)
            error=max(abs(a-b)/max(abs(a),1e-15) for a,b in zip(old['curve'],new['curve']))
            exact=old['curve']==new['curve'] and old['trades']==[
                {k:v for k,v in e.items() if k in ('signal_session','execute_session','target','reason','fee','traded')}
                for e in new['trades']]
            golden.append({'fee_bps':fee,'exact_equity_and_trades':exact,'max_relative_error':error})
        if not all(x['exact_equity_and_trades'] for x in golden):
            write_once(output/'c0_regression_failure.json',golden)
            raise ValueError('C0_HISTORICAL_REGRESSION')
        comparisons=[];primary_paths={};trials=0
        for fee in par['fees_bps']:
            for slip in par['slippage_bps']:
                for model in MODELS:
                    p=simulate(*args,model,fee,slip);comparisons.append(p['summary']);trials+=1
                    if fee==15 and slip==0:primary_paths[model]=p
        sensitivity=[]
        for execution in par['execution'][1:]:
            for slip in par['slippage_bps']:
                for model in MODELS:
                    p=simulate(*args,model,15,slip,execution);sensitivity.append(p['summary']);trials+=1
        # Distinct scenario budgets are registered, not picked after seeing performance.
        budgets=[]
        for vol in par['portfolio_vol_scenarios']:
            p=simulate(data,fs,trends,policy,dict(par,portfolio_vol_target=vol),advisory.review_weights,strategy.rebalance,'C3_PORTFOLIO_RISK_BUDGET')
            budgets.append({'budget':vol,'kind':'DYNAMIC_C3','summary':p['summary']});trials+=1
            for name,w in [('TARGET60_40',{'QQQ':.6,'TQQQ':.4,'CASH':0.}),('STEP60_5_35',{'QQQ':.6,'TQQQ':.05,'CASH':.35}),('CONFIRMED60_0_40',{'QQQ':.6,'TQQQ':0.,'CASH':.4}),('QQQ100',{'QQQ':1.,'TQQQ':0.,'CASH':0.})]:
                # Same reference path repeats under each named risk budget to expose exceedances.
                result=simulate(*args,'C0_ORIGINAL',fixed_weights=w)
                budgets.append({'budget':vol,'kind':name,'summary':result['summary'],
                                'latest_risk':portfolio_risk(fs[-1]['q_returns60'],fs[-1]['t_returns60'],w,vol)})
                trials+=1
        normalized=[]
        # Ex-post normalization is descriptive, explicitly not a causal trading strategy.
        for model,p in primary_paths.items():
            m=p['summary'];scale=min(1.,.15/m['annual_vol']) if m['annual_vol'] else 1.
            norm=[1.]
            for r in returns(p['curve']):norm.append(norm[-1]*(1+scale*r))
            normalized.append({'model_id':model,'scale':scale,'method':'EX_POST_VOL_NORMALIZATION_NOT_INVESTABLE',**path_metrics(norm)})
            trials+=1
        # Prefix equality verifies all challenger histories, independently of headline metrics.
        prefixes=[]
        dshort={'dates':data['dates'][:-20],'prices':{s:v[:-20] for s,v in data['prices'].items()}}
        sf=features(dshort['prices']['QQQ'],dshort['prices']['TQQQ'],par['ewma_lambda'])
        for model in MODELS:
            short=simulate(dshort,sf,trends[:-20],policy,par,advisory.review_weights,strategy.rebalance,model)
            ok=primary_paths[model]['curve'][:len(short['curve'])]==short['curve']
            prefixes.append({'model_id':model,'prefix_equal':ok})
        if not all(r['prefix_equal'] for r in prefixes):raise ValueError('PREFIX_CAUSALITY_FAILURE')
        risk=conflict(fs[-1],original,report['portfolio']['as_of'],cutoff)
        latest_portfolios={}
        for name,w in [('TARGET',{'QQQ':.6,'TQQQ':.4}),('NEXT_STEP',{'QQQ':.6,'TQQQ':.05}),('LAST_CONFIRMED',{'QQQ':.6,'TQQQ':0.})]:
            latest_portfolios[name]=portfolio_risk(fs[-1]['q_returns60'],fs[-1]['t_returns60'],w)
        base=primary_paths['C0_ORIGINAL']['summary']; decisions=[]
        for name,p in primary_paths.items():
            m=p['summary'];improvement=1-abs(m['cvar95_daily'])/abs(base['cvar95_daily'])
            accepted=name!='C0_ORIGINAL' and improvement>=par['cvar_risk_improvement_min'] and m['cagr']>=base['cagr']-par['cagr_loss_max']
            decisions.append({'model_id':name,'historical_cvar_improvement':improvement,
                              'cagr_delta':m['cagr']-base['cagr'],'diagnostic_threshold_met':accepted,
                              'production_approved':False,'decision':'RESEARCH_ONLY_PENDING_FORWARD_EVIDENCE'})
        corporate={'status':'DATA_LIMITED','independent_adjusted_history':'NOT_VERIFIED',
                   'missing_independent_period':'2010-2015','corporate_actions':'NOT_VERIFIED',
                   'source_policy':'ARCHIVED_YAHOO_HISTORY_NO_ONLINE_REPLACEMENT',
                   'ohlc':'NOT_AVAILABLE_OPEN_IS_EXPLICIT_ASSUMPTION',
                   'end':cutoff,'start':data['dates'][0],'sessions':len(data['dates'])}
        # Exercise the same strict contract on the archived primary rows; missing
        # action and payload linkage remain explicit instead of being fabricated.
        from .engine.research.qualified_bars import QualifiedDailyBar,validate
        primary_contract=[]
        for symbol in ('QQQ','TQQQ'):
            bars=[QualifiedDailyBar(symbol,r['trade_date'],r['source'],'VENDOR_DAILY','VENDOR_ADJUSTED',
                     r['raw_close'],r['adjusted_close'],r['fetched_at'],None,None) for r in data0[symbol]]
            primary_contract.append({'symbol':symbol,**validate(bars,cutoff,monitor.is_regular_session,expected_sessions=data['dates'])})
        corporate['primary_contract']=primary_contract
        stress={}
        for name,rets in {'SLOW_DECLINE':[-.01]*20,'V_REBOUND':[-.10,-.08,.12,.15],
                          'WHIPSAW':[.10,-.10]*10,'EXTREME_GAP':[-.20,.05],
                          'UPWARD_HIGH_VOL':[.02,.08]*10}.items():
            qp=[1.];tp=[1.]
            for r in rets:qp.append(qp[-1]*(1+r));tp.append(tp[-1]*(1+max(-.99,3*r)))
            stress[name]={'synthetic':True,'assumption':'DAILY_3X_IDEALIZATION_NOT_REAL_TQQQ',
                          'qqq_return':qp[-1]-1,'tqqq_path_return':tp[-1]-1,
                          'three_times_qqq_multiday':3*(qp[-1]-1),
                          'target_buy_hold_return':.6*(qp[-1]-1)+.4*(tp[-1]-1)}
            stress[name]['target_path_metrics']=path_metrics([.6*a+.4*b for a,b in zip(qp,tp)])
        out={'schema_version':1,'experiment_id':registry['experiment_id'],'source_commit':head,
             'code_hash':registry['code_hash'],'input_hash':registry['input_hash'],
             'parameter_hash':registry['parameter_hash'],'session_date':cutoff,'model_id':'C0_C4_SHADOW',
             'status':'PARTIAL_RESEARCH','scope':'PAPER','historical_label':registry['historical_label'],
             'production_review':original,'risk_conflict':risk,'portfolio_risk':latest_portfolios,
             'data_qualification':corporate,'c0_regression':golden,'prefix_checks':prefixes,
             'comparisons':comparisons,'execution_sensitivity':sensitivity,'budget_scenarios':budgets,
             'risk_normalized_diagnostics':normalized,'candidate_decisions':decisions,
             'completed_registered_trials':trials,'stress_scenarios':stress,
             'counterexamples':rebound_counterexamples(data,fs,primary_paths),
             'limits':['NO_PERSONAL_RISK_APPROVAL','NO_FORWARD_STRATEGY_EVIDENCE','NO_VERIFIED_HISTORICAL_OHLC',
                       'CASH_ZERO_YIELD','TAX_FX_EXCLUDED','ETF_FUND_COSTS_ALREADY_IN_PRICES',
                       'INDEPENDENT_ADJUSTED_HISTORY_NOT_VERIFIED','MULTI_TIMEPOINT_RESTORE_SEPARATE_GATE'],
             'account_database_before':before,'production_approved':False,'orders':[]}
        if trials!=registry['total_registered_trials']:raise ValueError('TRIAL_COUNT_MISMATCH')
        if study_code_identity()!=registry['code_hash']:raise ValueError('RESEARCH_SOURCE_CHANGED_DURING_RUN')
        after=hashlib.sha256(db.read_bytes()).hexdigest()
        if before!=after:raise ValueError('SOURCE_LEDGER_CHANGED')
        out['account_database_after']=after;out['result_hash']=digest(out)
        write_once(output/'challenger_comparison.json',out)
        write_once(output/'primary_paths.json',{k:{x:v for x,v in p.items() if x in ('curve','dates','trades','blocked_executions')} for k,p in primary_paths.items()})
        from .risk_view import render,markdown
        with (output/'report.html').open('x',encoding='utf-8') as f:f.write(render(out))
        with (output/'REPORT.md').open('x',encoding='utf-8') as f:f.write(markdown(out))
        return {'status':out['status'],'output':str(output),'trials':trials,'result_hash':out['result_hash'],
                'risk_conflict':risk['risk_conflict'],'ledger_unchanged':before==after}
    finally:
        sys.path.remove(str(ENGINE))
