import math
import random
import unittest
from investlab.verification import piecewise_rebalance, replay_trade_schedule, historical_folds


class VerificationTests(unittest.TestCase):
    def test_hand_calculated_full_entry_fee(self):
        values,fee=piecewise_rebalance([0,0,1],[.6,.4,0],50)
        self.assertAlmostEqual(sum(values),1/1.005)
        self.assertAlmostEqual(fee,1-1/1.005)

    def test_random_portfolios_conserve_cash_with_independent_solver(self):
        rng=random.Random(42)
        for _ in range(1000):
            values=[rng.random()*1000 for _ in range(3)]
            raw=[rng.random() for _ in range(3)];weights=[x/sum(raw) for x in raw];bps=rng.choice([0,15,50,100])
            result,fee=piecewise_rebalance(values,weights,bps)
            traded=sum(abs(a-b) for a,b in zip(result[:2],values[:2]))
            self.assertAlmostEqual(sum(result)+fee,sum(values),places=9)
            self.assertAlmostEqual(fee,traded*bps/10000,places=9)
            self.assertGreaterEqual(min(result),0)

    def test_execution_jump_does_not_profit_new_position(self):
        data={'dates':['2026-01-02','2026-01-05','2026-01-06'],'prices':{'QQQ':[100,200,220],'TQQQ':[100,200,220]}}
        schedule={'dates':data['dates'],'trades':[{'signal_session':'2026-01-02','execute_session':'2026-01-05','target':{'QQQ':1,'TQQQ':0,'CASH':0}}]}
        self.assertEqual(replay_trade_schedule(data,schedule,0),[1,1,1.1])

    def test_same_session_signal_rejected(self):
        data={'dates':['a','b'],'prices':{'QQQ':[1,2],'TQQQ':[1,2]}}
        schedule={'dates':['a','b'],'trades':[{'signal_session':'b','execute_session':'b','target':{'QQQ':1,'TQQQ':0,'CASH':0}}]}
        with self.assertRaises(ValueError):replay_trade_schedule(data,schedule,0)

    def test_folds_mark_seen_history(self):
        r={'curve':[1,1.2,.9,1.1],'dates':['a','b','c','d']}
        folds=historical_folds(r,2)
        self.assertEqual(folds[0]['sessions'],2)
        self.assertAlmostEqual(folds[0]['max_drawdown_pct'],-25)
        self.assertIn('ALREADY_SEEN',folds[0]['evidence'])
