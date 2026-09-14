"""FTS5 external-content regression suite for the SQLite wiki plane.

Root cause pinned here (hotfix WIKI-FTS-RESCAN): ``pages_fts`` and
``symbols_fts`` used to declare ``concept_id UNINDEXED`` and were
maintained by hand with ``DELETE FROM <fts> WHERE concept_id = ?``.
``concept_id`` is not an indexed FTS column, so SQLite answered every
one of those deletes with a FULL SCAN of the FTS index — once per page,
inside ``executemany``. A ``wikitoolkit build`` over this repository
therefore degraded to O(pages x sources) and took hours.

The fix makes both FTS tables **external-content** tables mirroring
``pages``/``symbols`` by ``rowid``, synchronised by triggers. The
scanning DELETE becomes structurally impossible (the column no longer
exists) and every delete/update is a rowid operation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.symbols import SymbolKind, SymbolRecord


def _page(concept_id: str, *, body: str, source_id: str = "src-1", title: str = "Title") -> WikiPageRecord:
    """Build a minimal page record for the plane under test."""
    return WikiPageRecord(
        concept_id=concept_id,
        title=title,
        category="module",
        summary="summary text",
        body=body,
        source_id=source_id,
    )


def _symbol(name: str, *, doc: str, rel_path: str = "pkg/mod.py") -> SymbolRecord:
    """Build a minimal symbol record for the plane under test."""
    return SymbolRecord(
        rel_path=rel_path,
        language="python",
        kind=SymbolKind.FUNCTION,
        name=name,
        qualname=name,
        signature="()",
        doc=doc,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=10,
        content_hash="a" * 40,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Path to a fresh, not-yet-created plane."""
    return tmp_path / "wiki.db"


@pytest.fixture
def store(db_path: Path) -> SQLiteWikiStore:
    """A writable SQLite wiki store on a fresh plane."""
    return SQLiteWikiStore(db_path)


