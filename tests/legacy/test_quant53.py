import copy
import datetime as dt
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import monitor as m
from research import quant as q
from research.dataset import from_candles
from test_research import fixture


class FormulaAndScenarioTests(unittest.TestCase):
    def test_drift_is_buy_hold_not_daily_rebalance(self):
        result=q.scenario_path([(.1,.3),(-1/11,-3/11)],{'QQQ':.7,'TQQQ':.2,'CASH':.1})
        self.assertAlmostEqual(result['terminal_return'],-.01090909090909)

    def test_loss_can_reach_zero_never_negative(self):
        r=q.scenario_path([(-1.,-1.)],{'QQQ':0.,'TQQQ':1.,'CASH':0.})
        self.assertEqual(r,{'terminal_return':-1.,'max_drawdown':-1.})

    def test_invalid_prices_and_weights_rejected(self):
        for w in ({'QQQ':.8,'TQQQ':.3,'CASH':-.1},{'QQQ':float('nan'),'TQQQ':0,'CASH':0}):
            with self.assertRaises(ValueError):q.scenario_path([],w)
        with self.assertRaises(ValueError):q.scenario_path([(0,-1.1)],{'QQQ':1,'TQQQ':0,'CASH':0})

    def test_joint_paths_preserve_same_asset_samples(self):
        d=fixture();d['TQQQ']=copy.deepcopy(d['QQQ'])
        result=q.paths(d,{'Q':{'QQQ':1.,'TQQQ':0.,'CASH':0.},'T':{'QQQ':0.,'TQQQ':1.,'CASH':0.}},q.config(),count=20)
        self.assertEqual(result['portfolios']['Q']['terminal_return_p05_p50_p95'],result['portfolios']['T']['terminal_return_p05_p50_p95'])
        self.assertEqual(result['paired_comparisons']['T']['terminal_return_difference_p05_p50_p95'],[0.,0.,0.])

    def test_paths_are_deterministic(self):
        d=fixture();w={'P':{'QQQ':.7,'TQQQ':.2,'CASH':.1}}
        self.assertEqual(q.paths(d,w,q.config(),count=12),q.paths(d,w,q.config(),count=12))

    def test_risk_contributions_add_to_one(self):
        r=q.risk_contributions(fixture(),{'QQQ':.7,'TQQQ':.2,'CASH':.1})
        self.assertAlmostEqual(sum(r['variance_contribution_share'].values()),1.)
        self.assertAlmostEqual(r['approximate_single_day_ndx_exposure'],1.3)

    def test_cash_has_zero_model_risk(self):
        r=q.risk_contributions(fixture(),{'QQQ':0.,'TQQQ':0.,'CASH':1.})
        self.assertEqual(r['annual_volatility'],0)

    def test_fx_includes_cross_term(self):
        r=q.fx_sensitivity({'QQQ':1.,'TQQQ':0.,'CASH':0.})
        x=next(x for x in r['grid'] if x['usd_etf_sleeve_return']==.3 and x['usd_cny_change']==-.1)
        self.assertAlmostEqual(x['hypothetical_cny_portfolio_return'],.17)

    def test_small_ticket_cost_hurdle(self):
        r=q.cost_hurdles({'portfolio':{'as_of':'2026-10-08','total_cny':20000},'allocation_review':{'current_baseline_weights':{'QQQ':.6,'TQQQ':0,'CASH':.4},'next_review_weights':{'QQQ':.7,'TQQQ':.05,'CASH':.25}}},q.config())
        ticket=next(x for x in r['tickets'] if x['symbol']=='TQQQ')
        x=next(x for x in ticket['grid'] if x['bps']==15 and x['fixed_cny']==5)
        self.assertAlmostEqual(x['roundtrip_hurdle_on_traded_slice'],.013)


class ForecastTests(unittest.TestCase):
    def test_training_labels_finish_before_origin(self):
        d=fixture(500);p=q.config();rows=q.samples(d,q.design(d),450,p)
        self.assertTrue(rows);self.assertTrue(all(x['end_i']<450 for x in rows))

    def test_changing_future_cannot_change_past_forecast(self):
        d=fixture(500);prefix={**d, 'dates':d['dates'][:450], **{s:d[s][:450] for s in m.SYMBOLS}}
        a=q.forecast(prefix,q.config())
        for s in m.SYMBOLS:
            for r in d[s][450:]:r['adjusted_close']*=3
        prefix2={**d,'dates':d['dates'][:450],**{s:d[s][:450] for s in m.SYMBOLS}}
        self.assertEqual(a,q.forecast(prefix2,q.config()))

    def test_constant_labels_use_finite_base_rate(self):
        p=q.config();rows=[{'x':[1.,0.,1.,0.],'y':0} for _ in range(100)]
        model=q.fit(rows,p);self.assertEqual(model['status'],'BASE_RATE_FALLBACK')
        self.assertGreater(q.predict(model,[1,0,0,0]),0);self.assertLess(q.predict(model,[1,0,0,0]),1)

    def test_batch_has_nonoverlap_and_purged_year_boundary(self):
        d=fixture(1800,dt.date(2010,2,11));r=q.validate_forecast(d,q.config())
        dates=d['dates'];points=r['points']
        self.assertTrue(all(dates.index(b['date'])-dates.index(a['date'])>=20 for a,b in zip(points,points[1:])))
        self.assertTrue(all(f['latest_label_end'] is None or f['latest_label_end']<f['training_cutoff_exclusive'] for f in r['folds']))


class QuantIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Path(self.tmp.name)/'db.sqlite3'
        m.init_db(self.db);m.set_portfolio(12000,8000,'2026-10-08',db=self.db)
        self.data=fixture(340,dt.date(2025,1,2));self.rows=self.data['QQQ']
        for s in m.SYMBOLS:m.ingest(s,[{'date':r['trade_date'],'raw_close':r['raw_close'],'adjusted_close':r['adjusted_close']} for r in self.data[s]],'YAHOO_QUERY1',db=self.db)
        day=dt.date.fromisoformat(self.data['dates'][-1]);self.now=dt.datetime.combine(day,dt.time(23,59),tzinfo=dt.timezone.utc)

    def tearDown(self):self.tmp.cleanup()

    def report(self):
        def download(sym,**kwargs):return [{'date':r['trade_date'],'raw_close':r['raw_close'],'adjusted_close':r['adjusted_close']} for r in self.data[sym]]
        with patch('monitor.yahoo_download',side_effect=download): return m.build_report(now=self.now,online=True,db=self.db)

    def test_daily_online_archive_is_idempotent_and_preserves_account(self):
        before=m.portfolio(self.db);r=self.report();s=r['quant_analysis']
        self.assertEqual(s['status'],'ONLINE_RESEARCH_CONTEXT')
        for _ in range(2):q.persist(s,r['created_at_bjt'],self.db)
        self.assertEqual(q.audit(self.db)['analyses'],1);self.assertEqual(m.portfolio(self.db),before)
        self.assertEqual(s['orders'],[]);self.assertFalse(s['allocation_override'])

    def test_cache_cannot_archive_live_prediction(self):
        r=m.build_report(now=self.now,db=self.db);q.persist(r['quant_analysis'],r['created_at_bjt'],self.db)
        self.assertEqual(r['quant_analysis']['status'],'CACHE_REPLAY_ONLY');self.assertEqual(q.audit(self.db)['analyses'],0)

    def test_conflict_does_not_emit_probabilities(self):
        r=self.report();r['data_evidence_grade']='SOURCE_CONFLICT';s=q.observe(r,m.price_data(self.db))
        self.assertEqual(s['status'],'DATA_BLOCKED');self.assertNotIn('risk_forecast',s)

    def test_only_matured_outcomes_count_and_tamper_detected(self):
        r=self.report();q.persist(r['quant_analysis'],r['created_at_bjt'],self.db)
        self.assertEqual(q.evaluate(self.db,self.data['dates'][-1])['matured_forecasts'],0)
        with m.conn(self.db) as c:c.execute("UPDATE quant53_analyses SET analysis_sha256='bad'")
        self.assertEqual(q.audit(self.db)['analysis_hash_errors'],1)

    def test_full_report_and_audit_expose_quant(self):
        r=self.report();m.save_report(r,self.db,Path(self.tmp.name))
        self.assertNotIn('quant_persistence_error',r)
        self.assertIn('量化模型与路径推演',m.text_report(r));self.assertIn('量化模型与路径推演',m.html_report(r))
        self.assertEqual(m.audit(self.db)['quant53']['analysis_hash_errors'],0)

    def test_matured_downside_forecast_is_scored_once_per_session(self):
        r=self.report();s=r['quant_analysis'];q.persist(s,r['created_at_bjt'],self.db)
        # Keep revisions for evidence, but score the first qualified forecast only.
        revision=copy.deepcopy(s);revision['risk_forecast']['probability']=.99
        revision['analysis_id']='revision';q.persist(revision,r['created_at_bjt']+'1',self.db)
        day=dt.date.fromisoformat(self.data['dates'][-1]);rows=[]
        while len(rows)<20:
            day+=dt.timedelta(days=1)
            if m.is_regular_session(day):
                price=self.data['QQQ'][-1]['adjusted_close']*.85
                rows.append({'date':day.isoformat(),'raw_close':price,'adjusted_close':price})
        m.ingest('QQQ',rows,'YAHOO_QUERY1',db=self.db)
        result=q.evaluate(self.db,rows[-1]['date'])
        self.assertEqual((result['new_outcomes'],result['distinct_forecast_sessions']),(1,1))
        self.assertEqual(q.evaluate(self.db,rows[-1]['date'])['new_outcomes'],0)
        with m.conn(self.db) as c:
            out=__import__('json').loads(c.execute('SELECT outcome_json FROM quant53_outcomes').fetchone()[0])
        self.assertEqual(out['event'],1)
        self.assertAlmostEqual(out['brier'],(s['risk_forecast']['probability']-1)**2)

