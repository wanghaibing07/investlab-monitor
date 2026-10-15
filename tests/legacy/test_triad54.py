import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import monitor as m
import advisory as a
from research import quant,mature
from test_research import fixture


class TriadTests(unittest.TestCase):
    def test_asset_whitelist_and_collectors(self):
        self.assertEqual(m.SYMBOLS,('QQQ','QLD','TQQQ'))
        self.assertEqual(mature.ASSETS,m.ACTIVE_SYMBOLS)
        self.assertEqual(mature.config()['asset_universe'],list(m.ACTIVE_SYMBOLS))
        self.assertFalse({'TLT','GLD'} & set(mature.ASSETS))

    def test_three_asset_daily_exposure_and_variance_shares(self):
        d=fixture();w={'QQQ':.5,'QLD':.25,'TQQQ':.1,'CASH':.15}
        out=quant.risk_contributions(d,w)
        self.assertAlmostEqual(out['approximate_single_day_ndx_exposure'],1.3)
        self.assertAlmostEqual(sum(out['variance_contribution_share'].values()),1.)

    def test_joint_path_maps_2x_asset_correctly(self):
        w={'QQQ':.5,'QLD':.25,'TQQQ':.15,'CASH':.1}
        self.assertAlmostEqual(quant.scenario_path([(.1,.2,.3)],w)['terminal_return'],.145)
        with self.assertRaises(ValueError):quant.scenario_path([(.1,.3)],w)

    def test_shared_tactical_step_and_model_weight_labels(self):
        d=fixture();candles={s:d[s] for s in m.SYMBOLS};p=a.config()
        ref=a.full_reference(candles,p,d['dates'][-1])
        current={'QQQ':.6,'QLD':0.,'TQQQ':0.,'CASH':.4}
        out,_=a.review_weights(current,True,15,p,ref)
        self.assertAlmostEqual(out['QLD']+out['TQQQ'],.05)
        self.assertEqual(out['QLD'],0);self.assertGreater(out['TQQQ'],0)
        self.assertAlmostEqual(sum(out.values()),1.)
        self.assertIn('USER_CONFIRMED_TARGET',p['allocation_source'])

    def test_future_qld_prices_cannot_rewrite_reference(self):
        d=fixture();candles={s:copy.deepcopy(d[s]) for s in m.SYMBOLS};p=a.config();cut=d['dates'][-1]
        before=a.full_reference(candles,p,cut)
        candles['QLD'].append({**candles['QLD'][-1],'trade_date':'2099-01-02','adjusted_close':1})
        self.assertEqual(before,a.full_reference(candles,p,cut))

    def test_qld_confirmed_value_preserved_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'x.sqlite3';m.init_db(db)
            m.set_portfolio(10000,6000,'2026-10-08',db=db,qld=2000,tqqq=2000)
            m.set_portfolio(10500,6000,'2026-10-09',db=db)
            self.assertEqual(m.portfolio(db)['qld_value_cny'],2000)
            with self.assertRaises(ValueError):m.set_portfolio(0,0,db=db,qld=-1)

    def test_old_price_constraints_migrate_without_data_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'x.sqlite3'
            with sqlite3.connect(db) as c:
                c.execute("CREATE TABLE daily_prices(symbol TEXT CHECK(symbol IN ('QQQ','TQQQ')),trade_date TEXT,adjusted_close REAL,raw_close REAL,source TEXT,fetched_at TEXT,PRIMARY KEY(symbol,trade_date))")
                c.execute("INSERT INTO daily_prices VALUES('QQQ','2026-10-08',100,100,'YAHOO_QUERY1','old')")
            m.init_db(db)
            m.ingest('QLD',[{'date':'2026-10-08','adjusted_close':200,'raw_close':200}],'YAHOO_QUERY1',db=db)
            self.assertEqual(m.price_data(db)['QQQ'][0]['adjusted_close'],100)
            self.assertEqual(m.price_data(db)['QLD'][0]['adjusted_close'],200)

