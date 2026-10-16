"""Decision summary must fail closed when user state or live evidence is stale."""
import copy
import unittest

from investlab.brief import decision_brief


def example():
    account={"account_initialized": True, "as_of":"2026-10-14",
             "values":{"QQQ":"6000","TQQQ":"500","QLD":"0","CASH":"3500"}}
    run={"status":"SUCCEEDED","qualified_online":True,"audit":"PASS",
         "research_verification":"PASS","completed_at":"2026-10-15T01:30:00Z"}
    report={"demo":False,"qualified_online":True,"session_date":"2026-10-14",
            "created_at":"2026-10-15T01:30:00Z","review_id":"test-reviewed",
            "is_actionable":True,"market_session_current":True,
            "operation":{"status":"SUCCEEDED"},"latest_attempt":{"status":"SUCCEEDED"},
            "portfolio":{"as_of":"2026-10-14","qqq_value_cny":6000,
                         "tqqq_value_cny":500,"qld_value_cny":0,"cash_cny":3500},
            "review":{"status":"ALLOCATION_REVIEW",
                      "actions":{"QQQ":"HOLD","TQQQ":"INCREASE_REVIEW","QLD":"HOLD","CASH":"REDUCE_REVIEW"},
                      "next_review_weights":{"QQQ":.6,"TQQQ":.075,"QLD":0.0,"CASH":.325},
                      "strategic_reference":{"QQQ":.6,"TQQQ":.4,"QLD":0.0,"CASH":0.0},
                      "tactical_reason":"TREND_ENTRY_STEP","trend_active":True,
                      "qqq_vol20_pct":22.4,"full_reference_daily_exposure":1.8,
                      "next_review_daily_exposure":.825,
                      "entry_conditions":[
                         {"met":True,"rule":"QQQ 趋势开启"},
                         {"met":True,"rule":"波动低于25%"},
                         {"met":False,"rule":"仓位存在调整条件"}
                      ]},
            "risk":{"annual_volatility":.25,"tqqq_variance_share":.62}}
    return account,run,report


