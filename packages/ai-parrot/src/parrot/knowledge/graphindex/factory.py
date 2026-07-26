"""Factory for persistent, write-enabled graph memory toolkits.

Productizes the load → assemble → embed → publish loop so an agent (or a
mixin) can open its durable knowledge graph in one call::

    toolkit = await build_graph_memory_toolkit(
        db_dir=Path("~/.parrot/agents/my-agent/graph_memory"),
        agent_id="my-agent",
    )

The returned ``GraphIndexToolkit`` has every write tool wired for
write-through persistence (via :class:`GraphPublisher`), so knowledge the
agent files survives process restarts — "the agent forgets, the graph
does not".

``GraphIndexToolkit`` lives in the sibling ``ai-parrot-tools``
distribution; it is imported lazily inside the factory (mirroring
``ToolInterface._capture_knowledge_toolkit``) so ``ai-parrot`` core keeps
no hard dependency on it.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.schema import UniversalNode
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext

if TYPE_CHECKING:  # pragma: no cover — typing only
    from parrot_tools.graphindex.toolkit import GraphIndexToolkit

logger = logging.getLogger(__name__)

DEFAULT_DIMENSION = 256


def make_stub_tenant_context(tenant_id: str) -> TenantContext:
    """Build a minimal :class:`TenantContext` for local graph planes.

    The ontology is a stub (same pattern as the flowtask component) —
    full hydration is only needed for ArangoDB/ontology deployments.

    Args:
        tenant_id: Tenant identifier for the graph plane.

    Returns:
        A ``TenantContext`` suitable for ``SQLitePersistence``.
    """
    ontology = MergedOntology.model_construct(
        name="graphindex",
        version="1.0",
        entities={},
        relations={},
        traversal_patterns={},
        layers=[],
        merge_timestamp=None,
    )
    return TenantContext(
        tenant_id=tenant_id,
        arango_db=f"db_{tenant_id}",
        pgvector_schema=f"schema_{tenant_id}",
        ontology=ontology,
    )


def _embed_text(text: str, dim: int) -> np.ndarray:
    """Hash tokens into a normalised bag-of-tokens vector.

    Deterministic ACROSS PROCESSES (bucket derivation uses SHA-1, never
    Python's salted ``hash()``) — a hard requirement for persistent
    memory, where nodes embedded in one session must stay findable from
    queries encoded in the next.

    Args:
        text: Text to embed.
        dim: Vector dimension.

    Returns:
        L2-normalised ``(dim,)`` float32 vector.
    """
    vec = np.zeros(dim, dtype=np.float32)
    for tok in text.lower().split():
        tok = tok.strip(".,;:!?()[]{}\"'`")
        if not tok:
            continue
        digest = hashlib.sha1(tok.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        vec[bucket] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


class _HashingModel:
    """Minimal ``model`` object exposing the ``encode`` the toolkit calls."""

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts into a ``(len(texts), dim)`` float32 matrix."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([_embed_text(t, self.dim) for t in texts]).astype(
            np.float32
        )


class HashingGraphEmbedder:
    """Deterministic, offline embedder compatible with ``GraphIndexToolkit``.

    Implements the subset of the ``GraphIndexEmbedder`` API the toolkit
    uses: ``model.encode``, ``index`` (the shared FAISS index), an
    internal ``_node_id_map`` (FAISS position → node_id) and
    ``embed_nodes``. Used as the zero-dependency fallback when no real
    embedding model is configured — lexical bag-of-tokens vectors are
    enough for ``find_node``/``search_hybrid`` over agent memory.

    Args:
        dimension: Embedding vector dimension.
    """

    def __init__(self, dimension: int = DEFAULT_DIMENSION) -> None:
        from parrot.utils.faiss_logging import quiet_faiss_loader

        quiet_faiss_loader()
        import faiss

        self.dimension = dimension
        self.model = _HashingModel(dimension)
        self.index = faiss.IndexFlatL2(dimension)
        self._node_id_map: list[str] = []
        self._vectors: dict[str, np.ndarray] = {}

    async def embed_nodes(
        self, nodes: list[UniversalNode], batch_size: int = 64
    ) -> list[UniversalNode]:
        """Embed (or re-embed) nodes, keeping FAISS positions stable.

        New node ids are appended; an already-embedded node id has its
        vector refreshed in place. The FAISS index is rebuilt in the
        same object (``reset`` + ``add``) so shared references stay
        valid and positions remain aligned with ``node_id_list``.

        Args:
            nodes: Nodes to embed.
            batch_size: Unused (single batch); kept for API parity.

        Returns:
            The same nodes with ``embedding_ref`` populated.
        """
        if not nodes:
            return nodes
        texts = [f"{n.summary or ''} {n.title or ''}".strip() for n in nodes]
        vecs = self.model.encode(texts)
        for i, node in enumerate(nodes):
            if node.node_id not in self._vectors:
                self._node_id_map.append(node.node_id)
            self._vectors[node.node_id] = vecs[i]
        self.index.reset()
        ordered = np.vstack([self._vectors[nid] for nid in self._node_id_map])
        self.index.add(ordered.astype(np.float32))
        for node in nodes:
            node.embedding_ref = f"faiss:{self._node_id_map.index(node.node_id)}"
        return nodes

    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:
        """Return the stored vector for a node id, or ``None``."""
        return self._vectors.get(node_id)

    async def search_similar(
        self, query: str, top_k: int = 10
    ) -> list[tuple[str, float]]:
        """FAISS L2 search over the embedded nodes.

        Args:
            query: Natural-language query text.
            top_k: Maximum results.

        Returns:
            ``(node_id, distance)`` pairs, closest first.
        """
        if self.index.ntotal == 0:
            return []
        vec = self.model.encode([query])
        distances, positions = self.index.search(vec, min(top_k, self.index.ntotal))
        results: list[tuple[str, float]] = []
        for pos, dist in zip(positions[0], distances[0]):
            if 0 <= pos < len(self._node_id_map):
                results.append((self._node_id_map[pos], float(dist)))
        return results


async def build_graph_memory_toolkit(
    db_dir: Path | str,
    tenant_id: str = "default",
    agent_id: str = "agent",
    run_id: Optional[str] = None,
    embedder: Optional[Any] = None,
    client: Optional[Any] = None,
    dimension: int = DEFAULT_DIMENSION,
) -> "GraphIndexToolkit":
    """Open (or create) a persistent graph memory and return its toolkit.

    Loads the durable graph plane from ``db_dir``, assembles the
    in-memory rustworkx graph, embeds the loaded nodes, and wires a
    :class:`GraphPublisher` so every toolkit write persists as an
    audited, revertible commit.

    Args:
        db_dir: Directory holding the per-tenant SQLite graph plane.
        tenant_id: Tenant identifier (one ``<tenant_id>.db`` per tenant).
        agent_id: Stable agent identity stamped onto writes.
        run_id: Optional run/session id stamped onto writes (mutable on
            the returned toolkit — set per ask).
        embedder: Optional embedder implementing the
            ``GraphIndexEmbedder`` surface. Defaults to the deterministic
            offline :class:`HashingGraphEmbedder`.
        client: Optional ``AbstractClient`` for ``explain()``.
        dimension: Vector dimension for the default embedder.

    Returns:
        A write-enabled, persistence-backed ``GraphIndexToolkit``.
    """
    # Lazy import — keeps ai-parrot core free of a hard dependency on
    # the ai-parrot-tools distribution (same seam as ToolInterface).
    from parrot_tools.graphindex.toolkit import GraphIndexToolkit

    ctx = make_stub_tenant_context(tenant_id)
    persistence = SQLitePersistence(Path(db_dir))
    publisher = GraphPublisher(persistence, ctx)

    nodes, edges = await persistence.load_graph(ctx)

    assembler = GraphAssembler(tenant_id=tenant_id)
    for node in nodes:
        assembler.add_node(node)
    skipped_edges = 0
    for edge in edges:
        if assembler.add_edge(edge) is None:
            skipped_edges += 1
    if skipped_edges:
        logger.warning(
            "build_graph_memory_toolkit: %d edges skipped (missing endpoints)",
            skipped_edges,
        )

    embedder = embedder or HashingGraphEmbedder(dimension=dimension)
    if nodes:
        await embedder.embed_nodes(nodes)

    toolkit = GraphIndexToolkit(
        graph=assembler.graph,
        faiss_index=embedder.index,
        node_map=dict(assembler._node_index_map),
        node_id_list=list(embedder._node_id_map),
        client=client,
        assembler=assembler,
        embedder=embedder,
        nodes=nodes,
        publisher=publisher,
        agent_id=agent_id,
        run_id=run_id,
    )
    logger.info(
        "build_graph_memory_toolkit: tenant %r — %d nodes, %d edges loaded",
        tenant_id,
        len(nodes),
        len(edges),
    )
    return toolkit
