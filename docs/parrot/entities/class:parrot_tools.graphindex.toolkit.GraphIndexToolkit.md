---
type: Wiki Entity
title: GraphIndexToolkit
id: class:parrot_tools.graphindex.toolkit.GraphIndexToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Agent-facing tools for querying AND mutating the GraphIndex graph.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# GraphIndexToolkit

Defined in [`parrot_tools.graphindex.toolkit`](../summaries/mod:parrot_tools.graphindex.toolkit.md).

```python
class GraphIndexToolkit(AbstractToolkit)
```

Agent-facing tools for querying AND mutating the GraphIndex graph.

Read-only queries work with the original three-positional-arg
constructor (graph, faiss_index, node_map, node_id_list). Write
capabilities and signal/community wrappers require the
``assembler``, ``embedder``, and ``nodes`` kwargs.

Args:
    graph: The assembled ``rustworkx.PyDiGraph``. Node payloads
        must be dicts with at least ``node_id``, ``kind``, ``title``.
    faiss_index: FAISS index populated with node embeddings.
    node_map: Mapping ``node_id`` (str) → rustworkx integer index.
    node_id_list: Ordered list mapping FAISS position → ``node_id``.
        Mutations may set entries to ``None`` to orphan a FAISS row
        (FAISS does not support row deletion for ``IndexFlatL2``).
    client: Optional ``AbstractClient`` for ``explain()``.
    assembler: Optional ``GraphAssembler`` — required for the write
        tools. Without it, write methods return a structured
        ``{"error": ...}`` response instead of raising.
    embedder: Optional ``GraphIndexEmbedder`` — used to embed new
        nodes (``create_concept`` / ``create_node``) and to encode
        queries for ``find_node`` / ``search_hybrid``. Falls back
        to the placeholder hash encoder when missing.
    nodes: Optional list of ``UniversalNode`` instances kept in
        sync with the graph; required by signal/community tools
        and by ``attach_summary`` (so the model object stays
        authoritative).
    signal_config: Optional :class:`SignalRelevanceConfig` (FEAT-190).
        Defaults to the library's default config when not supplied.

## Methods

- `async def find_node(self, query: str) -> dict` — Find the most semantically similar node to the query.
- `async def find_references(self, node_id: str) -> list[dict]` — Return all edges where node_id is source or target.
- `async def get_neighborhood(self, node_id: str, depth: int=2) -> dict` — BFS subgraph around a node up to a given depth.
- `async def traverse(self, from_id: str, relation: str, to_kind: Optional[str]=None) -> list[dict]` — Walk edges of a specific relation type from a node.
- `async def search_hybrid(self, query: str, top_k: int=10) -> list[dict]` — Combine FAISS similarity with graph proximity for hybrid search.
- `async def find_central_nodes(self, top_k: int=10, metric: str='betweenness') -> list[dict]` — Return top-K most central nodes by the specified centrality metric.
- `async def export_graph_html(self, output_dir: str, top_k_god_nodes: int=15) -> dict` — Export an interactive ``graph.html`` map plus ``graph.json``.
- `async def shortest_path(self, from_id: str, to_id: str) -> list[dict]` — Find the shortest path between two nodes.
- `async def explain(self, node_id: str) -> str` — LLM-generated summary of a node's role in the knowledge graph.
- `async def create_concept(self, title: str, summary: str, source_uri: Optional[str]=None, categories: Optional[list[str]]=None) -> dict` — Create a CONCEPT node and embed it.
- `async def create_node(self, kind: str, title: str, summary: Optional[str]=None, source_uri: Optional[str]=None, parent_id: Optional[str]=None, domain_tags: Optional[dict]=None) -> dict` — Generic node creation for any ``NodeKind``.
- `async def link_nodes(self, source_id: str, target_id: str, kind: str, confidence: Optional[float]=None) -> dict` — Add a directed edge.
- `async def unlink_nodes(self, source_id: str, target_id: str, kind: Optional[str]=None) -> dict` — Remove edge(s) between two nodes.
- `async def attach_summary(self, node_id: str, summary: str) -> dict` — Set / overwrite the summary on an existing node and re-embed.
- `async def tag_node(self, node_id: str, key: str, value: Any) -> dict` — Shallow-merge a single key/value into the node's ``domain_tags``.
- `async def merge_nodes(self, canonical_id: str, duplicate_id: str) -> dict` — Re-point every edge of ``duplicate_id`` to ``canonical_id`` and
- `async def relevance(self, node_a: str, node_b: str) -> dict` — Decomposed five-signal relevance between two nodes (FEAT-190).
- `async def neighborhood_by_relevance(self, node_id: str, top_k: int=10) -> list[dict]` — Top-K nodes most relevant to ``node_id`` by combined signal score.
- `async def list_communities(self, min_size: int=2) -> list[dict]` — FEAT-191 Louvain communities, filtered by minimum size.
- `async def find_community(self, node_id: str) -> dict` — Return the Community containing ``node_id`` (FEAT-191).
- `async def search_with_expansion(self, query: str, seed_top_k: int=10, max_hops: int=2, decay_base: float=0.7, max_tokens: int=8000) -> dict` — Search with graph-expanded retrieval: seeds → graph expansion → result assembly.
- `async def find_isolated_nodes(self, max_degree: int=1) -> list[dict]` — Find nodes with few connections — potential knowledge gaps.
- `async def find_sparse_communities(self, min_size: int=3, max_cohesion: float=0.15) -> list[dict]` — Find Louvain communities with low internal cohesion.
- `async def find_bridge_nodes(self, min_communities: int=3) -> list[dict]` — Find nodes that bridge multiple distinct communities.
- `async def dismiss_insight(self, insight_id: str) -> dict` — Mark an insight as dismissed so it won't appear in future reports.
- `async def list_unreviewed_insights(self) -> list[dict]` — List all insights not yet dismissed.
