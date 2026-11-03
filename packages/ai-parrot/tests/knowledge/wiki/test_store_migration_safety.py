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


async def test_failed_migration_does_not_discard_concurrent_committed_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restoring the full pre-migration snapshot must not erase what another writer committed meanwhile."""
    db = await _stale_plane(tmp_path)

    async def boom(self, conn):  # noqa: ANN001
        other = sqlite3.connect(db)  # an already-initialised writer: takes no migration lock
        other.execute("INSERT INTO meta (key, value) VALUES ('concurrent', 'kept')")
        other.commit()
        other.close()
        raise RuntimeError("migration failed")

    monkeypatch.setattr(SQLiteWikiStore, "_migrate", boom)
    with pytest.raises(RuntimeError, match="migration failed"):
        await SQLiteWikiStore(db, "t").get_meta("k")
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'concurrent'").fetchone() == ("kept",)
    assert list(tmp_path.glob("wiki.db.bak-*"))  # backup kept for manual recovery


def test_stale_reclaim_never_deletes_a_fresh_replacement_lock(tmp_path: Path) -> None:
    """Two contenders see the same stale lock; the loser must not unlink the winner's fresh lock."""
    lock = tmp_path / "x.lock"
    assert store_mod._try_acquire_migration_lock(lock) is True
    observed = store_mod._lock_identity(lock)  # what contender B saw as stale
    lock.unlink()  # contender A reclaimed it ...
    assert store_mod._try_acquire_migration_lock(lock) is True  # ... and now holds a FRESH lock
    store_mod._reclaim_stale_lock(lock, observed)  # B proceeds with its (outdated) decision
    assert lock.exists(), "B deleted A's live lock — two owners"
    store_mod._release_migration_lock(lock)


def test_release_does_not_delete_a_lock_owned_by_someone_else(tmp_path: Path) -> None:
    """A holder whose lock was reclaimed must not remove the new owner's lockfile on release."""
    lock = tmp_path / "x.lock"
    assert store_mod._try_acquire_migration_lock(lock) is True
    lock.unlink()
    lock.write_text("999999 0 someone-elses-token", encoding="utf-8")
    store_mod._release_migration_lock(lock)
    assert lock.exists()


async def test_legacy_plane_is_untouched_when_backup_cannot_be_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy plane missing tables must not be altered by the schema replay before the lock + backup succeed."""
    db = tmp_path / "wiki.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")

    def no_backup(self):  # noqa: ANN001
        raise store_mod.WikiStoreMigrationError(tmp_path, "create the pre-migration backup", OSError("denied"))

    monkeypatch.setattr(SQLiteWikiStore, "_backup_store", no_backup)
    with pytest.raises(store_mod.WikiStoreMigrationError):
        await SQLiteWikiStore(db, "t").get_meta("k")
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == {"meta"}, f"legacy plane modified before backup: {tables}"
    assert not store_mod._migration_lock_path(db).exists()


async def test_backups_in_the_same_second_do_not_overwrite_each_other(tmp_path: Path) -> None:
    """Backup names carry sub-second resolution and never collide."""
    db = await _stale_plane(tmp_path)
    store = SQLiteWikiStore(db, "t")
    first, second = store._backup_store(), store._backup_store()
    assert first != second and first.exists() and second.exists()


async def test_plane_created_by_source_manager_is_stamped_without_backup(tmp_path: Path) -> None:
    """`wikitoolkit build` creates the schema via SourceCollectionManager (no meta rows); stamping it is not a migration."""
    from parrot.knowledge.wiki.sources import SourceCollectionManager

    db = tmp_path / "wiki.db"
    SourceCollectionManager(tmp_path / "sources", db_path=db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() is None

    assert await SQLiteWikiStore(db, "t").get_meta("k") is None
    assert not list(tmp_path.glob("wiki.db.bak-*")), "a freshly built plane must not leave a backup sidecar"
    assert not store_mod._migration_lock_path(db).exists()
    with sqlite3.connect(db) as conn:
        stamped = dict(conn.execute("SELECT key, value FROM meta"))
    assert stamped["schema_version"] == store_mod.SCHEMA_VERSION
    assert store_mod.MIN_RUNTIME_KEY in stamped


async def test_stale_version_row_is_still_backed_up(tmp_path: Path) -> None:
    """A PRESENT but different schema_version is a real version change: the backup still runs."""
    db = await _stale_plane(tmp_path)
    assert await SQLiteWikiStore(db, "t").get_meta("k") == "v"
    assert list(tmp_path.glob("wiki.db.bak-*"))


async def test_unstamped_plane_missing_a_column_is_still_backed_up(tmp_path: Path) -> None:
    """No version row AND structural work pending (a missing column) is a migration: the backup still runs."""
    from parrot.knowledge.wiki.sources import SourceCollectionManager

    db = tmp_path / "wiki.db"
    SourceCollectionManager(tmp_path / "sources", db_path=db)
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE pages DROP COLUMN content_hash")

    await SQLiteWikiStore(db, "t").get_meta("k")
    assert list(tmp_path.glob("wiki.db.bak-*"))
    with sqlite3.connect(db) as conn:
        assert "content_hash" in {row[1] for row in conn.execute("PRAGMA table_info(pages)")}
