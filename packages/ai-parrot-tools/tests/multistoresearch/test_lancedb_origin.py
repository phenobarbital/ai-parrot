"""LanceDBOrigin contract and lifecycle tests (FEAT-542, AC7). No SDK required."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch.origins import LanceDBOrigin


class FakeSearchResult:
    def __init__(self, id: str, content: str, score: float, metadata: dict):
        self.id = id
        self.content = content
        self.score = score
        self.metadata = metadata


class FakeStore:
    """Records calls; returns canned results. No SDK, no I/O."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.disconnect_called = False
        self.results: list[FakeSearchResult] = [
            FakeSearchResult("lancedb:uuid:a", "doc a", 0.1, {"_lancedb": {"score_kind": "cosine_distance"}}),
            FakeSearchResult("lancedb:uuid:b", "doc b", 0.5, {"_lancedb": {"score_kind": "cosine_distance"}}),
        ]
        self.raise_on_search: Exception | None = None

    async def similarity_search(self, query, collection=None, limit=10, metadata_filters=None, include_parents=False):
        self.calls.append(
            (
                "similarity_search",
                {
                    "query": query,
                    "collection": collection,
                    "limit": limit,
                    "metadata_filters": metadata_filters,
                    "include_parents": include_parents,
                },
            )
        )
        if self.raise_on_search:
            raise self.raise_on_search
        return self.results

    async def hybrid_search(self, query, collection=None, limit=10, metadata_filters=None, include_parents=False):
        self.calls.append(
            (
                "hybrid_search",
                {
                    "query": query,
                    "collection": collection,
                    "limit": limit,
                    "metadata_filters": metadata_filters,
                    "include_parents": include_parents,
                },
            )
        )
        if self.raise_on_search:
            raise self.raise_on_search
        return self.results

    async def fulltext_search(self, query, collection=None, limit=10, metadata_filters=None, include_parents=False):
        self.calls.append(
            (
                "fulltext_search",
                {
                    "query": query,
                    "collection": collection,
                    "limit": limit,
                    "metadata_filters": metadata_filters,
                    "include_parents": include_parents,
                },
            )
        )
        if self.raise_on_search:
            raise self.raise_on_search
        return self.results

    async def disconnect(self):  # pragma: no cover — must never be called
        self.disconnect_called = True
        raise AssertionError("LanceDBOrigin must never close/disconnect a borrowed store")


class TestDispatch:
    @pytest.mark.parametrize("mode,expected_call", [("vector", "similarity_search"), ("hybrid", "hybrid_search")])
    async def test_search_dispatches_by_mode(self, mode, expected_call):
        store = FakeStore()
        origin = LanceDBOrigin(store, mode=mode)
        await origin.search("hello", k=5)
        assert store.calls[0][0] == expected_call
        assert store.calls[0][1]["query"] == "hello"
        assert store.calls[0][1]["limit"] == 5

    async def test_fts_search_always_routes_to_fulltext(self):
        store = FakeStore()
        origin = LanceDBOrigin(store, mode="vector")  # even in vector mode
        await origin.fts_search("hello", k=3)
        assert store.calls[0][0] == "fulltext_search"

        store2 = FakeStore()
        origin2 = LanceDBOrigin(store2, mode="hybrid")
        await origin2.fts_search("hello", k=3)
        assert store2.calls[0][0] == "fulltext_search"

    async def test_fixed_scope_is_forwarded(self):
        store = FakeStore()
        origin = LanceDBOrigin(
            store,
            mode="hybrid",
            collection="agent_knowledge",
            metadata_filters={"source": "x"},
            include_parents=True,
        )
        await origin.search("hello", k=5)
        kwargs = store.calls[0][1]
        assert kwargs["collection"] == "agent_knowledge"
        assert kwargs["metadata_filters"] == {"source": "x"}
        assert kwargs["include_parents"] is True


class TestNormalization:
    async def test_native_score_and_order_unchanged_and_rank_is_one_based(self):
        store = FakeStore()
        origin = LanceDBOrigin(store, mode="vector")
        hits = await origin.search("hello", k=5)
        assert [h.native_rank for h in hits] == [1, 2]
        assert hits[0].score == 0.1
        assert hits[1].score == 0.5
        assert hits[0].content == "doc a"
        assert hits[0].origin == "lancedb"
        assert hits[0].origin_kind == SearchOriginKind.VECTOR

    async def test_provenance_metadata_survives(self):
        store = FakeStore()
        origin = LanceDBOrigin(store, mode="hybrid")
        hits = await origin.search("hello", k=5)
        assert hits[0].metadata["_lancedb"]["score_kind"] == "cosine_distance"


class TestLifecycleAndErrors:
    async def test_origin_never_closes_the_borrowed_store(self):
        store = FakeStore()
        origin = LanceDBOrigin(store, mode="vector")
        await origin.search("hello", k=5)
        assert store.disconnect_called is False

    async def test_errors_propagate(self):
        store = FakeStore()
        store.raise_on_search = RuntimeError("backend failure")
        origin = LanceDBOrigin(store, mode="hybrid")
        with pytest.raises(RuntimeError, match="backend failure"):
            await origin.search("hello", k=5)

    async def test_cancellation_propagates(self):
        store = FakeStore()

        async def cancelling_search(*a, **k):
            raise asyncio.CancelledError()

        store.hybrid_search = cancelling_search
        origin = LanceDBOrigin(store, mode="hybrid")
        with pytest.raises(asyncio.CancelledError):
            await origin.search("hello", k=5)


def test_importing_origins_package_requires_no_sdk():
    script = (
        "import sys, builtins\n"
        "_real_import = builtins.__import__\n"
        "def _blocked(name, globals=None, locals=None, fromlist=(), level=0):\n"
        "    # Only block the real, top-level 'lancedb' SDK package (level=0,\n"
        "    # absolute import) — NOT the relative 'from .lancedb import X'\n"
        "    # submodule import inside parrot_tools.multistoresearch.origins.\n"
        "    if level == 0 and (name == 'lancedb' or name.startswith('lancedb.')):\n"
        "        raise ImportError('lancedb must not be imported here')\n"
        "    return _real_import(name, globals, locals, fromlist, level)\n"
        "builtins.__import__ = _blocked\n"
        "from parrot_tools.multistoresearch.origins import LanceDBOrigin\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
