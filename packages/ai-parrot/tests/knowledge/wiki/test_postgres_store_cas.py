"""PostgresWikiStore CAS contract against a live plane (FEAT-578 M2, AC8)."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.wiki.postgres_store import PostgresWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord

#: AC8 requires a MISSING live backend to be reported, not silently green.
SKIP_REASON = "Postgres live fixture unavailable: set the wiki Postgres DSN env to validate AC8 parity"

PG_DSN = os.environ.get("WIKI_POSTGRES_DSN") or os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn

pytestmark = pytest.mark.skipif(not PG_DSN, reason=SKIP_REASON)


def _page(concept_id: str = "adr:doc:a", body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    """A minimal managed-looking page; the CAS primitive is category-agnostic."""
    return WikiPageRecord(concept_id=concept_id, title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
def tmp_schema() -> str:
    """Generate a unique temporary schema name."""
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def store(tmp_schema):
    """A live Postgres plane on a throwaway schema."""
    store = PostgresWikiStore(PG_DSN, wiki_name="test-wiki", schema=tmp_schema)
    try:
        yield store
    finally:
        pool = await store._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await store.close()


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

    async def test_conflict_leaves_open_row_intact(self, store):
        """AC6: a loser must not be able to erase the winner's write."""
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page(body="winner", content_hash="h2"), "h1")
        assert await store.compare_and_swap_page(_page(body="loser", content_hash="h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"

    async def test_version_history_is_preserved(self, store):
        """Close-and-insert, not in-place update: the old version survives."""
        # Two successful CAS writes
        await store.compare_and_swap_page(_page(body="v1", content_hash="h1"), None)
        await store.compare_and_swap_page(_page(body="v2", content_hash="h2"), "h1")

        # Query node_versions for this concept_id
        pool = await store._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT validity, content_hash FROM {store._schema}.node_versions
                WHERE concept_id = $1
                ORDER BY updated_at ASC
                """,
                "adr:doc:a",
            )

        # Assert there are 2 rows, exactly one with upper_inf(validity)
        assert len(rows) == 2
        open_count = sum(1 for row in rows if row["validity"].upper_inf)
        closed_count = sum(1 for row in rows if not row["validity"].upper_inf)
        assert open_count == 1, f"Expected 1 open row, got {open_count}"
        assert closed_count == 1, f"Expected 1 closed row, got {closed_count}"

    async def test_full_record_roundtrips(self, store):
        """Every page field written by _upsert_page survives a CAS write."""
        page = WikiPageRecord(
            concept_id="adr:doc:b",
            title="Full Title",
            category="adr",
            body="Full body content",
            content_hash="hash_full",
            summary="Summary text",
            source_id="source:123",
            origin="manual",
            asserted_by="test-user",
            updated_at="2020-01-01T00:00:00+00:00",
        )

        # CAS the fully populated page
        assert await store.compare_and_swap_page(page, None) is True

        # Read it back
        read_page = await store.get_page("adr:doc:b")
        assert read_page is not None
        assert read_page["title"] == "Full Title"
        assert read_page["body"] == "Full body content"
        assert read_page["content_hash"] == "hash_full"
        assert read_page["summary"] == "Summary text"
        assert read_page["source_id"] == "source:123"
        assert read_page["origin"] == "manual"
        assert read_page["asserted_by"] == "test-user"
        assert read_page["updated_at"] == "2020-01-01T00:00:00+00:00"


async def test_concurrent_cas_has_exactly_one_winner(store):
    """AC6/AC8: two writers from the same read — exactly one lands."""
    # Insert initial page
    await store.compare_and_swap_page(_page(), None)

    # Two concurrent writers both trying to write based on the same hash
    results = await asyncio.gather(
        store.compare_and_swap_page(_page(body="a", content_hash="h2"), "h1"),
        store.compare_and_swap_page(_page(body="b", content_hash="h3"), "h1"),
    )

    # Exactly one should succeed, one should fail
    assert sorted(results) == [False, True]

    # Verify the winner's body is stored (whichever one won)
    stored_page = await store.get_page("adr:doc:a")
    assert stored_page["body"] in ("a", "b")
    assert stored_page["content_hash"] in ("h2", "h3")


async def test_concurrent_insert_when_absent_has_exactly_one_winner(store):
    """AC6/AC8: two writers racing an insert-only CAS on the SAME absent page.

    Regression guard for the absent-insert TOCTOU: `FOR UPDATE OF v` alone
    cannot lock a row that does not exist yet, so both concurrent callers
    could previously read the "absent" precondition as true and both
    report `True` after the `nodes` table's own ON CONFLICT serialized
    their writes (see `compare_and_swap_page`'s advisory-lock fix). Distinct
    from `test_concurrent_cas_has_exactly_one_winner`, which only races the
    replace-on-matching-hash branch against a page that already exists.
    """
    results = await asyncio.gather(
        store.compare_and_swap_page(_page(body="a", content_hash="h2"), None),
        store.compare_and_swap_page(_page(body="b", content_hash="h3"), None),
    )

    # Exactly one insert-only write should land; the other must see the row
    # the winner just created and report a lost race, not a second "success".
    assert sorted(results) == [False, True]

    stored_page = await store.get_page("adr:doc:a")
    assert stored_page["body"] in ("a", "b")
    assert stored_page["content_hash"] in ("h2", "h3")

    # Exactly one node_versions row must exist for this concept_id — two
    # "successful" inserts would otherwise each leave their own row behind.
    pool = await store._ensure_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            f"SELECT count(*) FROM {store._schema}.node_versions WHERE concept_id = $1",
            "adr:doc:a",
        )
    assert count == 1
