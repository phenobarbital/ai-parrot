"""FEAT-557 — SourceCollectionManager SQLite policy tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import WikiStoreBusy


@pytest.fixture
def manager(tmp_path: Path) -> SourceCollectionManager:
    """A SQLite-backed source manager on a temp plane."""
    return SourceCollectionManager(tmp_path / "sources", db_path=tmp_path / "wiki.db")


class TestSQLitePolicy:
    def test_default_busy_timeout(self, manager: SourceCollectionManager) -> None:
        """Defaults to 15 seconds (spec §2)."""
        assert manager.busy_timeout == 15.0

    def test_connection_applies_busy_timeout_pragma(self, manager: SourceCollectionManager) -> None:
        """PRAGMA busy_timeout reflects the configured value, in ms."""
        conn = manager._connect()
        try:
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 15_000
        finally:
            conn.close()

    def test_busy_at_begin_raises_wiki_store_busy(self, tmp_path: Path) -> None:
        """A held peer writer surfaces as WikiStoreBusy, not 'database is locked'."""
        manager = SourceCollectionManager(
            tmp_path / "sources",
            db_path=tmp_path / "wiki.db",
            busy_timeout=1.0,
        )
        peer = sqlite3.connect(str(manager.db_path), timeout=1.0, isolation_level=None)
        try:
            peer.execute("BEGIN IMMEDIATE")
            with pytest.raises(WikiStoreBusy) as exc_info:
                with manager._write("t"):
                    pass
            exc = exc_info.value
            assert exc.db_path == manager.db_path
            assert exc.operation == "t"
            assert exc.waited_seconds == 1.0
        finally:
            peer.execute("ROLLBACK")
            peer.close()

    def test_failed_write_rolls_back(self, manager: SourceCollectionManager) -> None:
        """An exception inside the body leaves no row behind."""

        class _Boom(Exception):
            pass

        with pytest.raises(_Boom):
            with manager._write("t") as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS t_probe (id INTEGER)")
                conn.execute("INSERT INTO t_probe (id) VALUES (1)")
                raise _Boom("body failed")

        check_conn = sqlite3.connect(str(manager.db_path))
        try:
            row = check_conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 't_probe'"
            ).fetchone()
        finally:
            check_conn.close()
        assert row is None


class TestOtherBackendsUnchanged:
    def test_json_backend_writes_no_sqlite(self, tmp_path: Path) -> None:
        """The JSON branch is behaviourally unchanged (AC-6)."""
        from parrot.knowledge.wiki.models import SourceManifestEntry

        manager = SourceCollectionManager(tmp_path / "sources", backend="json")
        entry = SourceManifestEntry(
            source_id="s1",
            source_uri="file:///tmp/a.md",
            file_hash="abc123",
            mtime=0.0,
            ingested_at="2026-09-14T00:00:00+00:00",
        )
        manager._upsert(entry)
        assert manager.manifest_path.exists()
        assert not (tmp_path / "wiki.db").exists()
