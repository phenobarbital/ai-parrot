"""Client-side chunking of the remote ``wiki_sync_push`` (FEAT-678)."""

import json

import pytest

from parrot.knowledge.wiki.remote_cli import sync_push_remote
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.tools import SYNC_PUSH_MAX_BYTES, SYNC_PUSH_MAX_PAGES


class _RecordingClient:
    """Answers ``wiki_sync_push`` like the server would, recording every call."""

    def __init__(self):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def call_tool(self, name, arguments):
        assert name == "wiki_sync_push"
        self.calls.append(arguments)
        payload = {"created": len(arguments["pages"]), "updated": 1, "skipped_older": 0}
        return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def _mem(concept_id: str, body: str = "b") -> WikiPageRecord:
    return WikiPageRecord(
        concept_id=concept_id,
        title=concept_id,
        body=body,
        origin="memory",
        asserted_by="human:a",
        updated_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "wiki"
    root.mkdir()
    return create_wiki_store(root, wiki_name="t", backend="sqlite")


async def test_push_is_chunked_by_count_and_edges_follow_their_pages(store):
    """Pages beyond the cap travel in several calls; every edge rides with an endpoint."""
    total = SYNC_PUSH_MAX_PAGES * 2 + 5
    await store.upsert_pages([_mem(f"memory:m{i:04d}") for i in range(total)])
    edges = [(f"memory:m{i:04d}", f"memory:m{(i + 1) % total:04d}", "references", "asserted") for i in range(total)]
    await store.add_edges(edges)
    client = _RecordingClient()

    result = await sync_push_remote(client, store)

    assert len(client.calls) == 3
    assert all(len(c["pages"]) <= SYNC_PUSH_MAX_PAGES for c in client.calls)
    assert all(len(json.dumps(c).encode()) <= SYNC_PUSH_MAX_BYTES for c in client.calls)
    assert sum(len(c["pages"]) for c in client.calls) == total
    for call in client.calls:
        ids = {p["concept_id"] for p in call["pages"]}
        assert all(e[0] in ids or e[1] in ids for e in call["edges"])
    assert sum(len(c["edges"]) for c in client.calls) == total
    assert result["created"] == total and result["updated"] == 3 and result["rejected"] == []


async def test_push_is_chunked_by_bytes_and_rejects_oversized_pages(store):
    """Large bodies split by byte budget; a page over the budget alone is reported, not sent."""
    body = "x" * 300_000
    await store.upsert_pages([_mem(f"memory:b{i}", body) for i in range(6)] + [_mem("memory:huge", "y" * 1_100_000)])
    client = _RecordingClient()

    result = await sync_push_remote(client, store)

    assert result["rejected"] == ["memory:huge"]
    assert len(client.calls) == 2
    assert all(len(json.dumps(c).encode()) <= SYNC_PUSH_MAX_BYTES for c in client.calls)
    assert sum(len(c["pages"]) for c in client.calls) == 6
    assert result["created"] == 6


async def test_push_with_no_memory_pages_sends_nothing(store):
    """An empty memory plane makes no remote calls."""
    client = _RecordingClient()
    result = await sync_push_remote(client, store)
    assert client.calls == []
    assert result == {"created": 0, "updated": 0, "skipped_older": 0, "rejected": []}
