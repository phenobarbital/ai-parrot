"""ArangoDB CAS contract against a live plane (FEAT-578 M2, AC8)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord

#: AC8 requires a MISSING live backend to be reported, not silently green.
#: The reason string is asserted on by the parity test in TASK-3497.
SKIP_REASON = "ArangoDB live fixture unavailable: set ARANGODB_HOST/ARANGODB_PASSWORD to validate AC8 parity"

pytestmark = pytest.mark.skipif(not os.getenv("ARANGODB_HOST"), reason=SKIP_REASON)


def _page(body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    return WikiPageRecord(concept_id="adr:doc:a", title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
async def store():
    """A live ArangoDB plane on a throwaway database."""
    test_db_name = f"wiki_test_cas_{uuid.uuid4().hex[:8]}"
    arango_params = {
        "host": os.getenv("ARANGODB_HOST", "127.0.0.1"),
        "port": int(os.getenv("ARANGODB_PORT", "8529")),
        "username": os.getenv("ARANGODB_USERNAME", "root"),
        "password": os.getenv("ARANGODB_PASSWORD", ""),
    }
    store_instance = ArangoDBWikiStore(
        arango_params,
        database=test_db_name,
        wiki_name="test_cas",
    )
    await store_instance.initialize()

    yield store_instance

    await store_instance.close()
    if store_instance._db is not None:
        try:
            await store_instance._db._connection.delete_database(test_db_name)
        except Exception:
            pass


class TestCasInsertUpdateConflict:
    """Test insert-only, update on match, and conflict handling."""

    async def test_insert_when_absent(self, store):
        """Insert succeeds when document does not exist."""
        assert await store.compare_and_swap_page(_page(), None) is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_insert_refuses_when_present(self, store):
        """expected=None must NOT behave like an UPSERT."""
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), None) is False
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_replace_on_matching_hash(self, store):
        """Update succeeds when content_hash matches."""
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), "h1") is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_conflict_returns_false_not_raises(self, store):
        """A lost race is a False return — the driver's error never escapes."""
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page("winner", "h2"), "h1")
        assert await store.compare_and_swap_page(_page("loser", "h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"

    async def test_full_record_roundtrips(self, store):
        """Every page field written by upsert_pages survives a CAS write."""
        page = WikiPageRecord(
            concept_id="adr:doc:b",
            node_id="node123",
            title="ADR Title",
            category="adr",
            summary="A brief summary",
            body="Full body content",
            source_id="source:adr",
            token_count=42,
            origin="authored",
            asserted_by="agent:reviewer",
            updated_at="2026-09-19T12:00:00+00:00",
            content_hash="h_initial",
        )
        assert await store.compare_and_swap_page(page, None) is True
        stored = await store.get_page("adr:doc:b")
        assert stored is not None
        assert stored["node_id"] == "node123"
        assert stored["title"] == "ADR Title"
        assert stored["category"] == "adr"
        assert stored["summary"] == "A brief summary"
        assert stored["body"] == "Full body content"
        assert stored["source_id"] == "source:adr"
        assert stored["token_count"] == 42
        assert stored["origin"] == "authored"
        assert stored["asserted_by"] == "agent:reviewer"
        assert stored["content_hash"] == "h_initial"

    async def test_read_only_store_refuses(self):
        """read_only=True raises before any network call."""
        arango_params = {
            "host": os.getenv("ARANGODB_HOST", "127.0.0.1"),
            "port": int(os.getenv("ARANGODB_PORT", "8529")),
            "username": os.getenv("ARANGODB_USERNAME", "root"),
            "password": os.getenv("ARANGODB_PASSWORD", ""),
        }
        read_only_store = ArangoDBWikiStore(
            arango_params,
            database="wiki_test_cas",
            wiki_name="test_cas",
            read_only=True,
        )
        with pytest.raises(PermissionError):
            await read_only_store.compare_and_swap_page(_page(), None)


async def test_concurrent_cas_has_exactly_one_winner(store):
    """AC6/AC8: two concurrent writers from the same read — one wins."""
    assert await store.compare_and_swap_page(_page(body="base", content_hash="h_base"), None) is True

    async def cas_writer(body: str) -> bool:
        return await store.compare_and_swap_page(_page(body=body, content_hash="h_next"), "h_base")

    results = await asyncio.gather(
        cas_writer("winner"),
        cas_writer("loser"),
    )

    assert results.count(True) == 1
    assert results.count(False) == 1

    stored = await store.get_page("adr:doc:a")
    assert stored["body"] in ["winner", "loser"]
    assert stored["content_hash"] == "h_next"
