"""No credentials or network required; the brokerage adapter must stay GET-only."""
import io
import json
import os
import unittest
from unittest.mock import patch

from investlab.integrations import alpaca


class Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode()
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def read(self, _size):
        return self.data


class AlpacaReadOnlyTests(unittest.TestCase):
    def test_requires_private_environment_credentials(self):
        with patch.dict(os.environ, {"APCA_API_KEY_ID": "", "APCA_API_SECRET_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "private process environment"):
                alpaca.paper_get("/v2/account", opener=lambda *_a, **_k: None)

    def test_always_paper_host_and_only_get(self):
        seen = []
        def open_mock(request, timeout):
            seen.append((request.full_url, request.get_method(), timeout))
            return Response({"currency": "USD", "status": "ACTIVE", "equity": "100000", "cash": "60000"})
        with patch.dict(os.environ, {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"}):
            alpaca.paper_get("/v2/account", opener=open_mock)
            with self.assertRaisesRegex(ValueError, "Forbidden"):
                alpaca.paper_get("/v2/orders", opener=open_mock)
        self.assertEqual(seen, [(alpaca.PAPER_BASE + "/v2/account", "GET", 12)])

    def test_basic_qqq_tqqq_paper_risk(self):
        report = alpaca.normalize(
            {"currency": "USD", "status": "ACTIVE", "equity": "100000", "cash": "0"},
            [{"symbol": "QQQ", "asset_class": "us_equity", "side": "long", "market_value": "60000"},
             {"symbol": "TQQQ", "asset_class": "us_equity", "side": "long", "market_value": "40000"}],
        )
        self.assertEqual(report["known_daily_index_exposure_proxy"], 1.8)
        self.assertEqual(report["simple_one_day_index_scenarios_pct"]["-10%"], -18.0)
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(report["currency"], "USD")
        self.assertEqual(report["other_symbols"], [])

    def test_untracked_symbols_make_risk_partial(self):
        report = alpaca.normalize(
            {"currency": "USD", "status": "ACTIVE", "equity": "100000", "cash": "50000"},
            [{"symbol": "QQQ", "side": "long", "market_value": "20000"},
             {"symbol": "SPY", "side": "long", "market_value": "30000"}],
        )
        self.assertEqual(report["scenario_coverage"], "PARTIAL_OTHER_HOLDINGS")
        self.assertEqual(report["other_symbols"], ["SPY"])

    def test_rejects_nonfinite_short_and_duplicate(self):
        a = {"currency": "USD", "status": "ACTIVE", "equity": "100000", "cash": "0"}
        with self.assertRaisesRegex(ValueError, "Invalid Alpaca numerical"):
            alpaca.normalize({**a, "equity": "NaN"}, [])
        with self.assertRaisesRegex(ValueError, "Short or negative"):
            alpaca.normalize(a, [{"symbol": "QQQ", "side": "short", "market_value": "-1"}])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            alpaca.normalize(a, [{"symbol": "QQQ", "market_value": "1"}, {"symbol": "QQQ", "market_value": "1"}])

    def test_credentials_never_in_output_or_error(self):
        def fail(_request, **kwargs):
            raise __import__("urllib.error", fromlist=["HTTPError"]).HTTPError(
                "https://paper-api.alpaca.markets/v2/account", 403, "denied", None, None
            )
        with patch.dict(os.environ, {"APCA_API_KEY_ID": "secret_key", "APCA_API_SECRET_KEY": "secret_secret"}):
            with self.assertRaises(RuntimeError) as cm:
                alpaca.paper_get("/v2/account", opener=fail)
            self.assertNotIn("secret_key", str(cm.exception))
            self.assertNotIn("secret_secret", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
