"""compare_and_swap_page contract — SQLite + the base default (FEAT-578 M2)."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord


def _page(concept_id: str = "adr:doc:a", body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    """A minimal managed-looking page; the CAS primitive is category-agnostic."""
    return WikiPageRecord(concept_id=concept_id, title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
async def store(tmp_path):
    """A real SQLite plane — the conflict semantics only exist at the DB level."""
    return SQLiteWikiStore(tmp_path / "wiki.db")


class TestCasInsertUpdateConflict:
    async def test_insert_when_absent(self, store):
        """expected=None inserts a brand-new row."""
        assert await store.compare_and_swap_page(_page(), None) is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_insert_refuses_when_present(self, store):
        """expected=None is insert-ONLY — it never matches an existing row."""
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page(body="v2", content_hash="h2"), None) is False
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_replace_on_matching_hash(self, store):
        """The happy path: the hash we last read is still stored."""
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page(body="v2", content_hash="h2"), "h1") is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_conflict_on_stale_hash_leaves_row_intact(self, store):
        """AC6: a loser must not be able to erase the winner's write."""
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page(body="winner", content_hash="h2"), "h1")
        assert await store.compare_and_swap_page(_page(body="loser", content_hash="h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"

    async def test_update_of_absent_row_is_a_conflict(self, store):
        """A non-None expectation against a missing row is False, not an insert."""
        assert await store.compare_and_swap_page(_page(), "h1") is False
        assert await store.get_page("adr:doc:a") is None

    async def test_read_only_store_refuses(self, tmp_path):
        """A read-only plane raises rather than silently reporting a conflict."""
        db_path = tmp_path / "wiki.db"
        writable = SQLiteWikiStore(db_path)
        await writable.compare_and_swap_page(_page(), None)
        read_only_store = SQLiteWikiStore(db_path, read_only=True)
        with pytest.raises(PermissionError):
            await read_only_store.compare_and_swap_page(_page(body="v2", content_hash="h2"), "h1")


class _MinimalWikiStore(BaseWikiStore):
    """Out-of-tree-style backend that implements only the abstract surface.

    Used to prove that leaving ``compare_and_swap_page`` unoverridden does
    not prevent instantiation — the concrete default matters precisely
    because @abstractmethod would.
    """

    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int:
        return 0

    async def add_edges(self, edges: list[tuple]) -> int:
        return 0

    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
    ) -> dict[str, Any]:
        return {}

    async def delete_page(self, concept_id: str) -> bool:
        return False

    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None:
        return None

    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]:
        return None

    async def list_pages(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        origin: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        return []

    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:
        return []

    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
        return []

    async def neighbors(
        self,
        concept_id: str,
        rel: Optional[str] = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        return []

    async def dump_pages(self) -> list[dict[str, Any]]:
        return []

    async def dump_edges(self) -> list[dict[str, Any]]:
        return []

    async def stats(self) -> dict[str, Any]:
        return {}

    async def orphan_sources(self) -> list[str]:
        return []

    async def broken_edges(self) -> list[dict[str, Any]]:
        return []

    async def missing_bodies(self) -> list[str]:
        return []


class TestUnsupportedBackend:
    async def test_base_default_raises_not_implemented(self):
        """An out-of-tree backend stays instantiable but cannot CAS."""
        backend = _MinimalWikiStore()
        with pytest.raises(NotImplementedError):
            await backend.compare_and_swap_page(_page(), None)
