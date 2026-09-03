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
    assert row[0] == SCHEMA_VERSION == "2"


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
