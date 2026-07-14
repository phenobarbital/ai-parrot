"""GraphIndex Toolkit — Agent-Facing Tools.

Exposes the knowledge graph to AI agents as a set of 19 callable tools
via ``GraphIndexToolkit(AbstractToolkit)``.  All public async methods
are auto-discovered and registered as tools by the ``AbstractToolkit``
base class.

Hot read queries operate over the in-memory ``rustworkx.PyDiGraph``
and FAISS index. Write tools mutate the same in-memory state through
the ``GraphAssembler`` reference (when supplied) so the graph stays
consistent; agents can build the wiki from inside a tool call.

Optional integrations:

* ``GraphIndexEmbedder`` — when injected, replaces the placeholder
  query encoder with a real ``model.encode`` call and embeds freshly
  created nodes so ``find_node`` and ``search_hybrid`` see them.
* ``SignalRelevanceConfig`` (FEAT-190) — drives ``relevance()`` and
  ``neighborhood_by_relevance()``. Lazy-imported.
* FEAT-191 communities — ``list_communities`` / ``find_community``
  cache the partition until a write tool runs. Lazy-imported.

Tool surface:

  # READ
  find_node, find_references, get_neighborhood, traverse,
  search_hybrid, find_central_nodes, shortest_path, explain,
  relevance, neighborhood_by_relevance, list_communities,
  find_community, export_graph_html

  # WRITE
  create_concept, create_node, link_nodes, unlink_nodes,
  attach_summary, tag_node, merge_nodes
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
import rustworkx

from parrot.tools.toolkit import AbstractToolkit
from parrot.utils.faiss_logging import quiet_faiss_loader

quiet_faiss_loader()  # silence faiss boot logs before the first import
import faiss  # noqa: E402 — must follow quiet_faiss_loader()

if TYPE_CHECKING:
    from parrot.knowledge.graphindex.assemble import GraphAssembler
    from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
    from parrot.knowledge.graphindex.schema import UniversalNode
    from parrot.knowledge.graphindex.signals import SignalRelevanceConfig

logger = logging.getLogger(__name__)

# Number of surprising connections returned by _get_or_compute_analytics.
DEFAULT_ANALYTICS_TOP_K = 10


class GraphIndexToolkit(AbstractToolkit):
    """Agent-facing tools for querying AND mutating the GraphIndex graph.

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
    """

    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        faiss_index: faiss.Index,
        node_map: dict[str, int],
        node_id_list: list[str],
        client=None,
        assembler: Optional["GraphAssembler"] = None,
        embedder: Optional["GraphIndexEmbedder"] = None,
        nodes: Optional[list["UniversalNode"]] = None,
        signal_config: Optional["SignalRelevanceConfig"] = None,
    ) -> None:
        super().__init__()
        self.graph = graph
        self.faiss_index = faiss_index
        self.node_map = node_map
        self.node_id_list = node_id_list
        self.client = client
        self.assembler = assembler
        self.embedder = embedder
        self.nodes = nodes if nodes is not None else []
        self.signal_config = signal_config
        self._community_cache: Optional[Any] = None
        self._analytics_cache: Optional[Any] = None  # FEAT-215
        self._encoder_warning_emitted = False
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _write_supported(self) -> bool:
        """True iff the toolkit has the dependencies to mutate state."""
        return self.assembler is not None and self.embedder is not None

    def _no_write_error(self, op: str) -> dict:
        return {
            "error": (
                f"{op}: write tools require an assembler + embedder. "
                "Construct GraphIndexToolkit with assembler=... and "
                "embedder=... to enable writes."
            ),
        }

    def _invalidate_community_cache(self) -> None:
        self._community_cache = None
        self._analytics_cache = None  # FEAT-215: analytics depends on communities

    def _node_by_id(self, node_id: str) -> Optional["UniversalNode"]:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        return None


    # ------------------------------------------------------------------
    # Public agent tools
    # ------------------------------------------------------------------

    async def find_node(self, query: str) -> dict:
        """Find the most semantically similar node to the query.

        Uses the FAISS index to find the closest embedding.  Requires
        the query to be a non-empty string.

        Args:
            query: Natural language search query.

        Returns:
            Dict with ``node_id``, ``title``, ``kind``, and
            ``similarity_score``, or an error dict if no nodes are
            indexed.
        """
        if self.faiss_index.ntotal == 0:
            return {"error": "No nodes indexed in FAISS."}

        try:
            dim = self.faiss_index.d
            query_vec = await self._encode_query(query, dim)
            distances, indices = self.faiss_index.search(query_vec, 1)
            faiss_pos = int(indices[0][0])
            if faiss_pos < 0 or faiss_pos >= len(self.node_id_list):
                return {"error": "No matching node found."}
            node_id = self.node_id_list[faiss_pos]
            node_idx = self.node_map.get(node_id)
            if node_idx is None:
                return {"error": f"Node {node_id} not in graph."}
            payload = self.graph[node_idx]
            return {
                "node_id": node_id,
                "title": payload.get("title", ""),
                "kind": payload.get("kind", ""),
                "similarity_score": float(distances[0][0]),
            }
        except Exception as exc:
            logger.error("find_node failed: %s", exc)
            return {"error": str(exc)}

    async def find_references(self, node_id: str) -> list[dict]:
        """Return all edges where node_id is source or target.

        Args:
            node_id: The node to find references for.

        Returns:
            List of edge dicts with ``source_id``, ``target_id``,
            ``kind``, and ``confidence``.
        """
        idx = self.node_map.get(node_id)
        if idx is None:
            return []

        result: list[dict] = []

        for _src, _tgt, payload in self.graph.out_edges(idx):
            result.append(
                {
                    "source_id": payload.get("source_id", node_id),
                    "target_id": payload.get("target_id", ""),
                    "kind": payload.get("kind", ""),
                    "confidence": payload.get("confidence"),
                    "direction": "outgoing",
                }
            )

        for _src, _tgt, payload in self.graph.in_edges(idx):
            result.append(
                {
                    "source_id": payload.get("source_id", ""),
                    "target_id": payload.get("target_id", node_id),
                    "kind": payload.get("kind", ""),
                    "confidence": payload.get("confidence"),
                    "direction": "incoming",
                }
            )

        return result

    async def get_neighborhood(self, node_id: str, depth: int = 2) -> dict:
        """BFS subgraph around a node up to a given depth.

        Args:
            node_id: Center node identifier.
            depth: Maximum traversal depth (default 2).

        Returns:
            Dict with ``center``, ``nodes`` (list of node dicts), and
            ``edges`` (list of edge dicts) within the neighborhood.
        """
        idx = self.node_map.get(node_id)
        if idx is None:
            return {"center": node_id, "nodes": [], "edges": []}

        visited_nodes: dict[int, dict] = {}
        visited_edges: list[dict] = []

        # BFS queue: (node_index, current_depth)
        queue: list[tuple[int, int]] = [(idx, 0)]
        seen: set[int] = {idx}
        visited_nodes[idx] = self.graph[idx]

        while queue:
            current_idx, current_depth = queue.pop(0)
            if current_depth >= depth:
                continue
            for _src, child_idx, edge_payload in self.graph.out_edges(current_idx):
                if child_idx not in seen:
                    seen.add(child_idx)
                    visited_nodes[child_idx] = self.graph[child_idx]
                    queue.append((child_idx, current_depth + 1))
                visited_edges.append(edge_payload)

        return {
            "center": node_id,
            "nodes": list(visited_nodes.values()),
            "edges": visited_edges,
        }

    async def traverse(
        self,
        from_id: str,
        relation: str,
        to_kind: Optional[str] = None,
    ) -> list[dict]:
        """Walk edges of a specific relation type from a node.

        Args:
            from_id: Starting node identifier.
            relation: Edge kind to follow (e.g., ``"contains"``,
                ``"references"``).
            to_kind: Optional filter for target node kind (e.g.,
                ``"document"``).

        Returns:
            List of reached node payload dicts.
        """
        idx = self.node_map.get(from_id)
        if idx is None:
            return []

        result: list[dict] = []
        for _src, tgt_idx, edge_payload in self.graph.out_edges(idx):
            if edge_payload.get("kind") != relation:
                continue
            target_payload = self.graph[tgt_idx]
            if to_kind is not None and target_payload.get("kind") != to_kind:
                continue
            result.append(target_payload)

        return result

    async def search_hybrid(self, query: str, top_k: int = 10) -> list[dict]:
        """Combine FAISS similarity with graph proximity for hybrid search.

        Retrieves FAISS nearest neighbours and boosts their scores by the
        number of graph connections (degree), combining both signals.

        Args:
            query: Natural language search query.
            top_k: Number of results to return.

        Returns:
            List of node dicts ranked by combined score (descending).
        """
        if self.faiss_index.ntotal == 0:
            return []

        k = min(top_k * 2, self.faiss_index.ntotal)
        try:
            dim = self.faiss_index.d
            query_vec = await self._encode_query(query, dim)
            distances, indices = self.faiss_index.search(query_vec, k)
        except Exception as exc:
            logger.error("search_hybrid FAISS search failed: %s", exc)
            return []

        results: list[dict] = []
        for faiss_pos, distance in zip(indices[0], distances[0]):
            if faiss_pos < 0 or faiss_pos >= len(self.node_id_list):
                continue
            node_id = self.node_id_list[faiss_pos]
            node_idx = self.node_map.get(node_id)
            if node_idx is None:
                continue
            payload = self.graph[node_idx]
            degree = len(self.graph.out_edges(node_idx)) + len(self.graph.in_edges(node_idx))
            # Combined score: semantic similarity + log(1 + degree)
            import math
            combined = float(distance) + 0.1 * math.log1p(degree)
            results.append(
                {
                    "node_id": node_id,
                    "title": payload.get("title", ""),
                    "kind": payload.get("kind", ""),
                    "similarity_score": float(distance),
                    "degree": degree,
                    "combined_score": combined,
                }
            )

        results.sort(key=lambda x: x["combined_score"], reverse=True)
        return results[:top_k]

    async def find_central_nodes(
        self, top_k: int = 10, metric: str = "betweenness"
    ) -> list[dict]:
        """Return top-K most central nodes by the specified centrality metric.

        Args:
            top_k: Number of top nodes to return.
            metric: Centrality metric to use: ``"betweenness"`` (default)
                or ``"eigenvector"``.

        Returns:
            List of node dicts with ``node_id``, ``title``, ``kind``,
            and ``centrality_score``, sorted by score descending.
        """
        if self.graph.num_nodes() == 0:
            return []

        try:
            if metric == "eigenvector":
                _cm = rustworkx.eigenvector_centrality(self.graph)
            else:
                _cm = rustworkx.betweenness_centrality(self.graph)
            centrality = dict(_cm.items())
        except Exception as exc:
            logger.warning("Centrality computation failed: %s", exc)
            centrality = {}

        result: list[dict] = []
        for node_idx in self.graph.node_indices():
            payload = self.graph[node_idx]
            if not isinstance(payload, dict):
                continue
            result.append(
                {
                    "node_id": payload.get("node_id", str(node_idx)),
                    "title": payload.get("title", ""),
                    "kind": payload.get("kind", ""),
                    "centrality_score": centrality.get(node_idx, 0.0),
                }
            )

        result.sort(key=lambda x: x["centrality_score"], reverse=True)
        return result[:top_k]

    async def export_graph_html(
        self, output_dir: str, top_k_god_nodes: int = 15
    ) -> dict:
        """Export an interactive ``graph.html`` map plus ``graph.json``.

        Renders the current in-memory graph as a self-contained, clickable
        force-directed page: nodes are concepts, colour is the detected
        community, node size scales with centrality (god nodes are highlighted),
        and clicking a node opens a detail panel. The page inlines the ECharts
        runtime so it works fully offline. A sibling ``graph.json`` carries the
        serialized graph for programmatic reuse.

        Args:
            output_dir: Directory where ``graph.html`` and ``graph.json`` are
                written (created if missing).
            top_k_god_nodes: Number of most-central "god" nodes to highlight.

        Returns:
            Dict with ``graph_html``, ``graph_json``, ``node_count``,
            ``edge_count`` and ``community_count`` — or an ``error`` dict when
            the export module is unavailable.
        """
        try:
            from parrot.knowledge.graphindex.export_html import export_graph
        except ImportError as exc:
            return {"error": f"HTML export unavailable: {exc}"}

        if self.graph.num_nodes() == 0:
            return {"error": "Graph is empty; nothing to export."}

        communities = self._get_or_compute_communities()
        analytics = self._get_or_compute_analytics()
        try:
            html_path, json_path = export_graph(
                self.graph,
                output_dir,
                communities=communities,
                analytics=analytics,
                god_top_k=top_k_god_nodes,
            )
        except Exception as exc:
            logger.error("export_graph_html failed: %s", exc)
            return {"error": str(exc)}

        community_count = (
            len(communities.communities) if communities is not None else 0
        )
        return {
            "graph_html": str(html_path),
            "graph_json": str(json_path),
            "node_count": self.graph.num_nodes(),
            "edge_count": self.graph.num_edges(),
            "community_count": community_count,
        }

    async def shortest_path(self, from_id: str, to_id: str) -> list[dict]:
        """Find the shortest path between two nodes.

        Args:
            from_id: Source node identifier.
            to_id: Target node identifier.

        Returns:
            Ordered list of node payload dicts forming the path, or an
            empty list if no path exists.
        """
        from_idx = self.node_map.get(from_id)
        to_idx = self.node_map.get(to_id)

        if from_idx is None or to_idx is None:
            return []

        try:
            paths = rustworkx.dijkstra_shortest_paths(self.graph, from_idx, target=to_idx)
            if to_idx not in paths:
                return []
            path_indices = paths[to_idx]
            return [self.graph[i] for i in path_indices]
        except Exception as exc:
            logger.warning("shortest_path failed: %s", exc)
            return []

    async def explain(self, node_id: str) -> str:
        """LLM-generated summary of a node's role in the knowledge graph.

        Requires an ``AbstractClient`` to be provided at construction time.
        If no client is available, returns a fallback description built
        from the node's metadata.

        Args:
            node_id: The node to explain.

        Returns:
            Natural language explanation of the node's significance.
        """
        idx = self.node_map.get(node_id)
        if idx is None:
            return f"Node '{node_id}' not found in the graph."

        payload = self.graph[idx]
        title = payload.get("title", node_id)
        kind = payload.get("kind", "unknown")
        summary = payload.get("summary") or ""
        degree = len(self.graph.out_edges(idx)) + len(self.graph.in_edges(idx))

        if self.client is None:
            # Fallback: return structured description without LLM
            return (
                f"Node '{title}' (kind: {kind}) has {degree} connections. "
                f"{summary}"
            ).strip()

        prompt = (
            f"You are an expert knowledge graph analyst. Explain the role of the "
            f"following node in the knowledge graph:\n\n"
            f"Node ID: {node_id}\n"
            f"Title: {title}\n"
            f"Kind: {kind}\n"
            f"Connections: {degree}\n"
            f"Summary: {summary}\n\n"
            f"Provide a concise 2-3 sentence explanation of this node's significance."
        )

        try:
            response = await self.client.ask(prompt, model=None)
            if isinstance(response, str):
                return response
            # Handle MessageResponse objects
            return str(response)
        except Exception as exc:
            logger.warning("explain() LLM call failed: %s", exc)
            return (
                f"Node '{title}' (kind: {kind}) has {degree} connections. "
                f"{summary}"
            ).strip()

    # ==================================================================
    # WRITE tools (require assembler + embedder)
    # ==================================================================

    async def create_concept(
        self,
        title: str,
        summary: str,
        source_uri: Optional[str] = None,
        categories: Optional[list[str]] = None,
    ) -> dict:
        """Create a CONCEPT node and embed it.

        The deterministic node_id is a SHA-1 prefix of
        ``"concept::title::summary"`` so re-creating an identical
        concept is idempotent at the id level. Categories are stored
        in ``domain_tags['categories']``.

        Returns ``{node_id, kind, title, status}`` or ``{"error": ...}``.
        """
        return await self._create_node(
            kind="concept",
            title=title,
            summary=summary,
            source_uri=source_uri,
            categories=categories,
        )

    async def create_node(
        self,
        kind: str,
        title: str,
        summary: Optional[str] = None,
        source_uri: Optional[str] = None,
        parent_id: Optional[str] = None,
        domain_tags: Optional[dict] = None,
    ) -> dict:
        """Generic node creation for any ``NodeKind``."""
        return await self._create_node(
            kind=kind,
            title=title,
            summary=summary,
            source_uri=source_uri,
            parent_id=parent_id,
            domain_tags=domain_tags,
        )

    async def _create_node(
        self,
        kind: str,
        title: str,
        summary: Optional[str] = None,
        source_uri: Optional[str] = None,
        parent_id: Optional[str] = None,
        categories: Optional[list[str]] = None,
        domain_tags: Optional[dict] = None,
    ) -> dict:
        if not self._write_supported:
            return self._no_write_error("create_node")
        if not isinstance(title, str) or not title.strip():
            return {"error": "create_node: title must be a non-empty string"}

        from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
        try:
            kind_enum = NodeKind(kind)
        except ValueError:
            return {"error": f"create_node: unknown kind {kind!r}"}

        node_id = self._mint_node_id(kind, title, summary or "")
        if node_id in self.node_map:
            return {"error": f"create_node: node_id {node_id!r} already exists"}

        tags = dict(domain_tags or {})
        if categories:
            tags["categories"] = sorted({str(c) for c in categories})

        node = UniversalNode(
            node_id=node_id,
            kind=kind_enum,
            title=title.strip(),
            source_uri=source_uri or f"agent://{kind}/{node_id}",
            summary=summary or "",
            parent_id=parent_id,
            domain_tags=tags,
        )

        try:
            rust_idx = self.assembler.add_node(node)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"create_node: assembler rejected: {exc}"}
        self.node_map[node_id] = rust_idx

        # Embed the new node and append to FAISS / node_id_list bookkeeping.
        try:
            await self.embedder.embed_nodes([node])
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("create_node: embed failed for %s: %s", node_id, exc)
        # The embedder appends to its own internal map; mirror onto the
        # toolkit's node_id_list so query encoding stays consistent.
        if node_id not in self.node_id_list:
            self.node_id_list.append(node_id)

        self.nodes.append(node)
        self._invalidate_community_cache()
        return {
            "node_id": node_id,
            "kind": kind_enum.value,
            "title": node.title,
            "status": "created",
        }

    async def link_nodes(
        self,
        source_id: str,
        target_id: str,
        kind: str,
        confidence: Optional[float] = None,
    ) -> dict:
        """Add a directed edge.

        ``confidence`` is allowed iff ``kind`` is treated as INFERRED
        provenance — the underlying ``UniversalEdge`` validator
        enforces ``confidence ⇔ provenance=INFERRED``.
        """
        if not self._write_supported:
            return self._no_write_error("link_nodes")
        if source_id not in self.node_map or target_id not in self.node_map:
            return {"error": "link_nodes: unknown source_id or target_id"}

        from parrot.knowledge.graphindex.schema import (
            EdgeKind, Provenance, UniversalEdge,
        )
        try:
            kind_enum = EdgeKind(kind)
        except ValueError:
            return {"error": f"link_nodes: unknown edge kind {kind!r}"}

        provenance = (
            Provenance.INFERRED if confidence is not None else Provenance.EXTRACTED
        )

        try:
            edge = UniversalEdge(
                source_id=source_id,
                target_id=target_id,
                kind=kind_enum,
                provenance=provenance,
                confidence=confidence,
            )
        except Exception as exc:  # noqa: BLE001 — surface validator failures
            return {"error": f"link_nodes: {exc}"}

        try:
            self.assembler.add_edge(edge)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"link_nodes: assembler rejected: {exc}"}

        self._invalidate_community_cache()
        return {
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind_enum.value,
            "status": "linked",
        }

    async def unlink_nodes(
        self,
        source_id: str,
        target_id: str,
        kind: Optional[str] = None,
    ) -> dict:
        """Remove edge(s) between two nodes.

        ``kind=None`` removes every edge between them (in either
        direction); a specific kind removes only matching edges.
        """
        if not self._write_supported:
            return self._no_write_error("unlink_nodes")
        src_idx = self.node_map.get(source_id)
        tgt_idx = self.node_map.get(target_id)
        if src_idx is None or tgt_idx is None:
            return {"error": "unlink_nodes: unknown source_id or target_id"}

        removed = 0
        for s, t in ((src_idx, tgt_idx), (tgt_idx, src_idx)):
            for _eidx, payload in list(self._edges_between(s, t)):
                if kind is not None and payload.get("kind") != kind:
                    continue
                try:
                    self.graph.remove_edge(s, t)
                    removed += 1
                except Exception:
                    pass
                # Also clean the assembler's edge_index_map entry.
                if hasattr(self.assembler, "_edge_index_map"):
                    edge_key = (
                        payload.get("source_id"),
                        payload.get("target_id"),
                        payload.get("kind"),
                    )
                    self.assembler._edge_index_map.pop(edge_key, None)

        if removed == 0:
            return {
                "source_id": source_id,
                "target_id": target_id,
                "removed": 0,
                "status": "no_op",
            }

        self._invalidate_community_cache()
        return {
            "source_id": source_id,
            "target_id": target_id,
            "removed": removed,
            "status": "unlinked",
        }

    def _edges_between(self, src_idx: int, tgt_idx: int):
        """Yield (edge_index, payload) for every edge from src to tgt."""
        try:
            edge_indices = self.graph.edge_indices_from_endpoints(src_idx, tgt_idx)
        except Exception:
            edge_indices = []
        for eidx in edge_indices:
            try:
                yield eidx, self.graph.get_edge_data_by_index(eidx)
            except Exception:
                continue

    async def attach_summary(self, node_id: str, summary: str) -> dict:
        """Set / overwrite the summary on an existing node and re-embed."""
        if not self._write_supported:
            return self._no_write_error("attach_summary")
        idx = self.node_map.get(node_id)
        if idx is None:
            return {"error": f"attach_summary: node {node_id!r} not found"}
        if not isinstance(summary, str):
            return {"error": "attach_summary: summary must be a string"}

        payload = self.graph[idx]
        if isinstance(payload, dict):
            payload["summary"] = summary

        node = self._node_by_id(node_id)
        if node is not None:
            node.summary = summary
            try:
                await self.embedder.embed_nodes([node])
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "attach_summary: re-embed failed for %s: %s", node_id, exc,
                )

        self._invalidate_community_cache()
        return {"node_id": node_id, "summary": summary, "status": "updated"}

    async def tag_node(self, node_id: str, key: str, value: Any) -> dict:
        """Shallow-merge a single key/value into the node's ``domain_tags``."""
        if not self._write_supported:
            return self._no_write_error("tag_node")
        if not isinstance(key, str) or not key:
            return {"error": "tag_node: key must be a non-empty string"}
        idx = self.node_map.get(node_id)
        if idx is None:
            return {"error": f"tag_node: node {node_id!r} not found"}

        payload = self.graph[idx]
        if isinstance(payload, dict):
            tags = payload.setdefault("domain_tags", {})
            if isinstance(tags, dict):
                tags[key] = value

        node = self._node_by_id(node_id)
        if node is not None:
            node.domain_tags[key] = value

        self._invalidate_community_cache()
        return {"node_id": node_id, "key": key, "value": value, "status": "tagged"}

    async def merge_nodes(
        self,
        canonical_id: str,
        duplicate_id: str,
    ) -> dict:
        """Re-point every edge of ``duplicate_id`` to ``canonical_id`` and
        remove the duplicate node.

        FAISS does not support row deletion for ``IndexFlatL2``, so the
        duplicate's FAISS position is orphaned: ``node_id_list[pos]``
        is set to ``None`` and read tools skip the position. Edges that
        would duplicate an existing canonical edge (same source, target,
        kind) are dropped, not double-added. Self-loops created by the
        merge are dropped.
        """
        if not self._write_supported:
            return self._no_write_error("merge_nodes")
        if canonical_id not in self.node_map or duplicate_id not in self.node_map:
            return {"error": "merge_nodes: unknown canonical_id or duplicate_id"}
        if canonical_id == duplicate_id:
            return {"error": "merge_nodes: canonical_id == duplicate_id"}

        dup_idx = self.node_map[duplicate_id]
        canonical_idx = self.node_map[canonical_id]

        # Collect every (other_id, payload, direction) before we mutate.
        out_edges: list[dict] = list(
            payload for _s, _t, payload in self.graph.out_edges(dup_idx)
        )
        in_edges: list[dict] = list(
            payload for _s, _t, payload in self.graph.in_edges(dup_idx)
        )

        existing_keys = self._existing_edge_keys(canonical_idx)
        redirected = 0

        from parrot.knowledge.graphindex.schema import (
            EdgeKind, Provenance, UniversalEdge,
        )

        for payload in out_edges:
            target = payload.get("target_id")
            kind_v = payload.get("kind")
            if target in (canonical_id, duplicate_id) or not target or not kind_v:
                continue
            key = (canonical_id, target, kind_v)
            if key in existing_keys:
                continue
            try:
                edge = UniversalEdge(
                    source_id=canonical_id,
                    target_id=target,
                    kind=EdgeKind(kind_v),
                    provenance=Provenance(payload.get("provenance", "extracted")),
                    confidence=payload.get("confidence"),
                )
                self.assembler.add_edge(edge)
                existing_keys.add(key)
                redirected += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("merge_nodes: out-edge redirect failed: %s", exc)

        for payload in in_edges:
            source = payload.get("source_id")
            kind_v = payload.get("kind")
            if source in (canonical_id, duplicate_id) or not source or not kind_v:
                continue
            key = (source, canonical_id, kind_v)
            if key in existing_keys:
                continue
            try:
                edge = UniversalEdge(
                    source_id=source,
                    target_id=canonical_id,
                    kind=EdgeKind(kind_v),
                    provenance=Provenance(payload.get("provenance", "extracted")),
                    confidence=payload.get("confidence"),
                )
                self.assembler.add_edge(edge)
                existing_keys.add(key)
                redirected += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("merge_nodes: in-edge redirect failed: %s", exc)

        # Remove the duplicate node + its references in every map.
        try:
            self.graph.remove_node(dup_idx)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"merge_nodes: remove_node failed: {exc}"}
        self.node_map.pop(duplicate_id, None)
        if hasattr(self.assembler, "_node_index_map"):
            self.assembler._node_index_map.pop(duplicate_id, None)
        try:
            faiss_pos = self.node_id_list.index(duplicate_id)
            self.node_id_list[faiss_pos] = None
        except ValueError:
            pass
        self.nodes = [n for n in self.nodes if n.node_id != duplicate_id]

        self._invalidate_community_cache()
        return {
            "canonical_id": canonical_id,
            "duplicate_id": duplicate_id,
            "redirected_edges": redirected,
            "status": "merged",
        }

    def _existing_edge_keys(self, node_idx: int) -> set[tuple]:
        """Return the set of ``(source_id, target_id, kind)`` triples
        currently incident on ``node_idx``."""
        keys: set[tuple] = set()
        for _s, _t, payload in self.graph.out_edges(node_idx):
            keys.add((payload.get("source_id"), payload.get("target_id"),
                      payload.get("kind")))
        for _s, _t, payload in self.graph.in_edges(node_idx):
            keys.add((payload.get("source_id"), payload.get("target_id"),
                      payload.get("kind")))
        return keys

    @staticmethod
    def _mint_node_id(kind: str, title: str, summary: str) -> str:
        import hashlib
        raw = f"{kind}::{title}::{summary}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:16]

    # ==================================================================
    # READ tools — signal + community surface (FEAT-190 / FEAT-191)
    # ==================================================================

    async def relevance(self, node_a: str, node_b: str) -> dict:
        """Decomposed five-signal relevance between two nodes (FEAT-190).

        Returns ``{direct, source_overlap, adamic_adar, type_affinity,
        embedding, combined, direct_edges, shared_sources,
        aa_neighbours, embedding_available}`` or
        ``{"error": "FEAT-190 not available"}``.
        """
        try:
            from parrot.knowledge.graphindex.signals import signal_relevance
        except ImportError:
            return {"error": "FEAT-190 signals module not available"}
        try:
            result = signal_relevance(
                graph=self.graph,
                nodes=self.nodes,
                node_a=node_a,
                node_b=node_b,
                config=self.signal_config,
                embedder=self.embedder,
            )
        except KeyError as exc:
            return {"error": str(exc)}
        return result.model_dump()

    async def neighborhood_by_relevance(
        self,
        node_id: str,
        top_k: int = 10,
    ) -> list[dict]:
        """Top-K nodes most relevant to ``node_id`` by combined signal score."""
        try:
            from parrot.knowledge.graphindex.signals import relevance_neighborhood
        except ImportError:
            return [{"error": "FEAT-190 signals module not available"}]
        if node_id not in self.node_map:
            return [{"error": f"node {node_id!r} not found"}]
        results = relevance_neighborhood(
            graph=self.graph,
            nodes=self.nodes,
            node_id=node_id,
            top_k=top_k,
            config=self.signal_config,
            embedder=self.embedder,
        )
        return [r.model_dump() for r in results]

    async def list_communities(self, min_size: int = 2) -> list[dict]:
        """FEAT-191 Louvain communities, filtered by minimum size.

        The result is cached until any write tool runs. Repeated calls
        do not re-run Louvain.
        """
        cached = self._get_or_compute_communities()
        if cached is None:
            return [{"error": "FEAT-191 communities module not available"}]
        return [
            c.model_dump()
            for c in cached.communities
            if c.size >= min_size
        ]

    async def find_community(self, node_id: str) -> dict:
        """Return the Community containing ``node_id`` (FEAT-191)."""
        cached = self._get_or_compute_communities()
        if cached is None:
            return {"error": "FEAT-191 communities module not available"}
        cid = cached.node_to_community.get(node_id)
        if cid is None:
            return {"error": f"node {node_id!r} not in any community"}
        for c in cached.communities:
            if c.community_id == cid:
                return c.model_dump()
        return {"error": f"community {cid!r} not found"}

    async def search_with_expansion(
        self,
        query: str,
        seed_top_k: int = 10,
        max_hops: int = 2,
        decay_base: float = 0.7,
        max_tokens: int = 8000,
    ) -> dict:
        """Search with graph-expanded retrieval: seeds → graph expansion → result assembly.

        Runs the full 4-phase ``GraphExpandedRetriever`` pipeline using the
        toolkit's stored graph, embedder, and signal configuration.

        Phase 1 uses the ``GraphIndexEmbedder`` (FAISS) for seed search.
        Phase 2 expands N hops with exponential score decay.
        Phase 3 community annotation is skipped — pass a ``CommunitiesResult`` to ``GraphExpandedRetriever`` directly if community context is needed.
        Phase 4 applies a token budget and sorts results by combined score.

        Args:
            query: Natural language search query.
            seed_top_k: Number of seed nodes from the initial FAISS search.
            max_hops: Maximum graph traversal depth (1–4).
            decay_base: Score decay per hop (0–1, default 0.7).
            max_tokens: Token budget for the returned result set.

        Returns:
            Dictionary representation of a ``GraphRetrievalResult`` with keys:
            ``query``, ``nodes``, ``total_candidates``, ``nodes_expanded``,
            ``communities_touched``, ``budget_used``, ``budget_limit``,
            ``truncated``.
        """
        from parrot.knowledge.graphindex.retriever import (
            BudgetConfig,
            ExpansionConfig,
            GraphExpandedRetriever,
        )

        if self.embedder is None:
            return {"error": "search_with_expansion requires an embedder; pass embedder=... at construction."}

        retriever = GraphExpandedRetriever(
            graph=self.graph,
            nodes=self.nodes,
            embedder=self.embedder,
            signal_config=self.signal_config,
        )
        max_hops = max(1, min(4, max_hops))
        expansion = ExpansionConfig(max_hops=max_hops, decay_base=decay_base)
        budget = BudgetConfig(max_tokens=max_tokens)
        result = await retriever.search(
            query,
            seed_top_k=seed_top_k,
            expansion=expansion,
            budget=budget,
        )
        return result.model_dump()

    def _get_or_compute_communities(self):
        if self._community_cache is not None:
            return self._community_cache
        try:
            from parrot.knowledge.graphindex.communities import (
                detect_communities,
            )
        except ImportError:
            return None
        result = detect_communities(
            graph=self.graph,
            nodes=self.nodes,
            signal_config=self.signal_config,
            embedder=self.embedder if self.signal_config else None,
            write_back_to_nodes=False,
        )
        self._community_cache = result
        return result

    def _extract_edges_from_graph(self) -> list:
        """Extract UniversalEdge-like objects from the graph edge payloads.

        Graph edges are stored as dicts with keys matching UniversalEdge fields.
        Returns a list of UniversalEdge instances where possible.
        """
        try:
            from parrot.knowledge.graphindex.schema import UniversalEdge, EdgeKind, Provenance
        except ImportError:
            return []
        edges = []
        for src_idx, tgt_idx, payload in self.graph.weighted_edge_list():
            if not isinstance(payload, dict):
                continue
            try:
                edge = UniversalEdge(
                    source_id=payload.get("source_id", ""),
                    target_id=payload.get("target_id", ""),
                    kind=EdgeKind(payload.get("kind", "contains")),
                    provenance=Provenance(payload.get("provenance", "extracted")),
                    confidence=payload.get("confidence"),
                )
                edges.append(edge)
            except (ValueError, KeyError):
                continue
        return edges

    def _get_or_compute_analytics(self):
        """Lazy-compute and cache an AnalyticsResult for the current graph state.

        Returns the cached result if available. When communities are available,
        re-runs _rank_surprising_connections with communities so the
        cross-community signal (+3) is applied correctly.
        """
        if self._analytics_cache is not None:
            return self._analytics_cache
        try:
            from parrot.knowledge.graphindex.analytics import (
                compute_analytics,
                _rank_surprising_connections,
            )
        except ImportError:
            return None
        edges = self._extract_edges_from_graph()
        result = compute_analytics(self.graph, self.nodes, edges)
        # Attach communities if already cached.
        communities = self._get_or_compute_communities()
        result.communities = communities
        # Re-rank now that communities are available so cross-community (+3) applies.
        if communities is not None:
            result.surprising_connections = _rank_surprising_connections(
                edges,
                self.nodes,
                top_k=DEFAULT_ANALYTICS_TOP_K,
                graph=self.graph,
                communities_result=communities,
            )
        self._analytics_cache = result
        return result

    # ------------------------------------------------------------------
    # FEAT-215: Knowledge gap detection tools
    # ------------------------------------------------------------------

    async def find_isolated_nodes(self, max_degree: int = 1) -> list[dict]:
        """Find nodes with few connections — potential knowledge gaps.

        Returns nodes with total degree (in + out) <= max_degree. DOCUMENT
        root nodes are excluded by default as they are structural anchors.

        Args:
            max_degree: Maximum total degree for a node to be considered
                isolated. Defaults to 1.

        Returns:
            List of dicts with ``node_id``, ``title``, ``kind``, ``degree``.
        """
        from parrot.knowledge.graphindex.analytics import (
            find_isolated_nodes as _find,
        )
        return _find(self.graph, self.nodes, max_degree=max_degree)

    async def find_sparse_communities(
        self, min_size: int = 3, max_cohesion: float = 0.15
    ) -> list[dict]:
        """Find Louvain communities with low internal cohesion.

        Communities that are large enough to be meaningful but poorly
        connected internally represent areas where knowledge is fragmented.

        Args:
            min_size: Minimum number of community members. Defaults to 3.
            max_cohesion: Maximum cohesion threshold (exclusive). Defaults to 0.15.

        Returns:
            List of dicts with ``community_id``, ``size``, ``cohesion``,
            ``top_titles``. Returns ``[{"error": ...}]`` if communities are
            not available.
        """
        from parrot.knowledge.graphindex.analytics import (
            find_sparse_communities as _find,
        )
        cached = self._get_or_compute_communities()
        if cached is None:
            return [{"error": "FEAT-191 communities module not available"}]
        return _find(cached, min_size=min_size, max_cohesion=max_cohesion)

    async def find_bridge_nodes(self, min_communities: int = 3) -> list[dict]:
        """Find nodes that bridge multiple distinct communities.

        Bridge nodes are critical connectors spanning at least
        ``min_communities`` distinct Louvain communities. They represent
        important cross-domain knowledge links.

        Args:
            min_communities: Minimum number of neighbor communities for a node
                to be classified as a bridge. Defaults to 3.

        Returns:
            List of dicts with ``node_id``, ``title``, ``kind``,
            ``community_count``, ``neighbor_community_ids``. Returns
            ``[{"error": ...}]`` if communities are not available.
        """
        from parrot.knowledge.graphindex.analytics import (
            find_bridge_nodes as _find,
        )
        cached = self._get_or_compute_communities()
        if cached is None:
            return [{"error": "FEAT-191 communities module not available"}]
        return _find(self.graph, self.nodes, cached, min_communities=min_communities)

    async def dismiss_insight(self, insight_id: str) -> dict:
        """Mark an insight as dismissed so it won't appear in future reports.

        The dismissal is persisted in a cached AnalyticsResult for the
        lifetime of this toolkit instance (session-scoped).

        Args:
            insight_id: The stable insight ID to dismiss. Conventions:
                ``"surprise:<src>:<tgt>"``, ``"isolated:<node_id>"``,
                ``"sparse:<community_id>"``, ``"bridge:<node_id>"``.

        Returns:
            Dict with ``dismissed`` (the ID) and ``total_dismissed`` (count).
        """
        from parrot.knowledge.graphindex.analytics import (
            dismiss_insight as _dismiss,
        )
        analytics = self._get_or_compute_analytics()
        if analytics is None:
            return {"error": "analytics module not available"}
        _dismiss(analytics, insight_id)
        return {
            "dismissed": insight_id,
            "total_dismissed": len(analytics.dismissed.dismissed_ids),
        }

    async def list_unreviewed_insights(self) -> list[dict]:
        """List all insights not yet dismissed.

        Aggregates surprising connections and knowledge gap entries (isolated
        nodes, sparse communities, bridge nodes) and filters out any that
        have been dismissed via ``dismiss_insight``.

        Returns:
            List of insight dicts, each with an ``id`` field and the original
            insight data. Empty list when no insights remain or analytics is
            unavailable.
        """
        from parrot.knowledge.graphindex.analytics import (
            list_unreviewed_insights as _list,
        )
        analytics = self._get_or_compute_analytics()
        if analytics is None:
            return []
        return _list(analytics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _encode_query(self, query: str, dim: int) -> np.ndarray:
        """Encode a query string into a FAISS-compatible ``(1, dim)`` vector.

        When a :class:`GraphIndexEmbedder` was injected, delegates to
        its underlying embedding model — this is the production path
        and matches what the build pipeline used to index nodes. The
        underlying ``model.encode`` may be sync or async; both are
        supported.

        When no embedder is available, falls back to a deterministic
        character-code hash so the read tools still work in unit-tests
        and ad-hoc demos. A WARNING is logged once per toolkit instance
        the first time the fallback triggers.

        Args:
            query: The query string.
            dim: Vector dimension expected by the FAISS index.

        Returns:
            A ``(1, dim)`` float32 numpy array.
        """
        if self.embedder is not None:
            try:
                vecs = self.embedder.model.encode([query])
                # Support both sync and async encoders.
                if asyncio.iscoroutine(vecs):
                    vecs = await vecs
                arr = np.asarray(vecs, dtype=np.float32)
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                if arr.shape[1] != dim:
                    raise ValueError(
                        f"_encode_query: embedder returned dim {arr.shape[1]} "
                        f"but FAISS index dim is {dim}"
                    )
                # Normalise — FAISS IndexFlatIP / IndexFlatL2 read
                # better with unit vectors.
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                return (arr / norms).astype(np.float32)
            except Exception as exc:  # noqa: BLE001 — surface fallback path
                self.logger.warning(
                    "_encode_query: embedder failed (%s); falling back to "
                    "placeholder hash encoder",
                    exc,
                )

        if not self._encoder_warning_emitted:
            self.logger.warning(
                "_encode_query: no embedder injected — using deterministic "
                "placeholder hash. find_node / search_hybrid results will "
                "NOT reflect real semantic similarity. Pass embedder=... "
                "at construction to fix.",
            )
            self._encoder_warning_emitted = True

        vec = np.zeros(dim, dtype=np.float32)
        for i, ch in enumerate(query[:dim]):
            vec[i % dim] += float(ord(ch))
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.reshape(1, -1)
