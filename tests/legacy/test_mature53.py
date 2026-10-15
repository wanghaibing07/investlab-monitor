import copy
import math
import unittest
from unittest.mock import patch
from research import mature as a


def data(n=360):
    import datetime as dt
    import monitor as m
    dates=[];day=dt.date(2024,1,2)
    while len(dates)<n:
        if m.is_regular_session(day):dates.append(day.isoformat())
        day+=dt.timedelta(days=1)
    prices={s:[100*math.exp(.0003*i+.01*math.sin(i*.3+j)) for i in range(n)] for j,s in enumerate(a.ASSETS)}
    return {'dates':dates,'prices':prices}


class MatureTests(unittest.TestCase):
    def test_equal_risk_not_equal_money(self):
        w=a.equal_risk([[.04,0],[0,.09]])
        self.assertAlmostEqual(w[0],.6);self.assertAlmostEqual(w[1],.4)

    def test_correlated_three_asset_risk_parity(self):
        cov=[[.04,-.005,.004],[-.005,.01,.002],[.004,.002,.0225]];w=a.equal_risk(cov)
        v=a.variance(w,cov);shares=[w[i]*sum(cov[i][j]*w[j] for j in range(3))/v for i in range(3)]
        for s in shares:self.assertAlmostEqual(s,1/3,places=6)

    def test_nonpositive_variance_rejected(self):
        with self.assertRaises(ValueError):a.equal_risk([[0,0],[0,.1]])

    def test_self_financing_costs(self):
        initial=[0,0,0,0,1];w=[.3,.1,.2,.3,.1]
        result,fee,traded=a.rebalance(initial,w,50)
        self.assertAlmostEqual(sum(result)+fee,1);self.assertAlmostEqual(fee,traded*.005)
        self.assertTrue(all(x>=0 for x in result))

    def test_vol_target_cuts_exposure_in_high_vol(self):
        p=a.config();f={'qqq_vol':.6,'cov':[]}
        w=a.target('VOL_TARGET_QQQ',f,p,{},300,False)
        self.assertAlmostEqual(w[0],.2);self.assertAlmostEqual(w[-1],.8)

    def test_tsmom_negative_trend_goes_to_cash(self):
        f={'cov':[],'qqq_vol':.15,'momentum':{'QQQ':-.1}}
        self.assertEqual(a.target('TSMOM12_QQQ',f,a.config(),{},300,True),[0.]*len(a.ASSETS)+[1.])

    def test_mean_reversion_requires_finite_half_life_and_exits_in_ten_sessions(self):
        f={'cov':[],'z':-2.5,'mr_trend_on':True,'ou_half_life':None};p=a.config();state={}
        self.assertEqual(a.target('MR_Z_OU_QQQ',f,p,state,300,False)[0],0)
        f['ou_half_life']=3
        self.assertEqual(a.target('MR_Z_OU_QQQ',f,p,state,300,False)[0],.25)
        self.assertEqual(a.target('MR_Z_OU_QQQ',f,p,state,310,False)[0],0)

    def test_unknown_model_rejected(self):
        with self.assertRaises(ValueError):a.target('TYPO',{'cov':[]},a.config(),{},300,True)

    def test_future_suffix_cannot_change_previous_targets_or_equity(self):
        d=data();p=a.config();fs=a.features(d,p);other=copy.deepcopy(d)
        for s in a.ASSETS:
            for i in range(330,len(other['dates'])):other['prices'][s][i]*=1.1
        changed=a.features(other,p)
        self.assertEqual(fs[:330],changed[:330])
        for name in ('RP_QQQ_TQQQ','VOL_TARGET_QQQ','MR_Z_OU_QQQ','TSMOM12_MULTI','B_FIXED60_40'):
            x=a.simulate(d,fs,p,name,15);y=a.simulate(other,changed,p,name,15)
            self.assertEqual(x['curve'][:78],y['curve'][:78])

    def test_next_close_entry_cannot_capture_that_close_jump(self):
        d=data()
        for s in a.ASSETS:d['prices'][s]=[100 if i<270 else 200 for i in range(len(d['dates']))]
        fs=[{'cov':[]} for _ in d['dates']]
        def rule(name,f,p,state,index,monthly):return [1.,0.,0.] if index==270 else None
        with patch('research.mature.target',side_effect=rule):r=a.simulate(d,fs,a.config(),'TEST',0)
        self.assertAlmostEqual(r['curve'][-1],1)

    def test_macro_explains_sensitivity_without_faking_risk_premia(self):
        d=data();dates=d['dates'];factors=a.config()['macro']['factors']
        obs={s:{day:((100+math.sin(i*.2)) if s=='DTWEXBGS' else 2+math.sin(i*(.2+j*.1))*.1) for i,day in enumerate(dates)} for j,s in enumerate(factors)}
        with patch('research.mature.macro_inputs',return_value=obs):r=a.macro_regression(d,a.config())
        self.assertEqual(r['end'],dates[-1]);self.assertEqual(len(r['beta']),4)
        self.assertIsNone(r['expected_return_from_risk_premia']);self.assertFalse(r['point_in_time_vintages'])

    def test_all_strategies_nonnegative_and_cost_sensitive(self):
        d=data();p=a.config();fs=a.features(d,p)
        for name in p['models']:
            x=a.simulate(d,fs,p,name,15);y=a.simulate(d,fs,p,name,50)
            self.assertTrue(all(v>0 for v in x['curve']))
            self.assertTrue(all(t['signal_session']<t['execute_session'] for t in x['trades']))
            # Constant-weight benchmark permits an exact monotonic cost comparison.
            if name=='B_QQQ90':self.assertGreater(x['curve'][-1],y['curve'][-1])
