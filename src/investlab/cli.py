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
    serve = sub.add_parser("serve"); serve.add_argument("--port", type=int, default=8765); serve.add_argument("--public-demo", action="store_true", help="仅允许使用虚构账户的公开只读展示"); serve.add_argument("--local-edit", action="store_true", help="仅在本机开启需要明确确认的估值编辑和重新计算")
    ev = sub.add_parser("ledger-import"); ev.add_argument("file")
    ac = sub.add_parser("account"); ac.add_argument("name", default="default", nargs="?")
    val = sub.add_parser("valuation-import"); val.add_argument("file")
    export = sub.add_parser("export"); export.add_argument("--output", required=True)
    sub.add_parser("alpaca-paper-snapshot", help="只读保存Alpaca模拟账户风险快照（USD）")
    sub.add_parser("alpaca-quote-check", help="用Alpaca IEX收盘样本核对本机最近完整行情（独立背景证据，不改信号）")
    cycle = sub.add_parser("daily-cycle", help="完整私有每日执行：行情、审计、复算、效果到期评价及失败记录")
    cycle.add_argument("--skip-macro", action="store_true")
    cycle.add_argument("--skip-evaluate", action="store_true")
    sub.add_parser("daily-status", help="查看上一次私有每日运行结果")
    sub.add_parser("notify-pending", help="用私有SMTP配置发送待发失败或降级通知")
    sub.add_parser("summary")
    risk = sub.add_parser("shadow-risk", help="独立影子风险研究；只读账本，输出到新目录")
    risk.add_argument("--output", required=True)
    risk.add_argument("--source-commit", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv); home = home_path(args.home); cmd = args.command
    try:
        if cmd == "shadow-risk":
            from .risk_study import study
            result = study(home, args.output, args.source_commit)
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        elif cmd == "serve":
            service.settings(home)
            from .server import serve
            serve(home, args.port, public_demo=args.public_demo, local_edit=args.local_edit); return 0
        if cmd == "alpaca-paper-snapshot":
            from .integrations.alpaca import snapshot
            record = snapshot()
            output = home / "data" / "alpaca-paper-snapshot.json"
            atomic(output, record)
            result = {
                "status": record["status"],
                "source": record["source"],
                "saved": str(output),
                "currency": record["currency"],
                "equity_usd": record["equity_usd"],
                "known_weights": record["known_weights"],
                "known_daily_index_exposure_proxy": record["known_daily_index_exposure_proxy"],
                "scenario_coverage": record["scenario_coverage"],
                "other_symbols": record["other_symbols"],
                "execution_enabled": False
            }
        elif cmd == "alpaca-quote-check":
            from .integrations.alpaca_market import check
            with lock(home):
                report = check(home)
                path = home / "data" / "alpaca-quote-check.json"
                atomic(path, report)
            result = {**report, "saved": str(path)}
        elif cmd == "daily-status":
            from .daily import current_status
            result = current_status(home)
        elif cmd == "daily-cycle":
            from .daily import run_cycle
            with lock(home):
                result = run_cycle(home, update_macro=not args.skip_macro,
                                   evaluate=not args.skip_evaluate)
        elif cmd == "notify-pending":
            from .daily import dispatch_pending
            if service.settings(home).get("demo"):
                raise ValueError("虚构演示账户不允许发送正式监控告警")
            with lock(home):
                result = dispatch_pending(home)
        elif cmd == "account": result = ledger.account(home, args.name)
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
        if cmd == "daily-cycle" and result["status"] != "SUCCEEDED": return 2
        if cmd == "notify-pending" and result["status"] == "DELIVERY_FAILED": return 2
        if cmd in ("audit", "verify") and result["status"] != "PASS": return 2
        if cmd == "run" and args.require_current and not result["qualified_online"]: return 2
        return 0
    except (ValueError, RuntimeError, OSError, TimeoutError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print("未完成：" + str(exc), file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