def _fts_columns(db_path: Path, table: str) -> list[str]:
    """Column names the given FTS table exposes."""
    conn = sqlite3.connect(db_path)
    try:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _table_sql(db_path: Path, name: str) -> str:
    """The stored ``CREATE`` statement for a table/trigger."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (name,)).fetchone()
        return row[0] if row and row[0] else ""
    finally:
        conn.close()


class TestExternalContentSchema:
    """The schema itself is what makes the full scan impossible."""

    @pytest.mark.asyncio
    async def test_pages_fts_is_external_content_over_pages(self, store: SQLiteWikiStore, db_path: Path) -> None:
        await store.upsert_pages([_page("file:a.py", body="alpha")])
        sql = _table_sql(db_path, "pages_fts")
        assert "content=" in sql.replace(" ", "")
        assert "pages" in sql
        assert "concept_id" not in _fts_columns(db_path, "pages_fts")

    @pytest.mark.asyncio
    async def test_symbols_fts_is_external_content_over_symbols(self, store: SQLiteWikiStore, db_path: Path) -> None:
        await store.upsert_symbols([_symbol("alpha_fn", doc="alpha doc")], source_id="src-1")
        sql = _table_sql(db_path, "symbols_fts")
        assert "content=" in sql.replace(" ", "")
        assert "symbols" in sql
        assert "concept_id" not in _fts_columns(db_path, "symbols_fts")

    @pytest.mark.asyncio
    async def test_scanning_delete_is_structurally_impossible(self, store: SQLiteWikiStore, db_path: Path) -> None:
        """The exact statement that caused the hours-long build must not parse.

        ``DELETE FROM pages_fts WHERE concept_id = ?`` used to be a legal
        full scan. With an external-content table the column is gone, so
        the anti-pattern fails loudly instead of silently costing a scan.
        """
        await store.upsert_pages([_page("file:a.py", body="alpha")])
        conn = sqlite3.connect(db_path)
        try:
            for table in ("pages_fts", "symbols_fts"):
                with pytest.raises(sqlite3.OperationalError):
                    conn.execute(f"DELETE FROM {table} WHERE concept_id = 'x'")
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_sync_triggers_exist(self, store: SQLiteWikiStore, db_path: Path) -> None:
        await store.upsert_pages([_page("file:a.py", body="alpha")])
        conn = sqlite3.connect(db_path)
        try:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        finally:
            conn.close()
        assert {"pages_ai", "pages_ad", "pages_au"} <= names
        assert {"symbols_ai", "symbols_ad", "symbols_au"} <= names


class TestPagesFtsStaysInSync:
    """Trigger-maintained index must behave exactly like the manual one."""

    @pytest.mark.asyncio
    async def test_insert_is_searchable(self, store: SQLiteWikiStore) -> None:
        await store.upsert_pages([_page("file:a.py", body="alphaword")])
        hits = await store.search_fts("alphaword")
        assert [h["concept_id"] for h in hits] == ["file:a.py"]

    @pytest.mark.asyncio
    async def test_update_replaces_old_terms(self, store: SQLiteWikiStore) -> None:
        await store.upsert_pages([_page("file:a.py", body="alphaword")])
        await store.upsert_pages([_page("file:a.py", body="betaword")])
        assert await store.search_fts("alphaword") == []
        assert [h["concept_id"] for h in await store.search_fts("betaword")] == ["file:a.py"]

    @pytest.mark.asyncio
    async def test_upsert_never_duplicates_fts_rows(self, store: SQLiteWikiStore) -> None:
        for _ in range(3):
            await store.upsert_pages([_page("file:a.py", body="alphaword")])
        assert len(await store.search_fts("alphaword")) == 1

    @pytest.mark.asyncio
    async def test_delete_page_drops_it_from_search(self, store: SQLiteWikiStore) -> None:
        await store.upsert_pages([_page("file:a.py", body="alphaword")])
        assert await store.delete_page("file:a.py") is True
        assert await store.search_fts("alphaword") == []

    @pytest.mark.asyncio
    async def test_replace_source_slice_evicts_stale_pages(self, store: SQLiteWikiStore) -> None:
        await store.upsert_pages(
            [
                _page("file:a.py", body="alphaword", source_id="src-1"),
                _page("sym:a.py#old", body="staleword", source_id="src-1"),
            ]
        )
        await store.replace_source_slice(
            "src-1",
            [
                _page("file:a.py", body="alphaword", source_id="src-1"),
                _page("sym:a.py#new", body="freshword", source_id="src-1"),
            ],
        )
        assert await store.search_fts("staleword") == []
        assert [h["concept_id"] for h in await store.search_fts("freshword")] == ["sym:a.py#new"]
        assert len(await store.search_fts("alphaword")) == 1


class TestSymbolsFtsStaysInSync:
    """Same contract for the FEAT-498 structural plane."""

    @pytest.mark.asyncio
    async def test_symbol_is_searchable(self, store: SQLiteWikiStore) -> None:
        await store.upsert_symbols([_symbol("alpha_fn", doc="alphadoc")], source_id="src-1")
        hits = await store.search_symbols_fts("alphadoc")
        assert [s.qualname for s in hits] == ["alpha_fn"]

    @pytest.mark.asyncio
    async def test_symbol_update_replaces_old_terms(self, store: SQLiteWikiStore) -> None:
        await store.upsert_symbols([_symbol("alpha_fn", doc="alphadoc")], source_id="src-1")
        await store.upsert_symbols([_symbol("alpha_fn", doc="betadoc")], source_id="src-1")
        assert await store.search_symbols_fts("alphadoc") == []
        assert [s.qualname for s in await store.search_symbols_fts("betadoc")] == ["alpha_fn"]

    @pytest.mark.asyncio
    async def test_replace_source_slice_evicts_symbol_rows(self, store: SQLiteWikiStore) -> None:
        await store.upsert_symbols([_symbol("alpha_fn", doc="alphadoc")], source_id="src-1")
        await store.replace_source_slice("src-1", [])
        assert await store.search_symbols_fts("alphadoc") == []


LEGACY_V2_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    source_uri TEXT NOT NULL UNIQUE,
    external_id TEXT
);
CREATE TABLE pages (
    concept_id  TEXT PRIMARY KEY,
    node_id     TEXT,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'concept',
    summary     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    source_id   TEXT,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    origin      TEXT NOT NULL DEFAULT 'ingest',
    asserted_by TEXT,
    content_hash TEXT
);
CREATE TABLE edges (
    src TEXT NOT NULL, dst TEXT NOT NULL,
    rel TEXT NOT NULL DEFAULT 'references',
    provenance TEXT NOT NULL DEFAULT 'extracted',
    PRIMARY KEY (src, dst, rel)
);
CREATE VIRTUAL TABLE pages_fts USING fts5(
    concept_id UNINDEXED, title, summary, body, tokenize = 'unicode61'
);
CREATE TABLE embeddings (
    concept_id TEXT PRIMARY KEY, vector BLOB NOT NULL, model TEXT NOT NULL DEFAULT ''
);
CREATE TABLE symbols (
    concept_id  TEXT PRIMARY KEY,
    rel_path    TEXT NOT NULL,
    language    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    name        TEXT NOT NULL,
    qualname    TEXT NOT NULL,
    parent      TEXT,
    signature   TEXT NOT NULL DEFAULT '',
    doc         TEXT NOT NULL DEFAULT '',
    exported    INTEGER NOT NULL DEFAULT 0,
    is_async    INTEGER NOT NULL DEFAULT 0,
    depth       INTEGER NOT NULL DEFAULT 1,
    start_line  INTEGER, end_line INTEGER,
    start_byte  INTEGER, end_byte INTEGER,
    node_kind   TEXT, content_hash TEXT, source_id TEXT
);
CREATE VIRTUAL TABLE symbols_fts USING fts5(
    concept_id UNINDEXED, name, qualname, doc, signature, tokenize = 'unicode61'
);
"""


