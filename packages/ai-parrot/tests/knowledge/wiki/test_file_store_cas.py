"""InMemoryWikiStore CAS contract + stale-snapshot regression (FEAT-578 M2)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord


def _page(body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    return WikiPageRecord(concept_id="adr:doc:a", title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture
def bundle(tmp_path):
    """A fresh OKF bundle directory."""
    return tmp_path / "pages"


class TestCasInsertUpdateConflict:
    async def test_insert_when_absent(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        assert await store.compare_and_swap_page(_page(), None) is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v1"

    async def test_insert_refuses_when_present(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), None) is False

    async def test_replace_on_matching_hash(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        await store.compare_and_swap_page(_page(), None)
        assert await store.compare_and_swap_page(_page("v2", "h2"), "h1") is True
        assert (await store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_conflict_leaves_row_intact(self, bundle):
        store = InMemoryWikiStore(bundle, wiki_name="t")
        await store.compare_and_swap_page(_page(), None)
        await store.compare_and_swap_page(_page("winner", "h2"), "h1")
        assert await store.compare_and_swap_page(_page("loser", "h3"), "h1") is False
        assert (await store.get_page("adr:doc:a"))["body"] == "winner"


class TestStaleSnapshot:
    async def test_cas_sees_a_peer_process_write(self, bundle):
        """spec §7: a startup snapshot must never authorize a write.

        Two stores over one bundle stand in for two processes.
        """
        writer_a = InMemoryWikiStore(bundle, wiki_name="t")
        writer_b = InMemoryWikiStore(bundle, wiki_name="t")

        # Both "processes" start from the same initial state.
        assert await writer_a.compare_and_swap_page(_page(), None) is True
        # Force writer_b to load its RAM snapshot now, while it still
        # matches writer_a's initial write (content_hash="h1").
        await writer_b._ensure_loaded()
        assert writer_b._pages["adr:doc:a"]["content_hash"] == "h1"

        # writer_a advances the file to h2 — a peer process's write that
        # writer_b's RAM snapshot does not know about.
        assert await writer_a.compare_and_swap_page(_page("a-wins", "h2"), "h1") is True

        # writer_b, still holding a stale "h1" expectation in its own head
        # (never re-read after its own _ensure_loaded), must lose — the
        # persisted file (not its RAM snapshot) is the source of truth.
        assert await writer_b.compare_and_swap_page(_page("b-loses", "h3"), "h1") is False

        # The file must still hold writer_a's body, unharmed.
        on_disk = await writer_a.get_page("adr:doc:a")
        assert on_disk["body"] == "a-wins"
        assert on_disk["content_hash"] == "h2"

    async def test_write_is_atomic_on_disk(self, bundle):
        """A replacement never leaves a partial page file behind."""
        store = InMemoryWikiStore(bundle, wiki_name="t")
        assert await store.compare_and_swap_page(_page(), None) is True
        assert await store.compare_and_swap_page(_page("v2", "h2"), "h1") is True

        page_dir = store._page_path({"concept_id": "adr:doc:a", "category": "adr"}).parent
        names = [p.name for p in page_dir.iterdir()]
        assert not any(name.endswith(".tmp") or name.startswith(".") and ".tmp." in name for name in names), names
        # Exactly the one rendered page file remains, nothing else.
        assert len(names) == 1
