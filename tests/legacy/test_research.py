import copy
import datetime as dt
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import monitor as m
import strategy
from research.common import read_protocol,digest,ROOT
from research.dataset import from_candles,features,rsi
from research.leverage import ideal_path,growth,tracking
from research.engine import simulate
from research.policies import decision,weights
from research.validation import purged_indices,folds
from research import shadow

def fixture(n=350,start=dt.date(2024,1,2)):
    rs=[];day=start
    while len(rs)<n:
        if m.is_regular_session(day):
            i=len(rs);price=100*math.exp(.0004*i+.004*math.sin(i*.7))
            rs.append({'trade_date':day.isoformat(),'raw_close':price,'adjusted_close':price,
                       'source':'YAHOO_QUERY1','fetched_at':'2026-10-14T12:00:00+08:00'})
        day+=dt.timedelta(days=1)
    candles={'QQQ':rs,'TQQQ':[{**r,'raw_close':r['raw_close']**1.5,'adjusted_close':r['adjusted_close']**1.5} for r in rs]}
    result=from_candles(candles,rs[-1]['trade_date'])
    result['QLD']=[{**r,'raw_close':r['raw_close']**1.25,'adjusted_close':r['adjusted_close']**1.25} for r in rs]
    return result

class LeverageTests(unittest.TestCase):
    def test_round_trip_path(self):
        rs=[.1,-1/11]
        self.assertAlmostEqual(ideal_path(rs,1)['return_pct'],0)
        self.assertAlmostEqual(ideal_path(rs)['return_pct'],-5.4545454545)
    def test_growth_comparison_bases(self):
        x=growth(.1,.35)
        self.assertAlmostEqual(x['relative_to_L_times_unlevered_log_growth_variance_drag'],-.3675)
        self.assertAlmostEqual(x['extra_variance_drag_vs_one_unlevered_unit'],-.49)
    def test_costs_reduce_synthetic_growth(self):
        self.assertLess(growth(.1,.2,3,.04,.005,.0097)['expected_log_growth'],growth(.1,.2)['expected_log_growth'])
    def test_nonpositive_nav_not_negative_wealth(self):
        x=ideal_path([-.34]);self.assertEqual(x['status'],'THEORETICAL_NAV_NONPOSITIVE');self.assertIsNone(x['return_pct'])
    def test_nav_missing_not_zero_tracking(self):
        self.assertIsNone(tracking([100,101],None)['tracking_diff'])
    def test_positive_tracking_not_always_decay(self):
        self.assertGreater(tracking([100,101],[100,104],True)['tracking_diff'][0],0)
    def test_nan_not_permitted(self):
        with self.assertRaises(ValueError):ideal_path([float('nan')])

class DatasetTests(unittest.TestCase):
    def setUp(self):self.data=fixture();self.p=read_protocol()
    def candles(self):return {s:copy.deepcopy(self.data[s]) for s in m.LEGACY_SYMBOLS}
    def test_internal_gap_blocks(self):
        c=self.candles();c['QQQ'].pop(290)
        with self.assertRaisesRegex(ValueError,'Missing aligned'):from_candles(c,self.data['cutoff'])
    def test_duplicate_blocks(self):
        c=self.candles();c['QQQ'].append(c['QQQ'][-1])
        with self.assertRaisesRegex(ValueError,'duplicate'):from_candles(c,self.data['cutoff'])
    def test_dividend_split_anomaly_quarantined(self):
        c=self.candles();c['TQQQ'][280]['raw_close']*=2
        with self.assertRaisesRegex(ValueError,'Quarantined'):from_candles(c,self.data['cutoff'])
    def test_future_rows_excluded(self):
        c=self.candles();cut=c['QQQ'][-10]['trade_date'];d=from_candles(c,cut)
        self.assertEqual(d['dates'][-1],cut)
    def test_future_price_suffix_cannot_change_features(self):
        c=self.candles();before=features(self.data,self.p)
        for s in m.LEGACY_SYMBOLS:
            for row in c[s][300:]:row['raw_close']*=1.02;row['adjusted_close']*=1.02
        after=features(from_candles(c,self.data['cutoff']),self.p)
        self.assertEqual(before[:300],after[:300])
    def test_rsi_flat_is_neutral(self):self.assertEqual(rsi([100]*20)[-1],50)
    def test_conflicting_duplicates_not_silently_replaced(self):
        with self.assertRaisesRegex(RuntimeError,'Conflicting duplicate'):
            m.validate([{'date':'2025-01-02','adjusted_close':100},{'date':'2025-01-02','adjusted_close':101}])
    def test_protocol_hash_is_frozen(self):
        lock=json.loads((ROOT/'data/research/protocol_lock.json').read_text())
        self.assertEqual(lock['protocol_sha256'],digest(self.p))

