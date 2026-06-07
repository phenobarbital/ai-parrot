"""LLM Wiki — composing PageIndex + GraphIndex + Ontology into a knowledge repo.

This module is the *inline glue* for the LLM-Wiki example. It wires three
AI-Parrot knowledge subsystems into a single agent-maintained knowledge
repository, in the spirit of Andrej Karpathy's "LLM wiki" idea: instead of
re-synthesising an answer from scratch on every query (classic RAG), the agent
**compiles** sources into durable, cross-linked pages and **contributes its own
knowledge** back into the repository (the LLM does the bookkeeping — filing,
cross-referencing, summarising).

Mapping of the Karpathy LLM-Wiki concepts onto AI-Parrot infrastructure:

================  ===========================================================
LLM-Wiki concept  AI-Parrot subsystem
================  ===========================================================
``raw/``          Seed source documents (``examples/knowledge_wiki/raw``)
``wiki/`` pages   PageIndex tree (JSON ToC + per-node markdown sidecars)
the knowledge     GraphIndex graph (``rustworkx`` + FAISS) that the LLM grows
graph             via the *write* tools of :class:`GraphIndexToolkit`
entity layer      Ontology (:class:`OntologyRAGMixin`) — structured entities,
                  optional, degrades gracefully without ArangoDB
"lint"            :func:`wiki_lint` — orphan-node / missing-page report
================  ===========================================================

Everything here is intentionally **example-local**: no framework files are
modified. The functions are importable so the bundled tests can exercise the
exact same wiring the runnable script uses.

Design note — graph embeddings
------------------------------
The production graph embedder is
:class:`parrot.knowledge.graphindex.embed.GraphIndexEmbedder`, which resolves a
real semantic model through the embedding registry. To keep this example
**offline, deterministic, and dependency-light**, the default embedder here is
:class:`HashingGraphEmbedder` — a bag-of-tokens hashing embedder that satisfies
the exact interface :class:`GraphIndexToolkit` relies on. Swap in the real
``GraphIndexEmbedder`` for production-quality semantic similarity; the rest of
the wiring is unchanged.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import faiss
import numpy as np

from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
from parrot.knowledge.pageindex import PageIndexLLMAdapter, PageIndexToolkit
from parrot_tools.graphindex.toolkit import GraphIndexToolkit

logger = logging.getLogger("knowledge_wiki")

#: Default embedding dimension for the offline hashing embedder. Small enough
#: to stay fast, large enough that token collisions stay rare for a demo corpus.
DEFAULT_DIM = 128


# ===========================================================================
# Offline, deterministic graph embedder (drop-in for GraphIndexEmbedder)
# ===========================================================================

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _embed_text(text: str, dim: int) -> np.ndarray:
    """Hash tokens into a normalised bag-of-tokens vector.

    Deterministic and offline: lexically similar texts land close together
    under L2 distance, which is enough for ``find_node`` / ``search_hybrid`` to
    behave sensibly in the demo without any model download or network call.
    """
    vec = np.zeros(dim, dtype=np.float32)
    for tok in _tokenize(text):
        # Stable per-token bucket — independent of PYTHONHASHSEED.
        bucket = (hash((tok, "knowledge_wiki")) & 0x7FFFFFFF) % dim
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
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([_embed_text(t, self.dim) for t in texts]).astype(np.float32)


class HashingGraphEmbedder:
    """Deterministic, offline embedder compatible with ``GraphIndexToolkit``.

    Implements the subset of the :class:`GraphIndexEmbedder` API the toolkit
    uses: ``model.encode``, ``index`` (the shared FAISS index), an internal
    ``_node_id_map`` (FAISS position → node_id), ``embed_nodes`` and
    ``get_embedding``. The toolkit is constructed with
    ``faiss_index=embedder.index`` so freshly created nodes become searchable
    immediately.
    """

    def __init__(self, dimension: int = DEFAULT_DIM) -> None:
        self.dimension = dimension
        self.model = _HashingModel(dimension)
        self.index: faiss.Index = faiss.IndexFlatL2(dimension)
        self._node_id_map: list[str] = []
        self._vectors: dict[str, np.ndarray] = {}

    async def embed_nodes(
        self, nodes: list[UniversalNode], batch_size: int = 64
    ) -> list[UniversalNode]:
        """Embed (or re-embed) nodes, keeping FAISS positions stable.

        New node ids are appended; an already-embedded node id has its vector
        refreshed in place. The FAISS index is rebuilt in the *same* object
        (``reset`` + ``add``) so the toolkit's shared ``faiss_index`` reference
        stays valid and positions remain aligned with ``node_id_list``. This
        avoids the duplicate-row drift that append-only re-embedding would cause
        when a write tool (e.g. ``attach_summary``) re-embeds an existing node.
        """
        if not nodes:
            return nodes
        texts = [f"{n.summary or ''} {n.title or ''}".strip() for n in nodes]
        vecs = self.model.encode(texts)
        dirty = False
        for i, node in enumerate(nodes):
            if node.node_id not in self._vectors:
                self._node_id_map.append(node.node_id)
            self._vectors[node.node_id] = vecs[i]
            dirty = True
        if dirty:
            self.index.reset()
            ordered = np.vstack([self._vectors[nid] for nid in self._node_id_map])
            self.index.add(ordered.astype(np.float32))
        for node in nodes:
            pos = self._node_id_map.index(node.node_id)
            node.embedding_ref = f"faiss:{pos}"
        return nodes

    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:
        return self._vectors.get(node_id)


# ===========================================================================
# PageIndex side — the durable wiki pages
# ===========================================================================


def build_pageindex_toolkit(
    *,
    adapter: PageIndexLLMAdapter,
    storage_dir: str | Path,
    lightweight_model: Optional[str] = None,
    default_bm25_k: int = 20,
) -> PageIndexToolkit:
    """Construct the PageIndex toolkit that owns the wiki's durable pages."""
    return PageIndexToolkit(
        adapter=adapter,
        storage_dir=storage_dir,
        lightweight_model=lightweight_model,
        default_bm25_k=default_bm25_k,
    )


