"""Never make real HTTP requests or Blob calls; test cloud HTTP authorization boundaries."""
from pathlib import Path
from unittest.mock import patch
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

    def test_docs_disabled_and_cloud_is_vaulted(self):
        self.assertEqual(self.client.get("/docs").status_code,404)
        self.assertEqual(self.client.get("/openapi.json").status_code,404)


if __name__=="__main__":
    unittest.main()