class EngineTests(unittest.TestCase):
    def setUp(self):self.data=fixture();self.p=read_protocol();self.fs=features(self.data,self.p)
    def test_next_close_cannot_profit_from_execution_jump(self):
        d=copy.deepcopy(self.data)
        for s in m.LEGACY_SYMBOLS:
            for i,row in enumerate(d[s]):row['adjusted_close']=100 if i<270 else 200
        def rule(name,i,*args):return {'target':weights(1,0) if i==269 else None,'reason':'TEST','risk_budget_infeasible':False}
        with patch('research.engine.decision',side_effect=rule):r=simulate(d,self.fs,self.p,'B_QQQ',0)
        self.assertAlmostEqual(r['curve'][-1],1)
        self.assertEqual(r['trades'][0]['signal_session'],d['dates'][269])
        self.assertEqual(r['trades'][0]['execute_session'],d['dates'][270])
    def test_all_registered_models_nonnegative_self_financing(self):
        for name in self.p['models']:
            r=simulate(self.data,self.fs,self.p,name,15)
            self.assertTrue(all(v>0 for v in r['curve']))
            self.assertTrue(all(x>=-1e-12 and sum(w)<=1+1e-10 for w in r['weights_earning_return'] for x in w))
            self.assertTrue(all(t['signal_session']<t['execute_session'] for t in r['trades']))
    def test_initial_buy_fee_and_exit_fee_both_charged(self):
        def rule(name,i,*args):return {'target':weights(1,0) if i==251 else (weights(0,0) if i==252 else None),'reason':'TEST','risk_budget_infeasible':False}
        d=copy.deepcopy(self.data)
        for s in m.LEGACY_SYMBOLS:
            for row in d[s]:row['adjusted_close']=100
        with patch('research.engine.decision',side_effect=rule):r=simulate(d,self.fs,self.p,'B_QQQ',15)
        self.assertEqual(len(r['trades']),2);self.assertTrue(all(t['fee']>0 for t in r['trades']))
        self.assertAlmostEqual(r['curve'][-1]+sum(t['fee'] for t in r['trades']),1)
    def test_buy_hold_fee_sensitivity(self):
        a=simulate(self.data,self.fs,self.p,'B_QQQ',0);b=simulate(self.data,self.fs,self.p,'B_QQQ',50)
        self.assertGreater(a['curve'][-1],b['curve'][-1])
    def test_execution_halt_is_not_guaranteed_fill(self):
        date=self.data['dates'][252]
        r=simulate(self.data,self.fs,self.p,'B_QQQ',15,[date])
        self.assertEqual(r['summary']['blocked_execution_count'],1)
        self.assertEqual(r['trades'][0]['execute_session'],self.data['dates'][253])
    def test_future_suffix_cannot_rewrite_prior_portfolio(self):
        d=copy.deepcopy(self.data)
        for s in m.LEGACY_SYMBOLS:
            for row in d[s][300:]:row['adjusted_close']*=1.02
        for n in ('M1_TREND_EWMA','M2_COVARIANCE_BUDGET','R_RSI2_SWING','R_VALUE_AVERAGE_STRESS'):
            a=simulate(self.data,self.fs,self.p,n);b=simulate(d,features(d,self.p),self.p,n)
            self.assertEqual(a['curve'][:49],b['curve'][:49])
    def test_budget_infeasibility_is_reported(self):
        f=dict(self.fs[-1]);f.update(qqq_var=1,tqqq_var=9,cov=3)
        farr=list(self.fs);farr[-1]=f
        r=decision('M2_COVARIANCE_BUDGET',len(farr)-1,self.data,farr,[.5,0,.5],{},self.p)
        self.assertTrue(r['risk_budget_infeasible']);self.assertGreaterEqual(r['target']['QQQ'],.5)
    def test_clock_observer_and_research_same_anchor(self):
        i=300;anchor=self.data['dates'][270];elapsed=strategy.elapsed_sessions(self.data['dates'][:i+1],anchor)
        self.assertEqual(elapsed,30)
        self.assertEqual(strategy.targets(self.fs[i],strategy.config(),elapsed),strategy.targets(strategy.indicators(self.data['QQQ'][:i+1]),strategy.config(),elapsed))
    def test_invalid_weights_rejected(self):
        with self.assertRaises(ValueError):weights(.8,.3)
    def test_invalid_external_cost_rejected(self):
        with self.assertRaises(ValueError):simulate(self.data,self.fs,self.p,'B_QQQ',float('nan'))

