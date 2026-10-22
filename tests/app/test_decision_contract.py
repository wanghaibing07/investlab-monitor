from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from investlab import ledger, service
from investlab.core import connection, digest
from investlab.decision import account_evidence, decide, risk_budget_status, summary_lines
from investlab.engine.advisory import config, review_weights, trend_history


def budget():
    # Synthetic fixture, not a user's assessed risk tolerance.
    return dict(confirmed=True, source="SYNTHETIC_TEST", confirmed_at="2026-10-01",
                emergency_reserve_cny="2000", reserve_location="OUTSIDE_ACCOUNT",
                investable_capital_cny="10000", max_acceptable_loss_cny="2000",
                minimum_cash_cny="0", maximum_daily_ndx_exposure=1.8,
                maximum_tqqq_weight=.4)


def evidence(q=6000, t=0, cash=4000):
    a = dict(account="default", valuation_as_of="2026-10-21", valuation_id="fixture",
             baseline_scope="CURRENT_CONFIRMED_AGGREGATE", reported_activity=[],
             unreconciled_event_ids=[], reconciliation_required=False,
             current_values_cny={"QQQ": q, "TQQQ": t, "QLD": 0, "CASH": cash},
             blockers=[], shares=None, cost_basis=None, actual_pnl=None)
    a["evidence_id"] = digest(a)
    return a


def report(vol=15., trend=True, session="2026-10-21", current=None):
    current = current or {"QQQ": .6, "TQQQ": 0., "CASH": .4}
    target, reason = review_weights(current, trend, vol, config())
    return {"as_of_expected_session": session, "mode": "ONLINE_2_OF_2",
            "data_evidence_grade": "CURRENT_SINGLE_SOURCE",
            "market": {s: {"quality": "CURRENT", "last_date": session} for s in ("QQQ", "TQQQ")},
            "allocation_review": {"status": "ALLOCATION_REVIEW", "trend_active": trend,
                "qqq_vol20_pct": vol, "next_review_weights": target, "tactical_reason": reason}}


def partial():
    return dict(event_id="synthetic-reported-buy", account="default", occurred_at="2026-10-15",
                kind="REPORTED_BUY", currency="CNY", symbol="TQQQ", amount="375",
                confirmed=True, evidence_level="USER_REPORTED", source="SYNTHETIC_TEST",
                amount_is_approximate=True, note="Date and approximate amount only; price, shares and FX unknown.")


