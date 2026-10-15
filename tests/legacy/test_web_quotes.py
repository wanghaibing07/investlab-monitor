import datetime as dt
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import monitor as m

NOW=dt.datetime(2026,10,8,9,20,tzinfo=dt.timezone.utc)

def sample():
    return {'trade_date':'2026-10-07','quotes':{
      'QQQ':[{'source':'STOCKANALYSIS','raw_close':757.73,'url':'https://stockanalysis.com/etf/qqq/history/'},
             {'source':'CHARTEXCHANGE','raw_close':757.84,'url':'https://chartexchange.com/symbol/nasdaq-qqq/historical/'}],
      'TQQQ':[{'source':'STOCKANALYSIS','raw_close':83.62,'url':'https://stockanalysis.com/etf/tqqq/history/'},
              {'source':'CHARTEXCHANGE','raw_close':83.59,'url':'https://chartexchange.com/symbol/nasdaq-tqqq/historical/'}]}}

class WebQuoteTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.TemporaryDirectory()
        self.db=Path(self.dir.name)/'monitor.sqlite3'
        m.init_db(self.db)
        m.set_portfolio(12000,8000,'2026-10-08',db=self.db)
    def tearDown(self):self.dir.cleanup()
    def test_cross_site_validated(self):
        result=m.import_web_closes(sample(),db=self.db,now=NOW)
        self.assertEqual(result['sites'],{'QQQ':2,'TQQQ':2})
        quotes=m.web_close_snapshot(self.db)
        self.assertEqual(quotes['QQQ']['date'],'2026-10-07')
        self.assertEqual(quotes['TQQQ']['raw_close'],83.605)
    def test_import_idempotent(self):
        for _ in range(2):m.import_web_closes(sample(),db=self.db,now=NOW)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('select count(*) from web_closes').fetchone()[0],4)
    def test_future_close_rejected(self):
        data=sample();data['trade_date']='2026-10-08'
        with self.assertRaises(ValueError):m.import_web_closes(data,db=self.db,now=NOW)
    def test_conflicting_website_rejected_atomically(self):
        data=sample();data['quotes']['TQQQ'][1]['raw_close']=60
        with self.assertRaises(ValueError):m.import_web_closes(data,db=self.db,now=NOW)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('select count(*) from web_closes').fetchone()[0],0)
    def test_one_website_not_sufficient(self):
        data=sample();data['quotes']['QQQ']=data['quotes']['QQQ'][:1]
        with self.assertRaises(ValueError):m.import_web_closes(data,db=self.db,now=NOW)
    def test_fake_hostname_rejected(self):
        data=sample();data['quotes']['QQQ'][0]['url']='https://stockanalysis.com.evil.test/etf/qqq/history/'
        with self.assertRaises(ValueError):m.import_web_closes(data,db=self.db,now=NOW)
    def test_existing_close_conflict_rejected(self):
        m.import_web_closes(sample(),db=self.db,now=NOW)
        data=sample();data['quotes']['QQQ'][0]['raw_close']=757.78
        with self.assertRaises(ValueError):m.import_web_closes(data,db=self.db,now=NOW)
    def test_web_doesnt_mutate_adjusted_series(self):
        before=m.audit(self.db)['price_records']
        m.import_web_closes(sample(),db=self.db,now=NOW)
        self.assertEqual(before,m.audit(self.db)['price_records'])
    def test_cross_checked_raw_not_dubbed_online_adjusted(self):
        m.import_web_closes(sample(),db=self.db,now=NOW)
        r=m.build_report(now=NOW,online=False,db=self.db)
        self.assertEqual(r['data_evidence_grade'],'WEB_CROSS_CHECKED_RAW_ONLY')  # Both active ETFs are corroborated; QLD is excluded.
        self.assertEqual(r['mode'],'OFFLINE_CACHE')
        self.assertEqual(r['market']['QQQ']['quality'],'MISSING')
        self.assertEqual(r['market']['TQQQ']['web_cross_checked_raw_close']['websites'],2)

if __name__=='__main__':unittest.main()
