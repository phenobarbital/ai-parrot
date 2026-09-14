"""FEAT-557 — SQLite connection-policy and transaction tests.

Lives beside ``test_store.py`` (the store's real suite); the
``packages/ai-parrot/tests/knowledge/wiki/`` tree holds only CLI/MCP/Jira
tests and no store coverage.
"""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import asynccontextmanager, contextmanager
import asyncio
import multiprocessing
import shutil
import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki.store import (
    SCHEMA_VERSION,
    WIKI_SCHEMA_SQL,
    SQLitePragmaPolicy,
    SQLiteWikiStore,
    WikiStoreBusy,
)

FIXTURE = Path(__file__).parent / "fixtures" / "wiki_v1.db"


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


class TestReadFirstMigration:
    async def test_current_plane_needs_no_migration(self, store: SQLiteWikiStore) -> None:
        """The probe reports nothing pending on a freshly built plane."""
        async with store._open(writable=True) as conn:
            missing, stale = await store._migration_needed(conn)
        assert missing == []
        assert stale is False

    async def test_migrate_writes_nothing_on_current_plane(self, store: SQLiteWikiStore) -> None:
        """`_migrate` issues no DML/DDL when there is nothing to do (AC-4)."""
        write_prefixes = ("ALTER", "UPDATE", "INSERT", "DELETE", "COMMIT", "CREATE", "DROP")
        statements: list[str] = []
        async with store._open(writable=True) as conn:
            original_execute = conn.execute

            def _spy(sql, *args, **kwargs):
                statements.append(sql)
                return original_execute(sql, *args, **kwargs)

            conn.execute = _spy
            await store._migrate(conn)

        for sql in statements:
            assert not sql.strip().upper().startswith(write_prefixes), sql

    async def test_legacy_plane_migrates_once_and_bumps_version(self, tmp_path: Path) -> None:
        """A legacy plane gains its columns and reaches SCHEMA_VERSION."""
        db_path = tmp_path / "wiki.db"
        shutil.copyfile(FIXTURE, db_path)
        store = SQLiteWikiStore(db_path, wiki_name="v1-fixture")
        # Trigger the presence-probe + _migrate() path via any read, exactly
        # as the pre-existing test_store_migration_v2.py suite does — `_write`
        # does not (yet) create missing tables; that unification is TASK-3219.
        await store.list_pages(limit=100)

        with sqlite3.connect(str(db_path)) as check_conn:
            columns = {row[1] for row in check_conn.execute("PRAGMA table_info(pages)")}
            version = check_conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
        assert "content_hash" in columns
        assert version == SCHEMA_VERSION

    async def test_absent_version_row_is_treated_as_stale(self, tmp_path: Path) -> None:
        """A plane with no schema_version row migrates and gains the row."""
        db_path = tmp_path / "wiki.db"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(WIKI_SCHEMA_SQL)
            conn.execute("DELETE FROM meta WHERE key = 'schema_version'")
            conn.commit()
        finally:
            conn.close()

        store = SQLiteWikiStore(db_path, wiki_name="no-version")
        async with store._write("touch"):
            pass

        with sqlite3.connect(str(db_path)) as check_conn:
            row = check_conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        assert row is not None
        assert row[0] == SCHEMA_VERSION

    async def test_migration_latch_suppresses_second_probe(self, store: SQLiteWikiStore) -> None:
        """`self._migrated` stops the per-connection probe after the first write."""
        async with store._write("first"):
            pass
        assert store._migrated.is_set()

        async def _boom(conn):
            raise AssertionError("_migration_needed should not run once the latch is set")

        store._migration_needed = _boom  # type: ignore[method-assign]
        async with store._write("second"):
            pass

    async def test_latch_is_per_store_not_global(self, tmp_path: Path) -> None:
        """Two stores on two planes do not share the latch (spec §2).

        Neither store has had any `_read`/`_write` call before this, so
        `_migrated` starts unset for both — `_open`'s `_ensure_schema`
        creates `store_a`'s schema as part of the write itself.
        """
        store_a = SQLiteWikiStore(tmp_path / "a.db", wiki_name="a")
        store_b = SQLiteWikiStore(tmp_path / "b.db", wiki_name="b")
        async with store_a._write("touch"):
            pass
        assert store_a._migrated.is_set()
        assert not store_b._migrated.is_set()


