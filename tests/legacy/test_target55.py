import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import advisory
import daily_summary
import monitor as m
from research import mature,quant
from test_research import fixture


class Target6040Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'monitor.sqlite3';m.init_db(self.db)
        m.set_portfolio(12000,8000,'2026-10-08',db=self.db)
        self.data=fixture(340,dt.date(2025,1,2))
        for symbol in m.ACTIVE_SYMBOLS:
            m.ingest(symbol,self.rows(symbol),'YAHOO_QUERY1',db=self.db)
        day=dt.date.fromisoformat(self.data['dates'][-1]);self.now=dt.datetime.combine(day,dt.time(23,59),tzinfo=dt.timezone.utc)

    def rows(self,symbol):
        return [{'date':r['trade_date'],'raw_close':r['raw_close'],'adjusted_close':r['adjusted_close']} for r in self.data[symbol]]

    def report(self):
        def download(symbol,**kwargs):return self.rows(symbol)
        with patch('monitor.yahoo_download',side_effect=download) as download:
            result=m.build_report(now=self.now,online=True,db=self.db)
        self.assertEqual({c.args[0] for c in download.call_args_list},{'QQQ','TQQQ'})
        return result

    def test_target_is_user_confirmed_and_not_a_trade(self):
        before=m.portfolio(self.db);r=self.report();review=r['allocation_review']
        self.assertEqual(review['strategic_reference'],{'QQQ':.6,'QLD':0.,'TQQQ':.4,'CASH':0.})
        self.assertIn('USER_CONFIRMED_TARGET',review['allocation_source'])
        m.save_report(r,self.db,Path(self.tmp.name)/'output')
        self.assertEqual(before,m.portfolio(self.db));self.assertEqual(review['orders'],[])

    def test_empty_qld_history_does_not_block_any_current_module(self):
        self.assertEqual(m.price_data(self.db)['QLD'],[])
        r=self.report();self.assertEqual(r['mode'],'ONLINE_2_OF_2')
        self.assertEqual(set(r['market']),{'QQQ','TQQQ'})
        self.assertEqual(r['allocation_review']['status'],'ALLOCATION_REVIEW')
        self.assertEqual(r['quant_analysis']['status'],'ONLINE_RESEARCH_CONTEXT')
        self.assertEqual(r['mature_models']['status'],'RESEARCH_CONTEXT')
        for weights in r['mature_models']['current_hypothetical_targets'].values():
            self.assertEqual(set(weights),{'QQQ','TQQQ','CASH'})

    def test_full_target_is_not_clipped_by_old_cash_or_exposure_limits(self):
        current={'QQQ':.6,'QLD':0.,'TQQQ':.4,'CASH':0.}
        result,_=advisory.review_weights(current,True,15,advisory.config())
        for key in current:self.assertAlmostEqual(result[key],current[key])
        self.assertAlmostEqual(result['QQQ']+3*result['TQQQ'],1.8)

    def test_staged_additions_and_risk_exits_still_apply(self):
        current={'QQQ':.6,'QLD':0.,'TQQQ':0.,'CASH':.4};p=advisory.config()
        result,_=advisory.review_weights(current,True,15,p)
        self.assertAlmostEqual(result['TQQQ'],.05);self.assertAlmostEqual(result['CASH'],.35)
        for trend,vol in ((False,15),(True,35)):
            result,_=advisory.review_weights({'QQQ':.6,'QLD':0.,'TQQQ':.4,'CASH':0.},trend,vol,p)
            self.assertEqual(result['TQQQ'],0.)

    def test_notification_starts_with_action_and_explains_partial_acceptance(self):
        r=self.report();health={'continuity':{'consecutive_verified_distinct_sessions_after_readback':3}}
        text=daily_summary.build_summary(r,health,saved=True)
        self.assertTrue(text.startswith('今日：QQQ维持；TQQQ分批增加至5%'))
        for expected in ('QQQ 60%、TQQQ 40%','稳定性观察3/5','备用行情核对','已保存并核对'):
            self.assertIn(expected,text)
        for jargon in ('INCREASE_REVIEW','ONLINE_2_OF_2','CURRENT_SINGLE_SOURCE','已全部完成','QLD'):
            self.assertNotIn(jargon,text)
        self.assertLess(len(text),300)

    def test_offline_or_conflicting_data_cannot_look_like_new_buy_signal(self):
        r=self.report()
        for status,grade in (('CACHE_REPLAY_ONLY','LIMITED'),('DATA_BLOCKED','SOURCE_CONFLICT')):
            other=copy.deepcopy(r);other['allocation_review']['status']=status;other['data_evidence_grade']=grade
            text=daily_summary.build_summary(other)
            self.assertNotIn('分批增加至',text);self.assertNotIn('文件：已保存',text)

    def test_6040_paths_and_risk_use_full_target(self):
        r=self.report();w=quant.portfolios_for(r)['FULL_TARGET_REFERENCE']
        self.assertEqual(w['TQQQ'],.4);self.assertEqual(w['QQQ'],.6)
        self.assertAlmostEqual(quant.scenario_path([(-.05,-.15)],w)['terminal_return'],-.09)
        risk=r['quant_analysis']['risk_contributions']['FULL_TARGET_REFERENCE']
        self.assertAlmostEqual(risk['approximate_single_day_ndx_exposure'],1.8)

    def test_short_notification_does_not_hide_partial_model_failure(self):
        r=self.report();r['mature_persistence_error']='FAULT_INJECTION'
        text=daily_summary.build_summary(r)
        self.assertIn('成熟模型记录未保存',text)
        self.assertNotIn('FAULT_INJECTION',text)
        self.assertNotIn('已全部完成',text)

    def test_fixed_6040_benchmark_enters_at_next_close(self):
        p=mature.config();self.assertEqual(mature.target('B_FIXED60_40',{'cov':[]},p,{},300,True),[.6,.4,0.])
        d={'dates':self.data['dates'],'prices':{s:[r['adjusted_close'] for r in self.data[s]] for s in m.ACTIVE_SYMBOLS}}
        f=mature.features(d,p);result=mature.simulate(d,f,p,'B_FIXED60_40',15)
        self.assertTrue(all(t['signal_session']<t['execute_session'] for t in result['trades']))
        self.assertEqual(result['trades'][0]['target'],{'QQQ':.6,'TQQQ':.4,'CASH':0.})
