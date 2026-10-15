import datetime as dt
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import monitor as m

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.db=Path(self.dir.name)/'monitor.sqlite3'
        m.init_db(self.db)
        m.set_portfolio(12000,8000,'2026-10-08',db=self.db)
    def tearDown(self):self.dir.cleanup()
    def rows(self,s=1,n=300):
        today=dt.date(2025,1,1)
        return [{'date':(today+dt.timedelta(days=i)).isoformat(),'adjusted_close':100+i*s,'raw_close':100+i*s} for i in range(n)]
    def test_account_exact(self):
        p=m.portfolio(self.db)
        self.assertEqual((p['qqq_value_cny'],p['cash_cny'],p['tqqq_value_cny']), (12000,8000,0))
    def test_zero_legacy_tables(self):
        a=m.audit(self.db);self.assertFalse(a['legacy_trade_tables_present'])
    def test_cant_create_negative_tqqq_holding(self):
        with m.conn(self.db) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute('INSERT INTO portfolio_baselines(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,note) VALUES(?,?,?,?,?,?)',('x','2026-10-08',1,1,-1,'bad'))
    def test_portfolio_idempotent(self):
        idx=m.set_portfolio(12000,8000,'2026-10-08',db=self.db)
        self.assertEqual(idx,1);self.assertEqual(m.audit(self.db)['baselines'],1)
    def test_portfolio_new_observation_not_trade(self):
        m.set_portfolio(10500,9000,'2026-10-09',db=self.db)
        self.assertEqual(m.audit(self.db)['baselines'],2)
        self.assertEqual(m.portfolio(self.db)['qqq_value_cny'],10500)
    def test_negative_rejected(self):
        with self.assertRaises(ValueError):m.set_portfolio(-1,0,db=self.db)
    def test_bad_symbol_rejected(self):
        with self.assertRaises(ValueError):m.ingest('SPY',self.rows(),'LEGACY_YAHOO_CACHE',db=self.db)
    def test_bad_provider_rejected(self):
        with self.assertRaises(ValueError):m.ingest('QQQ',self.rows(),'FAKE',db=self.db)
    def test_invalid_price_removed(self):
        rows=self.rows(n=5)+[{'date':'2025-01-12','adjusted_close':-2,'raw_close':-3}]
        self.assertEqual(m.ingest('QQQ',rows,'LEGACY_YAHOO_CACHE',db=self.db)['received'],5)
    def test_malformed_date_removed(self):
        rows=self.rows(n=5)+[{'date':'NOT_A_DATE','adjusted_close':200,'raw_close':200}]
        self.assertEqual(m.ingest('QQQ',rows,'LEGACY_YAHOO_CACHE',db=self.db)['received'],5)
    def test_duplicates_deduplicated(self):
        rows=self.rows(n=5);rows.append(rows[0])
        self.assertEqual(m.ingest('QQQ',rows,'LEGACY_YAHOO_CACHE',db=self.db)['received'],5)
    def test_shortened_input_cant_truncate(self):
        m.ingest('QQQ',self.rows(n=100),'LEGACY_YAHOO_CACHE',db=self.db)
        m.ingest('QQQ',self.rows(n=2),'YAHOO_QUERY1',db=self.db)
        self.assertEqual(m.audit(self.db)['price_records']['QQQ'],100)
    def test_cache_does_not_overwrite_live(self):
        rows=self.rows(n=3)
        m.ingest('QQQ',rows,'YAHOO_QUERY1',db=self.db)
        other=[{**r,'adjusted_close':r['adjusted_close']+20} for r in rows]
        m.ingest('QQQ',other,'LEGACY_YAHOO_CACHE',db=self.db)
        self.assertEqual(m.price_data(self.db)['QQQ'][0]['adjusted_close'],100)
    def test_current_metric(self):
        rows=m.validate(self.rows(n=300))
        r=[{'trade_date':x['date'],'adjusted_close':x['adjusted_close'],'raw_close':x['raw_close']} for x in rows]
        a=m.calc_metrics(r,dt.date.fromisoformat(rows[-1]['date']))
        self.assertEqual(a['quality'],'CURRENT')
        self.assertIsNotNone(a['sma_200'])
        self.assertIsNotNone(a['volatility_20d_annualized_pct'])
    def test_stale_signal_cannot_be_current(self):
        r=[{'trade_date':x['date'],'adjusted_close':x['adjusted_close'],'raw_close':x['raw_close']} for x in self.rows(n=300)]
        a=m.calc_metrics(r,dt.date(2026,10,8))
        self.assertEqual(a['quality'],'STALE')
        self.assertFalse(a['signals_actionable'])
    def test_drawdown_rule_trigger(self):
        rows=[{'trade_date':(dt.date(2025,1,1)+dt.timedelta(days=i)).isoformat(),'adjusted_close':100,'raw_close':100} for i in range(252)]
        rows[-1]['adjusted_close']=80;rows[-1]['raw_close']=80
        a=m.calc_metrics(rows,dt.date.fromisoformat(rows[-1]['trade_date']))
        self.assertTrue(any('20%' in s for s in a['signals']))
    def test_empty_data(self):self.assertEqual(m.calc_metrics([],dt.date(2026,10,8))['quality'],'MISSING')
    def test_online_failure_marks_cache_not_live(self):
        now=dt.datetime(2026,10,8,8,tzinfo=dt.timezone.utc)
        r=m.build_report(now=now,online=False,db=self.db)
        self.assertEqual(r['mode'],'OFFLINE_CACHE')
        self.assertEqual(r['data_evidence_grade'],'LIMITED')
    def test_no_autotrading(self):
        r=m.build_report(online=False,db=self.db)
        self.assertFalse(r['trading_enabled'])
        self.assertFalse(r['old_decisions_imported'])
    def test_durable_json_and_report(self):
        r=m.build_report(online=False,db=self.db)
        out=m.save_report(r,self.db,Path(self.dir.name))
        self.assertTrue(Path(out['report_path']).exists())
        self.assertTrue((Path(self.dir.name)/'dashboard.html').exists())
        self.assertEqual(m.audit(self.db)['runs'],1)
        m.save_report(r,self.db,Path(self.dir.name))
        self.assertEqual(m.audit(self.db)['runs'],1)
    def test_holiday_fri_expected_previous(self):
        now=dt.datetime(2026,12,25,21,tzinfo=dt.timezone.utc)
        self.assertEqual(m.expected_close_session(now),dt.date(2026,12,24))
    def test_holiday_2027_mlk(self):
        now=dt.datetime(2027,1,18,23,tzinfo=dt.timezone.utc)
        self.assertEqual(m.expected_close_session(now),dt.date(2027,1,15))
    def test_holiday_2026_july3(self):
        self.assertIn(dt.date(2026,7,3),m.market_holidays(2026))
    def test_good_friday_2026(self):
        self.assertIn(dt.date(2026,4,3),m.market_holidays(2026))
    def test_weekend_expected_date(self):
        now=dt.datetime(2026,10,10,18,tzinfo=dt.timezone.utc)
        self.assertEqual(m.expected_close_session(now),dt.date(2026,10,9))
    def test_preclose_expected_date(self):
        now=dt.datetime(2026,10,8,19,tzinfo=dt.timezone.utc)
        self.assertEqual(m.expected_close_session(now),dt.date(2026,10,7))
    def test_postclose_expected_date(self):
        now=dt.datetime(2026,10,8,23,tzinfo=dt.timezone.utc)
        self.assertEqual(m.expected_close_session(now),dt.date(2026,10,8))
    def test_qqq_weight(self):
        r=m.build_report(online=False,db=self.db)
        self.assertEqual(r['portfolio']['qqq_weight_pct'],60.0)
        self.assertEqual(r['portfolio']['profit_loss'],'UNKNOWN')

if __name__=='__main__':unittest.main()
