import copy
import json
import math
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch
import monitor as m
from research import shadow,snapshots
from research.common import read_protocol,code_sources,code_hash,digest
from research.dataset import from_candles,features,semantic_content
from research.policies import decision,portfolio_vol,flexible_target
from research.engine import simulate
import test_research as support
fixture=support.fixture

class IdentityTests(unittest.TestCase):
    def test_fetch_timestamp_not_price_identity(self):
        a=fixture();c={s:copy.deepcopy(a[s]) for s in m.SYMBOLS}
        for rows in c.values():
            for row in rows:row['fetched_at']='2026-10-14T14:00:00+08:00';row['source']='YAHOO_QUERY2'
        b=from_candles(c,a['cutoff'])
        self.assertEqual(a['data_sha256'],b['data_sha256'])
        self.assertNotEqual(a['data_vintage_sha256'],b['data_vintage_sha256'])
    def test_price_revision_changes_identity(self):
        a=fixture();c={s:copy.deepcopy(a[s]) for s in m.SYMBOLS}
        c['QQQ'][-1]['adjusted_close']*=1.0001
        self.assertNotEqual(a['data_sha256'],from_candles(c,a['cutoff'])['data_sha256'])
    def test_config_is_archived_with_source(self):
        sources=code_sources()
        self.assertIn('strategy_config.json',sources);self.assertIn('research/protocol.json',sources)
        self.assertEqual(code_hash(),snapshots.source_hash(sources))

class RiskAndAblationTests(unittest.TestCase):
    def setUp(self):self.p=read_protocol();self.data=fixture();self.fs=features(self.data,self.p)
    def test_trend_only_independent_of_ewma(self):
        idx=len(self.fs)-1;f=self.fs[idx]
        low=copy.deepcopy(self.fs);high=copy.deepcopy(self.fs)
        low[idx]['ewma_vol']=.1;high[idx]['ewma_vol']=.9
        a=decision('M1_TREND_ONLY',idx,self.data,low,[0,0,1],{},self.p)
        b=decision('M1_TREND_ONLY',idx,self.data,high,[0,0,1],{},self.p)
        self.assertEqual(a['target'],b['target'])
    def test_flexible_budget_reduces_qqq_below_legacy_floor(self):
        f=dict(self.fs[-1]);f.update(qqq_var=1.,tqqq_var=9.,cov=3.)
        w=flexible_target(f,.7,.05,self.p)
        self.assertLess(w['QQQ'],.5);self.assertAlmostEqual(portfolio_vol(f,w['QQQ'],w['TQQQ']),.12)
        fs=copy.deepcopy(self.fs);fs[-1]=f
        a=decision('M2_FLEXIBLE_FLOOR_PAPER',len(fs)-1,self.data,fs,[.5,0,.5],{},self.p)
        self.assertFalse(a['risk_budget_infeasible'])
        b=decision('M2_COVARIANCE_BUDGET',len(fs)-1,self.data,fs,[.5,0,.5],{},self.p)
        self.assertTrue(b['risk_budget_infeasible']);self.assertGreaterEqual(b['target']['QQQ'],.5)
    def test_matched_comparator_has_same_forecast_risk_at_signal(self):
        i=len(self.fs)-1
        a=decision('M2_FLEXIBLE_FLOOR_PAPER',i,self.data,self.fs,[0,0,1],{},self.p)['target']
        b=decision('B_MATCHED_COV_VOL_PAPER',i,self.data,self.fs,[0,0,1],{},self.p)['target']
        self.assertAlmostEqual(portfolio_vol(self.fs[i],a['QQQ'],a['TQQQ']),portfolio_vol(self.fs[i],b['QQQ'],0))
    def test_unknown_model_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unregistered'):
            simulate(self.data,self.fs,self.p,'TYPO_MODEL')
    def test_swing_timeout_accounts_for_next_close_delay(self):
        i=len(self.fs)-1;fs=copy.deepcopy(self.fs)
        fs[i].update(close=150,sma200=100,prior_high5=200,rsi2=50)
        state={'initialized':True,'entry_index':i-7,'t_entry':100}
        d=decision('R_RSI2_SWING',i,self.data,fs,[.7,.05,.25],state,self.p)
        self.assertEqual(d['target']['TQQQ'],0)
    def test_all_flexible_targets_meet_budget(self):
        for var in (.01,.04,.16,.64,1.):
            f={'qqq_var':var,'tqqq_var':9*var,'cov':2.9*var}
            w=flexible_target(f,.7,.05,self.p)
            self.assertLessEqual(portfolio_vol(f,w['QQQ'],w['TQQQ']),.12+1e-12)
            self.assertAlmostEqual(sum(w.values()),1)

