"""Command line interface; every writer holds the same process lock."""
from pathlib import Path
import argparse
import json
import sys
import sqlite3
import subprocess
from . import __version__
from .core import atomic, code_identity, connection, home_path, lock, utcnow
from . import ledger, service, storage, verification


def parser():
    p = argparse.ArgumentParser(description="InvestLab：QQQ/TQQQ长期监控与研究")
    p.add_argument("--home", help="私有运行数据目录；默认~/.local/share/investlab")
    p.add_argument("--json", action="store_true", help="输出机器可读JSON")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="初始化空账户或虚构演示")
    init.add_argument("--demo", action="store_true")
    sub.add_parser("migrate", help="迁移v5.5完整项目").add_argument("source")
    run = sub.add_parser("run", help="计算、保存并核验备份")
    run.add_argument("--online", action="store_true")
    run.add_argument("--independent-check", action="store_true")
    run.add_argument("--require-current", action="store_true")
    for name in ("audit", "research", "evaluate", "verify", "freeze", "doctor"):
        sub.add_parser(name)
    sub.add_parser("refresh-macro", help="更新四组宏观解释变量")
    b = sub.add_parser("backup"); b.add_argument("--output")
    r = sub.add_parser("restore"); r.add_argument("archive"); r.add_argument("--to", required=True)
    serve = sub.add_parser("serve"); serve.add_argument("--port", type=int, default=8765)
    ev = sub.add_parser("ledger-import"); ev.add_argument("file")
    ac = sub.add_parser("account"); ac.add_argument("name", default="default", nargs="?")
    val = sub.add_parser("valuation-import"); val.add_argument("file")
    export = sub.add_parser("export"); export.add_argument("--output", required=True)
    sub.add_parser("summary")
    return p


def main(argv=None):
    args = parser().parse_args(argv); home = home_path(args.home); cmd = args.command
    try:
        if cmd == "serve":
            service.settings(home)
            from .server import serve
            serve(home, args.port); return 0
        if cmd == "account": result = ledger.account(home, args.name)
        elif cmd == "summary":
            v = service.latest(home)
            if not v: raise ValueError("尚无已保存报告")
            print(service.plain_summary(v)); return 0
        elif cmd == "doctor":
            cfg = service.settings(home)
            with connection(home, readonly=True) as c:
                integrity = c.execute("PRAGMA quick_check").fetchone()[0]
                account = c.execute("SELECT count(*) FROM portfolio_baselines").fetchone()[0]
            result = {"version": __version__, "python": sys.version.split()[0], "home": str(home),
                      "sqlite": integrity, "confirmed_baselines": account, "demo": cfg["demo"],
                      "target": cfg["target"], "code_sha256": code_identity(), "trading_enabled": False}
        elif cmd == "restore":
            target = home_path(args.to)
            # No target lock file before the empty-directory check.
            with lock(home): result = storage.restore(args.archive, target)
        else:
            with lock(home):
                if cmd == "init": result = service.init(home, args.demo)
                elif cmd == "migrate": result = storage.migrate(args.source, home)
                elif cmd == "run": result = service.run(home, online=args.online, independent=args.independent_check)
                elif cmd == "audit": result = service.audit(home)
                elif cmd == "research": result = service.worker(home, "research", timeout=1200)
                elif cmd == "refresh-macro": result = service.worker(home, "refresh")
                elif cmd == "evaluate": result = service.worker(home, "evaluate")
                elif cmd == "verify": result = verification.verify(home)
                elif cmd == "freeze": result = verification.freeze(home)
                elif cmd == "backup": result = storage.backup(home, args.output)
                elif cmd == "ledger-import": result = ledger.import_events(home, json.loads(Path(args.file).read_text()))
                elif cmd == "valuation-import": result = ledger.valuation(home, json.loads(Path(args.file).read_text()))
                elif cmd == "export":
                    result = {"exported_at": utcnow(), "latest": service.latest(home)}
                    atomic(Path(args.output), result)
                    result = {"exported": str(Path(args.output).resolve()), "contains_private_account_data": True}
                else: raise ValueError("Unknown command")
        if cmd == "run" and not args.json:
            print(result["summary"])
            print("本地保存与备份：已核验。")
        elif cmd == "verify" and not args.json:
            print(json.dumps({k: v for k, v in result.items() if k not in ("curves", "comparisons")}, ensure_ascii=False, indent=2))
            print(f'独立复算：{len(result["comparisons"])}组规则与费用；完整结果在data/verification.json。')
        else: print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        if cmd in ("audit", "verify") and result["status"] != "PASS": return 2
        if cmd == "run" and args.require_current and not result["qualified_online"]: return 2
        return 0
    except (ValueError, RuntimeError, OSError, TimeoutError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print("未完成：" + str(exc), file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
