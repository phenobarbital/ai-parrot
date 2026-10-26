"""FEAT-633 M7 / spike S6 — migration backup, lock and skew (TASK-4093)."""

from __future__ import annotations

import multiprocessing
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from parrot.knowledge.wiki import store as store_mod
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiStoreVersionError


async def _stale_plane(tmp_path: Path) -> Path:
    """A built plane whose schema_version is stale, so the next open migrates."""
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    return db


async def test_migration_backup_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §4 — a failed migration restores the sidecar backup and re-raises."""
    db = await _stale_plane(tmp_path)

    async def boom(self, conn):  # noqa: ANN001
        await conn.execute("UPDATE meta SET value = 'corrupted' WHERE key = 'k'")
        raise RuntimeError("migration failed")

    monkeypatch.setattr(SQLiteWikiStore, "_migrate", boom)
    with pytest.raises(RuntimeError, match="migration failed"):
        await SQLiteWikiStore(db, "t").get_meta("k")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'k'").fetchone()[0] == "v"
    assert list(tmp_path.glob("wiki.db.bak-*"))
    assert not store_mod._migration_lock_path(db).exists()


async def test_current_plane_takes_no_backup(tmp_path: Path) -> None:
    """A current plane keeps the read-first path: no backup, no lockfile."""
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")
    assert await SQLiteWikiStore(db, "t").get_meta("k") == "v"
    assert not list(tmp_path.glob("wiki.db.bak-*"))
    assert not store_mod._migration_lock_path(db).exists()


async def test_store_migrate_then_old_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §4 integration — migrate, then an older runtime (mocked older SCHEMA_VERSION) fails fast."""
    db = await _stale_plane(tmp_path)
    await SQLiteWikiStore(db, "t").get_meta("k")  # migrates + stamps (TASK-4092)
    # [rev 0.5] the gate compares schema numbers only; an older release with the same schema would open
    monkeypatch.setattr(store_mod, "SCHEMA_VERSION", str(int(store_mod.SCHEMA_VERSION) - 1))
    with pytest.raises(WikiStoreVersionError):
        await SQLiteWikiStore(db, "t").get_meta("k")


def _hold_lock(lock_path: str, acquired, release) -> None:  # noqa: ANN001 — multiprocessing child
    from parrot.knowledge.wiki import store as child_store

    acquired.value = int(child_store._try_acquire_migration_lock(Path(lock_path)))
    release.wait(10)
    child_store._release_migration_lock(Path(lock_path))


def test_migration_lock_is_exclusive_across_processes(tmp_path: Path) -> None:
    lock = tmp_path / "wiki.db.migrate.lock"
    ctx = multiprocessing.get_context("spawn")
    acquired, release = ctx.Value("i", -1), ctx.Event()
    child = ctx.Process(target=_hold_lock, args=(str(lock), acquired, release))
    child.start()
    try:
        deadline = time.monotonic() + 10
        while acquired.value == -1 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert acquired.value == 1
        assert store_mod._try_acquire_migration_lock(lock) is False
    finally:
        release.set()
        child.join(10)
    assert store_mod._try_acquire_migration_lock(lock) is True
    store_mod._release_migration_lock(lock)


def test_migration_lock_windows_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §4 — not a no-op when fcntl is unavailable."""
    monkeypatch.setitem(sys.modules, "fcntl", None)  # any `import fcntl` now raises ImportError
    lock = tmp_path / "x.lock"
    assert store_mod._try_acquire_migration_lock(lock) is True
    assert store_mod._try_acquire_migration_lock(lock) is False
    store_mod._release_migration_lock(lock)


def test_stale_lock_is_reclaimed(tmp_path: Path) -> None:
    lock = tmp_path / "x.lock"
    assert store_mod._try_acquire_migration_lock(lock) is True
    old = time.time() - 2 * store_mod.STALE_MIGRATION_LOCK_S
    os.utime(lock, (old, old))
    assert store_mod._try_acquire_migration_lock(lock) is True
    store_mod._release_migration_lock(lock)


async def test_read_only_plane_never_migrates(tmp_path: Path) -> None:
    db = await _stale_plane(tmp_path)
    assert await SQLiteWikiStore(db, "t", read_only=True).get_meta("k") == "v"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "2"
    assert not list(tmp_path.glob("wiki.db.bak-*"))
    assert not store_mod._migration_lock_path(db).exists()


_needs_posix_perms = pytest.mark.skipif(
    os.name == "nt" or getattr(os, "geteuid", lambda: 0)() == 0, reason="needs POSIX dir permissions, non-root"
)


@_needs_posix_perms
async def test_lock_or_backup_unwritable_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rev 0.5 C24 / D8 (3) — a non-FileExistsError OSError on lock/backup creation raises a clear error
    naming the directory; the stale plane is not migrated and the open does not silently succeed."""
    db = await _stale_plane(tmp_path)
    holder = sqlite3.connect(db)  # keeps -wal/-shm alive: the writable open still reaches _maybe_migrate (reproduced)
    holder.execute("SELECT 1").fetchone()
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(store_mod.WikiStoreMigrationError) as lock_err:
            await SQLiteWikiStore(db, "t").get_meta("k")
        assert str(tmp_path) in str(lock_err.value)
        assert "lock" in str(lock_err.value)

        monkeypatch.setattr(store_mod, "_try_acquire_migration_lock", lambda *a, **k: True)
        with pytest.raises(store_mod.WikiStoreMigrationError) as backup_err:
            await SQLiteWikiStore(db, "t").get_meta("k")
        assert str(tmp_path) in str(backup_err.value)
        assert "backup" in str(backup_err.value)
    finally:
        tmp_path.chmod(0o755)
        holder.close()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "2"
    assert not list(tmp_path.glob("wiki.db.bak-*")) and not store_mod._migration_lock_path(db).exists()


@_needs_posix_perms
async def test_read_only_open_in_unwritable_dir(tmp_path: Path) -> None:
    """[rev 0.5 D8 (3)] — read-only opens keep working through _connect_readonly."""
    db = await _stale_plane(tmp_path)
    holder = sqlite3.connect(db)
    holder.execute("SELECT 1").fetchone()
    tmp_path.chmod(0o555)
    try:
        assert await SQLiteWikiStore(db, "t", read_only=True).get_meta("k") == "v"
    finally:
        tmp_path.chmod(0o755)
        holder.close()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "2"
    assert not list(tmp_path.glob("wiki.db.bak-*")) and not store_mod._migration_lock_path(db).exists()
