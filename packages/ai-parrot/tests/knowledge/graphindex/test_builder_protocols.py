"""GraphIndexBuilder against Protocol doubles (FEAT-540 M2)."""

from typing import Any

import pytest

from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.schema import SourceConfig
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext


class _Embedder:
    """Minimal Embedder protocol double with durable vectors."""

    async def embed_nodes(self, nodes: list[Any], batch_size: int = 64) -> list[Any]:
        """Return embedded nodes unchanged."""
        return nodes

    def get_embedding(self, node_id: str) -> None:
        """Return no vector for graph-resolution lookups."""
        return None

    async def search_similar(self, query: str, /, top_k: int = 10) -> list[tuple[str, float]]:
        """Return no similar nodes."""
        return []

    def vectors(self) -> dict[str, list[float]]:
        """Return vectors available for durable persistence."""
        return {"sample": [0.1, 0.2]}


class _Persistence:
    """Persistence double deliberately lacking IncrementalPersistence."""

    async def persist_graph(self, ctx: TenantContext, nodes: list[Any], edges: list[Any]) -> dict[str, int]:
        """Record a successful graph persistence operation."""
        return {"nodes_persisted": len(nodes), "edges_persisted": len(edges)}


class _EmbeddingPersistence(_Persistence):
    """Persistence double that records the vector hand-off."""

    def __init__(self) -> None:
        """Initialize the captured vector call."""
        self.received: tuple[TenantContext, dict[str, list[float]]] | None = None

    async def upsert_embeddings(self, ctx: TenantContext, vectors: dict[str, list[float]]) -> int:
        """Capture vectors supplied by the builder."""
        self.received = (ctx, vectors)
        return len(vectors)


def _context() -> TenantContext:
    """Create the minimal context required by GraphIndexBuilder."""
    ontology = MergedOntology.model_construct(
        name="test",
        version="1.0",
        entities={},
        relations={},
        traversal_patterns={},
        layers=[],
        merge_timestamp=None,
    )
    return TenantContext(
        tenant_id="test",
        arango_db="test",
        pgvector_schema="test",
        ontology=ontology,
    )


@pytest.mark.asyncio
async def test_builder_runs_with_protocol_doubles(tmp_path) -> None:
    """A persistence double without is_stale still permits a complete build."""
    (tmp_path / "sample.py").write_text("def sample() -> None:\n    return None\n")
    builder = GraphIndexBuilder(
        persistence=_Persistence(),
        embedder=_Embedder(),
        output_dir=tmp_path / "output",
    )

    result = await builder.build(SourceConfig(code_paths=[str(tmp_path)], tenant_id="test"), _context())

    assert result.tenant_id == "test"


@pytest.mark.asyncio
async def test_embedding_persistence_receives_vectors(tmp_path) -> None:
    """EmbeddingPersistence backends receive vectors exposed by the embedder."""
    persistence = _EmbeddingPersistence()
    builder = GraphIndexBuilder(
        persistence=persistence,
        embedder=_Embedder(),
        output_dir=tmp_path / "output",
    )
    context = _context()

    await builder.build(SourceConfig(tenant_id="test"), context)

    assert persistence.received == (context, {"sample": [0.1, 0.2]})
