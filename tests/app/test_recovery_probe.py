"""A recovery probe must validate real SQLite backup bytes without writing state."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from investlab import cloud, service
from investlab.core import connection


class PrivateRecoveryProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name) / "home"
        service.init(home, demo=False)
        with connection(home) as db:
            db.execute(
                "INSERT INTO portfolio_baselines"
                "(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,qld_value_cny,note)"
                " VALUES(?,?,?,?,?,?,?)",
                ("2026-10-16T10:00:00Z","2026-10-16",9000,1000,0,0,"SYNTHETIC")
            )
        self.archive = cloud._make_archive(home)
        self.names = ["state/20261015-old.zip", "state/20261016-new.zip"]

    def _objects(self):
        return [SimpleNamespace(pathname=name) for name in self.names]

    def test_two_versions_can_be_restored_without_writes(self):
        with (patch("investlab.cloud._list", new=AsyncMock(return_value=self._objects())),
              patch("investlab.cloud._read", new=AsyncMock(return_value=self.archive)) as reads,
              patch("investlab.cloud._write", new=AsyncMock()) as writes):
            result = asyncio.run(cloud.probe_private_recovery(limit=2))
        self.assertEqual(result["status"], "TWO_IN_STORE_SNAPSHOTS_RESTORABLE")
        self.assertTrue(result["current_restorable"])
        self.assertTrue(result["older_restorable"])
        self.assertEqual(result["snapshots_checked"], 2)
        self.assertFalse(result["independent_backup_verified"])
        self.assertFalse(result["automatic_recovery_verified"])
        self.assertEqual(reads.await_count, 2)
        writes.assert_not_awaited()

    def test_corrupt_latest_never_silently_falls_back(self):
        async def read(name, **kwargs):
            return b"invalid-current-archive" if name.endswith("new.zip") else self.archive
        with (patch("investlab.cloud._list", new=AsyncMock(return_value=self._objects())),
              patch("investlab.cloud._read", new=AsyncMock(side_effect=read)),
              patch("investlab.cloud._write", new=AsyncMock()) as writes):
            result = asyncio.run(cloud.probe_private_recovery())
        self.assertEqual(result["status"], "CURRENT_SNAPSHOT_NOT_RESTORABLE")
        self.assertFalse(result["current_restorable"])
        self.assertTrue(result["older_restorable"])
        self.assertFalse(result["independent_backup_verified"])
        self.assertNotIn("state/", str(result))
        writes.assert_not_awaited()

    def test_all_corrupt_reports_unavailable(self):
        with (patch("investlab.cloud._list", new=AsyncMock(return_value=self._objects())),
              patch("investlab.cloud._read", new=AsyncMock(return_value=b"corrupt"))):
            result = asyncio.run(cloud.probe_private_recovery())
        self.assertEqual(result["status"], "CURRENT_SNAPSHOT_NOT_RESTORABLE")
        self.assertFalse(result["current_restorable"])
        self.assertFalse(result["older_restorable"])

    def test_no_account_is_not_healthy(self):
        with patch("investlab.cloud._list", new=AsyncMock(return_value=[])):
            result = asyncio.run(cloud.probe_private_recovery())
        self.assertEqual(result["status"], "NO_ACCOUNT_SNAPSHOTS")
        self.assertFalse(result["current_restorable"])
        self.assertEqual(result["snapshots_checked"], 0)

    def test_limit_is_bounded_to_avoid_unlimited_blob_downloads(self):
        for bad in (0, -1, 6, True, "3"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                asyncio.run(cloud.probe_private_recovery(limit=bad))


if __name__ == "__main__":
    unittest.main()