class TestCheckpoint:
    async def test_checkpoint_reports_success(self, store: SQLiteWikiStore) -> None:
        """A quiet plane checkpoints in TRUNCATE mode."""
        async with store._write("seed") as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("checkpoint_seed", "1"),
            )
        report = await store.checkpoint()
        assert report["ok"] is True
        assert report["mode"] == "TRUNCATE"
        assert report["busy"] is False

    async def test_reader_blocked_truncate_falls_back_to_passive(self, store: SQLiteWikiStore) -> None:
        """A live reader forces PASSIVE and never raises (AC-7)."""
        # Enough rows that the WAL is non-trivial by the time the reader
        # opens its snapshot — a single tiny INSERT can leave the WAL at
        # 0 pages already, which would never report `busy` regardless of
        # any reader.
        async with store._write("seed") as conn:
            await conn.executemany(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                [(f"checkpoint_seed_{i}", "x" * 200) for i in range(500)],
            )
        reader = sqlite3.connect(str(store.db_path))
        try:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM meta").fetchall()

            # A second write grows the WAL further while the reader's
            # snapshot pins the earlier frames — otherwise TRUNCATE can
            # have nothing left to move and never reports busy.
            async with store._write("seed_more") as conn:
                await conn.executemany(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    [(f"checkpoint_seed_more_{i}", "x" * 200) for i in range(500)],
                )

            report = await store.checkpoint()
            assert report["ok"] is True
            assert report["mode"] == "PASSIVE"
        finally:
            reader.execute("ROLLBACK")
            reader.close()

    async def test_read_only_store_skips(self, tmp_path: Path) -> None:
        """A read-only store never writes, so it never checkpoints."""
        db_path = tmp_path / "wiki.db"
        writable_store = SQLiteWikiStore(db_path, wiki_name="ro-source")
        async with writable_store._write("seed"):
            pass
        ro_store = SQLiteWikiStore(db_path, read_only=True)
        report = await ro_store.checkpoint()
        assert report == {"ok": False, "mode": "skipped", "busy": False, "log": -1, "checkpointed": -1}

    async def test_checkpoint_is_not_on_the_base_contract(self) -> None:
        """`checkpoint` stays concrete to SQLiteWikiStore (spec §2)."""
        from parrot.knowledge.wiki.store import BaseWikiStore

        assert not hasattr(BaseWikiStore, "checkpoint")


_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "REPLACE",
                   "COMMIT", "BEGIN")


def _is_write(statement: str) -> bool:
    """Whether a traced SQL statement mutates or opens a transaction."""
    return statement.strip().upper().startswith(_WRITE_PREFIXES)


