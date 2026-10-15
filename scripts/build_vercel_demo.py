"""Create a public, read-only Vercel build from reproducible synthetic data.

This deliberately exports only four allowlisted JSON documents and three
frontend assets. Runtime data, databases and backups never enter the output.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from investlab.core import PACKAGE, canonical
from investlab.service import latest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ALLOWED_ROUTES = ("latest", "research", "history", "journal")


def run(home: Path, command: str) -> None:
    process = subprocess.run(
        [sys.executable, "-m", "investlab", "--home", str(home), command]
        + (["--demo"] if command == "init" else []),
        check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=900,
    )
    print(f"Demo {command}: OK", flush=True)


def export() -> None:
    with tempfile.TemporaryDirectory(prefix="investlab-vercel-fixture-") as private:
        home = Path(private)
        run(home, "init")
        run(home, "run")
        run(home, "verify")
        run(home, "audit")

        report = latest(home)
        if not report or report.get("demo") is not True:
            raise RuntimeError("Refusing to export non-synthetic account")
        if report["operation"]["status"] != "SUCCEEDED":
            raise RuntimeError("Demo calculation is not complete")
        verification = json.loads((home / "data/verification.json").read_text())
        if verification.get("status") != "PASS":
            raise RuntimeError("Independent research verification failed")

        with sqlite3.connect(home / "data/monitor.sqlite3") as conn:
            conn.row_factory = sqlite3.Row
            history = [dict(row) for row in conn.execute(
                "SELECT operation_id,started_at,completed_at,command,status "
                "FROM operations ORDER BY started_at DESC LIMIT 100"
            )]
            journal = [json.loads(row[0]) for row in conn.execute(
                "SELECT event_json FROM journal_events "
                "ORDER BY occurred_at DESC,event_id DESC LIMIT 100"
            )]

        snapshots = dict(latest=report, research=verification, history=history, journal=journal)
        if journal:
            raise RuntimeError("Public synthetic demo should not contain trade journal events")
        if DIST.exists():
            shutil.rmtree(DIST)
        DIST.mkdir(parents=True)
        for name in ("index.html", "app.js", "style.css"):
            shutil.copyfile(PACKAGE / "web" / name, DIST / name)
        data_dir = DIST / "data"
        data_dir.mkdir()
        for route in ALLOWED_ROUTES:
            (data_dir / f"{route}.json").write_text(
                canonical(snapshots[route]) + "\n", encoding="utf-8"
            )

        page = DIST / "index.html"
        raw_html = page.read_text(encoding="utf-8")
        if "<main>" not in raw_html:
            raise RuntimeError("Demo banner insertion point changed")
        footer_old = "数据在本机保存 · 无自动下单"
        if footer_old not in raw_html:
            raise RuntimeError("Public demo footer changed")
        raw_html = raw_html.replace(
            footer_old, "数据为部署时的虚构快照 · 无自动下单", 1
        )
        page.write_text(raw_html.replace(
            "<main>",
            '<main><div class="demo-banner" role="note">'
            '公开演示：所有账户与行情均为虚构，数据在部署时生成；'
            '这里不提供实时交易建议。'
            '</div>',
            1,
        ), encoding="utf-8")
        with (DIST / "style.css").open("a", encoding="utf-8") as out:
            out.write(
                "\n.demo-banner{padding:12px 16px;margin:8px 0 24px;"
                "border:1px solid #5676ab;border-radius:12px;"
                "background:#1d3553;color:#e3efff;font-size:14px}\n"
            )
        found = sorted(str(path.relative_to(DIST)) for path in DIST.rglob("*") if path.is_file())
        expected = sorted(["index.html", "app.js", "style.css"] +
                          [f"data/{route}.json" for route in ALLOWED_ROUTES])
        if found != expected:
            raise RuntimeError(f"Unexpected public build contents: {found}")
        print("Public synthetic artifact exported:", ", ".join(found))


if __name__ == "__main__":
    export()
