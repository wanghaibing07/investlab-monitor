"""Private valuation editor is explicit opt-in; HTTP authorization and ledger writes are verified."""
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from investlab import service
from investlab.core import connection
from investlab.server import handler


class LocalAccountHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        service.init(self.home, demo=False)
        self.token = "TEST_SESSION_SECRET_NOT_IN_PUBLIC_HTML"
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), handler(self.home, local_edit=True, csrf_token=self.token))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, *, data=None, headers=None):
        header = dict(headers or {})
        if data is not None:
            header.setdefault("Content-Type", "application/json")
            header.setdefault("Origin", self.base)
            header.setdefault("X-InvestLab-CSRF", self.token)
        req = urllib.request.Request(
            self.base + path, headers=header,
            data=json.dumps(data).encode() if data is not None else None,
            method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def valuation(self, **changes):
        payload = {"valuation_id": "browser-001", "account": "default",
                   "as_of": "2026-10-14", "currency": "CNY",
                   "values": {"QQQ": "6000", "TQQQ": "0", "QLD": "0", "CASH": "4000"},
                   "confirmed": True, "note": "用户明确确认的测试估值"}
        return {**payload, **changes}

    def test_session_visible_only_to_loopback_browser(self):
        code, data = self.request("/api/local-session")
        self.assertEqual(code, 200)
        self.assertTrue(data["local_edit"])
        self.assertEqual(data["csrf_token"], self.token)
        code, _ = self.request("/api/local-session", headers={"Host": "attacker.example"})
        self.assertEqual(code, 403)

    def test_confirmed_valuation_written_once_and_does_not_trade(self):
        status, result = self.request("/api/valuation", data=self.valuation())
        self.assertEqual(status, 201)
        self.assertEqual(result["status"], "SAVED")
        self.assertEqual(result["trades_created"], 0)
        self.assertFalse(result["duplicate"])
        status, result = self.request("/api/valuation", data=self.valuation())
        self.assertEqual(status, 201)
        self.assertTrue(result["duplicate"])
        with connection(self.home, readonly=True) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM portfolio_baselines").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0], 0)

    def test_requires_user_confirmation_and_valid_ledger_input(self):
        self.assertEqual(self.request("/api/valuation", data=self.valuation(confirmed=False))[0], 422)
        self.assertEqual(self.request("/api/valuation", data=self.valuation(
            values={"QQQ": "1.5", "TQQQ": "0", "QLD": "0", "CASH": "0"}))[0], 422)
        self.assertEqual(self.request("/api/valuation", data=self.valuation(
            valuation_id="future", as_of="2099-01-01"))[0], 422)
        with connection(self.home, readonly=True) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM portfolio_baselines").fetchone()[0], 0)

    def test_cross_origin_and_missing_token_rejected(self):
        self.assertEqual(self.request("/api/valuation", data=self.valuation(),
                     headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request("/api/valuation", data=self.valuation(),
                     headers={"X-InvestLab-CSRF": "wrong"})[0], 403)
        self.assertEqual(self.request("/api/valuation", data=self.valuation(),
                     headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.request("/api/valuation", data=self.valuation(),
                     headers={"Content-Type": "text/plain"})[0], 415)
        with connection(self.home, readonly=True) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM portfolio_baselines").fetchone()[0], 0)

    def test_explicit_recalculation_does_not_trade(self):
        fake = {"qualified_online": False}
        with patch("investlab.server.service.run", return_value=fake) as run:
            status, data = self.request("/api/recalculate", data={"online": False})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "SUCCEEDED")
        self.assertFalse(data["qualified_online"])
        self.assertTrue(data["manual_execution_only"])
        run.assert_called_once_with(self.home, online=False, independent=False)
        self.assertEqual(self.request("/api/recalculate", data={"online": "yes"})[0], 422)

    def test_public_and_default_server_still_reject_mutation(self):
        code, session = self.request("/api/local-session")
        self.assertTrue(session["local_edit"])
        other = ThreadingHTTPServer(("127.0.0.1", 0), handler(self.home))
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        url = f"http://127.0.0.1:{other.server_port}/api/valuation"
        req = urllib.request.Request(url, method="POST", data=b"{}", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(err.exception.code, 405)
        with self.assertRaisesRegex(ValueError, "Private edit"):
            handler(self.home, public_demo=True, local_edit=True, csrf_token=self.token)


if __name__ == "__main__":
    unittest.main()
