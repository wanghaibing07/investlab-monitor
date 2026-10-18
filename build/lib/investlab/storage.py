"""Consistent backups, manifest verification, restore and legacy migration."""
from pathlib import Path
from contextlib import closing
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from .core import atomic, canonical, connection, digest, file_hash, schema, utcnow


def db_backup(source, dest):
    source = Path(source).resolve()
    if not source.is_file(): raise ValueError("源数据库不存在")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as a, closing(sqlite3.connect(dest)) as b:
        a.backup(b)
        if b.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or b.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("SQLite备份校验失败")


def table_fingerprints(db):
    with closing(sqlite3.connect(db)) as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: {"count": c.execute('SELECT count(*) FROM "' + n + '"').fetchone()[0],
                    "sha256": digest(sorted([[(v.hex() if isinstance(v, bytes) else v) for v in r] for r in c.execute('SELECT * FROM "' + n + '"')], key=canonical))}
                for n in names}


def backup(home, destination=None):
    home = Path(home)
    directory = home / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    destination = Path(destination) if destination else directory / (utcnow().replace(":", "-") + ".zip")
    if destination.resolve().is_relative_to((home / "data").resolve()): raise ValueError("备份输出不能放在事实数据目录内")
    if destination.exists(): raise ValueError("不覆盖现有备份")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="backup-", dir=home) as temp:
        root = Path(temp)
        db_backup(home / "data/monitor.sqlite3", root / "monitor.sqlite3")
        files = {"data/monitor.sqlite3": root / "monitor.sqlite3"}
        # Evidence files are necessary to reproduce historical decisions.
        for p in (home / "data").rglob("*"):
            rel = p.relative_to(home)
            if p.is_symlink(): raise ValueError("备份拒绝符号链接")
            if not p.is_file() or p.name.startswith("monitor.sqlite3") or "backups" in rel.parts or p.name.endswith(("-wal", "-shm")):
                continue
            files[rel.as_posix()] = p
        for name in ("settings.json",):
            if (home / name).is_file(): files[name] = home / name
        manifest = {"format": "investlab-backup-v1", "created_at": utcnow(),
                    "files": {name: file_hash(path) for name, path in sorted(files.items())}}
        tmp = destination.with_suffix(".partial")
        try:
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for name, p in files.items(): z.write(p, name)
                z.writestr("MANIFEST.json", canonical(manifest))
            verify_archive(tmp)
            os.chmod(tmp, 0o600)
            os.replace(tmp, destination)
        finally:
            tmp.unlink(missing_ok=True)
    return {"path": str(destination), "sha256": file_hash(destination), "verified": True, "files": len(files)}


def verify_archive(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if len(names) != len(set(names)): raise ValueError("备份包含重名条目")
        for info in z.infolist():
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("备份包含不安全路径")
        manifest = json.loads(z.read("MANIFEST.json"))
        if manifest["format"] != "investlab-backup-v1": raise ValueError("不支持的备份格式")
        if "data/monitor.sqlite3" not in manifest["files"] or "settings.json" not in manifest["files"]:
            raise ValueError("备份缺少数据库或设置")
        if any(n != "settings.json" and not n.startswith("data/") for n in manifest["files"]):
            raise ValueError("备份包含无关根目录文件")
        if set(names) != set(manifest["files"]) | {"MANIFEST.json"}: raise ValueError("备份清单不完整")
        import hashlib
        for name, expected in manifest["files"].items():
            h = hashlib.sha256()
            with z.open(name) as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
            if h.hexdigest() != expected: raise ValueError("备份哈希不匹配: " + name)
    return manifest


def restore(path, target):
    """Restore into an empty location; never overwrite live history."""
    target = Path(target).absolute()
    if target.is_symlink(): raise ValueError("恢复目标不能是符号链接")
    if target.exists() and any(target.iterdir()): raise ValueError("恢复目录必须不存在或为空")
    manifest = verify_archive(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=target.parent) as temp:
        stage = Path(temp) / "state"; stage.mkdir(mode=0o700)
        with zipfile.ZipFile(path) as z:
            for name in manifest["files"]:
                p = stage / name; p.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as src, p.open("wb") as dst: shutil.copyfileobj(src, dst)
                p.chmod(0o600)
        with connection(stage, readonly=True) as c:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or c.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("恢复后的数据库校验失败")
            required = {"portfolio_baselines", "daily_prices", "monitor_runs"}
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not required <= tables: raise ValueError("备份数据库缺少必要表")
        config = json.loads((stage / "settings.json").read_text())
        if config.get("execution") != "MANUAL": raise ValueError("备份设置不符合人工执行模式")
        atomic(stage / "restore-receipt.json", {"source_sha256": file_hash(path), "restored_at": utcnow(), "files": len(manifest["files"])})
        # Only the fully validated state becomes visible at the target path.
        if target.exists() and any(target.iterdir()): raise ValueError("恢复目标在验证期间被其他任务占用")
        os.replace(stage, target)
    return {"restored": True, "target": str(target), "files": len(manifest["files"])}


def migrate(source, home):
    """Import the full v5 evidence directory using SQLite native backup."""
    source, home = Path(source).resolve(), Path(home).resolve()
    if home.is_relative_to(source) or source.is_relative_to(home):
        raise ValueError("迁移来源与目标目录不能相互嵌套")
    src = source / "data/monitor.sqlite3"
    if not src.is_file(): raise ValueError("源目录缺少data/monitor.sqlite3")
    if (home / "data/monitor.sqlite3").exists(): raise ValueError("目标已有账本，拒绝重新初始化")
    before = table_fingerprints(src)
    data = home / "data"; data.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in (source / "data").rglob("*"):
        if p.is_symlink(): raise ValueError("迁移拒绝符号链接")
        if not p.is_file() or p.name.startswith("monitor.sqlite3") or "__pycache__" in p.parts or "backups" in p.relative_to(source / "data").parts:
            continue
        dest = data / p.relative_to(source / "data"); dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest); dest.chmod(0o600)
    db_backup(src, data / "monitor.sqlite3")
    after = table_fingerprints(data / "monitor.sqlite3")
    if before != after: raise ValueError("迁移前后表内容不一致")
    schema(home)
    evidence = {"table_parity": True, "tables": before,
                "source_database_sha256": file_hash(src), "migrated_at": utcnow(),
                "source_is_aggregate_valuation_not_trade_history": True}
    with connection(home) as c:
        c.execute("INSERT INTO migrations VALUES(?,?,?)", (evidence["source_database_sha256"], utcnow(), canonical(evidence)))
    prior_settings = json.loads((source / "settings.json").read_text()) if (source / "settings.json").exists() else {}
    atomic(home / "settings.json", {"schema_version": 1, "demo": bool(prior_settings.get("demo", False)), "target": {"QQQ": .6, "TQQQ": .4},
                                    "execution": "MANUAL", "account": "default"})
    atomic(data / "migration-receipt.json", evidence)
    return {"migrated": True, "table_parity": True, "table_count": len(before),
            "runs_preserved": before.get("monitor_runs", {}).get("count", 0),
            "baselines_preserved": before.get("portfolio_baselines", {}).get("count", 0)}
