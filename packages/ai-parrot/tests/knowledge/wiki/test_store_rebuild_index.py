"""Tests for ``rebuild_index`` / ``index_drift`` on the wiki stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord


def _page(concept_id: str) -> WikiPageRecord:
    return WikiPageRecord(
        concept_id=concept_id,
        title=f"Title {concept_id}",
        category="module",
        summary="summary text",
        body=f"body of {concept_id}",
        source_id="src-1",
    )


async def test_base_defaults() -> None:
    assert await BaseWikiStore.rebuild_index(None) == {"rebuilt": []}  # type: ignore[arg-type]
    assert await BaseWikiStore.index_drift(None) == {}  # type: ignore[arg-type]


async def test_fts_rebuild_fix(tmp_path: Path) -> None:
    db = tmp_path / "wiki.db"
    store = SQLiteWikiStore(db)
    await store.upsert_pages([_page("a"), _page("b")])
    assert await store.index_drift() == {}

    raw = sqlite3.connect(db)
    raw.execute("DELETE FROM pages_fts_docsize")
    raw.commit()
    raw.close()

    assert await store.index_drift() != {}
    result = await store.rebuild_index()
    assert "pages_fts" in result["rebuilt"]
    assert await store.index_drift() == {}
