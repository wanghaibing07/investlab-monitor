from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
import zipfile
from investlab import ledger, service, storage
from investlab.core import atomic, connection, lock


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/'home';service.init(self.home,True)

    def test_backup_restore_preserves_every_table_and_evidence(self):
        atomic(self.home/'data/research/evidence.json',{'test':[1,2,3]})
        before=storage.table_fingerprints(self.home/'data/monitor.sqlite3')
        b=storage.backup(self.home);target=Path(self.temp.name)/'restored'
        storage.restore(b['path'],target)
        self.assertEqual(before,storage.table_fingerprints(target/'data/monitor.sqlite3'))
        self.assertEqual(json.loads((target/'data/research/evidence.json').read_text()),{'test':[1,2,3]})

    def test_restore_refuses_live_directory(self):
        b=storage.backup(self.home)
        with self.assertRaises(ValueError):storage.restore(b['path'],self.home)

    def test_restore_rejects_traversal_and_unmanifested(self):
        p=Path(self.temp.name)/'bad.zip'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('../escape','bad');z.writestr('MANIFEST.json','{}')
        with self.assertRaises(ValueError):storage.verify_archive(p)

    def test_tampered_backup_rejected(self):
        b=storage.backup(self.home);p=Path(self.temp.name)/'bad.zip'
        with zipfile.ZipFile(b['path']) as src,zipfile.ZipFile(p,'w') as dst:
            for name in src.namelist():dst.writestr(name,b'bad' if name=='data/monitor.sqlite3' else src.read(name))
        with self.assertRaises(ValueError):storage.verify_archive(p)

    def test_migration_preserves_source_and_rejects_overwrite(self):
        before=storage.table_fingerprints(self.home/'data/monitor.sqlite3')
        target=Path(self.temp.name)/'migrated';r=storage.migrate(self.home,target)
        self.assertTrue(r['table_parity'])
        for k,v in before.items():
            if k != 'migrations': self.assertEqual(storage.table_fingerprints(target/'data/monitor.sqlite3')[k],v)
        receipt=json.loads((target/'data/migration-receipt.json').read_text())
        self.assertEqual(receipt['tables'],before)
        self.assertEqual(before,storage.table_fingerprints(self.home/'data/monitor.sqlite3'))
        with self.assertRaises(ValueError):storage.migrate(self.home,target)

    def test_writer_lock_is_exclusive_and_released(self):
        with lock(self.home):
            with self.assertRaises(RuntimeError),lock(self.home):pass
        with lock(self.home):pass

    def test_atomic_replacement_has_valid_json(self):
        p=self.home/'data/state.json';atomic(p,{'v':1});atomic(p,{'v':2})
        self.assertEqual(json.loads(p.read_text()),{'v':2})