class DecisionTests(unittest.TestCase):
    def decision(self, r=None, a=None, b=None):
        return decide(r or report(), a or evidence(), b if b is not None else budget(), config())

    def test_add_is_capped_and_is_not_an_order(self):
        d = self.decision()
        self.assertEqual(d["status"], "ADD_REVIEW")
        self.assertAlmostEqual(d["target_weights"]["TQQQ"], .05)
        self.assertEqual(d["orders"], [])
        self.assertIsNone(d["executable_delta_cny"])
        self.assertFalse(d["execution_ready"])

    def test_25_pauses_and_35_exits(self):
        for vol, expected in [(24.999, "ADD_REVIEW"), (25., "PAUSE_ADD"),
                              (34.999, "PAUSE_ADD"), (35., "REDUCE_REVIEW")]:
            with self.subTest(vol=vol):
                r = report(vol=vol, current={"QQQ": .6, "TQQQ": .05, "CASH": .35})
                self.assertEqual(self.decision(r, evidence(6000, 500, 3500))["status"], expected)

    def test_exit_does_not_add_qqq_to_its_target(self):
        r = report(trend=False, current={"QQQ": .4, "TQQQ": .1, "CASH": .5})
        d = self.decision(r, evidence(4000, 1000, 5000))
        self.assertEqual(d["status"], "REDUCE_REVIEW")
        self.assertEqual(d["target_weights"]["QQQ"], .4)
        self.assertEqual(d["target_weights"]["TQQQ"], 0)

    def test_missing_position_still_exposes_verified_market_exit(self):
        a = evidence(); a.update(current_values_cny=None, blockers=["ACCOUNT_ACTIVITY_NOT_RECONCILED"])
        d = self.decision(report(trend=False), a)
        self.assertEqual(d["status"], "REDUCE_REVIEW")
        self.assertIsNone(d["target_weights"])
        self.assertFalse(d["review_ready"])

    def test_missing_budget_cannot_turn_target_into_add(self):
        d = self.decision(b={})
        self.assertEqual(d["status"], "PAUSE_ADD")
        self.assertIn("PERSONAL_RISK_BUDGET_NOT_CONFIRMED", d["blockers"])

    def test_bad_market_is_not_hold_or_add(self):
        for change in ("missing", "conflict", "offline", "nan"):
            r = report()
            if change == "missing": r["market"].pop("TQQQ")
            elif change == "conflict": r["data_evidence_grade"] = "SOURCE_CONFLICT"
            elif change == "offline": r["mode"] = "OFFLINE_CACHE"
            else: r["allocation_review"]["qqq_vol20_pct"] = float("nan")
            with self.subTest(change=change):
                self.assertEqual(self.decision(r)["status"], "DATA_BLOCKED")

    def test_rsi_cannot_replace_the_long_term_exit_rule(self):
        r = report()
        a = self.decision(r)
        r["rsi2"] = 99.; r["market"]["QQQ"]["sma20"] = 999999
        self.assertEqual(a, self.decision(r))

    def test_risk_envelope_precedes_target(self):
        b = budget(); b.update(maximum_daily_ndx_exposure=.7, minimum_cash_cny="4000")
        r = report(current={"QQQ": .6, "TQQQ": .2, "CASH": .2})
        d = self.decision(r, evidence(6000, 2000, 2000), b)
        self.assertEqual(d["status"], "REDUCE_REVIEW")
        self.assertNotIn("INCREASE_REVIEW", d["actions"].values())
        t = d["target_weights"]
        self.assertLessEqual(t["QQQ"] + 3 * t["TQQQ"], .7 + 1e-9)
        self.assertGreaterEqual(t["CASH"], .4 - 1e-9)

    def test_added_weight_respects_cash_and_exposure(self):
        b = budget(); b.update(maximum_daily_ndx_exposure=.66, minimum_cash_cny="3800")
        d = self.decision(b=b)
        self.assertLessEqual(d["target_weights"]["TQQQ"], .02 + 1e-9)
        self.assertGreaterEqual(d["target_weights"]["CASH"], .38 - 1e-9)

    def test_limited_investable_capital_is_not_spent_as_cash(self):
        b = budget(); b["investable_capital_cny"] = "6500"
        r = report(current={"QQQ": .6, "TQQQ": .1, "CASH": .3})
        d = self.decision(r, evidence(6000, 1000, 3000), b)
        self.assertEqual(d["status"], "REDUCE_REVIEW")
        self.assertGreaterEqual(d["target_weights"]["CASH"], .35 - 1e-9)

    def test_repeated_days_do_not_advance_the_same_proposal(self):
        a = self.decision()
        b = self.decision(report(session="2026-10-22"))
        self.assertEqual(a["proposal_id"], b["proposal_id"])
        self.assertEqual(a["target_weights"], b["target_weights"])

    def test_trend_buffer_keeps_prior_state_at_both_boundaries(self):
        p = deepcopy(config()); p["trend"].update(sma_sessions=2, entry_buffer=.03, exit_buffer=.02)
        # Exact integer boundaries: mean(97,103)=100 and mean(102,98)=100.
        rows = [{"adjusted_close": x} for x in [97., 103., 110., 108., 106., 104., 102.]]
        states = trend_history(rows, p)
        self.assertFalse(states[1]["active"])
        self.assertTrue(states[2]["active"])
        close = 98.
        states = trend_history(rows + [{"adjusted_close": close}], p)
        self.assertTrue(states[-1]["active"])
        states = trend_history(rows + [{"adjusted_close": close * .999}], p)
        self.assertFalse(states[-1]["active"])

    def test_unconfirmed_or_invalid_budget_is_rejected(self):
        for key, value in [("confirmed", False), ("minimum_cash_cny", "-1"),
                           ("maximum_daily_ndx_exposure", float("nan")),
                           ("investable_capital_cny", "1e9999"), ("source", "")]:
            b = budget(); b[key] = value
            with self.subTest(key=key):
                self.assertNotEqual(risk_budget_status(b, config())["status"], "CONFIRMED_ENVELOPE")


class ReportedActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name); service.init(self.home, demo=True)

    def test_report_import_is_idempotent_and_never_creates_a_fill(self):
        first = ledger.import_events(self.home, [partial()])
        second = ledger.import_events(self.home, [partial()])
        self.assertEqual((first["inserted"], second["inserted"]), (1, 0))
        account = ledger.account(self.home, "default")
        self.assertEqual(account["cash"], {})
        self.assertEqual(account["positions"], [])
        self.assertEqual(len(account["reported_activity"]), 1)
        self.assertFalse(account["position_detail_complete"])
        with connection(self.home) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM journal_events WHERE json_extract(event_json,'$.kind')='BUY'").fetchone()[0], 0)

    def test_partial_event_rejects_fake_price_or_future_date(self):
        for change in ({"price": "100"}, {"quantity": "1"}, {"occurred_at": "2099-01-01"},
                       {"evidence_level": "BROKER_CONFIRMED"}, {"occurred_at": "2026-10-15T00:00:00Z"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ledger.import_events(self.home, [dict(partial(), **change)])

    def test_conflicting_duplicate_rolls_back(self):
        ledger.import_events(self.home, [partial()])
        with self.assertRaises(ValueError):
            ledger.import_events(self.home, [dict(partial(), amount="376")])
        self.assertEqual(ledger.account(self.home, "default")["event_count"], 1)

    def test_report_invalidates_a_zero_aggregate_without_rewriting_it(self):
        ledger.import_events(self.home, [partial()])
        baseline = {"as_of": "2026-10-14", "qqq_value_cny": 60000, "cash_cny": 40000, "tqqq_value_cny": 0, "qld_value_cny": 0}
        a = account_evidence(self.home / "data/monitor.sqlite3", baseline, "2026-10-21")
        self.assertTrue(a["reconciliation_required"])
        self.assertIsNone(a["current_values_cny"])
        self.assertEqual(a["reported_activity"][0]["amount"], "375")
        self.assertIsNone(a["actual_pnl"])
        self.assertEqual(baseline["tqqq_value_cny"], 0)

    def test_complete_valuation_can_reconcile_report_but_not_create_fill(self):
        ledger.import_events(self.home, [partial()])
        value = dict(valuation_id="fixture-v2", account="default", as_of="2026-10-21",
                     currency="CNY", values={"QQQ": "6000", "QLD": "0", "TQQQ": "350", "CASH": "3650"},
                     confirmed=True, note="SYNTHETIC_TEST", reconciles_event_ids=[partial()["event_id"]])
        ledger.valuation(self.home, value)
        a = account_evidence(self.home / "data/monitor.sqlite3",
                             dict(as_of=value["as_of"], qqq_value_cny=6000, qld_value_cny=0,
                                  tqqq_value_cny=350, cash_cny=3650), "2026-10-21")
        self.assertFalse(a["reconciliation_required"])
        self.assertEqual(a["current_values_cny"]["TQQQ"], 350)
        self.assertIsNone(a["shares"])

    def test_valuation_cannot_reconcile_unknown_event(self):
        value = dict(valuation_id="fixture-v2", account="default", as_of="2026-10-21",
                     currency="CNY", values={"QQQ": "6000", "QLD": "0", "TQQQ": "350", "CASH": "3650"},
                     confirmed=True, note="SYNTHETIC_TEST", reconciles_event_ids=["missing"])
        with self.assertRaises(ValueError): ledger.valuation(self.home, value)

    def test_summary_never_calls_partial_report_zero_or_an_add(self):
        ledger.import_events(self.home, [partial()])
        a = account_evidence(self.home / "data/monitor.sqlite3",
                             dict(as_of="2026-10-14", qqq_value_cny=60000, qld_value_cny=0,
                                  tqqq_value_cny=0, cash_cny=40000), "2026-10-21")
        d = decide(report(), a, None, config())
        text = "\n".join(summary_lines(d, a))
        self.assertIn("不按零持仓判断", text)
        self.assertNotIn("增加至", text)
        self.assertIsNone(d["target_weights"])

    def test_current_journal_overrides_saved_report_immediately(self):
        service.run(self.home)
        ledger.import_events(self.home, [partial()])
        value = service.latest(self.home)
        self.assertTrue(value["account_state"]["reconciliation_required"])
        self.assertFalse(value["is_actionable"])
        self.assertEqual(value["decision"]["status"], "DATA_BLOCKED")

