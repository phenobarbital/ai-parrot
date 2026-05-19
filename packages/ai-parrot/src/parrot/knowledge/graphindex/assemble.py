"""Graph assembly stage for GraphIndex.

Builds a ``rustworkx.PyDiGraph`` from streams of ``UniversalNode`` and
``UniversalEdge``.  Node payloads are lightweight metadata dicts (IDs, kind,
title, domain_tags); source content is referenced via ``content_ref``, not
stored in the graph.

Per-tenant isolation: each ``GraphAssembler`` instance is scoped to a single
tenant, consistent with ``OntologyGraphStore`` isolation patterns.
"""

from __future__ import annotations

import logging
from typing import Optional

import rustworkx

from parrot.knowledge.graphindex.schema import UniversalEdge, UniversalNode

logger = logging.getLogger(__name__)


class GraphAssembler:
    """Build and query a rustworkx PyDiGraph from UniversalNode/UniversalEdge streams.

    Maintains per-tenant graph isolation.  Node payloads are lightweight
    metadata dicts (IDs, kind, title, domain_tags); source content is
    referenced via ``content_ref``, not stored in the graph.

    Args:
        tenant_id: Tenant identifier for graph isolation.
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.graph: rustworkx.PyDiGraph = rustworkx.PyDiGraph()
        self._node_index_map: dict[str, int] = {}  # node_id → rustworkx int index
        self._edge_index_map: dict[tuple[str, str, str], int] = {}  # (src, tgt, kind) → edge int index

    # ------------------------------------------------------------------
    # Mutation interface
    # ------------------------------------------------------------------

    def add_node(self, node: UniversalNode) -> int:
        """Add a node to the graph.  Updates existing payload on duplicate ``node_id``.

        Args:
            node: ``UniversalNode`` to add.

        Returns:
            The rustworkx integer index for the node.
        """
        payload = {
            "node_id": node.node_id,
            "kind": node.kind.value,
            "title": node.title,
            "source_uri": node.source_uri,
            "content_ref": node.content_ref,
            "summary": node.summary,
            "embedding_ref": node.embedding_ref,
            "domain_tags": node.domain_tags,
            "parent_id": node.parent_id,
            "provenance": node.provenance.value,
        }

        if node.node_id in self._node_index_map:
            idx = self._node_index_map[node.node_id]
            self.graph[idx] = payload
            logger.debug("Duplicate node_id '%s' — payload updated", node.node_id)
            return idx

        idx = self.graph.add_node(payload)
        self._node_index_map[node.node_id] = idx
        return idx

    def add_edge(self, edge: UniversalEdge) -> Optional[int]:
        """Add an edge to the graph.  Skips if source/target missing.

        Args:
            edge: ``UniversalEdge`` to add.

        Returns:
            The rustworkx edge index, or ``None`` if the edge was skipped.
        """
        src_idx = self._node_index_map.get(edge.source_id)
        tgt_idx = self._node_index_map.get(edge.target_id)

        if src_idx is None:
            logger.warning(
                "Edge source '%s' not found in graph — skipping edge", edge.source_id
            )
            return None
        if tgt_idx is None:
            logger.warning(
                "Edge target '%s' not found in graph — skipping edge", edge.target_id
            )
            return None

        payload = {
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "kind": edge.kind.value,
            "provenance": edge.provenance.value,
            "confidence": edge.confidence,
        }

        edge_key = (edge.source_id, edge.target_id, edge.kind.value)
        idx = self.graph.add_edge(src_idx, tgt_idx, payload)
        self._edge_index_map[edge_key] = idx
        return idx

    def add_nodes(self, nodes: list[UniversalNode]) -> list[int]:
        """Batch-add nodes to the graph.

        Args:
            nodes: List of nodes to add.

        Returns:
            List of rustworkx integer indices in the same order.
        """
        return [self.add_node(n) for n in nodes]

    def add_edges(self, edges: list[UniversalEdge]) -> list[Optional[int]]:
        """Batch-add edges to the graph.

        Args:
            edges: List of edges to add.

        Returns:
            List of edge indices (``None`` for skipped edges).
        """
        return [self.add_edge(e) for e in edges]

    # ------------------------------------------------------------------
    # Query interface
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get node payload by ``node_id``.

        Args:
            node_id: The application-level node identifier.

        Returns:
            Node payload dict, or ``None`` if not found.
        """
        idx = self._node_index_map.get(node_id)
        if idx is None:
            return None
        return self.graph[idx]

    def get_neighbors(
        self, node_id: str, direction: str = "outgoing"
    ) -> list[dict]:
        """Get neighboring node payloads.

        Args:
            node_id: The node to query.
            direction: ``"outgoing"``, ``"incoming"``, or ``"both"``.

        Returns:
            List of neighbor payload dicts.
        """
        idx = self._node_index_map.get(node_id)
        if idx is None:
            return []

        neighbor_indices: list[int] = []

        if direction in ("outgoing", "both"):
            for out_idx in self.graph.successor_indices(idx):
                neighbor_indices.append(out_idx)

        if direction in ("incoming", "both"):
            for in_idx in self.graph.predecessor_indices(idx):
                neighbor_indices.append(in_idx)

        # De-duplicate while preserving order
        seen: set[int] = set()
        result: list[dict] = []
        for i in neighbor_indices:
            if i not in seen:
                seen.add(i)
                result.append(self.graph[i])
        return result

    def get_edges_for_node(
        self, node_id: str, direction: str = "both"
    ) -> list[dict]:
        """Get edge payloads connected to a node.

        Args:
            node_id: The node to query.
            direction: ``"outgoing"``, ``"incoming"``, or ``"both"``.

        Returns:
            List of edge payload dicts.
        """
        idx = self._node_index_map.get(node_id)
        if idx is None:
            return []

        result: list[dict] = []

        if direction in ("outgoing", "both"):
            for _src, _tgt, payload in self.graph.out_edges(idx):
                result.append(payload)

        if direction in ("incoming", "both"):
            for _src, _tgt, payload in self.graph.in_edges(idx):
                result.append(payload)

        return result

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def node_count(self) -> int:
        """Number of nodes in the graph."""
        return self.graph.num_nodes()

    @property
    def edge_count(self) -> int:
        """Number of edges in the graph."""
        return self.graph.num_edges()
