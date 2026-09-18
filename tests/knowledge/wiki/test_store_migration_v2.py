"""FEAT-498 (TASK-2747) — SQLite schema v1 -> v2 migration.

Opens the committed ``fixtures/wiki_v1.db`` (a ``SCHEMA_VERSION == "1"``
plane with 3 pages, 2 edges, and NO ``content_hash`` column / ``symbols`` /
``symbols_fts`` tables) through :class:`SQLiteWikiStore` and asserts the
migration is idempotent and never rewrites existing rows.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from parrot.knowledge.wiki.store import SCHEMA_VERSION, SQLiteWikiStore

FIXTURE = Path(__file__).parent / "fixtures" / "wiki_v1.db"


@pytest.fixture
def v1_db(tmp_path: Path) -> Path:
    """Copy of the committed v1 fixture so the test never mutates it."""
    dest = tmp_path / "wiki.db"
    shutil.copyfile(FIXTURE, dest)
    return dest


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table')")
        return {row[0] for row in rows}
    finally:
        conn.close()


def _triggers(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        return {row[0] for row in rows}
    finally:
        conn.close()


def _fts_create_sql(db_path: Path, table: str) -> str:
    """Return the CREATE statement for an FTS virtual table (or '')."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        return row[0] if row and row[0] else ""
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_fixture_is_actually_v1(v1_db: Path):
    """Sanity check the fixture itself before asserting on the migration."""
    assert "content_hash" not in _columns(v1_db, "pages")
    assert "symbols" not in _tables(v1_db)
    conn = sqlite3.connect(str(v1_db))
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    finally:
        conn.close()
    assert row[0] == "1"


@pytest.mark.asyncio
async def test_open_v1_db_migrates_to_v2(v1_db: Path):
    store = SQLiteWikiStore(v1_db, wiki_name="v1-fixture")
    # Trigger the presence-probe + _migrate() path via any read.
    pages = await store.list_pages(limit=100)
    assert len(pages) == 3

    assert "content_hash" in _columns(v1_db, "pages")
    assert "symbols" in _tables(v1_db)
    assert "symbols_fts" in _tables(v1_db)

    conn = sqlite3.connect(str(v1_db))
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    finally:
        conn.close()
    # Assert against SCHEMA_VERSION only — the literal was "2" and went
    # stale the moment the FTS external-content fix bumped the schema to
    # "3". What this test owns is "a v1 plane is migrated up to the
    # current schema", not which number that currently is.
    assert row[0] == SCHEMA_VERSION


@pytest.mark.asyncio
async def test_migration_does_not_rewrite_existing_pages(v1_db: Path):
    store = SQLiteWikiStore(v1_db, wiki_name="v1-fixture")
    page = await store.get_page("file:a.py")
    assert page is not None
    assert page["title"] == "a.py"
    assert page["summary"] == "Module a."
    assert page["content_hash"] is None  # migrated column, unset on old rows

    edges_neighbors = await store.neighbors("dir:.", direction="out")
    assert {n["concept_id"] for n in edges_neighbors} == {"file:a.py", "file:b.py"}


@pytest.mark.asyncio
async def test_second_open_is_a_noop(v1_db: Path):
    store = SQLiteWikiStore(v1_db, wiki_name="v1-fixture")
    await store.list_pages()  # first migration

    # A second store instance over the already-migrated file must not
    # error or duplicate any DDL/rows.
    store2 = SQLiteWikiStore(v1_db, wiki_name="v1-fixture")
    pages = await store2.list_pages(limit=100)
    assert len(pages) == 3
    stats = await store2.stats()
    assert stats["pages"] == 3
    assert stats["symbols"] == 0


@pytest.mark.asyncio
async def test_open_v1_db_reaches_v3_external_content_fts(v1_db: Path):
    """Opening a v1 plane migrates through ``_migrate_fts`` (the 2->3 step),
    which rebuilds the FTS5 indexes onto the EXTERNAL-CONTENT shape.

    This is the distinctive v3 signature: a pre-v3 plane carried
    ``pages_fts`` / ``symbols_fts`` as standalone FTS5 tables (with a
    ``concept_id UNINDEXED`` column, synced by hand). ``_migrate_fts``
    (store.py, added by commit ``a26ff2824e``) drops and recreates them as
    external-content mirrors of their content tables. Asserting the CREATE
    statement (``content = 'pages'`` / ``content = 'symbols'``) plus the six
    sync triggers proves the 2->3 step actually ran — not merely that the
    final ``schema_version`` string is ``"3"``.
    """
    store = SQLiteWikiStore(v1_db, wiki_name="v1-fixture")
    await store.list_pages(limit=100)  # triggers migration up to the current schema

    assert SCHEMA_VERSION == "3"  # guards this test's premise about the 2->3 step

    pages_fts_sql = _fts_create_sql(v1_db, "pages_fts").lower().replace(" ", "")
    assert "content='pages'" in pages_fts_sql, "pages_fts must be external-content after _migrate_fts"
    symbols_fts_sql = _fts_create_sql(v1_db, "symbols_fts").lower().replace(" ", "")
    assert "content='symbols'" in symbols_fts_sql, "symbols_fts must be external-content after _migrate_fts"

    # The six FTS sync triggers WIKI_FTS_SQL creates must all exist.
    expected_triggers = {
        "pages_ai", "pages_ad", "pages_au",
        "symbols_ai", "symbols_ad", "symbols_au",
    }
    assert expected_triggers <= _triggers(v1_db)
