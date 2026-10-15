import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import advisory as a
import advisory_compare as compare
import monitor as m
from research.dataset import from_candles, features
from research.common import read_protocol


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.db = Path(self.tmp.name)/'monitor.sqlite3'
        m.init_db(self.db); m.set_portfolio(12000,8000,'2024-01-02',db=self.db)
        rows = []; day = dt.date(2024,1,2)
        while len(rows) < 310:
            if m.is_regular_session(day):
                price = 100*1.001**len(rows)
                rows.append({'date':day.isoformat(),'raw_close':price,'adjusted_close':price})
            day += dt.timedelta(days=1)
        for symbol in m.SYMBOLS: m.ingest(symbol,rows,'YAHOO_QUERY1',db=self.db)
        self.rows = rows; self.now = dt.datetime.combine(dt.date.fromisoformat(rows[-1]['date']),dt.time(23,59),tzinfo=dt.timezone.utc)

    def tearDown(self): self.tmp.cleanup()

    def report(self):
        with patch('monitor.yahoo_download',return_value=self.rows):
            return m.build_report(now=self.now,online=True,db=self.db)

    def test_uptrend_no_pullback_can_review_entry_and_core(self):
        r = self.report(); s = r['allocation_review']
        self.assertFalse(r['strategy_observation']['scenario_targets']['tqqq_entry_condition_met'])
        self.assertEqual(s['actions'],{'QQQ':'HOLD','TQQQ':'INCREASE_REVIEW'})
        self.assertAlmostEqual(s['next_review_weights']['QQQ'],.6)
        self.assertAlmostEqual(s['next_review_weights']['TQQQ']+s['next_review_weights']['QLD'],.05)
        self.assertFalse(s['legacy_pullback_condition']['blocks_current_advisory'])

    def test_repeat_without_confirmation_does_not_accumulate(self):
        before = m.portfolio(self.db); r = self.report(); m.save_report(r,self.db,Path(self.tmp.name))
        r2 = self.report(); m.save_report(r2,self.db,Path(self.tmp.name))
        self.assertEqual(r['allocation_review']['signal_id'],r2['allocation_review']['signal_id'])
        self.assertAlmostEqual(r2['allocation_review']['next_review_weights']['TQQQ']+r2['allocation_review']['next_review_weights']['QLD'],.05)
        self.assertEqual(m.portfolio(self.db),before)
        self.assertEqual(a.audit(self.db)['reviews'],1)

    def test_confirmed_holding_advances_one_step_and_old_cli_preserves_it(self):
        m.set_portfolio(14000,5000,self.rows[-1]['date'],db=self.db,tqqq=1000)
        s = self.report()['allocation_review']
        self.assertAlmostEqual(s['next_review_weights']['TQQQ']+s['next_review_weights']['QLD'],.1)
        m.set_portfolio(14100,5000,self.rows[-1]['date'],db=self.db)
        self.assertEqual(m.portfolio(self.db)['tqqq_value_cny'],1000)

    def test_trend_exit_overrides_buy_and_retains_core(self):
        x,reason = a.review_weights({'QQQ':.7,'TQQQ':.2,'CASH':.1},False,15,a.config())
        self.assertEqual(reason,'TREND_EXIT'); self.assertEqual(x['TQQQ'],0); self.assertEqual(x['QQQ'],.6)

    def test_volatility_pause_and_exit(self):
        current = {'QQQ':.7,'TQQQ':.1,'CASH':.2}
        x,_ = a.review_weights(current,True,26,a.config()); self.assertEqual(x['TQQQ'],.1)
        x,_ = a.review_weights(current,True,35,a.config()); self.assertEqual(x['TQQQ'],0)

    def test_reference_envelopes_and_no_full_position_jump(self):
        for t in (0,.05,.18,.2,.3,.4,.45):
            x,_ = a.review_weights({'QQQ':.5,'TQQQ':t,'CASH':.5-t},True,15,a.config())
            self.assertLessEqual(x['TQQQ'],.4); self.assertGreaterEqual(x['CASH'],-1e-9)
            self.assertLessEqual(x['QQQ']+3*x['TQQQ'],1.8+1e-9)
            if t<=.4: self.assertLessEqual(x['TQQQ']-t,.05+1e-9)

    def test_stale_account_does_not_hide_signal_or_invent_amounts(self):
        s = self.report()['allocation_review']
        self.assertEqual(s['status'],'ALLOCATION_REVIEW'); self.assertFalse(s['account_valuation_current'])
        self.assertIsNone(s['executable_delta_cny']); self.assertIsNone(s['executable_shares'])

    def test_source_conflict_blocks_new_risk(self):
        r = self.report(); r['strategy_observation']['data_blockers']=['SOURCE_CONFLICT']
        s = a.observe(r,m.price_data(self.db)); self.assertEqual(s['status'],'DATA_BLOCKED')
        self.assertIsNone(s['next_review_weights'])

    def test_offline_is_explicit_replay_not_current_entry(self):
        s = m.build_report(now=self.now,db=self.db)['allocation_review']
        self.assertEqual(s['status'],'CACHE_REPLAY_ONLY')

    def test_data_future_suffix_cannot_change_advisory(self):
        r = self.report(); c = m.price_data(self.db); original = a.observe(r,c)
        for rs in c.values(): rs.append({**rs[-1],'trade_date':'2099-01-02','adjusted_close':1})
        self.assertEqual(original,a.observe(r,c))

    def test_cash_counterfactual_signed_both_directions(self):
        r = self.report(); c = m.price_data(self.db)
        # A deliberately underweight core is needed for this counterfactual.
        r['portfolio']['qqq_value_cny']=10000
        self.assertGreater(a.opportunity_diagnostic(r,c,a.config())['qqq_instead_of_zero_yield_cash_difference_cny'],0)
        c['QQQ'][-1]['adjusted_close'] = c['QQQ'][0]['adjusted_close']*.8
        self.assertLess(a.opportunity_diagnostic(r,c,a.config())['qqq_instead_of_zero_yield_cash_difference_cny'],0)

    def test_source_and_signal_hash_tamper_detected(self):
        r = self.report(); m.save_report(r,self.db,Path(self.tmp.name))
        with m.conn(self.db) as c: c.execute("UPDATE allocation_reviews SET signal_sha256='bad'")
        self.assertEqual(a.audit(self.db)['signal_hash_errors'],1)

    def test_frozen_price_corruption_is_detected(self):
        r = self.report(); m.save_report(r,self.db,Path(self.tmp.name))
        self.assertEqual(a.audit(self.db)['input_hash_errors'],0)
        with m.conn(self.db) as c: c.execute("UPDATE allocation_price_inputs SET compressed_prices=X'0001'")
        self.assertEqual(a.audit(self.db)['input_hash_errors'],1)

    def test_old_zero_only_schema_migration_preserves_every_row(self):
        old = Path(self.tmp.name)/'old.sqlite3'
        with sqlite3.connect(old) as c:
            sql = 'CREATE TABLE portfolio_baselines (id INTEGER PRIMARY KEY AUTOINCREMENT,recorded_at TEXT NOT NULL,as_of TEXT NOT NULL,qqq_value_cny INTEGER NOT NULL CHECK(qqq_value_cny>=0),cash_cny INTEGER NOT NULL CHECK(cash_cny>=0),tqqq_value_cny INTEGER NOT NULL DEFAULT 0 CHECK(tqqq_value_cny=0),detail_level TEXT NOT NULL DEFAULT \'aggregate_value_no_shares\',note TEXT NOT NULL)'
            c.execute(sql); c.execute("INSERT INTO portfolio_baselines VALUES(7,'original','2026-10-08',12000,8000,0,'aggregate_value_no_shares','unchanged')")
        m.init_db(old); baseline = m.portfolio(old)
        self.assertEqual((baseline['id'],baseline['note'],baseline['recorded_at']),(7,'unchanged','original'))
        m.set_portfolio(14000,5000,'2026-10-14',db=old,tqqq=1000)
        self.assertEqual(m.portfolio(old)['id'],8)

    def test_no_gain_from_same_day_signal_jump(self):
        c = m.price_data(self.db)
        for rs in c.values():
            for i,row in enumerate(rs): row['adjusted_close'] = row['raw_close'] = (100 if i<270 else 130)
        data = from_candles(c,self.rows[-1]['date']); fs = features(data,read_protocol())
        result = compare.simulate_review(data,fs,a.config(),0)
        # Core existed before jump; TQQQ trend-entry was not held on the signal jump.
        self.assertAlmostEqual(result['summary']['total_return_pct'],18)


if __name__ == '__main__': unittest.main()
