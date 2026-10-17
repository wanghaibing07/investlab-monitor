"""Rebuild missing old research evidence only when its original hash matches.

Legacy Vercel state ZIPs contained SQLite but not mature strategy JSON snapshots.
This module reconstructs historical snapshots using existing saved price rows and
the exact original source bundle; it never rewrites reports or accepts a mismatch.
Not included in the hashed mature model sources.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from . import mature
from .common import digest, write_json


def recover_verified_mature_snapshots(db):
    db = Path(db)
    folder = db.parent / "quant53" / "mature_snapshots"
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT report_json FROM monitor_runs").fetchall()
    contexts = {}
    for (value,) in rows:
        try:
            model = json.loads(value).get("mature_models") or {}
            ref = model.get("input_snapshot_sha256")
            if isinstance(ref, str) and len(ref) == 64 and all(c in "0123456789abcdef" for c in ref):
                contexts.setdefault(ref, model)
        except (ValueError, TypeError):
            continue

    if not contexts:
        return {"needed": 0, "recovered": 0, "unresolved": 0}
    need = {ref: ctx for ref, ctx in contexts.items() if not (folder / (ref + ".json")).is_file()}
    if not need:
        return {"needed": 0, "recovered": 0, "unresolved": 0}
    import monitor
    candles = monitor.price_data(db)
    current_sources = mature.sources()
    current_model_hash = digest(current_sources)
    recovered = 0
    for ref, ctx in sorted(need.items()):
        if ctx.get("model_sha256") != current_model_hash:
            continue
        end = ctx.get("data_end")
        if not isinstance(end, str):
            continue
        try:
            data = mature.dataset(candles, end)
            if data["data_sha256"] != ctx.get("data_sha256"):
                continue
            macro_expected = (ctx.get("macro") or {}).get("input_sha256")
            if macro_expected is None:
                macro = None
            else:
                macro = mature.macro_inputs(end)
                if digest(macro) != macro_expected:
                    continue
            rebuilt = digest({
                "data_sha256": data["data_sha256"],
                "macro_sha256": digest(macro) if macro else None,
                "model_sha256": current_model_hash,
            })
            if rebuilt != ref:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            write_json(folder / (ref + ".json"), {
                "dataset": data, "macro": macro,
                "snapshot_sha256": rebuilt,
                "source_bundle": current_sources,
            })
            recovered += 1
        except (ValueError, OSError, KeyError, TypeError):
            # Old evidence is retained as missing if it cannot be reproduced.
            continue
    return {"needed": len(need), "recovered": recovered,
            "unresolved": len(need) - recovered}
