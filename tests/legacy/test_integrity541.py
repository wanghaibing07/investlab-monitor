"""Regression cases for observed triad input and independent macro failures."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import monitor as m
from research import mature, quant
from research.common import digest
from research.dataset import from_candles, semantic_content, triad_candles
from test_research import fixture


class TriadInputTests(unittest.TestCase):
    def setUp(self):
        self.data=fixture()
        self.candles={s:copy.deepcopy(self.data[s]) for s in m.SYMBOLS}
        self.cutoff=self.data['cutoff']

    def test_same_input_faults_rejected_for_every_asset_and_consumer(self):
        for symbol in m.SYMBOLS:
            for fault in ('duplicate','unsorted','negative_raw','nonfinite_raw','split_factor','extreme_adjusted','internal_gap','non_session'):
                with self.subTest(symbol=symbol,fault=fault):
                    candles=copy.deepcopy(self.candles);rows=candles[symbol]
                    if fault=='duplicate':rows.append(copy.deepcopy(rows[-1]))
                    elif fault=='unsorted':rows[280],rows[281]=rows[281],rows[280]
                    elif fault=='negative_raw':rows[280]['raw_close']=-1
                    elif fault=='nonfinite_raw':rows[280]['raw_close']=float('nan')
                    elif fault=='split_factor':rows[280]['raw_close']*=2
                    elif fault=='extreme_adjusted':
                        rows[280]['adjusted_close']*=2;rows[280]['raw_close']*=2
                    elif fault=='internal_gap':rows.pop(280)
                    else:
                        weekend=dt.date.fromisoformat(rows[280]['trade_date'])
                        while weekend.weekday()!=5:weekend+=dt.timedelta(days=1)
                        rows.append({**rows[280],'trade_date':weekend.isoformat()});rows.sort(key=lambda r:r['trade_date'])
                    consumers=(triad_candles,) if symbol=='QLD' else (quant.active_data,mature.dataset,triad_candles)
                    for consumer in consumers:
                        with self.assertRaises(ValueError):consumer(candles,self.cutoff)

    def test_qld_must_cover_both_ends_of_existing_history(self):
        for index in (0,-1):
            candles=copy.deepcopy(self.candles);candles['QLD'].pop(index)
            for consumer in (triad_candles,):
                with self.subTest(index=index,consumer=consumer.__name__),self.assertRaisesRegex(ValueError,'QLD_ALIGNED'):
                    consumer(candles,self.cutoff)

    def test_future_faults_do_not_contaminate_observable_history(self):
        cut=self.candles['QQQ'][-3]['trade_date']
        for symbol in m.SYMBOLS:
            self.candles[symbol][-1]['raw_close']=-1
            self.candles[symbol].append(self.candles[symbol][-1])
        self.assertEqual(quant.active_data(self.candles,cut)['dates'][-1],cut)
        self.assertEqual(mature.dataset(self.candles,cut)['dates'][-1],cut)

    def test_legacy_semantic_identity_remains_compatible(self):
        result=from_candles(self.candles,self.cutoff)
        self.assertNotIn('asset_universe',result)
        self.assertEqual(result['data_sha256'],digest(semantic_content(self.data)))

    def test_shared_validation_code_is_in_model_evidence(self):
        for sources in (quant.sources(),mature.sources()):self.assertIn('research/dataset.py',sources)


class MacroIsolationTests(unittest.TestCase):
    def setUp(self):
        self.data=fixture();self.candles={s:self.data[s] for s in m.SYMBOLS}
        self.cutoff=self.data['cutoff'];self.p=mature.config()
        self.obs={s:{d:100+i*.01 for i,d in enumerate(self.data['dates'][-30:])} for s in self.p['macro']['factors']}

    def test_short_macro_sample_still_archives_and_verifies_input(self):
        with patch('research.mature.macro_inputs',return_value=self.obs):
            context=mature.context({'as_of_expected_session':self.cutoff},self.candles)
            self.assertEqual(context['status'],'RESEARCH_CONTEXT')
            self.assertEqual(context['macro']['status'],'DATA_LIMITED')
            self.assertEqual(context['macro']['input_sha256'],digest(self.obs))
            with tempfile.TemporaryDirectory() as folder:
                mature.persist(context,self.candles,Path(folder)/'monitor.sqlite3')
                snapshot=json.loads(next((Path(folder)/'quant53/mature_snapshots').glob('*.json')).read_text())
                self.assertEqual(snapshot['macro'],self.obs)
                self.assertEqual(snapshot['snapshot_sha256'],context['input_snapshot_sha256'])

    def test_missing_macro_still_archives_asset_models(self):
        with patch('research.mature.macro_inputs',side_effect=ValueError('Missing macro series TEST')):
            context=mature.context({'as_of_expected_session':self.cutoff},self.candles)
            self.assertEqual(len(context['current_hypothetical_targets']),len(self.p['models']))
            with tempfile.TemporaryDirectory() as folder:
                mature.persist(context,self.candles,Path(folder)/'monitor.sqlite3')
                snapshot=json.loads(next((Path(folder)/'quant53/mature_snapshots').glob('*.json')).read_text())
                self.assertIsNone(snapshot['macro'])

    def test_macro_change_between_calculation_and_save_is_still_blocked(self):
        with patch('research.mature.macro_inputs',return_value=self.obs):
            context=mature.context({'as_of_expected_session':self.cutoff},self.candles)
        changed=copy.deepcopy(self.obs);changed['DFII10'][self.cutoff]+=1
        with patch('research.mature.macro_inputs',return_value=changed),tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError,'inputs changed'):
                mature.persist(context,self.candles,Path(folder)/'monitor.sqlite3')

    def test_conflicting_quotes_block_new_targets_and_snapshots(self):
        with patch('research.mature.dataset') as loader:
            context=mature.context({'as_of_expected_session':self.cutoff,'data_evidence_grade':'SOURCE_CONFLICT'},self.candles)
        loader.assert_not_called()
        self.assertEqual(context['status'],'DATA_BLOCKED')
        self.assertNotIn('current_hypothetical_targets',context)
        self.assertNotIn('input_snapshot_sha256',context)

    def test_unregistered_risk_parity_name_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError,'Unknown mature model'):
            mature.target('RP_TYPO',{'cov':[]},self.p,{},300,True)
