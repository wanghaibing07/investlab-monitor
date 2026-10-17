"""Private, immutable Vercel Blob snapshots for one-account InvestLab cloud runs.

Blob is used for append-only encrypted-at-rest private objects, not as a shared
mutable SQLite server. This v1 adapter intentionally forbids concurrent writers.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import io
import json
import re
import os
import sqlite3
import tempfile
import uuid
import zipfile


MAX_ARCHIVE_BYTES = 30 * 1024 * 1024
MAX_UNPACKED_BYTES = 120 * 1024 * 1024
STATE_FILES = frozenset({"settings.json", "data/monitor.sqlite3"})


def now():
    return datetime.now(timezone.utc).isoformat()


async def _list(prefix):
    """Use the supported async Vercel Blob 0.12.x iterator API."""
    from vercel.blob import query_blobs

    objects = []
    async for item in query_blobs(prefix=prefix, page_size=1000):
        if len(objects) >= 40000:
            raise RuntimeError("Private Blob list exceeds maximum supported items")
        objects.append(item)
    return objects


async def _read(pathname, *, max_size=MAX_ARCHIVE_BYTES):
    """Stream private Blob content with a strict application size limit."""
    from vercel.blob import stream_blob

    data = bytearray()
    async with stream_blob(pathname, access="private") as download:
        if download.metadata.status_code != 200:
            raise RuntimeError("Private Blob read returned an unexpected status")
        if download.metadata.size is not None and download.metadata.size > max_size:
            raise ValueError("Private Blob exceeds maximum allowed size")
        async for chunk in download:
            data.extend(chunk)
            if len(data) > max_size:
                raise ValueError("Private Blob exceeds maximum allowed size")
    return bytes(data)


async def _write(prefix, content, suffix="json"):
    """Write a unique immutable private Blob object; never overwrite data."""
    from vercel.blob import put_blob

    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = f"{prefix}/{name}-{uuid.uuid4().hex}.{suffix}"
    result = await put_blob(
        path, content, access="private", add_random_suffix=False,
        allow_overwrite=False,
        content_type="application/zip" if suffix == "zip" else "application/json",
    )
    return result.pathname


async def latest_json(prefix):
    objs = await _list(prefix+"/")
    names = sorted((obj.pathname for obj in objs if obj.pathname.endswith(".json")))
    if not names:
        return None
    raw = await _read(names[-1], max_size=2_000_000)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid private report")
    return data


MATURE_SNAPSHOT_PREFIX = "data/quant53/mature_snapshots/"
MATURE_SNAPSHOT_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
MAX_MATURE_SNAPSHOTS = 128


def _make_archive(home):
    """Back up SQLite plus content-addressed research evidence (format 2)."""
    home = Path(home)
    database = home / "data/monitor.sqlite3"
    settings = home / "settings.json"
    if not settings.is_file() or not database.is_file():
        raise ValueError("No initialized private account state")
    snapshot_dir = home / MATURE_SNAPSHOT_PREFIX
    snapshots = sorted(snapshot_dir.glob("*.json")) if snapshot_dir.exists() else []
    if len(snapshots) > MAX_MATURE_SNAPSHOTS:
        raise ValueError("Too many research evidence snapshots")
    for path in snapshots:
        if not MATURE_SNAPSHOT_NAME.fullmatch(path.name) or not path.is_file():
            raise ValueError("Invalid research evidence snapshot name")
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / "monitor.sqlite3"
        with sqlite3.connect(database) as source, sqlite3.connect(copied) as dest:
            source.backup(dest)
        manifest = {
            "schema_version": 2, "created_at": now(),
            "settings_sha256": hashlib.sha256(settings.read_bytes()).hexdigest(),
            "sqlite_sha256": hashlib.sha256(copied.read_bytes()).hexdigest(),
            "research_evidence_sha256": {},
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(settings, "settings.json")
            z.write(copied, "data/monitor.sqlite3")
            for file in snapshots:
                member = MATURE_SNAPSHOT_PREFIX + file.name
                data = file.read_bytes()
                manifest["research_evidence_sha256"][member] = hashlib.sha256(data).hexdigest()
                z.writestr(member, data)
            z.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
        data = output.getvalue()
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("Private database snapshot exceeded size limit")
        return data


def _restore_archive(home, raw):
    """Restore legacy v1 and verified v2 archive formats, with strict paths."""
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ValueError("Private snapshot is too large")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        contents = z.infolist()
        members = {item.filename: item for item in contents}
        if len(members) != len(contents):
            raise ValueError("Duplicate private snapshot entry")
        if sum(v.file_size for v in members.values()) > MAX_UNPACKED_BYTES:
            raise ValueError("Private snapshot expands beyond safe limit")
        manifest = json.loads(z.read("manifest.json"))
        version = manifest.get("schema_version")
        if version not in (1, 2):
            raise ValueError("Unsupported private snapshot version")
        extra = set(members) - (STATE_FILES | {"manifest.json"})
        if version == 1:
            if extra:
                raise ValueError("Unrecognized private snapshot contents")
        else:
            checks = manifest.get("research_evidence_sha256")
            if not isinstance(checks, dict) or set(checks) != extra or len(extra) > MAX_MATURE_SNAPSHOTS:
                raise ValueError("Research evidence inventory does not match archive")
            for name in extra:
                if not name.startswith(MATURE_SNAPSHOT_PREFIX) or not MATURE_SNAPSHOT_NAME.fullmatch(
                    name[len(MATURE_SNAPSHOT_PREFIX):]
                ):
                    raise ValueError("Unsafe research evidence archive entry")
        if set(members) != STATE_FILES | {"manifest.json"} | extra:
            raise ValueError("Unrecognized private snapshot contents")
        for name in ["settings.json", "data/monitor.sqlite3", *sorted(extra)]:
            check = ({"settings.json": "settings_sha256",
                      "data/monitor.sqlite3": "sqlite_sha256"}.get(name))
            expected = manifest.get(check) if check else manifest["research_evidence_sha256"][name]
            raw_value = z.read(name)
            if hashlib.sha256(raw_value).hexdigest() != expected:
                raise ValueError("Private snapshot integrity check failed")
            target = Path(home) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw_value)
            os.chmod(target, 0o600)
        if not (Path(home) / "data/monitor.sqlite3").read_bytes().startswith(b"SQLite format 3\x00"):
            raise ValueError("Private snapshot is not SQLite")


async def load_private_home(home, *, expected_version=None):
    objects = await _list("state/")
    names = sorted(obj.pathname for obj in objects if obj.pathname.endswith(".zip"))
    if not names:
        return False
    if expected_version is not None and expected_version != names[-1]:
        raise ValueError('Account version changed before run')
    raw = await _read(names[-1])
    _restore_archive(home, raw)
    return True



async def probe_private_recovery(*, limit=2):
    """Read-only restoration rehearsal of latest private snapshots.

    This checks checksum, SQLite integrity, confirmed non-demo account data.
    It NEVER overwrites the active state, and same-store versions do not
    constitute independent disaster-recovery backups.
    """
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("Invalid bounded recovery probe limit")
    from investlab.core import connection
    objects = await _list("state/")
    names = sorted(o.pathname for o in objects if o.pathname.endswith(".zip"))
    if not names:
        return {
            "status": "NO_ACCOUNT_SNAPSHOTS",
            "snapshots_checked": 0,
            "current_restorable": False,
            "older_restorable": False,
            "independent_backup_verified": False,
            "automatic_recovery_verified": False,
            "trading_enabled": False,
            "checks": [],
        }
    checks = []
    for index, pathname in enumerate(reversed(names[-limit:])):
        name = "current" if index == 0 else f"previous_{index}"
        with tempfile.TemporaryDirectory(prefix="investlab-recovery-probe-") as temp:
            try:
                home = Path(temp) / "restore"
                raw = await _read(pathname)
                await asyncio.to_thread(_restore_archive, home, raw)
                await asyncio.to_thread(_check_account, home)
                with connection(home, readonly=True) as db:
                    result = db.execute("PRAGMA quick_check").fetchone()
                if not result or result[0] != "ok":
                    raise ValueError("Restored SQLite integrity check failed")
                checks.append({"slot": name, "restorable": True})
            except Exception as exc:
                # Do not expose private pathname, account contents, credentials,
                # SQLite diagnostics, or exception messages to the UI.
                checks.append({"slot": name, "restorable": False,
                               "failure_type": type(exc).__name__})
    current = checks[0]["restorable"]
    previous = any(item["restorable"] for item in checks[1:])
    status = (
        "CURRENT_SNAPSHOT_NOT_RESTORABLE" if not current else
        "TWO_IN_STORE_SNAPSHOTS_RESTORABLE" if previous else
        "CURRENT_SNAPSHOT_RESTORABLE_ONLY"
    )
    return {
        "status": status,
        "snapshots_checked": len(checks),
        "current_restorable": current,
        "older_restorable": previous,
        "independent_backup_verified": False,
        "automatic_recovery_verified": False,
        "trading_enabled": False,
        "checks": checks,
    }


async def load_calculated_home(home, report, *, expected_account_version):
    """Open immutable research output only if it belongs to latest confirmed account."""
    import re
    name = report.get("computed_version")
    if not isinstance(name, str) or not re.fullmatch(
        r"computed/[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}\.zip", name
    ):
        raise ValueError("Missing scheduled calculation snapshot")
    if report.get("account_state_version") != expected_account_version:
        raise ValueError("Scheduled calculation belongs to an older account valuation")
    objects = await _list("state/")
    states = sorted(item.pathname for item in objects if item.pathname.endswith(".zip"))
    if not states or states[-1] != expected_account_version:
        raise ValueError("Confirmed account changed during scheduled report read")
    raw = await _read(name)
    _restore_archive(home, raw)
    await asyncio.to_thread(_check_account, home)
    return True


async def private_account_verified():
    """Read and validate actual private state; no inference from missing run reports.

    Returns False if no snapshot exists. Storage/auth corruption raises instead of
    reporting the account as absent. Never returns balances or private file names.
    """
    with tempfile.TemporaryDirectory(prefix="investlab-private-status-") as temp:
        home = Path(temp) / "private"
        if not await load_private_home(home):
            return False
        await asyncio.to_thread(_check_account, home)
        return True


async def verify_private_valuation(values, as_of):
    """Read persisted private Blob ZIP + SQLite and verify exact confirmed CNY amounts."""
    from investlab.core import connection
    from investlab import service

    with tempfile.TemporaryDirectory(prefix="investlab-private-readback-") as tmp:
        home = Path(tmp) / "private"
        if not await load_private_home(home):
            raise RuntimeError("Private account snapshot was not persisted")
        await asyncio.to_thread(_check_account, home)
        if service.settings(home)["demo"] is not False:
            raise RuntimeError("Readback unexpectedly contains demo data")
        with connection(home, readonly=True) as c:
            row = c.execute(
                "SELECT as_of, qqq_value_cny, tqqq_value_cny, "
                "qld_value_cny, cash_cny FROM portfolio_baselines "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        if row is None or row["as_of"] != as_of:
            raise RuntimeError("Private valuation readback date did not match")
        for symbol, column in (
            ("QQQ", "qqq_value_cny"),
            ("TQQQ", "tqqq_value_cny"),
            ("QLD", "qld_value_cny"),
            ("CASH", "cash_cny"),
        ):
            if row[column] != int(values[symbol]):
                raise RuntimeError("Private valuation readback amounts did not match")
        return {
            "verified": True,
            "as_of": row["as_of"],
            "values": {symbol: str(row[column]) for symbol, column in (
                ("QQQ", "qqq_value_cny"), ("TQQQ", "tqqq_value_cny"),
                ("QLD", "qld_value_cny"), ("CASH", "cash_cny")
            )},
            "total_value_cny": sum(int(v) for v in values.values()),
        }



async def read_private_account():
    """Read the most recent immutable Blob state and confirmed CNY baseline.

    Never infer an account from the existence of run reports.
    """
    from investlab.core import connection
    with tempfile.TemporaryDirectory(prefix="investlab-account-get-") as temp:
        home = Path(temp) / "private"
        objects = await _list("state/")
        names = sorted(item.pathname for item in objects if item.pathname.endswith(".zip"))
        if not names:
            return {"account_initialized": False, "state_version": None}
        raw = await _read(names[-1])
        _restore_archive(home, raw)
        await asyncio.to_thread(_check_account, home)
        with connection(home, readonly=True) as db:
            row = db.execute(
                "SELECT as_of, qqq_value_cny, tqqq_value_cny, "
                "qld_value_cny, cash_cny, note, recorded_at "
                "FROM portfolio_baselines ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("Confirmed account baseline missing")
        values = {symbol: str(row[column]) for symbol, column in (
            ("QQQ", "qqq_value_cny"), ("TQQQ", "tqqq_value_cny"),
            ("QLD", "qld_value_cny"), ("CASH", "cash_cny")
        )}
        return {
            "account_initialized": True, "as_of": row["as_of"], "values": values,
            "total_value_cny": sum(int(v) for v in values.values()),
            "state_version": names[-1], "recorded_at": row["recorded_at"],
            "note": row["note"], "trading_enabled": False,
        }


async def read_private_history(limit=100):
    """Read confirmed CNY valuation history from immutable private account storage.

    Only exposes private values behind Vercel Authentication, never public demo.
    No synthetic history or inferred investment returns are generated.
    """
    from investlab.core import connection

    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Invalid valuation history limit")
    with tempfile.TemporaryDirectory(prefix="investlab-history-read-") as temporary:
        home = Path(temporary) / "private"
        if not await load_private_home(home):
            return {"account_initialized": False, "history": [], "has_more": False}
        await asyncio.to_thread(_check_account, home)
        with connection(home, readonly=True) as db:
            rows = db.execute(
                "SELECT as_of, qqq_value_cny, tqqq_value_cny, "
                "qld_value_cny, cash_cny, recorded_at, note "
                "FROM portfolio_baselines ORDER BY rowid DESC LIMIT ?", (limit + 1,)
            ).fetchall()
        history = []
        for row in rows[:limit]:
            values = {key: str(row[column]) for key, column in (
                ("QQQ", "qqq_value_cny"), ("TQQQ", "tqqq_value_cny"),
                ("QLD", "qld_value_cny"), ("CASH", "cash_cny")
            )}
            history.append({
                "as_of": row["as_of"], "recorded_at": row["recorded_at"],
                "values": values, "total_value_cny": sum(int(v) for v in values.values()),
                "note": row["note"],
            })
        return {
            "account_initialized": True, "history": history,
            "has_more": len(rows) > limit,
        }


async def append_private_valuation(values, as_of, note, expected_version):
    """Append a confirmed valuation without overwriting any historical snapshot.

    A stale submitted version is rejected. This optimistic check is NOT a
    distributed mutex: enable recurring writers only after transaction locking.
    """
    from investlab import ledger
    with tempfile.TemporaryDirectory(prefix="investlab-account-update-") as temp:
        home = Path(temp) / "private"
        objects = await _list("state/")
        names = sorted(item.pathname for item in objects if item.pathname.endswith(".zip"))
        if not names:
            raise ValueError("Account has not been initialized")
        if names[-1] != expected_version:
            raise ValueError("Private account changed; reload before resubmitting")
        raw = await _read(names[-1])
        _restore_archive(home, raw)
        await asyncio.to_thread(_check_account, home)
        event = {
            "valuation_id": uuid.uuid4().hex,
            "account": "default", "as_of": as_of, "currency": "CNY",
            "values": values, "confirmed": True, "note": note,
        }
        await asyncio.to_thread(ledger.valuation, home, event)
        # Detect intervening updates; Blob cannot provide atomic CAS or a mutex.
        before_write = await _list("state/")
        latest = max((o.pathname for o in before_write if o.pathname.endswith(".zip")), default=None)
        if latest != expected_version:
            raise ValueError("Private account changed during update; reload and reconcile")
        saved = await save_private_home(home)
        return saved


async def save_private_home(home):
    archive = await asyncio.to_thread(_make_archive, home)
    return await _write("state", archive, "zip")


async def save_private_report(report):
    from investlab.core import canonical
    return await _write("runs", canonical(report).encode("utf-8"))


def _check_account(home):
    from investlab import service
    from investlab.core import connection
    cfg = service.settings(home)
    if cfg.get("demo") is not False:
        raise ValueError("Only non-demo private accounts are permitted")
    with connection(home,readonly=True) as c:
        if not c.execute("SELECT 1 FROM portfolio_baselines LIMIT 1").fetchone():
            raise ValueError("Confirmed private account valuation is required")


def _compute(home):
    from investlab import service, verification
    _check_account(home)
    calculated = service.run(home,online=True,independent=True)
    if not calculated.get("qualified_online"):
        raise ValueError("Live quotes were not independently qualified")
    audited = service.audit(home)
    if audited.get("status") != "PASS":
        raise ValueError("Account/evidence audit failed")
    verified = verification.verify(home)
    if verified.get("status") != "PASS":
        raise ValueError("Independent research verification failed")
    outcomes = service.worker(home,"evaluate",timeout=120)
    return {
        "status": "SUCCEEDED", "completed_at": now(),
        "review_id": calculated["review_id"],
        "qualified_online": True,
        "audit": "PASS", "research_verification": "PASS",
        "matured_outcome_evaluation": "ATTEMPTED_NOT_PROOF",
        "matured_outcomes": outcomes.get("research",{}).get("new_outcomes",0) if isinstance(outcomes,dict) else None,
        "trading_enabled": False,
    }


async def run_private_daily(*, expected_version=None):
    """Fail closed with a stored report and leave previous state intact on errors."""
    from investlab import service
    report = {"status": "RUNNING", "started_at": now(), "trading_enabled":False}
    with tempfile.TemporaryDirectory(prefix="investlab-cloud-") as tmp:
        home = Path(tmp) / "private"
        home.mkdir(mode=0o700)
        try:
            existing = await load_private_home(home, expected_version=expected_version)
            if not existing:
                report.update(status="SETUP_REQUIRED",issue_code="NO_PRIVATE_ACCOUNT_SNAPSHOT")
                return report
            result = await asyncio.to_thread(_compute, home)
            if expected_version is not None:
                objects = await _list("state/")
                names = sorted(o.pathname for o in objects if o.pathname.endswith(".zip"))
                if not names or names[-1] != expected_version:
                    raise ValueError("Account version changed during run; computed state not saved")
            saved = await save_private_home(home)
            report.update(result, state_version=saved)
        except Exception as exc:
            report.update(status="FAILED",issue_code="CLOUD_DAILY_FAILED",
                          failure_type=type(exc).__name__)
        finally:
            report["completed_at"] = now()
            try:
                report["report_version"] = await save_private_report(report)
            except Exception:
                # Never turn a persistence failure into success.
                report["status"] = "FAILED"
                report["issue_code"] = "CLOUD_PERSISTENCE_FAILED"
        return report


async def initialize_private_account(values, as_of, note):
    """One-time private account bootstrap; refuses overwrite of existing state."""
    from investlab import ledger, service
    if await _list("state/"):
        raise ValueError("Private cloud account already initialized; migration needed")
    with tempfile.TemporaryDirectory(prefix="investlab-cloud-init-") as tmp:
        home = Path(tmp) / "private"
        await asyncio.to_thread(service.init, home, False)
        event = {
            "valuation_id": uuid.uuid4().hex,
            "account": "default", "as_of": as_of, "currency": "CNY",
            "values": values, "confirmed": True, "note": note
        }
        await asyncio.to_thread(ledger.valuation, home, event)
        return await save_private_home(home)
