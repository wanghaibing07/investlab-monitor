"""IEX-vs-local is a separate evidence layer, never a trade signal."""
from pathlib import Path
from unittest.mock import patch
import json
import os
import tempfile
import unittest

from investlab import service
from investlab.core import connection
from investlab.integrations import alpaca_market


class Response:
    def __init__(self, data):
        self.body = json.dumps(data).encode()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, _):
        return self.body


class AlpacaMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        service.init(self.home)
        with connection(self.home) as c:
            c.executemany("INSERT INTO daily_prices VALUES(?,?,?,?,?,?)", [
                ("QQQ", "2026-10-14", 700., 700., "YAHOO", "2026-10-15T00:00:00+00:00"),
                ("TQQQ", "2026-10-14", 70., 70., "YAHOO", "2026-10-15T00:00:00+00:00")
            ])
        self.bars = {"bars": {
            "QQQ": [{"t": "2026-10-14T04:00:00Z", "c": 699.0}],
            "TQQQ": [{"t": "2026-10-14T04:00:00Z", "c": 70.3}]
        }, "next_page_token": None}

    def invoke(self, payload):
        def opener(request, timeout):
            self.assertTrue(request.full_url.startswith(alpaca_market.DATA_BASE + "?"))
            self.assertIn("feed=iex", request.full_url)
            self.assertIn("adjustment=all", request.full_url)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(timeout, 15)
            return Response(payload)
        with patch.dict(os.environ, {"APCA_API_KEY_ID": "unit_test_key", "APCA_API_SECRET_KEY": "unit_test_secret"}):
            return alpaca_market.check(self.home, opener=opener)

    def test_context_agreement_does_not_become_trading_signal(self):
        result = self.invoke(self.bars)
        self.assertEqual(result["status"], "CONTEXT_AGREEMENT")
        self.assertFalse(result["used_for_trading"])
        self.assertFalse(result["changes_strategy_signal"])
        self.assertEqual(result["session_date"], "2026-10-14")
        self.assertEqual(result["feed"], "iex")

    def test_excessive_disagreement_and_missing(self):
        bad = json.loads(json.dumps(self.bars))
        bad["bars"]["TQQQ"][0]["c"] = 65
        self.assertEqual(self.invoke(bad)["status"], "SOURCE_DISAGREEMENT")
        bad["bars"]["TQQQ"] = []
        self.assertEqual(self.invoke(bad)["status"], "INCOMPLETE")

    def test_no_real_quote_comparison_in_synthetic_account(self):
        other = self.home / "fictional"
        service.init(other, demo=True)
        with self.assertRaisesRegex(ValueError, "synthetic"):
            alpaca_market.check(other)

    def test_malformed_vendor_payload_rejected(self):
        bad = json.loads(json.dumps(self.bars))
        bad["bars"]["QQQ"].append(bad["bars"]["QQQ"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.invoke(bad)
        bad = json.loads(json.dumps(self.bars))
        bad["bars"]["QQQ"][0]["c"] = "NaN"
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            self.invoke(bad)

    def test_credentials_not_returned(self):
        result = self.invoke(self.bars)
        self.assertNotIn("unit_test_secret", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
