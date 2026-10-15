from datetime import datetime, date, timezone
import copy
import unittest
from investlab.providers import parse_yahoo


def payload():
    return {'chart':{'result':[{'meta':{'symbol':'QQQ','dataGranularity':'1d'},
       'timestamp':[int(datetime(2026,10,13,20,tzinfo=timezone.utc).timestamp()),int(datetime(2026,10,14,20,tzinfo=timezone.utc).timestamp())],
       'indicators':{'quote':[{'close':[100,101]}],'adjclose':[{'adjclose':[99,100]}]}}]}}

class ProviderTests(unittest.TestCase):
    def parse(self,p):return parse_yahoo(p,'QQQ',date(2026,10,14),lambda d:d.weekday()<5)
    def test_completed_daily_prices(self):self.assertEqual(len(self.parse(payload())),2)
    def test_symbol_interval_and_lengths_rejected(self):
        for key,value in [('symbol','TQQQ'),('dataGranularity','1mo')]:
            p=payload();p['chart']['result'][0]['meta'][key]=value
            with self.assertRaises(ValueError):self.parse(p)
        p=payload();p['chart']['result'][0]['indicators']['quote'][0]['close'].pop()
        with self.assertRaises(ValueError):self.parse(p)
    def test_invalid_price_does_not_silently_disappear(self):
        for bad in (None,0,float('nan'),float('inf'),True):
            p=payload();p['chart']['result'][0]['indicators']['quote'][0]['close'][0]=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.parse(p)
    def test_duplicate_and_unsorted_dates_rejected(self):
        for stamps in ([1,0],[0,0]):
            p=payload();s=p['chart']['result'][0]['timestamp'];p['chart']['result'][0]['timestamp']=[s[i] for i in stamps]
            with self.assertRaises(ValueError):self.parse(p)
    def test_unfinished_daily_bar_excluded(self):
        p=payload();item=p['chart']['result'][0];item['timestamp'].append(int(datetime(2026,10,15,17,tzinfo=timezone.utc).timestamp()))
        item['indicators']['quote'][0]['close'].append(None);item['indicators']['adjclose'][0]['adjclose'].append(None)
        self.assertEqual(len(self.parse(p)),2)
    def test_missing_latest_close_rejected(self):
        p=payload();item=p['chart']['result'][0];item['timestamp'].pop();item['indicators']['quote'][0]['close'].pop();item['indicators']['adjclose'][0]['adjclose'].pop()
        with self.assertRaises(ValueError):self.parse(p)