class TestLegacyPlaneMigration:
    """A v2 plane on disk must be upgraded in place, not corrupted."""

    @pytest.fixture
    def legacy_db(self, tmp_path: Path) -> Path:
        """A pre-hotfix plane carrying one page and one symbol."""
        path = tmp_path / "legacy.db"
        conn = sqlite3.connect(path)
        try:
            conn.executescript(LEGACY_V2_SCHEMA)
            conn.execute(
                "INSERT INTO pages (concept_id, node_id, title, category, summary, body,"
                " source_id, token_count, created_at, updated_at)"
                " VALUES ('file:a.py', NULL, 'A', 'module', 'sum', 'legacyword',"
                " 'src-1', 1, '2026-01-01', '2026-01-01')"
            )
            conn.execute(
                "INSERT INTO pages_fts (concept_id, title, summary, body)"
                " VALUES ('file:a.py', 'A', 'sum', 'legacyword')"
            )
            conn.execute(
                "INSERT INTO symbols (concept_id, rel_path, language, kind, name, qualname,"
                " signature, doc, source_id, content_hash)"
                " VALUES ('sym:a.py#f', 'a.py', 'python', 'function', 'f', 'f',"
                " '()', 'legacydoc', 'src-1', 'aaa')"
            )
            conn.execute(
                "INSERT INTO symbols_fts (concept_id, name, qualname, doc, signature)"
                " VALUES ('sym:a.py#f', 'f', 'f', 'legacydoc', '()')"
            )
            conn.commit()
        finally:
            conn.close()
        return path

    @pytest.mark.asyncio
    async def test_legacy_plane_is_migrated_and_reindexed(self, legacy_db: Path) -> None:
        store = SQLiteWikiStore(legacy_db)
        hits = await store.search_fts("legacyword")
        assert [h["concept_id"] for h in hits] == ["file:a.py"]
        assert "concept_id" not in _fts_columns(legacy_db, "pages_fts")

    @pytest.mark.asyncio
    async def test_legacy_symbols_are_reindexed(self, legacy_db: Path) -> None:
        store = SQLiteWikiStore(legacy_db)
        hits = await store.search_symbols_fts("legacydoc")
        assert [s.qualname for s in hits] == ["f"]
        assert "concept_id" not in _fts_columns(legacy_db, "symbols_fts")

    @pytest.mark.asyncio
    async def test_migration_is_idempotent(self, legacy_db: Path) -> None:
        for _ in range(3):
            store = SQLiteWikiStore(legacy_db)
            assert len(await store.search_fts("legacyword")) == 1

    @pytest.mark.asyncio
    async def test_read_only_legacy_plane_is_still_searchable(self, legacy_db: Path) -> None:
        """A federated, un-migratable plane must not answer silently empty.

        ``read_only=True`` planes (FEAT-450) are never written to, so
        they keep the legacy ``concept_id``-keyed index for good. The
        read path has to recognise that shape instead of joining by a
        rowid that means nothing there.
        """
        store = SQLiteWikiStore(legacy_db, read_only=True)
        assert [h["concept_id"] for h in await store.search_fts("legacyword")] == ["file:a.py"]
        assert [s.qualname for s in await store.search_symbols_fts("legacydoc")] == ["f"]
        # Reading it must not have upgraded (or otherwise touched) it.
        assert "concept_id" in _fts_columns(legacy_db, "pages_fts")

    @pytest.mark.asyncio
    async def test_writable_plane_prefers_the_migrated_shape(self, legacy_db: Path) -> None:
        """The same plane opened writable migrates, then reads by rowid."""
        store = SQLiteWikiStore(legacy_db)
        assert len(await store.search_fts("legacyword")) == 1
        assert "concept_id" not in _fts_columns(legacy_db, "pages_fts")
        await store.upsert_pages([_page("file:b.py", body="freshword")])
        assert [h["concept_id"] for h in await store.search_fts("freshword")] == ["file:b.py"]
