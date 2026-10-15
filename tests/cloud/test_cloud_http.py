"""Never make real HTTP requests or Blob calls; test cloud HTTP authorization boundaries."""
from pathlib import Path
from unittest.mock import patch, AsyncMock
import importlib.util
import os
import unittest

from fastapi.testclient import TestClient

source=Path(__file__).resolve().parents[2]/"deploy/cloud/app.py"
spec=importlib.util.spec_from_file_location("investlab_private_cloud_api",source)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CloudWebSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(module.app,raise_server_exceptions=True)

    def test_no_database_or_api_key_claims_success(self):
        with patch.dict(os.environ,{"BLOB_READ_WRITE_TOKEN":""}):
            health=self.client.get("/health")
            self.assertEqual(health.status_code,200)
            self.assertFalse(health.json()["storage_connected"])
            self.assertFalse(health.json()["execution_enabled"])
            self.assertEqual(self.client.get("/api/status").status_code,503)
            self.assertEqual(self.client.get("/api/latest").status_code,503)

    def test_cron_never_runs_without_private_secret(self):
        with patch.dict(os.environ,{"CRON_SECRET":"x"*48,"BLOB_READ_WRITE_TOKEN":"placeholder"}):
            with patch("investlab.cloud.run_private_daily") as invoked:
                self.assertEqual(self.client.get("/api/cron/daily").status_code,401)
                self.assertEqual(self.client.get("/api/cron/daily",headers={
                    "Authorization":"Bearer wrong-token"}).status_code,401)
                invoked.assert_not_called()

    def test_initialize_requires_origin_and_admin_secret(self):
        body={"as_of":"2026-10-14","values":{"QQQ":"6000","TQQQ":"0",
               "QLD":"0","CASH":"4000"},"note":"confirmed sample","confirmed":True}
        with patch.dict(os.environ,{"INVESTLAB_ADMIN_TOKEN":"z"*48,
                                   "BLOB_READ_WRITE_TOKEN":"test-blob-token"}):
            with patch("investlab.cloud.initialize_private_account") as invoked:
                self.assertEqual(self.client.post("/api/initialize",json=body).status_code,403)
                headers={"origin":"https://testserver","x-investlab-admin-token":"wrong"}
                self.assertEqual(self.client.post("/api/initialize",json=body,headers=headers).status_code,401)
                invoked.assert_not_called()

    def test_no_report_verifies_actual_account_absent(self):
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-token"}),
              patch("investlab.cloud.private_account_verified",
                    new=AsyncMock(return_value=False)) as verify,
              patch("investlab.cloud.latest_json",
                    new=AsyncMock(return_value=None)) as latest):
            response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "SETUP_REQUIRED")
        self.assertFalse(data["account_initialized"])
        self.assertTrue(data["storage_verified"])
        self.assertFalse(data["latest_run_exists"])
        verify.assert_awaited_once()
        latest.assert_awaited_once_with("runs")

    def test_account_exists_without_report_is_ready_for_first_run(self):
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-token"}),
              patch("investlab.cloud.private_account_verified",
                    new=AsyncMock(return_value=True)),
              patch("investlab.cloud.latest_json",
                    new=AsyncMock(return_value=None))):
            response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "READY_FOR_FIRST_RUN")
        self.assertTrue(response.json()["account_initialized"])
        self.assertFalse(response.json()["latest_run_exists"])

    def test_stale_report_without_account_is_not_reported_as_success(self):
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-token"}),
              patch("investlab.cloud.private_account_verified",
                    new=AsyncMock(return_value=False)),
              patch("investlab.cloud.latest_json",
                    new=AsyncMock(return_value={"status": "SUCCEEDED"}))):
            response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "STATE_INCONSISTENT")
        self.assertEqual(response.json()["issue_code"],
                         "RUN_REPORT_WITHOUT_CONFIRMED_ACCOUNT")

    def test_actual_storage_error_does_not_claim_account_missing(self):
        with (patch.dict(os.environ, {"BLOB_READ_WRITE_TOKEN": "test-token"}),
              patch("investlab.cloud.private_account_verified",
                    new=AsyncMock(side_effect=RuntimeError("do not expose token"))),
              patch("investlab.cloud.latest_json",
                    new=AsyncMock()) as latest):
            response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "STORAGE_ERROR")
        self.assertIsNone(response.json()["account_initialized"])
        self.assertFalse(response.json()["storage_verified"])
        self.assertNotIn("token", response.text)
        latest.assert_not_awaited()

    def test_docs_disabled_and_cloud_is_vaulted(self):
        self.assertEqual(self.client.get("/docs").status_code,404)
        self.assertEqual(self.client.get("/openapi.json").status_code,404)


if __name__=="__main__":
    unittest.main()
