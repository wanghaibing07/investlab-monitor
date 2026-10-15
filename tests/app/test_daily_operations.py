"""Daily operational truthfulness and opted-in alerting, without real network access."""
from pathlib import Path
from unittest.mock import patch
import json
import os
import tempfile
import unittest

from investlab import daily, service
from investlab.core import connection


class FakeSMTP:
    delivered = []
    def __init__(self, host, port, timeout):
        assert host == "smtp.example.test"
        assert port == 465
        assert timeout == 15
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def login(self, user, password):
        assert (user, password) == ("tester@example.test", "PRIVATE_SMTP_PASS")
    def send_message(self, msg):
        self.delivered.append(msg)


class DailyOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "user-home"
        service.init(self.home)
        with connection(self.home) as c:
            c.execute(
                "INSERT INTO portfolio_baselines "
                "(recorded_at,as_of,qqq_value_cny,cash_cny,tqqq_value_cny,qld_value_cny,note) "
                "VALUES (?,?,?,?,?,?,?)",
                ("2026-10-14T00:00:00+00:00", "2026-10-14", 6000, 4000, 0, 0, "Confirmed test fixture")
            )
        self.settings = {
            "INVESTLAB_SMTP_HOST": "smtp.example.test",
            "INVESTLAB_SMTP_USER": "tester@example.test",
            "INVESTLAB_SMTP_PASSWORD": "PRIVATE_SMTP_PASS",
            "INVESTLAB_ALERT_TO": "owner@example.test"
        }

    def cycle(self, *, qualified=True, macro_fails=False, research_pass=True,
              evaluator_fails=False, skip_macro=False, skip_evaluate=False):
        def worker(_home, command, **kwargs):
            if command == "refresh" and macro_fails:
                raise RuntimeError("provider credentials must not leak")
            if command == "evaluate" and evaluator_fails:
                raise RuntimeError("very private API message")
            return {"status": "OK", "research": {"new_outcomes": 0}}
        with (patch("investlab.daily.service.worker", side_effect=worker),
              patch("investlab.daily.service.run", return_value={
                  "review_id": "confirmed-report", "qualified_online": qualified}),
              patch("investlab.daily.service.audit", return_value={"status": "PASS"}),
              patch("investlab.daily.verification.verify", return_value={
                  "status": "PASS" if research_pass else "FAIL", "comparisons": [1,2,3]})):
            return daily.run_cycle(self.home, update_macro=not skip_macro,
                                  evaluate=not skip_evaluate)

    def test_success_evaluates_matured_outcomes_and_remains_no_trading(self):
        r = self.cycle()
        self.assertEqual(r["status"], "SUCCEEDED")
        self.assertEqual(r["steps"], {step: "SUCCEEDED" for step in daily.STEPS})
        self.assertEqual(r["verification_comparisons"], 3)
        self.assertTrue(r["qualified_online"])
        self.assertFalse(r["trading_enabled"])
        self.assertEqual(daily.current_status(self.home)["cycle_id"], r["cycle_id"])
        self.assertTrue((self.home / "data/daily-history" / (r["cycle_id"] + ".json")).exists())
        self.assertFalse(list(daily.outbox(self.home).glob("*.json")))

    def test_missing_account_gate_prevents_run(self):
        with connection(self.home) as c:
            c.execute("DELETE FROM portfolio_baselines")
        with patch("investlab.daily.service.run") as run:
            result = daily.run_cycle(self.home)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["issue_code"], "CONFIRMED_ACCOUNT_REQUIRED")
        run.assert_not_called()

    def test_macro_failure_is_degraded_not_success(self):
        r = self.cycle(macro_fails=True)
        self.assertEqual(r["status"], "DEGRADED")
        self.assertEqual(r["steps"]["online"], "SUCCEEDED")
        self.assertEqual(r["steps"]["macro"], "FAILED_OPTIONAL")
        self.assertEqual(r["issue_code"], "MACRO_REFRESH_UNAVAILABLE")
        self.assertNotIn("credentials", json.dumps(r))

    def test_unqualified_market_never_claims_ready(self):
        r = self.cycle(qualified=False)
        self.assertEqual(r["status"], "FAILED")
        self.assertEqual(r["issue_code"], "ONLINE_DATA_NOT_QUALIFIED")
        self.assertEqual(r["steps"]["online"], "SUCCEEDED")
        self.assertEqual(r["steps"]["audit"], "PENDING")
        self.assertFalse(r["qualified_online"])

    def test_evaluation_failure_keeps_previous_success_but_cycle_fails(self):
        r = self.cycle(evaluator_fails=True)
        self.assertEqual(r["status"], "FAILED")
        self.assertEqual(r["stage"], "evaluate")
        self.assertEqual(r["steps"]["verify"], "SUCCEEDED")
        self.assertEqual(r["steps"]["evaluate"], "FAILED")
        self.assertEqual(r["issue_code"], "FORWARD_EVALUATION_FAILED")
        self.assertNotIn("very private", json.dumps(r))
        self.assertNotIn("very private", json.dumps(json.loads(daily.status_file(self.home).read_text())))

    def test_skip_flags_explicitly_recorded(self):
        r = self.cycle(skip_macro=True, skip_evaluate=True)
        self.assertEqual(r["status"], "SUCCEEDED")
        self.assertEqual(r["steps"]["macro"], "SKIPPED")
        self.assertEqual(r["steps"]["evaluate"], "SKIPPED")

    def test_alert_deduplicates_and_sends_without_portfolio_data(self):
        r = self.cycle(qualified=False)
        q = self.cycle(qualified=False)
        self.assertEqual(r["alert_id"], q["alert_id"])
        self.assertEqual(len(list(daily.outbox(self.home).glob("*.json"))), 1)
        self.assertEqual(daily.dispatch_pending(self.home, env={})["status"], "NOT_CONFIGURED")
        FakeSMTP.delivered.clear()
        delivered = daily.dispatch_pending(self.home, env=self.settings, smtp_factory=FakeSMTP)
        self.assertEqual(delivered["status"], "OK")
        self.assertEqual(delivered["sent"], 1)
        self.assertEqual(len(FakeSMTP.delivered), 1)
        body = FakeSMTP.delivered[0].get_content()
        self.assertIn("ONLINE_DATA_NOT_QUALIFIED", body)
        self.assertNotIn("6000", body)
        self.assertNotIn("PRIVATE_SMTP_PASS", body)
        again = daily.dispatch_pending(self.home, env=self.settings, smtp_factory=FakeSMTP)
        self.assertEqual(again["sent"], 0)

    def test_demo_cannot_be_treated_as_actual_daily_monitor(self):
        home = self.home / "synthetic"
        service.init(home, demo=True)
        with patch("investlab.daily.service.run") as run:
            r = daily.run_cycle(home)
        self.assertEqual(r["status"], "FAILED")
        self.assertEqual(r["issue_code"], "SYNTHETIC_DEMO_NOT_ELIGIBLE")
        self.assertFalse(list(daily.outbox(home).glob("*.json")))
        run.assert_not_called()

    def test_unconfigured_status_is_explicit(self):
        self.assertEqual(daily.current_status(self.home)["status"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
