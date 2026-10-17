"""Recover historical research input snapshots only with exact source and data hashes."""
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from research import mature
from research.common import digest
from research.recovery import recover_verified_mature_snapshots


class RebuildMatureEvidenceTests(unittest.TestCase):
    def _setup(self, temp, *, bad_hash=False):
        db = Path(temp)/"monitor.sqlite3"
        semantics={"dates":["2026-10-15","2026-10-16"],
                   "prices":{"QQQ":[600.0,605.0],"TQQQ":[79.0,80.0]}}
        data={**semantics,"data_sha256":digest(semantics),"quality":"CURRENT_SINGLE_PROVIDER"}
        bundle=mature.sources()
        model=digest(bundle)
        source_input=digest({"data_sha256":data["data_sha256"],
                             "macro_sha256":None,"model_sha256":model})
        ref=("1"*64 if bad_hash else source_input)
        model_info={"input_snapshot_sha256":ref,"data_sha256":data["data_sha256"],
                    "model_sha256":model,"data_end":"2026-10-16",
                    "macro":{"input_sha256":None}}
        with sqlite3.connect(db) as con:
            con.execute("CREATE TABLE monitor_runs (report_json TEXT)")
            con.execute("INSERT INTO monitor_runs VALUES (?)",
                        (json.dumps({"mature_models":model_info}),))
        return db, data, ref

    def test_reconstructs_exact_historical_evidence_and_passes_original_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, data, ref = self._setup(tmp)
            with (patch("monitor.price_data",return_value={}),
                  patch.object(mature,"dataset",return_value=data)):
                result=recover_verified_mature_snapshots(db)
            self.assertEqual(result,{"needed":1,"recovered":1,"unresolved":0})
            self.assertEqual(mature.audit(db)["missing_run_input_snapshots"],0)
            self.assertEqual(mature.audit(db)["snapshot_hash_errors"],0)
            # Re-running does not overwrite or double count restored evidence.
            self.assertEqual(recover_verified_mature_snapshots(db)["needed"],0)
            self.assertTrue((db.parent/"quant53/mature_snapshots"/(ref+".json")).is_file())

    def test_original_hash_mismatch_must_remain_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, data, ref = self._setup(tmp,bad_hash=True)
            with (patch("monitor.price_data",return_value={}),
                  patch.object(mature,"dataset",return_value=data)):
                result=recover_verified_mature_snapshots(db)
            self.assertEqual(result["unresolved"],1)
            self.assertEqual(result["recovered"],0)
            self.assertEqual(mature.audit(db)["missing_run_input_snapshots"],1)
            self.assertFalse((db.parent/"quant53/mature_snapshots"/(ref+".json")).exists())


if __name__=="__main__":
    unittest.main()
