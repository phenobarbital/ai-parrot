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


async def test_successful_migration_prunes_old_backups(tmp_path: Path) -> None:
    """issue:092b311c2ad1 — a successful migration keeps only MIGRATION_BACKUP_KEEP sidecars."""
    db = await _stale_plane(tmp_path)
    # five sidecars left behind by earlier upgrades, oldest first
    older = [tmp_path / f"wiki.db.bak-2020010{n}T000000000000Z" for n in range(1, 6)]
    for path in older:
        path.write_bytes(b"old backup")

    await SQLiteWikiStore(db, "t").get_meta("k")  # migrates, then prunes

    kept = sorted(p.name for p in tmp_path.glob("wiki.db.bak-*"))
    assert len(kept) == store_mod.MIGRATION_BACKUP_KEEP, kept
    # the newest sidecar is this run's own backup; every hand-placed 2020 stamp is gone but the last
    assert kept[0] == older[-1].name
    assert not any(p.exists() for p in older[:-1])


async def test_failed_migration_keeps_its_backup_unpruned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """issue:092b311c2ad1 — pruning runs only on success, so a recovery snapshot survives."""
    db = await _stale_plane(tmp_path)
    stale_sidecars = [tmp_path / f"wiki.db.bak-2020010{n}T000000000000Z" for n in range(1, 4)]
    for path in stale_sidecars:
        path.write_bytes(b"old backup")

    async def boom(self, conn):  # noqa: ANN001
        raise RuntimeError("migration failed")

    monkeypatch.setattr(SQLiteWikiStore, "_migrate", boom)
    with pytest.raises(RuntimeError, match="migration failed"):
        await SQLiteWikiStore(db, "t").get_meta("k")

    # nothing pruned: the 3 pre-existing sidecars plus this run's own backup are all still there
    assert len(list(tmp_path.glob("wiki.db.bak-*"))) == len(stale_sidecars) + 1
    assert all(path.exists() for path in stale_sidecars)


async def test_prune_backups_survives_an_undeletable_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sidecar that cannot be unlinked is logged and skipped, never raised."""
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")
    sidecars = [tmp_path / f"wiki.db.bak-2020010{n}T000000000000Z" for n in range(1, 4)]
    for path in sidecars:
        path.write_bytes(b"old backup")

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if self == sidecars[0]:
            raise PermissionError("read-only sidecar")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    removed = SQLiteWikiStore(db, "t")._prune_backups(keep=1)

    # keep=1 makes sidecars[0] and sidecars[1] stale; the first refuses to go, the second still does
    assert removed == [sidecars[1]]
    assert sidecars[0].exists() and sidecars[2].exists()
    assert not sidecars[1].exists()


async def test_prune_backups_ignores_wal_and_shm_sidecars(tmp_path: Path) -> None:
    """A backup's own -wal/-shm must not be counted as a backup and push a real one out."""
    db = tmp_path / "wiki.db"
    await SQLiteWikiStore(db, "t").set_meta("k", "v")
    newest = tmp_path / "wiki.db.bak-20991231T000000000000Z"
    newest.write_bytes(b"newest backup")
    (tmp_path / "wiki.db.bak-20991231T000000000000Z-wal").write_bytes(b"")
    (tmp_path / "wiki.db.bak-20991231T000000000000Z-shm").write_bytes(b"")
    older = tmp_path / "wiki.db.bak-20200101T000000000000Z"
    older.write_bytes(b"old backup")

    removed = SQLiteWikiStore(db, "t")._prune_backups(keep=1)

    assert removed == [older]
    assert newest.exists()
