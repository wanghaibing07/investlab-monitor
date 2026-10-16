import copy
import json
from dataclasses import replace
from datetime import date
import math
from pathlib import Path
import tempfile
import unittest
from investlab.engine.research.qualified_bars import QualifiedDailyBar,validate,compare_sources,source_failure
from investlab.engine.research.tqqq_risk import features,portfolio_risk,path_metrics,conflict
from investlab.engine.research.risk_challengers import target
from investlab.engine.research.experiment_registry import write_once,digest
from investlab.providers import parse_alpaca_daily_evidence


def bar(session='2026-10-15',**kwargs):
    return QualifiedDailyBar(exchange_session=session,symbol='QQQ',source='A',feed='sip',
                             adjustment='all',raw_close=100.,adjusted_close=100.,
                             retrieved_at='2026-10-16T02:00:00Z',original_payload_sha='a'*64,
                             corporate_actions=(),**kwargs)


class BarContracts(unittest.TestCase):
    def check(self,bars,**kw):return validate(bars,'2026-10-15',lambda d:d.weekday()<5,**kw)
    def test_future_and_weekend_blocked(self):
        for day in ('2026-10-16','2026-10-11'):
            with self.assertRaises(ValueError):self.check([bar(day)])
    def test_duplicate_and_unsorted_blocked(self):
        for seq in ([bar(),bar()],[bar(),bar('2026-10-14')]):
            with self.assertRaises(ValueError):self.check(seq)
    def test_monthly_and_pagination_blocked(self):
        for args in ({'timeframe':'1Month'},{'next_page_token':'more'}):
            with self.assertRaises(ValueError):self.check([bar()],**args)
    def test_missing_session_and_wrong_date_blocked(self):
        with self.assertRaises(ValueError):self.check([bar()],expected_sessions=['2026-10-14','2026-10-15'])
    def test_invalid_prices_blocked(self):
        for v in (0.,-1.,float('nan'),float('inf'),True,None):
            with self.assertRaises(ValueError):self.check([replace(bar(),raw_close=v)])
    def test_iex_does_not_become_consolidated(self):
        r=self.check([replace(bar(),feed='iex')]);self.assertIn('IEX_NOT_CONSOLIDATED_CLOSE',r['limits'])
        self.assertFalse(r['independent_history_verified'])
    def test_source_403_never_upgrades_evidence(self):
        self.assertEqual(source_failure(403)['status'],'SOURCE_UNAVAILABLE')
        self.assertFalse(source_failure(403)['independent_history_verified'])
    def test_unexplained_split_and_jump_blocked(self):
        for raw,adj in ((50,100),(180,180)):
            with self.assertRaises(ValueError):self.check([bar('2026-10-14'),replace(bar(),raw_close=raw,adjusted_close=adj)])
    def test_explained_split_retains_source_contract_only(self):
        b=replace(bar(),raw_close=50,corporate_actions=({'type':'split','ratio':2},))
        r=self.check([bar('2026-10-14'),b]);self.assertFalse(r['independent_history_verified'])
    def test_conflicting_raw_close_blocked_without_overwrite(self):
        a=[bar()];b=[replace(bar(),source='B',raw_close=103)]
        self.assertEqual(compare_sources(a,b)['status'],'DATA_BLOCKED');self.assertEqual(a[0].raw_close,100)
    def test_adjustment_difference_and_incomplete_coverage_not_certified(self):
        a=[bar('2026-10-14'),bar()];b=[replace(bar(),source='B',adjusted_close=98)]
        r=compare_sources(a,b);self.assertFalse(r['coverage_complete']);self.assertFalse(r['adjusted_history_verified'])
    def test_intraday_retrieval_and_missing_timezone_rejected(self):
        for stamp in ('2026-10-15T16:00:00-04:00','2026-10-16T02:00:00'):
            with self.assertRaises(ValueError):self.check([replace(bar(),retrieved_at=stamp)])
    def test_invalid_ohlc_rejected(self):
        with self.assertRaises(ValueError):self.check([replace(bar(),open=99,low=102,high=103)])
    def test_alpaca_raw_never_certifies_adjusted_history(self):
        raw=json.dumps({'bars':{'QQQ':[{'t':'2026-10-15T04:00:00Z','c':100,'o':99,'h':101,'l':98}]}}).encode()
        query={'feed':'sip','adjustment':'raw','timeframe':'1Day'}
        r=parse_alpaca_daily_evidence([(raw,query)],symbol='QQQ',completed_session='2026-10-15',
                    is_session=lambda d:True,feed='sip',adjustment='raw',retrieved_at='2026-10-16T02:00:00Z')
        self.assertIn('ADJUSTED_CLOSE_MISSING',r['qualification']['limits']);self.assertFalse(r['production_grade_changed'])
    def test_alpaca_missing_page_and_wrong_adjustment_rejected(self):
        query={'feed':'sip','adjustment':'raw','timeframe':'1Day'}
        for obj in ({'next_page_token':'more','bars':{}},{'bars':{}}):
            raw=json.dumps(obj).encode()
            with self.assertRaises(ValueError):parse_alpaca_daily_evidence([(raw,query)],symbol='QQQ',completed_session='2026-10-15',
                    is_session=lambda d:True,feed='sip',adjustment='raw',retrieved_at='2026-10-16T02:00:00Z')


