"""Daily automation: no account writes, generation-bound idempotency, retry alarms."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from investlab import automation

VERSION="state/20261016T103339961525Z-"+"a"*32+".zip"
ACCOUNT={"account_initialized": True, "state_version":VERSION,
         "as_of":"2026-10-16","values":{"QQQ":"12000","TQQQ":"500","QLD":"0","CASH":"7500"}}
PASS={"qualified_online":True,"audit":"PASS","research_verification":"PASS",
      "review_id":"verified-research-only"}


class DailyAutomationTests(unittest.TestCase):
    def test_nyse_session_calendar_includes_latest_completed_market_day(self):
        from zoneinfo import ZoneInfo
        # 00:00 Tuesday UTC is 20:00 Monday in New York during DST.
        self.assertEqual(automation.nyse_session(datetime(2026,10,20,tzinfo=timezone.utc)), "2026-10-19")
        # 18:00 UTC Monday is 14:00 NY: the US session has not closed.
        self.assertIsNone(automation.nyse_session(datetime(2026,10,19,18,tzinfo=timezone.utc)))
        # Sunday UTC is Saturday NY time; no completed new trading session.
        self.assertIsNone(automation.nyse_session(datetime(2026,10,18,tzinfo=timezone.utc)))
        # Christmas Day 2026 is a market holiday.
        self.assertIsNone(automation.nyse_session(datetime(2026,12,26,tzinfo=timezone.utc)))
        # Zoneinfo works through the EST/EDT transition.
        self.assertEqual(automation.nyse_session(datetime(2026,11,3,tzinfo=timezone.utc)), "2026-11-02")

    def test_published_daily_research_never_writes_account_state(self):
        with (patch("investlab.automation.cloud.read_private_account",
                    new=AsyncMock(return_value=ACCOUNT)),
              patch("investlab.automation._last_receipt",
                    new=AsyncMock(return_value=None)),
              patch("investlab.automation._claim",
                    new=AsyncMock(return_value=True)) as claim,
              patch("investlab.automation.cloud.load_private_home",
                    new=AsyncMock(return_value=True)) as restore,
              patch("investlab.automation._run_sync",return_value=PASS),
              patch("investlab.automation.cloud._list",
                    new=AsyncMock(return_value=[SimpleNamespace(pathname=VERSION)])),
              patch("investlab.automation.cloud._make_archive",return_value=b"zip bytes"),
              patch("investlab.automation.cloud._write",
                    new=AsyncMock(return_value="computed/test.zip")) as writes,
              patch("investlab.automation.cloud.save_private_home",
                    new=AsyncMock()) as state_write,
              patch("investlab.automation._persist_receipt",
                    new=AsyncMock(side_effect=lambda r:r))):
            report=asyncio.run(automation.execute_once(current_session="2026-10-16"))
        self.assertEqual(report["status"],"SUCCEEDED")
        self.assertEqual(report["account_state_version"],VERSION)
        self.assertEqual(report["computed_version"],"computed/test.zip")
        self.assertTrue(report["qualified_online"])
        self.assertFalse(report["trading_enabled"])
        claim.assert_awaited_once_with("2026-10-16","primary",VERSION)
        restore.assert_awaited_once()
        writes.assert_awaited_once()
        self.assertEqual(writes.await_args.args[0],"computed")
        state_write.assert_not_awaited()

    def test_duplicate_receipt_prevents_second_execution(self):
        receipt={"status":"SUCCEEDED","scheduled_session":"2026-10-16",
                 "account_state_version":VERSION}
        with (patch("investlab.automation.cloud.read_private_account",
                    new=AsyncMock(return_value=ACCOUNT)),
              patch("investlab.automation._last_receipt",
                    new=AsyncMock(return_value=receipt)),
              patch("investlab.automation._claim",new=AsyncMock()) as claim):
            result=asyncio.run(automation.execute_once(current_session="2026-10-16"))
        self.assertEqual(result["status"],"ALREADY_VERIFIED")
        claim.assert_not_awaited()

    def test_account_changed_midrun_cannot_publish_computed_success(self):
        other="state/20261016T193339961525Z-"+"b"*32+".zip"
        async def keep_report(r): return r
        with (patch("investlab.automation.cloud.read_private_account",
                    new=AsyncMock(return_value=ACCOUNT)),
              patch("investlab.automation._last_receipt",new=AsyncMock(return_value=None)),
              patch("investlab.automation._claim",new=AsyncMock(return_value=True)),
              patch("investlab.automation.cloud.load_private_home",new=AsyncMock(return_value=True)),
              patch("investlab.automation._run_sync",return_value=PASS),
              patch("investlab.automation.cloud._list",
                    new=AsyncMock(return_value=[SimpleNamespace(pathname=other)])),
              patch("investlab.automation.cloud._write",new=AsyncMock()) as write,
              patch("investlab.automation._persist_receipt",new=AsyncMock(side_effect=keep_report))):
            result=asyncio.run(automation.execute_once(current_session="2026-10-16"))
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["issue_code"],"SCHEDULED_RESEARCH_FAILED")
        write.assert_not_awaited()

    def test_retry_checks_existing_success_before_execution(self):
        with (patch("investlab.automation.nyse_session",return_value="2026-10-16"),
              patch("investlab.automation._last_receipt",
                    new=AsyncMock(return_value={"status":"SUCCEEDED",
                      "scheduled_session":"2026-10-16","account_state_version":VERSION})),
              patch("investlab.automation.cloud.read_private_account",
                    new=AsyncMock(return_value=ACCOUNT)),
              patch("investlab.automation.execute_once",new=AsyncMock()) as run):
            result=asyncio.run(automation.daily_watchdog())
        self.assertEqual(result["status"],"VERIFIED")
        run.assert_not_awaited()

    def test_retry_alert_requires_real_delivery(self):
        with (patch("investlab.automation.nyse_session",return_value="2026-10-16"),
              patch("investlab.automation._last_receipt",new=AsyncMock(return_value=None)),
              patch("investlab.automation.cloud.read_private_account",
                    new=AsyncMock(return_value=ACCOUNT)),
              patch("investlab.automation.execute_once",
                    new=AsyncMock(return_value={"status":"FAILED",
                                                 "issue_code":"TWO_SOURCES_FAILED"})) as run,
              patch("investlab.automation._send_failure_email",
                    return_value="NOT_CONFIGURED") as send):
            result=asyncio.run(automation.daily_watchdog())
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["alert_delivery"],"NOT_CONFIGURED")
        run.assert_awaited_once_with("retry",current_session="2026-10-16")
        send.assert_called_once()

    def test_scheduler_readback_failure_is_not_claimed_success(self):
        with (patch("investlab.automation.cloud.read_private_account",new=AsyncMock(return_value=ACCOUNT)),
              patch("investlab.automation._last_receipt",new=AsyncMock(return_value=None)),
              patch("investlab.automation._claim",new=AsyncMock(return_value=True)),
              patch("investlab.automation.cloud.load_private_home",new=AsyncMock(return_value=True)),
              patch("investlab.automation._run_sync",return_value=PASS),
              patch("investlab.automation.cloud._list",new=AsyncMock(return_value=[
                    SimpleNamespace(pathname=VERSION)])),
              patch("investlab.automation.cloud._make_archive",return_value=b"zip"),
              patch("investlab.automation.cloud._write",
                    new=AsyncMock(return_value="computed/test.zip")),
              patch("investlab.automation._persist_receipt",
                    new=AsyncMock(side_effect=RuntimeError("storage unavailable")))):
            result=asyncio.run(automation.execute_once(current_session="2026-10-16"))
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["issue_code"],"SCHEDULED_RECEIPT_PERSIST_FAILED")


    def test_live_diagnostic_does_not_mutate_confirmed_account_or_production_reports(self):
        with (patch("investlab.automation.cloud.read_private_account",
                    new=AsyncMock(return_value=ACCOUNT)),
              patch("investlab.automation.cloud.load_private_home",
                    new=AsyncMock(return_value=True)),
              patch("investlab.automation._run_sync",
                    side_effect=ValueError("Live quotes were not independently qualified")),
              patch("investlab.automation.cloud._write",new=AsyncMock()) as write,
              patch("investlab.automation.cloud.save_private_report",
                    new=AsyncMock()) as receipt,
              patch("investlab.automation.cloud.save_private_home",
                    new=AsyncMock()) as state):
            result=asyncio.run(automation.diagnose_readonly())
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["failure_category"],"MARKET_DATA_NOT_QUALIFIED")
        self.assertFalse(result["saved_to_production"])
        self.assertFalse(result["trading_enabled"])
        write.assert_not_awaited()
        receipt.assert_not_awaited()
        state.assert_not_awaited()

    def test_diagnostic_market_evidence_redacts_fetch_exception_messages(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)
            (home/"data").mkdir()
            (home/"data"/"last_online_attempt.json").write_text(json.dumps({
                "market_dates":{"QQQ":"2026-10-15","TQQQ":None},
                "fetch":{"QQQ":{"online_success":False,"attempts":[{
                   "source":"YAHOO_QUERY1","status":"ERROR",
                   "reason":"confidential-secret SHOULD-NOT-LEAK"}]},
                 "TQQQ":{"online_success":True,"attempts":[],
                   "independent_status":"DATE_MISMATCH"}}
            }))
            result=automation._market_failure_facts(home)
        self.assertFalse(result["QQQ"]["online_success"])
        self.assertEqual(result["QQQ"]["latest_price_session"],"2026-10-15")
        self.assertEqual(result["TQQQ"]["independent_source"],"DATE_MISMATCH")
        self.assertNotIn("confidential-secret",json.dumps(result))



if __name__=="__main__":
    unittest.main()
