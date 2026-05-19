"""GraphIndex Toolkit — Agent-Facing Tools.

Exposes the knowledge graph to AI agents as a set of callable tools via
``GraphIndexToolkit(AbstractToolkit)``.  All public async methods are
auto-discovered and registered as tools by the ``AbstractToolkit``
base class.

Hot queries read from the in-memory ``rustworkx.PyDiGraph`` and FAISS
index.  ``explain()`` optionally uses an ``AbstractClient`` for LLM
summary generation.
"""

from __future__ import annotations

import logging
from typing import Optional

import faiss
import numpy as np
import rustworkx

from parrot.tools.toolkit import AbstractToolkit

logger = logging.getLogger(__name__)


class GraphIndexToolkit(AbstractToolkit):
    """Agent-facing tools for querying the GraphIndex knowledge graph.

    Provides semantic search, graph traversal, centrality queries,
    and LLM-powered explanations over the assembled knowledge graph.

    All public async methods are auto-discovered by ``AbstractToolkit``
    and registered as callable agent tools.

    Args:
        graph: The assembled ``rustworkx.PyDiGraph``.  Node payloads must
            be dicts with at least ``node_id``, ``kind``, and ``title``.
        faiss_index: FAISS index populated with node embeddings.
        node_map: Mapping from application-level ``node_id`` string to
            the rustworkx integer node index.
        node_id_list: Ordered list mapping FAISS position → ``node_id``.
        client: Optional ``AbstractClient`` instance for ``explain()``
            LLM summaries.
    """

    def __init__(
        self,
        graph: rustworkx.PyDiGraph,
        faiss_index: faiss.Index,
        node_map: dict[str, int],
        node_id_list: list[str],
        client=None,  # Optional[AbstractClient]
    ) -> None:
        super().__init__()
        self.graph = graph
        self.faiss_index = faiss_index
        self.node_map = node_map
        self.node_id_list = node_id_list
        self.client = client
        self.logger = logging.getLogger(__name__)

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
            # Encode query to a unit vector via a simple hash (placeholder
            # for real embedding; in production use the embedder's model)
            query_vec = self._encode_query(query, dim)
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
            query_vec = self._encode_query(query, dim)
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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _encode_query(self, query: str, dim: int) -> np.ndarray:
        """Encode a query string to a FAISS-compatible float32 vector.

        This is a deterministic placeholder encoder that creates a vector
        from the query's character codes.  In production, a real embedding
        model should be injected via a ``GraphIndexEmbedder``.

        Args:
            query: The query string.
            dim: The vector dimension.

        Returns:
            A (1, dim) float32 numpy array.
        """
        vec = np.zeros(dim, dtype=np.float32)
        for i, ch in enumerate(query[:dim]):
            vec[i % dim] += float(ord(ch))
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.reshape(1, -1)
