"""Persistence wrapping and ownership (close) semantics — no live services."""

from __future__ import annotations

from typing import Any

import pytest

from parrot.knowledge.graphindex.persist_arango import ArangoPersistence, create_arango_persistence
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.protocols import (
    EmbeddingPersistence,
    GraphPersistence,
    IncrementalPersistence,
    SourceCoherencePersistence,
)
from parrot.loaders.graphindex import capture_persistence


class _FakeClient:
    def __init__(self) -> None:
        self.closed = 0

    async def connection(self) -> None:
        return None

    async def close(self) -> None:
        self.closed += 1


def test_capture_wrapper_keeps_protocols_sqlite(tmp_path: Any) -> None:
    inner = SQLitePersistence(tmp_path)
    wrapped = capture_persistence(inner)
    assert isinstance(wrapped, GraphPersistence)
    assert isinstance(wrapped, IncrementalPersistence) == isinstance(inner, IncrementalPersistence)
    assert isinstance(wrapped, IncrementalPersistence)
    assert isinstance(wrapped, EmbeddingPersistence) == isinstance(inner, EmbeddingPersistence)
    assert isinstance(wrapped, SourceCoherencePersistence) == isinstance(inner, SourceCoherencePersistence)


@pytest.mark.asyncio
async def test_capture_forwards_is_stale_and_close() -> None:
    calls: list[str] = []

    class Inner:
        async def persist_graph(self, ctx, nodes, edges):
            return {}

        async def replace_document_slice(self, ctx, uri, nodes, edges):
            return {}

        async def is_stale(self, ctx, uri, mtime, sha1):
            calls.append("is_stale")
            return False

        async def close(self):
            calls.append("close")

    wrapped = capture_persistence(Inner())
    assert isinstance(wrapped, IncrementalPersistence)
    assert not isinstance(wrapped, EmbeddingPersistence)
    assert await wrapped.is_stale(None, "u", 0.0, "x") is False
    await wrapped.close()
    assert calls == ["is_stale", "close"]


@pytest.mark.asyncio
async def test_arango_factory_owns_client_it_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient()
    import asyncdb

    monkeypatch.setattr(asyncdb, "AsyncDB", lambda *a, **k: client)
    persistence = await create_arango_persistence(arango_params={"host": "x"})
    await persistence.close()
    await persistence.close()
    assert client.closed == 1


@pytest.mark.asyncio
async def test_arango_does_not_close_caller_store() -> None:
    client = _FakeClient()

    class Store:
        _client = client

    persistence = await create_arango_persistence(graph_store=Store())  # type: ignore[arg-type]
    assert isinstance(persistence, ArangoPersistence)
    await persistence.close()
    assert client.closed == 0


@pytest.mark.asyncio
async def test_loader_closes_persistence_after_build(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.loaders.graphindex import GraphIndexLoader

    src = tmp_path / "a.md"
    src.write_text("# Title\n\nbody text\n")
    loader = GraphIndexLoader(src, sqlite_dir=tmp_path / "db", output_dir=tmp_path / "out")
    closed: list[int] = []
    orig = SQLitePersistence.close

    async def _close(self: Any) -> None:
        closed.append(1)
        await orig(self)

    monkeypatch.setattr(SQLitePersistence, "close", _close)
    await loader.build_graph()
    assert closed == [1]


@pytest.mark.asyncio
async def test_build_toolkit_closes_on_failure(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.knowledge.graphindex import factory

    closed: list[int] = []

    class Boom:
        async def load_graph(self, ctx: Any) -> Any:
            raise RuntimeError("boom")

        async def close(self) -> None:
            closed.append(1)

    async def _create(*a: Any, **k: Any) -> Boom:
        return Boom()

    monkeypatch.setattr(factory, "create_graph_persistence", _create)
    with pytest.raises(Exception):
        await factory.build_graph_memory_toolkit(tenant_id="t", db_dir=tmp_path)
    assert closed == [1]
