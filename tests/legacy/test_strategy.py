import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import monitor as m
import strategy as s


def sessions(n=310):
    day=dt.date(2024,1,2);out=[]
    while len(out)<n:
        if m.is_regular_session(day):
            price=100*(1.001**len(out))
            out.append({'date':day.isoformat(),'raw_close':price,'adjusted_close':price})
        day+=dt.timedelta(days=1)
    return out


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'db.sqlite3'
        m.init_db(self.db);m.set_portfolio(12000,8000,'2024-01-02',db=self.db)
        self.rows=sessions()
        for symbol in m.SYMBOLS:m.ingest(symbol,self.rows,'YAHOO_QUERY1',db=self.db)
        date=dt.date.fromisoformat(self.rows[-1]['date'])
        self.now=dt.datetime.combine(date,dt.time(23,59),tzinfo=dt.timezone.utc)
    def tearDown(self):self.temp.cleanup()
    def report(self,now=None):return m.build_report(now=now or self.now,db=self.db)
    def test_complete_data_observed_no_orders(self):
        signal=self.report()['strategy_observation']
        self.assertEqual(signal['status'],'RESEARCH_OBSERVATION_ONLY')
        self.assertEqual(signal['orders'],[])
        self.assertIsNone(signal['executable_delta_cny'])
        self.assertEqual(signal['tqqq_scope'],'MONITOR_ONLY')
    def test_stale_blocks_targets(self):
        signal=self.report(self.now+dt.timedelta(days=7))['strategy_observation']
        self.assertEqual(signal['status'],'DATA_GATE_BLOCKED')
        self.assertIsNone(signal['scenario_targets'])
    def test_internal_history_gap_blocks(self):
        with m.conn(self.db) as c:c.execute('DELETE FROM daily_prices WHERE symbol=? AND trade_date=?',('QQQ',self.rows[-80]['date']))
        self.assertTrue(any('MISSING_SESSION' in r for r in self.report()['strategy_observation']['data_blockers']))
    def test_web_raw_cannot_fill_adjusted_history_gap(self):
        with m.conn(self.db) as c:c.execute('DELETE FROM daily_prices WHERE trade_date=?',(self.rows[-1]['date'],))
        self.assertEqual(self.report()['strategy_observation']['status'],'DATA_GATE_BLOCKED')
    def test_source_conflict_blocks(self):
        report=self.report();report['data_evidence_grade']='SOURCE_CONFLICT'
        self.assertIsNone(s.observe(report,m.price_data(self.db))['scenario_targets'])
    def test_intraday_never_updates_yahoo_history(self):
        ts=int(dt.datetime(2026,10,12,14,tzinfo=dt.timezone.utc).timestamp())
        body={'chart':{'result':[{'timestamp':[ts-3*86400,ts],
              'indicators':{'quote':[{'close':[100,110]}],'adjclose':[{'adjclose':[100,110]}]}}]}}
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps(body).encode()
        with patch('urllib.request.urlopen',return_value=Response()):
            rows=m.yahoo_download('QQQ',now=dt.datetime(2026,10,12,19,tzinfo=dt.timezone.utc))
        self.assertEqual([r['date'] for r in rows],['2026-10-09'])
    def test_clock_anchored_to_portfolio_not_run(self):
        x=self.report()['strategy_observation'];y=self.report(self.now+dt.timedelta(minutes=1))['strategy_observation']
        self.assertEqual(x['time_deployment_elapsed_sessions'],y['time_deployment_elapsed_sessions'])
        self.assertEqual(x['signal_id'],y['signal_id'])
    def test_crisis_overrides_buy_dip(self):
        metrics=s.indicators(m.price_data(self.db)['QQQ']);metrics['drawdown252_pct']=-30
        target=s.targets(metrics,s.config(),200)
        self.assertEqual(target['regime'],'CRISIS');self.assertEqual(target['qqq'],.5);self.assertEqual(target['tqqq'],0)
    def test_risk_constraints(self):
        metrics=s.indicators(m.price_data(self.db)['QQQ'])
        metrics.update(drawdown252_pct=-11,vol20_pct=20,two_closes_above_sma20=True)
        target=s.targets(metrics,s.config(),0)
        self.assertGreaterEqual(target['cash'],.15-1e-12)
        self.assertLessEqual(target['qqq']+3*target['tqqq'],1+1e-12)
    def test_signal_save_idempotent(self):
        report=self.report()
        for _ in range(2):m.save_report(report,self.db,Path(self.temp.name))
        with m.conn(self.db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM strategy_signals').fetchone()[0],1)
    def test_outcomes_not_due_no_fake_result(self):
        report=self.report();m.save_report(report,self.db,Path(self.temp.name))
        self.assertEqual(s.evaluate(self.db)['new_outcomes'],0)
    def test_forward_outcome_uses_trading_days(self):
        date=dt.date.fromisoformat(self.rows[-31]['date'])
        now=dt.datetime.combine(date,dt.time(23,59),tzinfo=dt.timezone.utc)
        report=self.report(now);m.save_report(report,self.db,Path(self.temp.name));s.evaluate(self.db)
        with m.conn(self.db) as c:
            r=c.execute('SELECT * FROM signal_outcomes WHERE horizon_sessions=7').fetchone()
            self.assertEqual(r['end_session'],self.rows[-24]['date'])
            self.assertAlmostEqual(json.loads(r['outcome_json'])['QQQ']['forward_return_pct'],(1.001**7-1)*100)
    def test_filter_cannot_profit_from_signal_day_price_jump(self):
        rows=copy.deepcopy(self.rows)
        for i,row in enumerate(rows):
            row['adjusted_close']=row['raw_close']=100-i*.01 if i<270 else 200
        for symbol in m.SYMBOLS:m.ingest(symbol,rows,'YAHOO_QUERY1',db=self.db)
        result=s.backtest(self.db,0)
        self.assertAlmostEqual(result['results']['QQQ_SMA200_FILTER']['total_return_pct'],0)
        self.assertGreater(result['results']['QQQ_BUY_HOLD']['total_return_pct'],100)
    def test_rebalance_cost_accounting(self):
        values,fee,traded=s.rebalance([.6,0,.4],.8,0,.0015)
        self.assertAlmostEqual(sum(values)+fee,1)
        self.assertAlmostEqual(values[0]/sum(values),.8)
        self.assertGreater(values[-1],0)
    def test_backtest_cost_monotonic_buy_hold(self):
        a=s.backtest(self.db,0);b=s.backtest(self.db,15)
        self.assertGreater(a['results']['QQQ_BUY_HOLD']['total_return_pct'],b['results']['QQQ_BUY_HOLD']['total_return_pct'])
        self.assertEqual(a['evaluation_sessions'],58)
    def test_emergency_closure_calendar(self):
        for date in ('2012-10-29','2012-10-30','2018-12-05','2025-01-09'):
            self.assertFalse(m.is_regular_session(dt.date.fromisoformat(date)))
    def test_monthly_bars_cannot_be_imported_as_daily(self):
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'chart':{'result':[{'meta':{'dataGranularity':'1mo'}}]}}).encode()
        with patch('urllib.request.urlopen',return_value=Response()):
            with self.assertRaisesRegex(ValueError,'Expected daily bars'):m.yahoo_download('QQQ')
    def test_strategy_change_changes_signal_identity(self):
        report=self.report();old=report['strategy_observation']['signal_id'];cfg=copy.deepcopy(s.config())
        cfg['qqq']['neutral_target']=.66
        with patch('strategy.config',return_value=cfg):
            self.assertNotEqual(old,s.observe(report,m.price_data(self.db))['signal_id'])
    def test_only_confirmation_updates_account(self):
        before=m.portfolio(self.db)
        s.backtest(self.db);m.save_report(self.report(),self.db,Path(self.temp.name))
        self.assertEqual(before,m.portfolio(self.db))
    def test_backup_restores_real_state(self):
        report=self.report();result=m.save_report(report,self.db,Path(self.temp.name))
        backup=Path(result['database_backup'])
        self.assertEqual(m.portfolio(backup),m.portfolio(self.db))
        self.assertEqual(m.audit(backup)['strategy_records'],m.audit(self.db)['strategy_records'])
        self.assertEqual(m.audit(backup)['run_hash_errors'],0)
    def test_audit_detects_tampered_run(self):
        report=self.report();m.save_report(report,self.db,Path(self.temp.name))
        with m.conn(self.db) as c:c.execute("UPDATE monitor_runs SET report_sha256='bad'")
        self.assertEqual(m.audit(self.db)['run_hash_errors'],1)


if __name__=='__main__':unittest.main()