async def seed_wiki_from_raw(
    pi_toolkit: PageIndexToolkit,
    tree_name: str,
    raw_dir: str | Path,
    *,
    doc_name: Optional[str] = None,
) -> dict[str, Any]:
    """Compile every source under ``raw_dir`` into the wiki tree.

    This is the "raw → wiki pages" step. Each ``*.md`` / ``*.txt`` file is
    ingested via :meth:`PageIndexToolkit.import_file` (Two-Step CoT ingest),
    producing structured, summarised pages. Returns a summary dict.
    """
    raw_path = Path(raw_dir)
    if tree_name not in await pi_toolkit.list_trees():
        await pi_toolkit.create_tree(tree_name, doc_name=doc_name or tree_name)

    sources = sorted(
        p for p in raw_path.iterdir()
        if p.is_file() and p.suffix.lower() in {".md", ".txt", ".markdown"}
    )
    ingested: list[dict[str, Any]] = []
    for src in sources:
        result = await pi_toolkit.import_file(tree_name=tree_name, file_path=str(src))
        ingested.append({"source": src.name, **result})
        logger.info("Ingested %s into wiki tree %r", src.name, tree_name)
    return {"tree_name": tree_name, "ingested": ingested, "count": len(ingested)}


# ===========================================================================
# GraphIndex side — the agent-maintained knowledge graph
# ===========================================================================


async def graph_seed_from_tree(
    pi_toolkit: PageIndexToolkit,
    tree_name: str,
) -> tuple[list[UniversalNode], list[UniversalEdge]]:
    """Bridge the two indices: derive graph nodes/edges from the wiki tree.

    Walks the PageIndex tree and emits one ``DOCUMENT`` node for the tree plus
    a ``SECTION`` node per page, connected by ``CONTAINS`` edges that mirror the
    page hierarchy. This seeds the graph with the same structure the LLM will
    later enrich with ``CONCEPT`` nodes and cross-reference edges.
    """
    tree = await pi_toolkit.get_tree(tree_name)
    nodes: list[UniversalNode] = []
    edges: list[UniversalEdge] = []

    doc_id = f"doc::{tree_name}"
    nodes.append(
        UniversalNode(
            node_id=doc_id,
            kind=NodeKind.DOCUMENT,
            title=tree.get("doc_name", tree_name),
            source_uri=f"wiki://{tree_name}",
            summary=f"Root of the {tree_name!r} wiki.",
        )
    )

    def walk(structure: list[dict], parent_id: str) -> None:
        for entry in structure or []:
            pid = entry.get("node_id")
            if not pid:
                continue
            sec_id = f"sec::{pid}"
            nodes.append(
                UniversalNode(
                    node_id=sec_id,
                    kind=NodeKind.SECTION,
                    title=entry.get("title", "") or "Untitled",
                    source_uri=f"wiki://{tree_name}/{pid}",
                    summary=entry.get("summary", "") or "",
                )
            )
            edges.append(
                UniversalEdge(
                    source_id=parent_id, target_id=sec_id, kind=EdgeKind.CONTAINS
                )
            )
            walk(entry.get("nodes", []), sec_id)

    walk(tree.get("structure", []), doc_id)
    return nodes, edges