class DecisionBriefTests(unittest.TestCase):
    def test_verified_fresh_account_generates_distinct_manual_actions(self):
        account,run,report=example()
        out=decision_brief(account,run,report)
        self.assertEqual(out["status"],"ACTION_REVIEW")
        self.assertTrue(out["actionable"])
        self.assertEqual(out["priority"],"REVIEW")
        self.assertTrue(out["verified_run"])
        self.assertFalse(out["trading_enabled"])
        self.assertTrue(out["manual_only"])
        self.assertEqual([v["action"] for v in out["steps"]],["HOLD","INCREASE_REVIEW"])
        self.assertEqual(out["steps"][1]["reference_weight"],.075)
        self.assertEqual(out["steps"][1]["change_pp"],2.5)
        self.assertEqual(out["metrics"]["trend_active"],True)
        self.assertEqual(out["metrics"]["qqq_vol20_pct"],22.4)
        self.assertEqual(out["report_session"],"2026-10-14")
        self.assertEqual(out["conditions"][2]["met"],False)
        self.assertIn("本人决定",out["next_step"])

    def test_confirmed_account_produces_review_amounts_not_trade_orders(self):
        account, run, report = example()
        result = decision_brief(account, run, report)
        self.assertTrue(result["actionable"])
        self.assertTrue(result["manual_only"])
        self.assertFalse(result["trading_enabled"])
        self.assertEqual(result["portfolio_total_cny"], 10000)
        self.assertEqual(result["cash_current_cny"], 3500)
        self.assertEqual(result["steps"][0]["current_value_cny"], 6000)
        self.assertEqual(result["steps"][0]["estimated_difference_cny"], 0)
        self.assertEqual(result["steps"][1]["current_value_cny"], 500)
        self.assertEqual(result["steps"][1]["step_reference_value_cny"], 750)
        self.assertEqual(result["steps"][1]["estimated_difference_cny"], 250)
        self.assertEqual(result["cash_step_reference_cny"], 3250)
        self.assertEqual(result["estimated_cash_change_cny"], -250)
        self.assertTrue(result["amounts_are_illustrative"])

    def test_stale_verified_run_keeps_historical_observation_not_trade_steps(self):
        account, run, report = example()
        report["market_session_current"] = False
        report["is_actionable"] = False
        result = decision_brief(account, run, report)
        self.assertEqual(result["status"], "MARKET_STALE")
        self.assertFalse(result["actionable"])
        self.assertEqual(result["steps"], [])
        self.assertTrue(result["historical_signal"]["not_current_advice"])
        self.assertEqual(result["historical_signal"]["session"], "2026-10-14")
        self.assertIn("分步复核", result["historical_signal"]["headline"])
        self.assertNotIn("estimated_difference_cny", result)

    def test_account_mismatch_can_show_historical_observation_but_no_steps(self):
        account, run, report = example()
        account["values"]["TQQQ"] = "700"
        account["values"]["CASH"] = "3300"
        result = decision_brief(account, run, report)
        self.assertEqual(result["status"], "ACCOUNT_MISMATCH")
        self.assertFalse(result["actionable"])
        self.assertEqual(result["steps"], [])
        self.assertIsNotNone(result["historical_signal"])
        self.assertTrue(result["historical_signal"]["not_current_advice"])

    def test_failed_or_unverified_run_never_exports_previous_historical_signal(self):
        account, run, report = example()
        run["status"] = "FAILED"
        result = decision_brief(account, run, report)
        self.assertIsNone(result["historical_signal"])
        run["status"] = "SUCCEEDED"
        run["qualified_online"] = False
        result = decision_brief(account, run, report)
        self.assertIsNone(result["historical_signal"])

    def test_verified_tech_does_not_mean_market_current(self):
        account,run,report=example()
        report["market_session_current"]=False
        report["is_actionable"]=False
        out=decision_brief(account,run,report)
        self.assertEqual(out["status"],"MARKET_STALE")
        self.assertFalse(out["actionable"])
        self.assertEqual(out["steps"],[])
        self.assertIsNone(out["step_weights"])

    def test_failed_run_ignores_previous_stored_research(self):
        account,run,report=example()
        run["status"]="FAILED"
        out=decision_brief(account,run,report)
        self.assertEqual(out["status"],"LAST_RUN_FAILED")
        self.assertFalse(out["actionable"])
        self.assertIsNone(out["step_weights"])

    def test_report_account_amount_mismatch_blocks_allocation(self):
        account,run,report=example()
        account["values"]["TQQQ"]="0"
        account["values"]["CASH"]="4000"
        out=decision_brief(account,run,report)
        self.assertEqual(out["status"],"ACCOUNT_MISMATCH")
        self.assertEqual(out["steps"],[])
        self.assertFalse(out["actionable"])

    def test_report_account_date_mismatch_blocks_allocation(self):
        account,run,report=example()
        account["as_of"]="2026-10-16"
        out=decision_brief(account,run,report)
        self.assertEqual(out["status"],"ACCOUNT_MISMATCH")
        self.assertEqual(out["steps"],[])

    def test_missing_research_after_technical_success_does_not_guess(self):
        account,run,_=example()
        out=decision_brief(account,run,None)
        self.assertEqual(out["status"],"REPORT_UNAVAILABLE")
        self.assertFalse(out["actionable"])

    def test_synthetic_research_is_never_actionable(self):
        account,run,report=example()
        report["demo"]=True
        out=decision_brief(account,run,report)
        self.assertEqual(out["status"],"REPORT_UNAVAILABLE")

    def test_model_blockers_do_not_create_trade_steps(self):
        account,run,report=example()
        report["review"]["status"]="DATA_BLOCKED"
        out=decision_brief(account,run,report)
        self.assertEqual(out["status"],"MODEL_BLOCKED")
        self.assertFalse(out["actionable"])

    def test_model_weight_total_and_leg_directions_must_agree(self):
        a,r,p=example()
        p["review"]["next_review_weights"]["QQQ"]=.5
        out=decision_brief(a,r,p)
        self.assertEqual(out["status"],"MODEL_BLOCKED")
        self.assertFalse(out["actionable"])
        a,r,p=example()
        p["review"]["actions"]["TQQQ"]="HOLD"
        out=decision_brief(a,r,p)
        self.assertEqual(out["status"],"MODEL_BLOCKED")
        self.assertEqual(out["steps"],[])

    def test_missing_account_requires_real_confirmation(self):
        _,run,report=example()
        out=decision_brief({"account_initialized":False},run,report)
        self.assertEqual(out["status"],"NEEDS_ACCOUNT")

    def test_holding_signal_is_not_repeated_buys(self):
        account,run,report=example()
        report["review"]["actions"]["TQQQ"]="HOLD"
        report["review"]["next_review_weights"]["TQQQ"]=.05
        report["review"]["next_review_weights"]["CASH"]=.35
        out=decision_brief(account,run,report)
        self.assertEqual(out["priority"],"HOLD")
        self.assertEqual(out["steps"][1]["action"],"HOLD")
        self.assertEqual(out["steps"][1]["reference_weight"],.05)

    def test_incomplete_raw_status_does_not_give_advice(self):
        a,r,p=example()
        r["research_verification"]="IN_PROGRESS"
        out=decision_brief(a,r,p)
        self.assertEqual(out["status"],"NEEDS_VERIFIED_RUN")
        self.assertFalse(out["verified_run"])

    def test_actual_values_are_not_baked_into_reference(self):
        account,run,report=example()
        values=copy.deepcopy(account["values"])
        values["QQQ"]="5700";values["CASH"]="3800"
        account["values"]=values
        report["portfolio"]["qqq_value_cny"]=5700
        report["portfolio"]["cash_cny"]=3800
        report["review"]["actions"]["QQQ"]="INCREASE_REVIEW"
        out=decision_brief(account,run,report)
        self.assertTrue(out["actionable"])
        self.assertAlmostEqual(out["current_weights"]["QQQ"],.57)


if __name__=="__main__":
    unittest.main()
