"""FEAT-461 Module 4 (TASK-2465): `updated_at` surfacing + upsert semantics.

`WikiPageRecord.updated_at` round-trips through both backends; a caller-
supplied stamp is preserved verbatim on upsert (the sync prerequisite),
while an absent one still gets stamped "now" — the pre-existing behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


def _page(cid: str, **kw) -> WikiPageRecord:
    """Shorthand page-record builder (mirrors test_store.py's helper)."""
    defaults = {
        "concept_id": cid,
        "title": kw.pop("title", cid.replace("-", " ").title()),
        "category": kw.pop("category", "concept"),
        "summary": kw.pop("summary", f"Summary of {cid}"),
        "body": kw.pop("body", f"# {cid}\n\nBody of {cid}."),
    }
    defaults.update(kw)
    return WikiPageRecord(**defaults)


def _is_iso_utc(value: str) -> bool:
    datetime.fromisoformat(value)
    return True


class TestSqliteUpdatedAt:
    async def test_upsert_stamps_now_when_none(self, tmp_path: Path) -> None:
        store = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="w")
        await store.upsert_pages([_page("intro")])
        page = await store.get_page("intro")
        assert page["updated_at"] is not None
        assert _is_iso_utc(page["updated_at"])

    async def test_upsert_preserves_explicit_stamp(self, tmp_path: Path) -> None:
        store = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="w")
        stamp = "2020-01-01T00:00:00+00:00"
        await store.upsert_pages([_page("intro", updated_at=stamp)])
        page = await store.get_page("intro")
        assert page["updated_at"] == stamp

    async def test_get_page_and_list_pages_return_updated_at(self, tmp_path: Path) -> None:
        store = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="w")
        await store.upsert_pages([_page("intro")])
        page = await store.get_page("intro")
        assert "updated_at" in page
        stubs = await store.list_pages()
        assert "updated_at" in stubs[0]

    async def test_created_at_survives_conflict_update(self, tmp_path: Path) -> None:
        store = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="w")
        await store.upsert_pages([_page("intro")])
        first = await store.get_page("intro")
        created_at = first["created_at"]
        # Second upsert of the SAME concept_id (conflict path) with an
        # explicit, different updated_at.
        await store.upsert_pages([_page("intro", updated_at="2099-01-01T00:00:00+00:00")])
        second = await store.get_page("intro")
        assert second["created_at"] == created_at
        assert second["updated_at"] == "2099-01-01T00:00:00+00:00"


class TestRememberStamp:
    @pytest.fixture
    def toolkit(self, tmp_path: Path):
        from parrot.knowledge.wiki.models import WikiConfig
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        config = WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path / "wiki")
        return LLMWikiToolkit(
            pageindex_toolkit=None,
            graphindex_toolkit=None,
            okf_toolkit=None,
            config=config,
        )

    async def test_remember_roundtrip_has_fresh_iso_stamp(self, toolkit) -> None:
        before = datetime.now(UTC).replace(microsecond=0)
        await toolkit.remember("test-wiki", "The sky is blue.", title="sky-fact")
        pages = await toolkit._store.list_pages(origin=["memory"])
        assert len(pages) == 1
        stamp = pages[0]["updated_at"]
        assert _is_iso_utc(stamp)
        parsed = datetime.fromisoformat(stamp)
        # `_now_iso()` truncates sub-second precision — allow equality.
        assert parsed >= before


@pytest.fixture
def arango_params():
    return {"host": "127.0.0.1", "port": 8529, "username": "root", "password": ""}


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.connection = AsyncMock(return_value=db)
    db.close = AsyncMock()
    db.collection_exists = AsyncMock(return_value=False)
    db.create_collection = AsyncMock()
    db.create_arangosearch_view = AsyncMock()
    db.query = AsyncMock(return_value=([], None))
    db.execute = AsyncMock(return_value=([], None))
    db._connection = MagicMock()
    db._connection.views = AsyncMock(return_value=[])
    db._connection.create_view = AsyncMock()
    return db


@pytest.fixture
def arango_store(arango_params, mock_db):
    with patch("parrot.knowledge.wiki.arango_store.AsyncDB", return_value=mock_db):
        yield ArangoDBWikiStore(arango_params, wiki_name="test")


class TestArangoUpdatedAt:
    """Mocked ``AsyncDB`` — no real ArangoDB server needed."""

    async def test_upsert_stamps_now_when_none(self, arango_store, mock_db) -> None:
        await arango_store.upsert_pages([_page("intro")])
        docs = mock_db.execute.call_args.kwargs["bind_vars"]["docs"]
        assert _is_iso_utc(docs[0]["updated_at"])

    async def test_upsert_preserves_explicit_stamp(self, arango_store, mock_db) -> None:
        stamp = "2020-01-01T00:00:00+00:00"
        await arango_store.upsert_pages([_page("intro", updated_at=stamp)])
        docs = mock_db.execute.call_args.kwargs["bind_vars"]["docs"]
        assert docs[0]["updated_at"] == stamp
        # created_at is never taken from the caller.
        assert docs[0]["created_at"] != stamp