class RiskSemantics(unittest.TestCase):
    def setUp(self):
        self.q=[100*1.001**i for i in range(330)];self.t=[50*1.002**i for i in range(330)]
        self.q[-3:]=[self.q[-4]*.99,self.q[-4]*.98,self.q[-4]*.97]
        self.f=features(self.q,self.t)[-1]
        self.par={'fast_vol_floor':.2,'fast_to_slow_ratio':1.5,'portfolio_vol_target':.25}
    def original(self,current,trend,vol,policy):
        w=dict(current);w['TQQQ']=min(.4,w['TQQQ']+.05) if trend and vol<25 else 0.
        w['CASH']=1-w['QQQ']-w['TQQQ'];return w,'ORIGINAL'
    def test_long_on_short_down_conflict(self):
        r=conflict(self.f,{'trend_active':True,'actions':{'TQQQ':'INCREASE_REVIEW'}},'2026-10-08','2026-10-15')
        self.assertTrue(r['risk_conflict']);self.assertFalse(r['execution_ready']);self.assertEqual(r['orders'],[])
    def test_filter_only_pauses_incremental_buys(self):
        f=dict(self.f,vol20=.1);current={'QQQ':.6,'TQQQ':.1,'CASH':.3}
        w,_,_=target('C1_SHORT_TERM_FILTER',current,True,f,{},self.par,self.original)
        self.assertEqual(w['TQQQ'],.1)
        w,_,_=target('C1_SHORT_TERM_FILTER',current,False,f,{},self.par,self.original)
        self.assertEqual(w['TQQQ'],0.)
    def test_rebound_releases_short_filter(self):
        q=self.q+[self.q[-1]*1.06];f=features(q,self.t+[self.t[-1]*1.15])[-1]
        self.assertFalse(f['three_down'])
    def test_high_upward_vol_is_not_short_down(self):
        q=[100.]
        for i in range(330):q.append(q[-1]*(1.08 if i%2 else 1.005))
        f=features(q,q)[-1];self.assertFalse(f['three_down']);self.assertGreater(f['vol5'],.2)
    def test_causal_prefix_and_low_vol_shock(self):
        a=features(self.q,self.t);q=self.q+[self.q[-1]*.8];t=self.t+[self.t[-1]*.4]
        b=features(q,t);self.assertEqual(a,b[:-1]);self.assertGreater(b[-1]['vol5'],a[-1]['vol5'])
    def test_collinear_leverage_variance_and_contributions(self):
        qr=[-.01,.02,-.02,.01]*15;tr=[3*r for r in qr]
        a=portfolio_risk(qr,tr,{'QQQ':.6,'TQQQ':.4});b=portfolio_risk(qr,tr,{'QQQ':1.,'TQQQ':0.})
        self.assertAlmostEqual(a['annual_vol'],1.8*b['annual_vol'])
        self.assertAlmostEqual(sum(a['variance_contribution'].values()),1.)
        self.assertAlmostEqual(a['variance_contribution']['TQQQ'],2/3)
    def test_drawdown_duration_cvar_and_cdar(self):
        r=path_metrics([1.,.9,.8,1.,.9]);self.assertAlmostEqual(r['max_drawdown'],-.2)
        self.assertEqual(r['longest_underwater_sessions'],2);self.assertLess(r['cdar95'],0)
    def test_registration_cannot_overwrite_results(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'evidence.json';write_once(p,{'a':1})
            with self.assertRaises(FileExistsError):write_once(p,{'a':2})
    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):target('FAKE',{},True,self.f,{},self.par,self.original)


if __name__=='__main__':unittest.main()
