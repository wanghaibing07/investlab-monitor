"""Protected HTTP recovery semantics and explicit cron enable guard."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

source = Path(__file__).resolve().parents[2] / "deploy/cloud/app.py"
spec = importlib.util.spec_from_file_location("investlab_recovery_http", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RecoveryAndCronTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(module.app)

    def test_recovery_probes_are_not_claimed_without_storage(self):
        with patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": ""}):
            response = self.client.get("/api/recovery")
        self.assertEqual(response.status_code, 503)

    def test_recovery_success_is_not_independent_backup_proof(self):
        data = {"status": "CURRENT_SNAPSHOT_RESTORABLE_ONLY",
                "current_restorable": True, "older_restorable": False,
                "independent_backup_verified": False,
                "automatic_recovery_verified": False,
                "snapshots_checked": 1, "checks": [{"slot": "current", "restorable": True}]}
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-blob"}),
              patch("investlab.cloud.probe_private_recovery",
                    new=AsyncMock(return_value=data)) as probe):
            response = self.client.get("/api/recovery")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["independent_backup_verified"])
        probe.assert_awaited_once_with(limit=2)

    def test_corrupted_current_snapshot_is_http_failure(self):
        data = {"status": "CURRENT_SNAPSHOT_NOT_RESTORABLE",
                "current_restorable": False, "older_restorable": True,
                "independent_backup_verified": False,
                "automatic_recovery_verified": False}
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-blob"}),
              patch("investlab.cloud.probe_private_recovery",
                    new=AsyncMock(return_value=data))):
            response = self.client.get("/api/recovery")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["current_restorable"])

    def test_recovery_error_never_leaks_exception_message(self):
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-blob"}),
              patch("investlab.cloud.probe_private_recovery",
                    new=AsyncMock(side_effect=RuntimeError("private-token must not leak")))):
            response = self.client.get("/api/recovery")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-token", response.text)

    def test_cron_requires_valid_secret_and_separate_opt_in(self):
        secret = "x" * 48
        with (patch.dict(os.environ, {
                "CRON_SECRET": secret, "BLOB_READ_WRITE_TOKEN": "test-blob",
                "INVESTLAB_CRON_ENABLED": "false"}),
              patch("investlab.automation.daily_primary",
                    new=AsyncMock()) as run):
            wrong = self.client.get("/api/cron/daily",
                                    headers={"Authorization": "Bearer wrong"})
            self.assertEqual(wrong.status_code, 401)
            blocked = self.client.get("/api/cron/daily",
                                      headers={"Authorization": f"Bearer {secret}"})
            self.assertEqual(blocked.status_code, 503)
            self.assertEqual(blocked.json()["status"], "DISABLED_BY_DEFAULT")
            run.assert_not_awaited()

    def test_approved_cron_path_can_run_once_in_synthetic_test(self):
        secret = "y" * 48
        with (patch.dict(os.environ, {
                "CRON_SECRET": secret, "BLOB_READ_WRITE_TOKEN": "test-blob",
                "INVESTLAB_CRON_ENABLED": "true"}),
              patch("investlab.automation.daily_primary",
                    new=AsyncMock(return_value={"status": "SUCCEEDED", "trading_enabled": False})) as run):
            response = self.client.get("/api/cron/daily",
                                       headers={"Authorization": f"Bearer {secret}"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["trading_enabled"])
        run.assert_awaited_once()


    def test_watchdog_requires_secret_and_explicit_enable(self):
        secret = "z" * 48
        with (patch.dict(os.environ, {
                "CRON_SECRET": secret, "BLOB_READ_WRITE_TOKEN": "test-blob",
                "INVESTLAB_CRON_ENABLED": "false"}),
              patch("investlab.automation.daily_watchdog",
                    new=AsyncMock()) as watch):
            self.assertEqual(self.client.get("/api/cron/watchdog").status_code,401)
            blocked=self.client.get("/api/cron/watchdog",
                                    headers={"Authorization": f"Bearer {secret}"})
            self.assertEqual(blocked.status_code,503)
            watch.assert_not_awaited()

    def test_watchdog_uses_verified_receipt_and_never_executes_trading(self):
        secret="z"*48
        with (patch.dict(os.environ, {
                "CRON_SECRET":secret, "BLOB_READ_WRITE_TOKEN":"test-blob",
                "INVESTLAB_CRON_ENABLED":"true"}),
              patch("investlab.automation.daily_watchdog",
                    new=AsyncMock(return_value={"status":"VERIFIED",
                                                 "trading_enabled":False})) as watch):
            resp=self.client.get("/api/cron/watchdog",
                                  headers={"Authorization":f"Bearer {secret}"})
        self.assertEqual(resp.status_code,200)
        self.assertFalse(resp.json()["trading_enabled"])
        watch.assert_awaited_once()



    def test_isolated_diagnostic_rejects_cross_origin_and_requires_consent(self):
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "configured"}),
              patch("investlab.automation.diagnose_readonly",new=AsyncMock()) as diag):
            self.assertEqual(self.client.post("/api/diagnostics/research",
                json={"confirmed":True}).status_code,403)
            self.assertEqual(self.client.post("/api/diagnostics/research",
                json={"confirmed":True},
                headers={"Origin":"https://attacker.example"}).status_code,403)
            self.assertEqual(self.client.post("/api/diagnostics/research",
                json={"confirmed":False},
                headers={"Origin":"https://testserver"}).status_code,422)
            diag.assert_not_awaited()

    def test_isolated_diagnostic_does_not_report_failure_as_success(self):
        failure={"status":"FAILED","failure_category":"MARKET_DATA_NOT_QUALIFIED",
                 "qualified_online":False,"saved_to_production":False,"trading_enabled":False}
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN":"configured"}),
              patch("investlab.automation.diagnose_readonly",
                    new=AsyncMock(return_value=failure)) as diag):
            response=self.client.post("/api/diagnostics/research",json={"confirmed":True},
                headers={"Origin":"https://testserver"})
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json()["failure_category"],"MARKET_DATA_NOT_QUALIFIED")
        self.assertFalse(response.json()["saved_to_production"])
        diag.assert_awaited_once()

    def test_isolated_diagnostic_success_is_still_not_a_saved_daily_run(self):
        success={"status":"QUALIFIED","qualified_online":True,
                 "saved_to_production":False,"trading_enabled":False}
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN":"configured"}),
              patch("investlab.automation.diagnose_readonly",
                    new=AsyncMock(return_value=success))):
            response=self.client.post("/api/diagnostics/research",json={"confirmed":True},
                headers={"Origin":"https://testserver"})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()["saved_to_production"])



if __name__ == "__main__":
    unittest.main()
