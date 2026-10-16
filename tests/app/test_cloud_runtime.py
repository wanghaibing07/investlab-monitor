"""Cloud snapshot correctness, non-demo gates, failure preservation and auth guards."""
import asyncio
from pathlib import Path
import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import AsyncMock, patch
from datetime import date

from investlab import cloud, service
from investlab.core import connection


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)/"home"
        service.init(self.home,demo=False)
        with connection(self.home) as c:
            c.execute(
                "INSERT INTO portfolio_baselines(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,qld_value_cny,note) "
                "VALUES(?,?,?,?,?,?,?)",
                ("2026-10-14T10:00:00+00:00","2026-10-14",6000,4000,0,0,"Explicit confirmation test")
            )

    def test_sqlite_backup_survives_wal_and_restore(self):
        archive = cloud._make_archive(self.home)
        restored = self.home.parent/"restored"
        cloud._restore_archive(restored,archive)
        self.assertEqual(service.settings(restored)["demo"],False)
        with connection(restored,readonly=True) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM portfolio_baselines").fetchone()[0],1)

    def test_modified_database_hash_fails_closed(self):
        archive = cloud._make_archive(self.home)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            values = {n:z.read(n) for n in z.namelist()}
        values["data/monitor.sqlite3"] = b"not a database"
        out=io.BytesIO()
        with zipfile.ZipFile(out,"w") as z:
            for key,content in values.items():
                z.writestr(key,content)
        with self.assertRaisesRegex(ValueError,"integrity"):
            cloud._restore_archive(self.home.parent/"tampered",out.getvalue())

    def test_path_injection_and_oversized_file_rejected(self):
        mem=io.BytesIO()
        with zipfile.ZipFile(mem,"w") as z:
            z.writestr("../../.ssh/id_rsa","attack")
        with self.assertRaisesRegex(ValueError,"contents"):
            cloud._restore_archive(self.home.parent/"unsafe",mem.getvalue())

    def test_demo_rejected_for_cloud_live_run(self):
        demo=self.home.parent/"demo";service.init(demo,True)
        with self.assertRaisesRegex(ValueError,"non-demo"):
            cloud._check_account(demo)

    def test_failure_stores_status_but_not_updated_account_state(self):
        async def load(home):
            service.init(home,False)
            with connection(home) as c:
                c.execute(
                    "INSERT INTO portfolio_baselines(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,qld_value_cny,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    ("2026-10-14T10:00:00+00:00","2026-10-14",6000,4000,0,0,"test")
                )
            return True
        with (patch("investlab.cloud.load_private_home",side_effect=load),
              patch("investlab.cloud._compute",side_effect=RuntimeError("secret token inside failure")),
              patch("investlab.cloud.save_private_home",new_callable=AsyncMock) as save,
              patch("investlab.cloud.save_private_report",new_callable=AsyncMock,return_value="runs/failed.json")):
            result=asyncio.run(cloud.run_private_daily())
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["failure_type"],"RuntimeError")
        self.assertNotIn("secret token",json.dumps(result))
        save.assert_not_awaited()

    def test_private_valuation_readback_checks_exact_amounts_and_date(self):
        from types import SimpleNamespace
        archive=cloud._make_archive(self.home)
        async def listing(prefix):
            return [SimpleNamespace(pathname="state/fixture.zip")]
        with (patch("investlab.cloud._list",side_effect=listing),
              patch("investlab.cloud._read",new=AsyncMock(return_value=archive))):
            confirmed=asyncio.run(cloud.verify_private_valuation(
                {"QQQ":"6000","TQQQ":"0","QLD":"0","CASH":"4000"},"2026-10-14"))
            self.assertTrue(confirmed["verified"])
            self.assertEqual(confirmed["total_value_cny"],10000)
            with self.assertRaisesRegex(RuntimeError,"amounts"):
                asyncio.run(cloud.verify_private_valuation(
                    {"QQQ":"6100","TQQQ":"0","QLD":"0","CASH":"3900"},"2026-10-14"))
            with self.assertRaisesRegex(RuntimeError,"date"):
                asyncio.run(cloud.verify_private_valuation(
                    {"QQQ":"6000","TQQQ":"0","QLD":"0","CASH":"4000"},"2026-10-15"))

    def test_private_account_verification_checks_real_restored_baseline(self):
        from types import SimpleNamespace
        archive = cloud._make_archive(self.home)
        with (patch("investlab.cloud._list", new=AsyncMock(
                    return_value=[SimpleNamespace(pathname="state/verified.zip")])),
              patch("investlab.cloud._read", new=AsyncMock(
                    return_value=archive))):
            self.assertTrue(asyncio.run(cloud.private_account_verified()))

    def test_private_account_verification_missing_snapshot_is_false(self):
        with patch("investlab.cloud._list", new=AsyncMock(return_value=[])):
            self.assertFalse(asyncio.run(cloud.private_account_verified()))

    def test_private_account_verification_rejects_corruption(self):
        from types import SimpleNamespace
        with (patch("investlab.cloud._list", new=AsyncMock(
                    return_value=[SimpleNamespace(pathname="state/bad.zip")])),
              patch("investlab.cloud._read", new=AsyncMock(
                    return_value=b"invalid archive"))):
            with self.assertRaises(zipfile.BadZipFile):
                asyncio.run(cloud.private_account_verified())

    def test_no_private_snapshot_never_claims_success(self):
        with (patch("investlab.cloud.load_private_home",new_callable=AsyncMock,return_value=False),
              patch("investlab.cloud.save_private_report",new_callable=AsyncMock,return_value="runs/not-ready.json"),
              patch("investlab.cloud._compute") as compute):
            result=asyncio.run(cloud.run_private_daily())
        self.assertEqual(result["status"],"SETUP_REQUIRED")
        self.assertEqual(result["issue_code"],"NO_PRIVATE_ACCOUNT_SNAPSHOT")
        compute.assert_not_called()


if __name__=="__main__":
    unittest.main()
