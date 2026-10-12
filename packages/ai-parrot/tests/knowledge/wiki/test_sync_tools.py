"""Unit tests for remote wiki sync bulk tools (FEAT-569 TASK-3357)."""

import pytest

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.tools import WikiSyncPullTool, WikiSyncPushTool, create_bulk_tools


def _mem(concept_id: str, body: str, updated_at: str, asserted_by: str = "human:a") -> WikiPageRecord:
    """Build a memory-origin record with a stable LWW timestamp."""
    return WikiPageRecord(
        concept_id=concept_id,
        title=concept_id,
        body=body,
        origin="memory",
        asserted_by=asserted_by,
        updated_at=updated_at,
    )


@pytest.fixture
def store(tmp_path):
    """Create an isolated SQLite wiki plane."""
    root = tmp_path / "wiki"
    root.mkdir()
    return create_wiki_store(root, wiki_name="t", backend="sqlite")


async def test_push_is_lww_and_copies_asserted_edges(store):
    """Older pushes preserve the server page, while newer pushes replace it."""
    await store.upsert_pages([_mem("memory:x", "server-new", "2026-02-01T00:00:00+00:00")])
    tool = WikiSyncPushTool(store, "t")
    await tool._execute(
        pages=[_mem("memory:x", "client-old", "2026-01-01T00:00:00+00:00")],
        edges=[("memory:x", "memory:related", "references", "asserted")],
    )
    assert (await store.get_page("memory:x"))["body"] == "server-new"
    assert await store.dump_edges() == [{"src": "memory:x", "dst": "memory:related", "rel": "references"}]
    await tool._execute(pages=[_mem("memory:x", "client-newer", "2026-03-01T00:00:00+00:00")])
    assert (await store.get_page("memory:x"))["body"] == "client-newer"


async def test_pull_paginates_filters_and_returns_asserted_edges(store, tmp_path):
    """Pull pages use stable cursors and exclude the requested author and old records."""
    await store.upsert_pages(
        [
            _mem(
                f"memory:p{i:04d}",
                "body",
                f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00",
                "human:skip" if i == 0 else "human:a",
            )
            for i in range(1201)
        ]
    )
    await store.add_edges([("memory:p1100", "memory:p1101", "references", "asserted")])
    tool = WikiSyncPullTool(store)
    seen, cursor = 0, None
    for expected in (500, 500, 200):
        result = (
            await tool._execute(
                since="2026-01-01T00:00:00+00:00",
                skip_asserted_by="human:skip",
                limit=500,
                cursor=cursor,
            )
        ).result
        assert len(result["pages"]) == expected
        seen += expected
        cursor = result["next_cursor"]
    assert cursor is None
    assert seen == 1200
    assert any(edge[:3] == ("memory:p1100", "memory:p1101", "references") for edge in result["edges"])
    assert [tool.name for tool in create_bulk_tools(store, tmp_path, WikiProjectConfig(wiki_name="t"))] == [
        "wiki_page_hashes",
        "wiki_ingest_batch",
        "wiki_sync_push",
        "wiki_sync_pull",
    ]
