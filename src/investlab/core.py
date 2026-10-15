"""Filesystem, concurrency and immutable identity primitives."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile

PACKAGE = Path(__file__).resolve().parent
ENGINE = PACKAGE / "engine"


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic(path, value):
    """Unique temp names, fsync and replace; simultaneous readers see whole files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = value if isinstance(value, bytes) else (canonical(value) + "\n").encode()
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        if os.name != "nt":
            d = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(d)
            finally:
                os.close(d)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def home_path(value=None):
    return Path(value or os.environ.get("INVESTLAB_HOME", "~/.local/share/investlab")).expanduser().resolve()


@contextmanager
def connection(home, *, readonly=False):
    path = Path(home) / "data/monitor.sqlite3"
    if readonly:
        c = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    if not readonly:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
    try:
        yield c
        if not readonly: c.commit()
    except BaseException:
        if not readonly: c.rollback()
        raise
    finally:
        c.close()


@contextmanager
def lock(home):
    """OS releases the writer lock after crashes; readers need no lock."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (home / ".writer.lock").open("a+b") as f:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0); f.write(b"0"); f.flush(); f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            raise RuntimeError("已有写入任务运行，请等该任务结束") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def code_identity():
    return digest({str(p.relative_to(PACKAGE)): file_hash(p)
                   for p in sorted(PACKAGE.rglob("*"))
                   if p.is_file() and p.suffix in (".py", ".json", ".js", ".html", ".css")
                   and "__pycache__" not in p.parts})


def schema(home):
    with connection(home) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS app_schema(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS journal_events(
          event_id TEXT PRIMARY KEY, account TEXT NOT NULL, occurred_at TEXT NOT NULL,
          recorded_at TEXT NOT NULL, event_json TEXT NOT NULL, event_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS account_valuations(
          valuation_id TEXT PRIMARY KEY, account TEXT NOT NULL, as_of TEXT NOT NULL,
          recorded_at TEXT NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operations(
          operation_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
          command TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_reviews(
          review_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES operations(operation_id),
          session_date TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notifications(
          notification_id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES app_reviews(review_id),
          created_at TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS experiments(
          experiment_id TEXT PRIMARY KEY, frozen_at TEXT NOT NULL, data_end TEXT NOT NULL,
          code_sha256 TEXT NOT NULL, specification TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS migrations(
          source_sha256 TEXT PRIMARY KEY, imported_at TEXT NOT NULL, evidence TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal_events
          BEGIN SELECT RAISE(ABORT,'journal is append only'); END;
        CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal_events
          BEGIN SELECT RAISE(ABORT,'journal is append only'); END;
        CREATE TRIGGER IF NOT EXISTS valuations_no_update BEFORE UPDATE ON account_valuations
          BEGIN SELECT RAISE(ABORT,'valuations are append only'); END;
        CREATE TRIGGER IF NOT EXISTS valuations_no_delete BEFORE DELETE ON account_valuations
          BEGIN SELECT RAISE(ABORT,'valuations are append only'); END;
        """)
        c.execute("INSERT OR IGNORE INTO app_schema VALUES(1,?)", (utcnow(),))