async def build_graphindex_toolkit(
    nodes: Optional[list[UniversalNode]] = None,
    edges: Optional[list[UniversalEdge]] = None,
    *,
    tenant: str = "wiki",
    dimension: int = DEFAULT_DIM,
    embedder: Optional[Any] = None,
) -> GraphIndexToolkit:
    """Wire a **write-enabled** GraphIndexToolkit.

    This is the ergonomic glue the framework does not yet ship: it assembles
    the graph, embeds the seed nodes, and hands the toolkit the consistent set
    of references (``graph``, ``faiss_index``, ``node_map``, ``node_id_list``,
    ``assembler``, ``embedder``, ``nodes``) that the 7 write tools mutate in
    place. Pass empty ``nodes`` to start a blank graph the agent fills from
    scratch.
    """
    nodes = list(nodes or [])
    edges = list(edges or [])

    assembler = GraphAssembler(tenant_id=tenant)
    for node in nodes:
        assembler.add_node(node)
    for edge in edges:
        assembler.add_edge(edge)

    embedder = embedder or HashingGraphEmbedder(dimension=dimension)
    if nodes:
        await embedder.embed_nodes(nodes)

    return GraphIndexToolkit(
        graph=assembler.graph,
        faiss_index=embedder.index,
        node_map=dict(assembler._node_index_map),
        node_id_list=list(embedder._node_id_map),
        assembler=assembler,
        embedder=embedder,
        nodes=nodes,
        signal_config=SignalRelevanceConfig(),
    )


# ===========================================================================
# Ontology side — structured entity layer (optional, graceful degradation)
# ===========================================================================


def make_wiki_agent_class() -> type:
    """Build the ``WikiAgent`` class.

    Defined lazily so importing this module does not require the full bot
    stack — the offline graph/pageindex helpers and tests stay lightweight.
    ``WikiAgent`` composes the Ontology entity layer
    (:class:`OntologyRAGMixin`) on top of ``BasicAgent`` via cooperative
    multiple inheritance: the mixin consumes its own kwargs
    (``tenant_manager``, ``graph_store`` …) and forwards the rest to
    ``BasicAgent``. With ``tenant_manager=None`` the ontology pipeline reports
    ``"not_configured"`` and the agent behaves as a plain PageIndex + GraphIndex
    agent; provide an ArangoDB-backed stack to light it up fully.
    """
    from parrot.bots.agent import BasicAgent
    from parrot.knowledge.ontology.mixin import OntologyRAGMixin

    class WikiAgent(OntologyRAGMixin, BasicAgent):
        """A PageIndex + GraphIndex + Ontology knowledge-wiki agent."""

    return WikiAgent


def build_wiki_agent(
    *,
    name: str,
    llm: str,
    system_prompt: str,
    pi_toolkit: PageIndexToolkit,
    gi_toolkit: GraphIndexToolkit,
    tenant_manager: Any = None,
    graph_store: Any = None,
    vector_store: Any = None,
    cache: Any = None,
    temperature: float = 0.1,
    **kwargs: Any,
) -> Any:
    """Instantiate a ``WikiAgent`` with both knowledge toolkits attached.

    The agent gets the full PageIndex *and* GraphIndex tool surface; the LLM
    decides when to *read* (retrieve pages, traverse the graph) and when to
    *write* (file a new concept, cross-link nodes, attach a summary).
    """
    WikiAgent = make_wiki_agent_class()
    tools = list(pi_toolkit.get_tools()) + list(gi_toolkit.get_tools())
    logger.info(
        "WikiAgent %r wired with %d tools (PageIndex + GraphIndex)", name, len(tools)
    )
    return WikiAgent(
        name=name,
        llm=llm,
        system_prompt=system_prompt,
        tools=tools,
        temperature=temperature,
        tenant_manager=tenant_manager,
        graph_store=graph_store,
        vector_store=vector_store,
        cache=cache,
        **kwargs,
    )


# ===========================================================================
# Lint — the "is the wiki healthy?" report
# ===========================================================================


async def wiki_lint(
    gi_toolkit: GraphIndexToolkit,
    pi_toolkit: PageIndexToolkit,
    tree_name: str,
) -> dict[str, Any]:
    """Report knowledge-repo health: orphan graph nodes + community structure.

    Mirrors Karpathy's "lint" pass — surfaces concepts the agent created but
    never connected, so they can be linked or pruned. Pure inspection: no
    mutation, no LLM calls.
    """
    orphans: list[dict[str, str]] = []
    for node_id, idx in gi_toolkit.node_map.items():
        degree = gi_toolkit.graph.in_degree(idx) + gi_toolkit.graph.out_degree(idx)
        if degree == 0:
            payload = gi_toolkit.graph[idx]
            orphans.append({"node_id": node_id, "title": payload.get("title", "")})

    communities = await gi_toolkit.list_communities(min_size=2)
    pages = (await pi_toolkit.get_tree(tree_name)).get("structure", [])

    return {
        "tree_name": tree_name,
        "graph_nodes": len(gi_toolkit.node_map),
        "orphan_nodes": orphans,
        "communities": len(communities),
        "top_level_pages": len(pages),
    }
