import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
import monitor as m
import web_extract as w

NOW=dt.datetime(2026,10,14,11,tzinfo=dt.timezone.utc)

def page(symbol='QQQ',source='CHARTEXCHANGE',price=743.57):
    url=next(k for k,v in w.URLS.items() if v==(symbol,source))
    return {'url':url,'final_url':url,'text':f'At Close 743.64 USD\nAfter-hours 9999\n| Date (EDT) | Open | Close | Adj. Close |\n| --- | --- | --- | --- |\n| 2026-10-13 | 700 | {price} | 111 |'}

class WebExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Path(self.tmp.name)/'db.sqlite3';m.init_db(self.db)
    def tearDown(self): self.tmp.cleanup()
    def test_daily_table_not_header_or_adjusted_close(self):
        self.assertEqual(w.parse_page(page(),dt.date(2026,10,13))['raw_close'],743.57)
    def test_us_date_table(self):
        p=page(source='STOCKANALYSIS');p['text']=p['text'].replace('2026-10-13','Oct 13, 2026')
        self.assertEqual(w.parse_page(p,dt.date(2026,10,13))['raw_close'],743.57)
    def test_redirect_and_missing_date_rejected(self):
        p=page();p['final_url']='https://evil.test/'
        with self.assertRaises(ValueError):w.parse_page(p,dt.date(2026,10,13))
        with self.assertRaises(ValueError):w.parse_page(page(),dt.date(2026,10,12))
    def test_partial_not_fabricated_as_four_successes(self):
        r=w.import_tinyfish({'results':[page()],'errors':[{'error':'bot_blocked'}]},self.db,NOW)
        self.assertEqual(r['status'],'PARTIAL');self.assertEqual(r['accepted_table_quotes'],1)
        self.assertEqual(m.web_close_snapshot(self.db)['QQQ']['websites'],1)
    def test_same_vendor_twice_not_two_sources(self):
        r=w.import_tinyfish({'results':[page(),page()]},self.db,NOW)
        self.assertEqual(r['accepted_table_quotes'],1)
    def test_quote_correction_preserves_legacy_evidence(self):
        with m.conn(self.db) as c:c.execute('INSERT INTO web_closes VALUES(?,?,?,?,?,?)',
            ('QQQ','2026-10-13','CHARTEXCHANGE',743.64,page()['url'],'old'))
        w.import_tinyfish({'results':[page()]},self.db,NOW)
        self.assertEqual(m.web_close_snapshot(self.db)['QQQ']['raw_close'],743.57)
        with m.conn(self.db) as c:self.assertEqual(c.execute('SELECT raw_close FROM web_closes').fetchone()[0],743.64)
    def test_cross_site_conflict_does_not_publish_new_quotes(self):
        p=page(source='STOCKANALYSIS',price=800)
        r=w.import_tinyfish({'results':[page(),p]},self.db,NOW)
        self.assertEqual(r['status'],'FAILED')
        self.assertIsNone(m.web_close_snapshot(self.db)['QQQ'])
    def test_intraday_row_is_not_latest_completed_close(self):
        p=page();p['text']=p['text'].replace('2026-10-13','2026-10-14')
        self.assertEqual(w.import_tinyfish({'results':[p]},self.db,NOW)['accepted_table_quotes'],0)
    def test_failed_fetch_keeps_evidence_but_no_prices(self):
        r=w.import_tinyfish({'results':[],'errors':[{'error':'bot_blocked'}]},self.db,NOW)
        self.assertEqual(r['status'],'FAILED');self.assertEqual(w.audit(self.db)['attempts'],1)
        with m.conn(self.db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0],0)
