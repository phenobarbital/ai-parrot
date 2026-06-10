"""Unit tests for parrot.knowledge.graphindex.loader.GraphIndexLoader.

The heavy pipeline pieces (embedder, builder, ArangoDB) are replaced with
fakes so the loader's wiring is exercised without models or a live database:

* a fake ``GraphIndexBuilder`` whose ``build`` feeds canned nodes/edges through
  the persistence object the loader supplied (so the capturing wrapper records
  them), then returns a ``BuildResult``;
* the no-credentials path is asserted to use the in-memory ``_NullPersistence``;
* the credentials path is asserted to construct an ``OntologyGraphStore`` +
  ``GraphIndexPersistence`` against a mocked asyncdb client.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

import parrot.knowledge.graphindex.loader as loader_mod
from parrot.knowledge.graphindex.loader import (
    GraphIndexLoader,
    _NullPersistence,
)
from parrot.knowledge.graphindex.schema import (
    BuildResult,
    NodeKind,
    UniversalNode,
)
from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document


_FAKE_NODES = [
    UniversalNode(
        node_id="n1",
        kind=NodeKind.DOCUMENT,
        title="Doc One",
        source_uri="a.md",
        summary="summary one",
    ),
    UniversalNode(
        node_id="n2",
        kind=NodeKind.SECTION,
        title="Section Two",
        source_uri="a.md",
        parent_id="n1",
    ),
]


@pytest.fixture
def patched(monkeypatch):
    """Patch the embedder and builder used inside the loader module."""
    captured: dict = {}

    monkeypatch.setattr(loader_mod, "GraphIndexEmbedder", MagicMock())

    class _FakeBuilder:
        def __init__(self, persistence, embedder, output_dir, **kwargs):
            self.persistence = persistence
            captured["persistence"] = persistence
            captured["output_dir"] = output_dir
            captured["kwargs"] = kwargs

        async def build(self, sources, ctx):
            captured["sources"] = sources
            await self.persistence.persist_graph(ctx, _FAKE_NODES, [])
            return BuildResult(
                tenant_id=ctx.tenant_id,
                node_count=len(_FAKE_NODES),
                edge_count=0,
                inferred_edge_count=0,
                report_path=None,
                errors=[],
            )

    monkeypatch.setattr(loader_mod, "GraphIndexBuilder", _FakeBuilder)
    return captured


class TestConstruction:
    def test_is_abstract_loader_subclass(self, patched):
        assert issubclass(GraphIndexLoader, AbstractLoader)

    def test_no_creds_disables_persistence(self, patched):
        loader = GraphIndexLoader(tenant_id="t")
        assert loader.persist_enabled is False

    def test_explicit_creds_enable_persistence(self, patched):
        loader = GraphIndexLoader(
            tenant_id="t",
            arango_host="127.0.0.1",
            arango_user="root",
            arango_password="secret",
            arango_database="kg",
        )
        assert loader.persist_enabled is True
        assert loader.arango_db == "kg"
        assert loader._arango_params["host"] == "127.0.0.1"


class TestLoad:
    @pytest.mark.asyncio
    async def test_load_returns_document_per_node(self, patched, tmp_path):
        loader = GraphIndexLoader(tenant_id="t", output_dir=tmp_path)
        (tmp_path / "a.md").write_text("x", encoding="utf-8")

        docs = await loader.load([tmp_path / "a.md"])

        assert len(docs) == 2
        assert all(isinstance(d, Document) for d in docs)
        assert {d.metadata["node_id"] for d in docs} == {"n1", "n2"}
        assert loader.build_result.node_count == 2

    @pytest.mark.asyncio
    async def test_no_creds_uses_null_persistence(self, patched, tmp_path):
        loader = GraphIndexLoader(tenant_id="t", output_dir=tmp_path)
        await loader.load([tmp_path])
        inner = patched["persistence"]._inner
        assert isinstance(inner, _NullPersistence)

    @pytest.mark.asyncio
    async def test_node_metadata_mapping(self, patched, tmp_path):
        loader = GraphIndexLoader(tenant_id="t", output_dir=tmp_path)
        docs = await loader.load([tmp_path])
        by_id = {d.metadata["node_id"]: d for d in docs}
        assert by_id["n1"].page_content == "summary one"
        assert by_id["n1"].metadata["kind"] == "document"
        assert by_id["n2"].metadata["parent_id"] == "n1"
        # Falls back to title when no summary.
        assert by_id["n2"].page_content == "Section Two"

    @pytest.mark.asyncio
    async def test_build_graph_exposes_nodes_edges(self, patched, tmp_path):
        loader = GraphIndexLoader(tenant_id="t", output_dir=tmp_path)
        result = await loader.build_graph([tmp_path])
        assert isinstance(result, BuildResult)
        assert len(loader.nodes) == 2
        assert loader.edges == []


class TestCredsPersistence:
    @pytest.mark.asyncio
    async def test_creds_path_builds_real_persistence(
        self, patched, monkeypatch, tmp_path
    ):
        # Mock asyncdb so no live server is touched.
        fake_db = MagicMock()
        fake_db.connection = AsyncMock()
        fake_asyncdb = MagicMock()
        fake_asyncdb.AsyncDB = MagicMock(return_value=fake_db)
        monkeypatch.setitem(__import__("sys").modules, "asyncdb", fake_asyncdb)

        fake_store = MagicMock()
        fake_store.initialize_tenant = AsyncMock()
        store_cls = MagicMock(return_value=fake_store)
        fake_persistence = MagicMock()
        fake_persistence.persist_graph = AsyncMock(
            return_value={"nodes_persisted": 2, "edges_persisted": 0}
        )
        persistence_cls = MagicMock(return_value=fake_persistence)
        monkeypatch.setattr(loader_mod, "OntologyGraphStore", store_cls)
        monkeypatch.setattr(loader_mod, "GraphIndexPersistence", persistence_cls)

        loader = GraphIndexLoader(
            tenant_id="t",
            output_dir=tmp_path,
            arango_host="127.0.0.1",
            arango_user="root",
            arango_password="secret",
            arango_database="kg",
        )
        await loader.build_graph([tmp_path])

        fake_asyncdb.AsyncDB.assert_called_once()
        store_cls.assert_called_once_with(arango_client=fake_db)
        fake_store.initialize_tenant.assert_awaited_once()
        persistence_cls.assert_called_once_with(fake_store)
