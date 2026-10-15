"""Failure-first review: stale success, interrupted recovery and path boundaries."""
from pathlib import Path
from unittest.mock import patch
import json
import sqlite3
import tempfile
import unittest
import zipfile
from investlab import service, storage
from investlab.core import canonical, connection


class HardeningReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)/'home';service.init(self.home,True)

    def test_failure_after_success_remains_visible(self):
        service.run(self.home)
        with patch('investlab.service.worker',side_effect=RuntimeError('new fetch failed')):
            with self.assertRaises(RuntimeError):service.run(self.home)
        value=service.latest(self.home)
        self.assertEqual(value['latest_attempt']['status'],'FAILED')
        self.assertFalse(value['is_actionable'])
        self.assertIn('失败',service.plain_summary(value))

    def test_newer_market_session_blocks_old_success(self):
        service.run(self.home)
        from datetime import date
        with patch('investlab.engine.monitor.expected_close_session',return_value=date(2026,10,15)):
            value=service.latest(self.home)
        self.assertFalse(value['market_session_current']);self.assertFalse(value['is_actionable'])

    def test_missing_database_is_not_created_by_backup(self):
        source=Path(self.tmp.name)/'absent.sqlite3'
        with self.assertRaises((OSError,ValueError,sqlite3.Error)):storage.db_backup(source,Path(self.tmp.name)/'out.sqlite3')
        self.assertFalse(source.exists())

    def test_restore_does_not_leave_partial_target_on_bad_database(self):
        import hashlib
        archive=Path(self.tmp.name)/'bad-db.zip'
        payload=b'not a sqlite database'
        manifest={'format':'investlab-backup-v1','files':{'data/monitor.sqlite3':hashlib.sha256(payload).hexdigest(),'settings.json':hashlib.sha256(b'{}').hexdigest()}}
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('data/monitor.sqlite3',payload);z.writestr('settings.json',b'{}');z.writestr('MANIFEST.json',canonical(manifest))
        target=Path(self.tmp.name)/'restored'
        with self.assertRaises((ValueError,sqlite3.Error)):storage.restore(archive,target)
        self.assertFalse(target.exists())

    def test_restore_refuses_arbitrary_manifest_root_files(self):
        import hashlib
        archive=Path(self.tmp.name)/'wrong-layout.zip'
        payload=b'bad'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('launch.py',payload);z.writestr('MANIFEST.json',canonical({'format':'investlab-backup-v1','files':{'launch.py':hashlib.sha256(payload).hexdigest()}}))
        with self.assertRaises(ValueError):storage.verify_archive(archive)

    def test_nested_migration_rejected_before_creating_destination(self):
        target=self.home/'data/nested'
        with self.assertRaises(ValueError):storage.migrate(self.home,target)
        self.assertFalse(target.exists())

    def test_restored_pending_operation_becomes_interrupted_on_next_run(self):
        service.run(self.home)
        with connection(self.home) as c:c.execute("UPDATE operations SET status='PERSISTED'")
        service.run(self.home)
        with connection(self.home) as c:
            states=[r[0] for r in c.execute('SELECT status FROM operations ORDER BY started_at')]
        self.assertEqual(states,['INTERRUPTED','SUCCEEDED'])

    def test_release_check_catches_forcibly_tracked_environment_file(self):
        import subprocess
        source=Path(__file__).resolve().parents[2]/'scripts/check_release.py'
        project=Path(self.tmp.name)/'release';(project/'scripts').mkdir(parents=True)
        (project/'scripts/check_release.py').write_bytes(source.read_bytes())
        (project/'.gitignore').write_text('.env\nbuild/\n')
        (project/'.env').write_text('PASSWORD=private-value')
        subprocess.run(['git','init','-q',str(project)],check=True)
        subprocess.run(['git','add','-f','.env'],cwd=project,check=True)
        p=subprocess.run([__import__('sys').executable,'scripts/check_release.py'],cwd=project,text=True,capture_output=True)
        self.assertEqual(p.returncode,1);self.assertIn('environment secrets: .env',p.stdout)

    def test_private_package_references_git_without_copying_working_source(self):
        import subprocess,sys
        script=Path(__file__).resolve().parents[2]/'scripts/package_private.py'
        out=Path(self.tmp.name)/'private-state.zip'
        revision='4d0660cda37c42e48f83f24feb7e586a940dda15'
        subprocess.run([sys.executable,str(script),'--home',str(self.home),'--output',str(out),'--repository','https://github.com/wanghaibing07/investlab-monitor','--revision',revision],check=True,capture_output=True)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(json.loads(z.read('SOURCE.json'))['revision'],revision)
            self.assertIn('runtime/data/monitor.sqlite3',z.namelist())
            self.assertFalse(any(n.startswith('investlab/') for n in z.namelist()))
