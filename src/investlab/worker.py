"""Isolated compatibility process for the validated v5 numerical engines."""
from pathlib import Path
import datetime as dt
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))
import monitor as m  # noqa: E402


def main():
    command = sys.argv[1]
    if command == "bootstrap":
        m.init_db()
        result = {"database": str(m.DB)}
    elif command == "run":
        online = "--online" in sys.argv
        now = None
        if "--demo" in sys.argv:
            now = dt.datetime(2026, 10, 15, 6, tzinfo=dt.timezone.utc)
        if online:
            # Install the strict boundary only in the new runtime.
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from investlab.providers import yahoo
            m.yahoo_download = yahoo
        report = m.build_report(online=online, independent_check="--independent-check" in sys.argv, now=now)
        saved = m.save_report(report)
        result = {"run_id": saved["run_id"], "mode": report["mode"], "report": report,
                  "backup": saved["database_backup"]}
    elif command == "audit":
        result = m.audit()
    elif command == "refresh":
        from research import mature
        result = mature.refresh()
    elif command == "research":
        from research import mature, quant
        result = {"mature": mature.run(m.DB), "quant": quant.run(m.DB)}
    elif command == "evaluate":
        import strategy
        from research import shadow, quant
        result = {"legacy": strategy.evaluate(m.DB), "research": shadow.evaluate(m.DB), "quant": quant.evaluate(m.DB)}
    else:
        raise ValueError("Unknown worker command")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