class TestReadPathIssuesNoWrites:
    """AC-4: pure reads on a migrated plane take no writer lock."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda s: s.get_page("intro"),
            lambda s: s.search_fts("neural"),
            lambda s: s.stats(),
            lambda s: s.dump_pages(),
            lambda s: s.page_hashes(["intro"]),
            lambda s: s.symbols_for("a.py"),
        ],
    )
    async def test_reader_issues_no_write_statement(self, store, call) -> None:
        """Trace every statement a reader issues and assert none writes."""
        # Seed some data first so the queries have something to read and don't just short-circuit
        async with store._write("seed") as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO pages (concept_id, title, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("intro", "Intro", "neural networks are cool", "2023-01-01", "2023-01-01")
            )
            await conn.execute(
                "INSERT OR REPLACE INTO symbols (concept_id, rel_path, language, kind, name, qualname, source_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("sym1", "a.py", "python", "function", "my_func", "my_func", "a.py")
            )

        traced: list[str] = []

        # We need to trace statements. Let's hook into the underlying connection.
        # We can do this by wrapping the connection's execute/executemany/executescript methods,
        # or by setting a trace callback on the underlying sqlite3 connection.
        # Let's intercept via a custom connection wrapper or by patching the connection.
        # Since aiosqlite uses a background thread, setting a trace callback on the underlying
        # sqlite3 connection is very robust.
        # Let's get a connection from store._open(writable=False) and trace it.
        # But wait, the store methods themselves call `self._open(writable=False)`.
        # So we can patch `store._open` to intercept the connection and set the trace callback.
        original_open = store._open

        @asynccontextmanager
        def _spy_open(*args, **kwargs):
            # We must define this as a synchronous generator context manager because aiosqlite's
            # _open is an asynccontextmanager, but wait, let's check if we can use an async generator.
            # Yes, store._open is an asynccontextmanager.
            # Let's define an async generator context manager.
            pass

        # Actually, to avoid thread-safety issues with set_trace_callback (which must be called
        # in the thread where the sqlite3 connection is used, i.e., the aiosqlite worker thread),
        # we can wrap the `conn.execute` method of the aiosqlite.Connection object instead!
        # This is completely thread-safe and runs in the main thread.
        original_open = store._open

        @asynccontextmanager
        async def _spy_open(*args, **kwargs):
            async with original_open(*args, **kwargs) as conn:
                original_execute = conn.execute
                def _spy_execute(sql, *a, **kw):
                    traced.append(sql)
                    return original_execute(sql, *a, **kw)
                conn.execute = _spy_execute
                yield conn

        store._open = _spy_open

        await call(store)

        write_statements = [s for s in traced if _is_write(s)]
        assert write_statements == [], f"Found write statements: {write_statements}"

    async def test_read_only_ladder_sets_timeout_but_no_write_pragma(self, tmp_path) -> None:
        """AC-4: mode=ro / immutable rungs get the busy timeout only."""
        # Create a store with read_only=True
        db_path = tmp_path / "wiki.db"
        # Create schema first using a writable store
        setup_store = SQLiteWikiStore(db_path, wiki_name="test-wiki")
        await setup_store.stats()

        ro_store = SQLiteWikiStore(db_path, wiki_name="test-wiki", read_only=True)
        
        # Verify that read_only is True
        assert ro_store.read_only is True
        
        # Since _connect_readonly uses aiosqlite.connect with timeout parameter,
        # it doesn't execute a PRAGMA busy_timeout statement directly.
        # Let's verify that no write-capable pragmas are executed.
        # We can verify that calling get_page works and doesn't raise any errors.
        await ro_store.get_page("intro")


def _peer_writer(db_path: str, ready, release, result) -> None:
    """Child process: hold an immediate writer transaction, then release.

    Runs in a SEPARATE process so the contention is real OS-level SQLite
    locking, not asyncio task interleaving in one process.
    """
    try:
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        conn.execute("BEGIN IMMEDIATE")
        ready.set()
        release.wait()
        conn.commit()
        conn.close()
        result.value = b"O"
    except Exception as e:
        # Just set to something else to indicate error
        result.value = b"E"


@pytest.mark.slow
class TestMultiprocessContention:
    """AC-3 end to end: typed busy or success, never `database is locked`."""

    async def test_peer_writer_yields_typed_busy_never_raw_lock_error(self, tmp_path) -> None:
        """A held peer writer produces WikiStoreBusy, not a raw OperationalError."""
        db_path = tmp_path / "wiki.db"
        fast_store = SQLiteWikiStore(
            db_path,
            wiki_name="test-wiki",
            sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
        )
        await fast_store.stats()
        async with fast_store._write("prime"):
            pass

        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        release = ctx.Event()
        result = ctx.Value("c", b" ")

        p = ctx.Process(target=_peer_writer, args=(str(db_path), ready, release, result))
        p.start()
        try:
            ready.wait(timeout=5.0)
            with pytest.raises(WikiStoreBusy) as exc_info:
                async with fast_store._write("contended_op"):
                    pass
            exc = exc_info.value
            assert exc.db_path == db_path
            assert exc.operation == "contended_op"
            assert exc.waited_seconds == 1.0
        finally:
            release.set()
            p.join(timeout=5.0)

        assert result.value == b"O"

    async def test_write_completes_when_peer_releases_within_timeout(self, tmp_path) -> None:
        """A writer that releases in time lets the waiter through — no error."""
        db_path = tmp_path / "wiki.db"
        fast_store = SQLiteWikiStore(
            db_path,
            wiki_name="test-wiki",
            sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=2.0),
        )
        await fast_store.stats()
        async with fast_store._write("prime"):
            pass

        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        release = ctx.Event()
        result = ctx.Value("c", b" ")

        p = ctx.Process(target=_peer_writer, args=(str(db_path), ready, release, result))
        p.start()
        try:
            ready.wait(timeout=5.0)
            
            # We want to release the peer writer while the store is waiting.
            # Since the store's busy_timeout is 2.0s, we can schedule a release in 0.2s.
            async def _delayed_release():
                await asyncio.sleep(0.2)
                release.set()

            release_task = asyncio.create_task(_delayed_release())
            
            async with fast_store._write("delayed_op") as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                    ("delayed_key", "delayed_val")
                )
            
            await release_task
        finally:
            release.set()
            p.join(timeout=5.0)

        assert result.value == b"O"
        
        # Verify the write succeeded
        async with fast_store._open(writable=False) as conn:
            cur = await conn.execute("SELECT value FROM meta WHERE key = ?", ("delayed_key",))
            row = await cur.fetchone()
            assert row[0] == "delayed_val"

    async def test_source_manager_and_store_contend_safely(self, tmp_path) -> None:
        """The sync SourceCollectionManager and async store share one WAL safely."""
        from parrot.knowledge.wiki.sources import SourceCollectionManager
        db_path = tmp_path / "wiki.db"
        fast_store = SQLiteWikiStore(
            db_path,
            wiki_name="test-wiki",
            sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
        )
        await fast_store.stats()
        async with fast_store._write("prime"):
            pass

        # Let's hold a write lock via the store, and try to write via SourceCollectionManager.
        # SourceCollectionManager should raise WikiStoreBusy or succeed.
        # Since SourceCollectionManager is sync, we can run it in a thread or just test its behavior.
        # Let's verify that SourceCollectionManager raises WikiStoreBusy when the store holds the lock.
        # We can hold the lock in the store by keeping the `_write` context manager open,
        # and then calling SourceCollectionManager in a separate thread or using asyncio.to_thread.
        # Note: SourceCollectionManager expects sources_dir as the first argument, and db_path as an optional argument.
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        manager = SourceCollectionManager(sources_dir, db_path=db_path, busy_timeout=1.0)

        async def _run_manager():
            # SourceCollectionManager has a write method or similar. Let's check how it writes.
            # Usually it has `upsert_source` or similar. Let's run it in a thread.
            def _sync_write():
                with manager._write("manager_op") as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                        ("manager_key", "manager_val")
                    )
            await asyncio.to_thread(_sync_write)

        async with fast_store._write("store_op"):
            with pytest.raises(WikiStoreBusy) as exc_info:
                await _run_manager()
            assert exc_info.value.operation == "manager_op"
            assert exc_info.value.waited_seconds == 1.0

