"""FEAT-609 M5: a read-only handle survives another process migrating its FTS shape."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore

from .test_sqlite_fts_external_content import LEGACY_V2_SCHEMA


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    """The same pre-hotfix plane as TestLegacyPlaneMigration.legacy_db."""
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
            "INSERT INTO pages_fts (concept_id, title, summary, body) VALUES ('file:a.py', 'A', 'sum', 'legacyword')"
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


async def test_legacy_fts_reprobe_after_migration(legacy_db: Path) -> None:
    reader = SQLiteWikiStore(legacy_db, read_only=True)
    assert await reader.search_symbols_fts("legacydoc")  # probes + caches "legacy"

    writer = SQLiteWikiStore(legacy_db)
    assert await writer.search_symbols_fts("legacydoc")  # migrates the plane

    hits = await reader.search_symbols_fts("legacydoc")  # before the fix: no such column
    assert hits, "read-only handle must recover after the plane was migrated"


async def test_legacy_pages_fts_reprobe_after_migration(legacy_db: Path) -> None:
    reader = SQLiteWikiStore(legacy_db, read_only=True)
    assert await reader.search_fts("legacyword")

    writer = SQLiteWikiStore(legacy_db)
    assert await writer.search_fts("legacyword")

    assert await reader.search_fts("legacyword"), "pages_fts must recover too"


async def test_other_operational_errors_propagate(legacy_db: Path, monkeypatch) -> None:
    """Only ``no such column`` is retried; anything else keeps its semantics."""
    reader = SQLiteWikiStore(legacy_db, read_only=True)

    async def _boom(conn, table):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(reader, "_uses_legacy_fts", _boom)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        await reader.search_symbols_fts("legacydoc")
