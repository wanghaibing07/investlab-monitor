"""Test private cloud recovery of research evidence, including ZIP v1 compatibility."""
import hashlib
import io
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
import zipfile

from investlab import cloud


def sample_home(root):
    home = Path(root) / "private"
    (home / "data").mkdir(parents=True)
    (home / "settings.json").write_text(
        json.dumps({"schema_version": 1, "demo": False, "execution": "MANUAL",
                    "target": {"QQQ": 0.6, "TQQQ": 0.4}}))
    with sqlite3.connect(home / "data/monitor.sqlite3") as db:
        db.execute("CREATE TABLE proof (name TEXT)")
        db.execute("INSERT INTO proof VALUES('snapshot')")
    return home


class ResearchArchiveTests(unittest.TestCase):
    def test_v2_archive_includes_research_evidence_and_verifies_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            home = sample_home(temp)
            sha = "a" * 64
            snapshot = home / cloud.MATURE_SNAPSHOT_PREFIX / (sha + ".json")
            snapshot.parent.mkdir(parents=True)
            snapshot.write_text('{"safe":"verified"}')
            blob = cloud._make_archive(home)
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                self.assertEqual(json.loads(archive.read("manifest.json"))["schema_version"],2)
                self.assertIn(cloud.MATURE_SNAPSHOT_PREFIX+sha+".json",archive.namelist())
            recovered = Path(temp) / "restored"
            cloud._restore_archive(recovered, blob)
            self.assertEqual((recovered/cloud.MATURE_SNAPSHOT_PREFIX/(sha+".json")).read_bytes(),
                             snapshot.read_bytes())
            with sqlite3.connect(recovered/"data/monitor.sqlite3") as db:
                self.assertEqual(db.execute("SELECT name FROM proof").fetchone()[0],"snapshot")

    def test_v1_existing_account_snapshots_remain_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            home=sample_home(temp)
            settings=(home/"settings.json").read_bytes()
            database=(home/"data/monitor.sqlite3").read_bytes()
            manifest={"schema_version":1,
                      "settings_sha256":hashlib.sha256(settings).hexdigest(),
                      "sqlite_sha256":hashlib.sha256(database).hexdigest()}
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,"w") as archive:
                archive.writestr("settings.json",settings)
                archive.writestr("data/monitor.sqlite3",database)
                archive.writestr("manifest.json",json.dumps(manifest))
            dest=Path(temp)/"old-account"
            cloud._restore_archive(dest,stream.getvalue())
            self.assertEqual((dest/"settings.json").read_bytes(),settings)

    def test_tampered_evidence_is_rejected_before_any_bypass(self):
        with tempfile.TemporaryDirectory() as temp:
            home=sample_home(temp)
            name="b"*64+".json"
            path=home/cloud.MATURE_SNAPSHOT_PREFIX/name
            path.parent.mkdir(parents=True)
            path.write_text('{"original":true}')
            blob=cloud._make_archive(home)
            target=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(blob)) as prior,zipfile.ZipFile(target,"w") as altered:
                for item in prior.namelist():
                    b=prior.read(item)
                    if item.endswith(name):b=b'{"forged":true}'
                    altered.writestr(item,b)
            with self.assertRaisesRegex(ValueError,"integrity"):
                cloud._restore_archive(Path(temp)/"tamper",target.getvalue())

    def test_rejects_archive_traversal_entry_even_with_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            home=sample_home(temp)
            raw=cloud._make_archive(home)
            corrupt=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(corrupt,"w") as dest:
                manifest=json.loads(src.read("manifest.json"))
                manifest["research_evidence_sha256"]["data/quant53/../evil.json"]=hashlib.sha256(b"x").hexdigest()
                for name in src.namelist():
                    dest.writestr(name,json.dumps(manifest) if name=="manifest.json" else src.read(name))
                dest.writestr("data/quant53/../evil.json",b"x")
            with self.assertRaisesRegex(ValueError,"Unsafe"):
                cloud._restore_archive(Path(temp)/"unsafe",corrupt.getvalue())


if __name__=="__main__":
    unittest.main()
