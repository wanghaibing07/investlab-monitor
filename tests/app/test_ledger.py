from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import sqlite3
import tempfile
import unittest
from investlab import ledger, service
from investlab.core import connection


def event(i, kind, **kwargs):
    return dict(event_id=f'e-{i:03}', account='broker', occurred_at=f'2026-10-01T10:{i:02}:00+00:00',
                kind=kind, currency='USD', confirmed=True, **kwargs)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name); service.init(self.home)

    def test_exact_cash_and_average_cost(self):
        rows=[event(1,'DEPOSIT',amount='1000'),event(2,'BUY',symbol='QQQ',quantity='2',price='100',fee='1'),
              event(3,'BUY',symbol='QQQ',quantity='2',price='200',fee='1'),event(4,'SELL',symbol='QQQ',quantity='1',price='180',fee='1')]
        ledger.import_events(self.home,rows)
        a=ledger.account(self.home,'broker')
        self.assertEqual(a['cash']['USD'],'577')
        self.assertEqual(a['positions'][0]['quantity'],'3')
        self.assertEqual(a['positions'][0]['cost_basis'],'451.5')
        self.assertEqual(a['realized_pnl']['USD'],'28.5')

    def test_duplicate_import_does_not_double_money(self):
        row=event(1,'DEPOSIT',amount='0.10')
        ledger.import_events(self.home,[row]); result=ledger.import_events(self.home,[row])
        self.assertEqual(result['inserted'],0)
        self.assertEqual(ledger.account(self.home,'broker')['cash']['USD'],'0.10')

    def test_conflicting_duplicate_rolls_back_batch(self):
        row=event(1,'DEPOSIT',amount='100');ledger.import_events(self.home,[row])
        with self.assertRaises(ValueError):ledger.import_events(self.home,[event(2,'DEPOSIT',amount='200'),dict(row,amount='999')])
        self.assertEqual(ledger.account(self.home,'broker')['event_count'],1)

    def test_overselling_rolls_back_all(self):
        with self.assertRaises(ValueError):ledger.import_events(self.home,[event(1,'DEPOSIT',amount='500'),event(2,'SELL',symbol='QQQ',quantity='1',price='100')])
        self.assertEqual(ledger.account(self.home,'broker')['event_count'],0)

    def test_negative_cash_is_rejected(self):
        with self.assertRaises(ValueError):ledger.import_events(self.home,[event(1,'BUY',symbol='QQQ',quantity='1',price='100')])

    def test_unknown_opening_cost_is_not_inferred(self):
        ledger.import_events(self.home,[event(1,'OPENING_POSITION',symbol='QQQ',quantity='10'),event(2,'SELL',symbol='QQQ',quantity='1',price='100')])
        a=ledger.account(self.home,'broker');self.assertIsNone(a['positions'][0]['cost_basis']);self.assertIsNone(a['realized_pnl']['USD'])

    def test_split_preserves_cost(self):
        ledger.import_events(self.home,[event(1,'DEPOSIT',amount='500'),event(2,'BUY',symbol='TQQQ',quantity='2',price='100'),event(3,'SPLIT',symbol='TQQQ',ratio='2')])
        p=ledger.account(self.home,'broker')['positions'][0]
        self.assertEqual(p['quantity'],'4');self.assertEqual(p['cost_basis'],'200')

    def test_currency_cash_is_never_combined(self):
        ledger.import_events(self.home,[event(1,'DEPOSIT',amount='100'),dict(event(2,'DEPOSIT',amount='700'),currency='CNY')])
        self.assertEqual(ledger.account(self.home,'broker')['cash'],{'USD':'100','CNY':'700'})

    def test_unconfirmed_future_naive_or_nonfinite_rejected(self):
        base=event(1,'DEPOSIT',amount='100')
        for override in ({'confirmed':False},{'occurred_at':'2099-01-01T00:00:00Z'},{'occurred_at':'2026-10-01T00:00:00'},{'amount':'NaN'},{'amount':0.1},{'amount':'-1'}):
            with self.subTest(override=override),self.assertRaises(ValueError):ledger.import_events(self.home,[dict(base,**override)])

    def test_journal_is_append_only(self):
        ledger.import_events(self.home,[event(1,'DEPOSIT',amount='100')])
        with self.assertRaises(sqlite3.IntegrityError),connection(self.home) as c:c.execute('DELETE FROM journal_events')
        with self.assertRaises(sqlite3.IntegrityError),connection(self.home) as c:c.execute("UPDATE journal_events SET account='other'")

    def test_valuation_does_not_create_trade(self):
        v={'valuation_id':'v1','account':'default','as_of':'2026-10-01','currency':'CNY','values':{'QQQ':'6000','QLD':'0','TQQQ':'0','CASH':'4000'},'confirmed':True,'note':'测试确认'}
        ledger.valuation(self.home,v);ledger.valuation(self.home,v)
        with connection(self.home) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM portfolio_baselines').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM journal_events').fetchone()[0],0)
        with self.assertRaises(ValueError):ledger.valuation(self.home,dict(v,valuation_id='v2',as_of='2026-09-01'))

    def test_valuation_rejects_silent_rounding(self):
        v={'valuation_id':'v1','account':'default','as_of':'2026-10-01','currency':'CNY','values':{'QQQ':'6000.10','QLD':'0','TQQQ':'0','CASH':'4000'},'confirmed':True,'note':'test'}
        with self.assertRaises(ValueError):ledger.valuation(self.home,v)

    def test_correction_preserves_original_but_removes_its_effect(self):
        rows=[event(1,'DEPOSIT',amount='100'),event(2,'VOID',reverses_event_id='e-001',note='错误入金，明确作废'),event(3,'DEPOSIT',amount='200')]
        ledger.import_events(self.home,rows)
        a=ledger.account(self.home,'broker')
        self.assertEqual(a['event_count'],3);self.assertEqual(a['cash']['USD'],'200');self.assertEqual(a['voided_event_ids'],['e-001'])
        with connection(self.home) as c:self.assertEqual(c.execute('SELECT count(*) FROM journal_events').fetchone()[0],3)

    def test_correction_cannot_break_later_cash_or_reference_other_account(self):
        ledger.import_events(self.home,[event(1,'DEPOSIT',amount='200'),event(2,'BUY',symbol='QQQ',quantity='1',price='100')])
        with self.assertRaises(ValueError):ledger.import_events(self.home,[event(3,'VOID',reverses_event_id='e-001',note='would break balance')])
        with self.assertRaises(ValueError):ledger.import_events(self.home,[dict(event(3,'VOID',reverses_event_id='e-002',note='wrong account'),account='other')])
        self.assertEqual(ledger.account(self.home,'broker')['event_count'],2)
