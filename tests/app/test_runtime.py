from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from investlab import service
from investlab.core import connection
from investlab.server import handler


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);service.init(self.home,True)
    def test_empty_real_account_never_fills_demo_money(self):
        other=self.home/'other';service.init(other)
        with connection(other) as c:self.assertEqual(c.execute('SELECT count(*) FROM portfolio_baselines').fetchone()[0],0)
    def test_demo_cannot_mix_live_quotes(self):
        with self.assertRaises(ValueError):service.run(self.home,online=True)
    def test_failed_worker_is_recorded_as_failure(self):
        with patch('investlab.service.worker',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):service.run(self.home)
        with connection(self.home) as c:self.assertEqual(c.execute('SELECT status FROM operations').fetchone()[0],'FAILED')
    def test_serve_read_only_host_validation_and_missing_route(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.home));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(base+'/health/live') as r:self.assertEqual(json.load(r)['status'],'UP')
        for req,code in [(urllib.request.Request(base+'/',headers={'Host':'attacker.example'}),403),
                         (urllib.request.Request(base+'/api/latest',data=b'{}'),405),
                         (urllib.request.Request(base+'/../settings.json'),404)]:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
            self.assertEqual(error.exception.code,code)
    def test_initialization_refuses_existing_state(self):
        with self.assertRaises(ValueError):service.init(self.home,True)
    def test_user_target_cannot_be_silently_overridden(self):
        path=self.home/'settings.json';v=json.loads(path.read_text());v['target']={'QQQ':.8,'TQQQ':.2};path.write_text(json.dumps(v))
        with self.assertRaises(ValueError):service.settings(self.home)

    def test_demo_repeat_neither_creates_trades_nor_counts_forward_sessions(self):
        first=service.run(self.home); second=service.run(self.home)
        with connection(self.home) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM notifications').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM journal_events').fetchone()[0],0)
        self.assertEqual(service.latest(self.home)['distinct_verified_sessions'],0)
        self.assertFalse(first['qualified_online']);self.assertFalse(second['qualified_online'])

    def test_backup_failure_does_not_claim_completed_operation(self):
        with patch('investlab.service.backup',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):service.run(self.home)
        self.assertEqual(service.latest(self.home)['operation']['status'],'FAILED')

    def test_tampered_application_report_fails_audit(self):
        service.run(self.home)
        with connection(self.home) as c:c.execute("UPDATE app_reviews SET payload_sha256='broken'")
        self.assertEqual(service.audit(self.home)['status'],'FAIL')

    def test_prototype_exclusion_cannot_hide_new_qualified_missing_inputs(self):
        base={'sqlite_integrity':'ok','research_evidence':{'signals_without_frozen_input_snapshot':1,'qualified_signals_without_frozen_input_snapshot':0}}
        with patch('investlab.service.worker',return_value=base):
            a=service.audit(self.home);self.assertEqual(a['status'],'PASS');self.assertEqual(len(a['warnings']),1)
        base['research_evidence']['qualified_signals_without_frozen_input_snapshot']=1
        with patch('investlab.service.worker',return_value=base):self.assertEqual(service.audit(self.home)['status'],'FAIL')
