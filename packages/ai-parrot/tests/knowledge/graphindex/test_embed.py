"""Unit tests for parrot.knowledge.graphindex.embed."""

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode


def make_node(node_id: str, title: str, summary: str | None = None) -> UniversalNode:
    """Create a minimal UniversalNode for testing."""
    return UniversalNode(
        node_id=node_id,
        kind=NodeKind.DOCUMENT,
        title=title,
        source_uri="test.txt",
        summary=summary,
    )


class TestGraphIndexEmbedder:
    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.encode = AsyncMock(return_value=np.random.rand(3, 384).astype(np.float32))
        return model

    @pytest.fixture
    def embedder(self, mock_model):
        with patch.object(
            GraphIndexEmbedder, "__init__",
            lambda self, model_name="test", dimension=384, pgvector_dsn=None: setattr(
                self, "_model_name", model_name
            ) or setattr(
                self, "dimension", dimension
            ) or setattr(
                self, "pgvector_dsn", pgvector_dsn
            ) or setattr(
                self, "model", mock_model
            ) or setattr(
                self, "index", __import__("faiss").IndexFlatL2(dimension)
            ) or setattr(
                self, "_node_id_map", []
            ),
        ):
            emb = GraphIndexEmbedder(model_name="test", dimension=384)
        return emb

    @pytest.mark.asyncio
    async def test_embed_nodes_populates_embedding_ref(self, embedder, mock_model):
        nodes = [
            make_node("n1", "Title 1", "Summary 1"),
            make_node("n2", "Title 2", "Summary 2"),
            make_node("n3", "Title 3"),
        ]
        mock_model.encode.return_value = np.random.rand(3, 384).astype(np.float32)
        result = await embedder.embed_nodes(nodes)
        assert all(n.embedding_ref is not None for n in result)

    @pytest.mark.asyncio
    async def test_embed_nodes_adds_to_faiss(self, embedder, mock_model):
        nodes = [make_node("n1", "Title 1"), make_node("n2", "Title 2")]
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        await embedder.embed_nodes(nodes)
        assert embedder.index.ntotal == 2

    @pytest.mark.asyncio
    async def test_embed_nodes_updates_node_id_map(self, embedder, mock_model):
        nodes = [make_node("n1", "Title 1"), make_node("n2", "Title 2")]
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        await embedder.embed_nodes(nodes)
        assert "n1" in embedder._node_id_map
        assert "n2" in embedder._node_id_map

    @pytest.mark.asyncio
    async def test_embed_nodes_embedding_ref_format(self, embedder, mock_model):
        nodes = [make_node("n1", "Title 1")]
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        await embedder.embed_nodes(nodes)
        assert nodes[0].embedding_ref.startswith("faiss:")

    @pytest.mark.asyncio
    async def test_search_similar_returns_results(self, embedder, mock_model):
        nodes = [make_node("n1", "Title 1"), make_node("n2", "Title 2")]
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        await embedder.embed_nodes(nodes)
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        results = await embedder.search_similar("query", top_k=2)
        assert len(results) == 2
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    @pytest.mark.asyncio
    async def test_search_similar_empty_index_returns_empty(self, embedder, mock_model):
        results = await embedder.search_similar("query", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_embed_failure_sets_none(self, embedder, mock_model):
        mock_model.encode.side_effect = RuntimeError("Model error")
        nodes = [make_node("n1", "Title 1")]
        result = await embedder.embed_nodes(nodes)
        assert result[0].embedding_ref is None

    @pytest.mark.asyncio
    async def test_empty_nodes_returns_empty(self, embedder):
        result = await embedder.embed_nodes([])
        assert result == []

    def test_get_embed_text_prefers_summary(self, embedder):
        node = make_node("n1", "Title", "Summary text")
        assert embedder._get_embed_text(node) == "Summary text"

    def test_get_embed_text_falls_back_to_title(self, embedder):
        node = make_node("n1", "Title Only")
        assert embedder._get_embed_text(node) == "Title Only"

    def test_node_id_map_starts_empty(self, embedder):
        assert embedder._node_id_map == []

    def test_get_embedding_nonexistent_returns_none(self, embedder):
        result = embedder.get_embedding("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_embedding_after_embed(self, embedder, mock_model):
        nodes = [make_node("n1", "Title 1")]
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        await embedder.embed_nodes(nodes)
        vec = embedder.get_embedding("n1")
        assert vec is not None
        assert vec.shape == (384,)