class WalkForwardTests(unittest.TestCase):
    def test_label_window_cannot_cross_boundary(self):
        dates=fixture()['dates'];boundary=dates[300]
        indices=purged_indices(dates,dates[251],dates[299],boundary,30)
        self.assertTrue(all(dates[i+30]<boundary for i in indices));self.assertNotIn(280,indices)
    def test_unmatured_labels_excluded(self):
        dates=fixture()['dates'];idx=purged_indices(dates,dates[251],dates[-1],'2099-01-01',90)
        self.assertTrue(all(i+90<len(dates) for i in idx))

class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'db.sqlite3';m.init_db(self.db);m.set_portfolio(12000,8000,'2026-10-08',db=self.db)
        data=fixture(500,dt.date(2025,1,2))
        candles={s:[r for r in data[s] if r['trade_date']<='2026-10-13'] for s in m.LEGACY_SYMBOLS}
        data=from_candles(candles,'2026-10-13');self.cutoff=data['dates'][-1]
        for s in m.LEGACY_SYMBOLS:m.ingest(s,[{'date':r['trade_date'],'raw_close':r['raw_close'],'adjusted_close':r['adjusted_close']} for r in data[s]],'YAHOO_QUERY1',db=self.db)
    def tearDown(self):self.tmp.cleanup()
    def report(self):
        now=dt.datetime.combine(dt.date.fromisoformat(self.cutoff),dt.time(23,59),tzinfo=dt.timezone.utc)
        r=m.build_report(now=now,db=self.db);r['mode']='ONLINE_2_OF_2';r['data_evidence_grade']='CURRENT_SINGLE_SOURCE'
        return r
    def test_offline_cannot_generate_new_qualified_signal(self):
        r=self.report();r['mode']='OFFLINE_CACHE';s=shadow.observe(r,m.price_data(self.db))
        self.assertEqual(s['status'],'DATA_GATE_BLOCKED');self.assertIsNone(s['hypothetical_target'])
    def test_conflict_blocks_new_signal(self):
        r=self.report();r['data_evidence_grade']='SOURCE_CONFLICT'
        self.assertEqual(shadow.observe(r,m.price_data(self.db))['status'],'DATA_GATE_BLOCKED')
    def test_no_account_mutation_and_idempotent_signal(self):
        before=m.portfolio(self.db);s=shadow.observe(self.report(),m.price_data(self.db))
        for _ in range(2):shadow.persist(s,self.db)
        self.assertEqual(before,m.portfolio(self.db));self.assertEqual(shadow.audit(self.db)['signals'],1)
        self.assertEqual(s['orders'],[]);self.assertIsNone(s['risk_probability'])
    def test_no_unmatured_outcome(self):
        s=shadow.observe(self.report(),m.price_data(self.db));shadow.persist(s,self.db)
        self.assertEqual(shadow.evaluate(self.db)['new_outcomes'],0)
    def test_signal_timestamp_does_not_create_duplicate(self):
        r=self.report();a=shadow.observe(r,m.price_data(self.db));r['created_at_bjt']='2026-10-15T12:00:00+08:00';b=shadow.observe(r,m.price_data(self.db))
        self.assertEqual(a['signal_id'],b['signal_id'])

if __name__=='__main__':unittest.main()

class NavTests(unittest.TestCase):
    def test_real_issuer_nav_history_arithmetic(self):
        from research.nav_diagnostics import official_nav
        path=ROOT/'data/research/PROSHARES_NAV_HISTORY.raw'
        if not path.exists():self.skipTest('Optional issuer data unavailable')
        nav=official_nav(path)
        self.assertGreater(len(nav['rows']),4000)
        self.assertEqual(nav['rows'][0]['date'],'2010-02-09')
    def test_nav_malformed_rows_rejected(self):
        from research.nav_diagnostics import official_nav
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'nav.csv';path.write_text('Date,Ticker,NAV,Prior NAV,NAV Change (%)\n10/13/2026,TQQQ,78.8,79.5,99\n')
            with self.assertRaises(ValueError):official_nav(path)
