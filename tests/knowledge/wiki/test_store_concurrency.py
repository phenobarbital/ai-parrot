"""FEAT-557 — SQLite connection-policy and transaction tests.

Lives beside ``test_store.py`` (the store's real suite); the
``packages/ai-parrot/tests/knowledge/wiki/`` tree holds only CLI/MCP/Jira
tests and no store coverage.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki.store import (
    SQLitePragmaPolicy,
    SQLiteWikiStore,
    WikiStoreBusy,
)


@pytest.fixture
async def store(tmp_path: Path) -> SQLiteWikiStore:
    """A built, current-schema SQLite plane."""
    plane = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")
    # Force schema creation + migration once so tests start migrated.
    await plane.stats()
    return plane


class TestOpenPolicy:
    async def test_busy_timeout_pragma_is_applied(self, store: SQLiteWikiStore) -> None:
        """PRAGMA busy_timeout reflects the policy, in milliseconds (AC-5)."""
        async with store._open(writable=True) as conn:
            cur = await conn.execute("PRAGMA busy_timeout")
            assert (await cur.fetchone())[0] == 15_000

    async def test_write_pragmas_only_on_writable_open(self, tmp_path: Path) -> None:
        """A read-only open issues no write-capable pragma (AC-4)."""
        plane = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")
        await plane.stats()
        async with plane._open(writable=False) as conn:
            cur = await conn.execute("PRAGMA synchronous")
            synchronous = (await cur.fetchone())[0]
            cur = await conn.execute("PRAGMA journal_size_limit")
            journal_size_limit = (await cur.fetchone())[0]
        # `synchronous` default is FULL (2); NORMAL (1) is only applied on a
        # writable open. `journal_size_limit` defaults to -1 (unset) until a
        # writable open sets it — a read-only open must never touch it.
        assert synchronous != 1 or journal_size_limit == -1
        assert journal_size_limit != plane._policy.journal_size_limit


class TestWriteTransaction:
    async def test_write_begins_immediate_and_commits(self, store: SQLiteWikiStore) -> None:
        """The happy path opens an immediate transaction and commits once."""
        async with store._write("test_insert") as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("test_key", "test_value"),
            )
        # Verify via a fresh stdlib connection that the row was committed.
        with sqlite3.connect(str(store.db_path)) as check_conn:
            row = check_conn.execute("SELECT value FROM meta WHERE key = ?", ("test_key",)).fetchone()
        assert row == ("test_value",)

    async def test_failed_body_rolls_back(self, store: SQLiteWikiStore) -> None:
        """An exception inside the body leaves no row behind (AC-3)."""

        class _Boom(Exception):
            pass

        with pytest.raises(_Boom):
            async with store._write("test_rollback") as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    ("rollback_key", "rollback_value"),
                )
                raise _Boom("body failed")

        with sqlite3.connect(str(store.db_path)) as check_conn:
            row = check_conn.execute("SELECT value FROM meta WHERE key = ?", ("rollback_key",)).fetchone()
        assert row is None

    async def test_busy_at_begin_raises_wiki_store_busy(self, tmp_path: Path) -> None:
        """A held peer writer surfaces as a typed, actionable error (AC-3)."""
        db_path = tmp_path / "wiki.db"
        fast_store = SQLiteWikiStore(
            db_path,
            wiki_name="test-wiki",
            sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
        )
        # Prime the schema (via the still-untouched `_connect` path) and the
        # per-instance migration latch (via `_write`) BEFORE the peer takes
        # the writer lock, so the contended write below fails at the BEGIN
        # IMMEDIATE boundary, not inside `_migrate` or on a missing table.
        await fast_store.stats()
        async with fast_store._write("prime"):
            pass

        peer = sqlite3.connect(str(db_path), timeout=1.0, isolation_level=None)
        try:
            peer.execute("BEGIN IMMEDIATE")
            with pytest.raises(WikiStoreBusy) as exc_info:
                async with fast_store._write("contended_op"):
                    pass
            exc = exc_info.value
            assert exc.db_path == db_path
            assert exc.operation == "contended_op"
            assert exc.waited_seconds == 1.0
        finally:
            peer.execute("ROLLBACK")
            peer.close()

    async def test_non_busy_error_keeps_its_semantics(self, store: SQLiteWikiStore) -> None:
        """A non-busy OperationalError is NOT converted to WikiStoreBusy (AC-3)."""
        with pytest.raises(sqlite3.OperationalError) as exc_info:
            async with store._write("bad_sql") as conn:
                await conn.execute("SELECT * FROM this_table_does_not_exist")
        assert not isinstance(exc_info.value, WikiStoreBusy)