class PersistentEvidenceTests(unittest.TestCase):
    setUp=support.ShadowTests.setUp
    tearDown=support.ShadowTests.tearDown
    report=support.ShadowTests.report
    # Shared fixture provides a completed 2026-10-13 session and a user-confirmed account.
    def test_redownload_same_prices_does_not_duplicate_signal(self):
        a=shadow.observe(self.report(),m.price_data(self.db));shadow.persist(a,self.db)
        with m.conn(self.db) as c:c.execute("UPDATE daily_prices SET fetched_at='2026-10-14T15:00:00+08:00'")
        report=self.report();report['created_at_bjt']='2026-10-14T15:01:00+08:00'
        b=shadow.observe(report,m.price_data(self.db));shadow.persist(b,self.db)
        self.assertEqual(a['signal_id'],b['signal_id']);self.assertNotEqual(a['data_vintage_sha256'],b['data_vintage_sha256'])
        audit=shadow.audit(self.db)
        self.assertEqual(audit['signals'],1);self.assertEqual(audit['observation_attempts'],2)
        self.assertEqual(audit['signals_without_frozen_input_snapshot'],0)
    def test_input_snapshot_replays_exact_prices(self):
        a=shadow.observe(self.report(),m.price_data(self.db));shadow.persist(a,self.db)
        with m.conn(self.db) as c:
            frozen=snapshots.read(c,a['data_sha256'])
            c.execute('UPDATE daily_prices SET adjusted_close=adjusted_close*1.0001')
            self.assertEqual(digest(frozen),a['data_sha256'])
        self.assertNotEqual(digest(semantic_content(from_candles(m.price_data(self.db),self.cutoff))),a['data_sha256'])
    def test_corrupted_snapshot_detected(self):
        a=shadow.observe(self.report(),m.price_data(self.db));shadow.persist(a,self.db)
        with m.conn(self.db) as c:c.execute("UPDATE research_data_snapshots SET dataset_zlib=x'010203'")
        self.assertEqual(shadow.audit(self.db)['dataset_hash_errors'],1)
        with self.assertRaises(ValueError):shadow.evaluate(self.db)
    def test_corrupted_source_detected(self):
        a=shadow.observe(self.report(),m.price_data(self.db));shadow.persist(a,self.db)
        with m.conn(self.db) as c:c.execute("UPDATE research_model_versions SET source_json='{}'")
        self.assertEqual(shadow.audit(self.db)['model_hash_errors'],1)
        with self.assertRaises(ValueError):shadow.evaluate(self.db)
    def test_core_report_survives_research_persistence_failure(self):
        report=self.report();report['research_shadow']=shadow.observe(report,m.price_data(self.db))
        with patch('research.shadow.persist',side_effect=ValueError('FAULT_INJECTION')):
            saved=m.save_report(report,self.db,Path(self.tmp.name)/'out')
        self.assertIn('research_persistence_error',report)
        self.assertTrue(Path(saved['report_path']).exists())
        self.assertEqual(m.audit(self.db)['runs'],1)
    def test_dashboard_explains_plan_budget(self):
        report=self.report();report['research_shadow']=shadow.observe(report,m.price_data(self.db))
        html=m.html_report(report);text=m.text_report(report)
        self.assertIn('QQQ 60%、TQQQ 40%',html)
        self.assertIn('量化模型与路径推演',html)
        self.assertIn('今日：',text)
        self.assertNotIn('INCREASE_REVIEW',text)

if __name__=='__main__':unittest.main()

class DecisionRevisionTests(unittest.TestCase):
    def test_micro_revision_retains_same_decision_identity(self):
        # Exact price evidence changes; the risk/allocation decision remains the same.
        cfg=read_protocol()
        signal={'status':'SHADOW_RESEARCH_OBSERVATION','session_date':'2026-10-13',
                'model_sha256':'model','protocol_sha256':'protocol','risk_level':'NORMAL',
                'direction_regime':'TREND_ON','quality':'CURRENT_SINGLE_PROVIDER_ADJUSTED',
                'hypothetical_target':{'QQQ':.7,'TQQQ':.05,'CASH':.25},
                'flexible_floor_paper_target':{'QQQ':.55789729,'TQQQ':.039849806,'CASH':.402252904},
                'data_sha256':'vintage_a','data_vintage_sha256':'fetch_a',
                'proposed_plan_risk':{'exceeds_paper_vol_budget':True,'existing_rule_violations':['EXPOSURE']}}
        revised=copy.deepcopy(signal);revised['data_sha256']='vintage_b';revised['data_vintage_sha256']='fetch_b';revised['flexible_floor_paper_target']['QQQ']+=.0000001
        self.assertEqual(shadow.decision_identity(signal,cfg),shadow.decision_identity(revised,cfg))
        revised['risk_level']='HIGH'
        self.assertNotEqual(shadow.decision_identity(signal,cfg),shadow.decision_identity(revised,cfg))

class PersistedMicroRevisionTests(unittest.TestCase):
    setUp=support.ShadowTests.setUp
    tearDown=support.ShadowTests.tearDown
    report=support.ShadowTests.report
    def test_micro_price_revision_keeps_signal_and_both_snapshots(self):
        a=shadow.observe(self.report(),m.price_data(self.db));shadow.persist(a,self.db)
        with m.conn(self.db) as c:c.execute('UPDATE daily_prices SET adjusted_close=adjusted_close*1.0000001')
        report=self.report();report['created_at_bjt']='2026-10-14T15:02:00+08:00'
        b=shadow.observe(report,m.price_data(self.db));shadow.persist(b,self.db)
        self.assertNotEqual(a['data_sha256'],b['data_sha256']);self.assertEqual(a['signal_id'],b['signal_id'])
        with m.conn(self.db) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_shadow_signals').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_data_snapshots').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM research_shadow_observations').fetchone()[0],2)
            c.execute('UPDATE research_data_snapshots SET dataset_zlib=? WHERE data_sha256=?',(b'bad',b['data_sha256']))
        self.assertEqual(shadow.audit(self.db)['dataset_hash_errors'],1)
