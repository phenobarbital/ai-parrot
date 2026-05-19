"""Persistence stage for GraphIndex.

Writes assembled graph nodes and edges to ArangoDB via
``OntologyGraphStore`` and embeddings to pgvector.  Supports atomic
per-document replacement for incremental refresh via soft-delete-then-upsert.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.graphindex.meta_ontology import (
    EDGE_KIND_TO_COLLECTION,
    KIND_TO_COLLECTION,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)


def _node_to_doc(node: UniversalNode) -> dict[str, Any]:
    """Convert a ``UniversalNode`` to an ArangoDB document dict.

    Args:
        node: The node to convert.

    Returns:
        A dict suitable for ``OntologyGraphStore.upsert_nodes``.
    """
    return {
        "_key": node.node_id,
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


def _edge_to_doc(
    edge: UniversalEdge,
    kind_to_collection: dict[str, str],
    node_kind_map: dict[str, str],
) -> dict[str, Any]:
    """Convert a ``UniversalEdge`` to an ArangoDB edge document dict.

    The ``_from`` and ``_to`` fields are fully-qualified ArangoDB document IDs
    of the form ``<collection>/<node_id>``.  The collection is resolved from
    ``node_kind_map`` (node_id → kind string) combined with
    ``kind_to_collection`` (kind string → vertex collection name).

    Args:
        edge: The edge to convert.
        kind_to_collection: Mapping from node-kind string to vertex collection
            name (e.g. ``{"symbol": "gi_symbols", ...}``).
        node_kind_map: Mapping from node_id to its kind string, built from
            the nodes being persisted in the same call.

    Returns:
        A dict suitable for ``OntologyGraphStore.create_edges``, with
        ``_from`` and ``_to`` as fully-qualified ArangoDB IDs.
    """
    src_kind = node_kind_map.get(edge.source_id, "")
    tgt_kind = node_kind_map.get(edge.target_id, "")
    src_collection = kind_to_collection.get(src_kind, "")
    tgt_collection = kind_to_collection.get(tgt_kind, "")

    from_ref = (
        f"{src_collection}/{edge.source_id}" if src_collection else edge.source_id
    )
    to_ref = (
        f"{tgt_collection}/{edge.target_id}" if tgt_collection else edge.target_id
    )

    return {
        "_from": from_ref,
        "_to": to_ref,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "kind": edge.kind.value,
        "provenance": edge.provenance.value,
        "confidence": edge.confidence,
    }


class GraphIndexPersistence:
    """Persists GraphIndex nodes, edges, and embeddings to ArangoDB + pgvector.

    Provides per-tenant locking to prevent race conditions during the
    soft-delete-then-upsert sequence in ``replace_document_slice``.

    Args:
        graph_store: An initialised ``OntologyGraphStore`` instance.
    """

    _tenant_locks: dict[str, asyncio.Lock]

    def __init__(self, graph_store: OntologyGraphStore) -> None:
        self.graph_store = graph_store
        self._tenant_locks = defaultdict(asyncio.Lock)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def persist_graph(
        self,
        ctx: TenantContext,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:
        """Persist all nodes and edges to ArangoDB.

        Nodes are routed to per-kind vertex collections.
        Edges are routed to per-kind edge collections.

        Args:
            ctx: Tenant context (db name, schema, ontology).
            nodes: All nodes to persist.
            edges: All edges to persist.

        Returns:
            Summary dict with ``nodes_persisted`` and ``edges_persisted`` counts.
        """
        if not nodes and not edges:
            return {"nodes_persisted": 0, "edges_persisted": 0}

        # Build node_id → kind lookup so _create_edges can form _from/_to refs.
        node_kind_map: dict[str, str] = {n.node_id: n.kind.value for n in nodes}

        nodes_persisted = await self._upsert_nodes(ctx, nodes)
        edges_persisted = await self._create_edges(ctx, edges, node_kind_map)

        logger.info(
            "Persisted %d nodes and %d edges for tenant %s",
            nodes_persisted,
            edges_persisted,
            ctx.tenant_id,
        )
        return {"nodes_persisted": nodes_persisted, "edges_persisted": edges_persisted}

    async def replace_document_slice(
        self,
        ctx: TenantContext,
        document_uri: str,
        nodes: list[UniversalNode],
        edges: list[UniversalEdge],
    ) -> dict[str, Any]:
        """Atomic per-document replacement: soft-delete old slice, upsert new.

        Acquires a per-tenant lock to serialise concurrent writes.

        Args:
            ctx: Tenant context.
            document_uri: URI of the document being replaced.  Used to
                identify the old nodes for soft-deletion.
            nodes: New nodes for this document.
            edges: New edges for this document.

        Returns:
            Summary dict with counts.
        """
        async with self._tenant_locks[ctx.tenant_id]:
            # 1. Collect _key values for existing nodes of this document
            old_keys_by_collection: dict[str, list[str]] = defaultdict(list)

            for collection in KIND_TO_COLLECTION.values():
                try:
                    existing = await self.graph_store.get_all_nodes(ctx, collection)
                    for doc in existing:
                        if doc.get("source_uri") == document_uri:
                            key = doc.get("_key") or doc.get("node_id")
                            if key:
                                old_keys_by_collection[collection].append(str(key))
                except Exception as exc:
                    logger.warning(
                        "Could not retrieve existing nodes from %s: %s", collection, exc
                    )

            # 2. Soft-delete old nodes
            for collection, keys in old_keys_by_collection.items():
                if keys:
                    try:
                        await self.graph_store.soft_delete_nodes(ctx, collection, keys)
                        logger.debug(
                            "Soft-deleted %d nodes from %s for document %s",
                            len(keys),
                            collection,
                            document_uri,
                        )
                    except Exception as exc:
                        logger.error(
                            "Failed to soft-delete nodes from %s: %s", collection, exc
                        )

            # 3. Upsert new nodes and edges
            node_kind_map: dict[str, str] = {n.node_id: n.kind.value for n in nodes}
            nodes_persisted = await self._upsert_nodes(ctx, nodes)
            edges_persisted = await self._create_edges(ctx, edges, node_kind_map)

        return {
            "nodes_replaced": nodes_persisted,
            "edges_replaced": edges_persisted,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _upsert_nodes(
        self, ctx: TenantContext, nodes: list[UniversalNode]
    ) -> int:
        """Route nodes to per-kind vertex collections and upsert.

        Args:
            ctx: Tenant context.
            nodes: Nodes to persist.

        Returns:
            Total number of nodes processed.
        """
        # Group nodes by kind → collection
        by_collection: dict[str, list[dict]] = defaultdict(list)
        for node in nodes:
            collection = KIND_TO_COLLECTION.get(node.kind.value)
            if not collection:
                logger.warning("Unknown kind '%s' for node %s", node.kind, node.node_id)
                continue
            by_collection[collection].append(_node_to_doc(node))

        total = 0
        for collection, docs in by_collection.items():
            if not docs:
                continue
            try:
                result = await self.graph_store.upsert_nodes(
                    ctx, collection, docs, key_field="node_id"
                )
                count = result.inserted + result.updated
                total += count
                logger.debug(
                    "Upserted %d nodes to %s (inserted=%d updated=%d)",
                    count,
                    collection,
                    result.inserted,
                    result.updated,
                )
            except Exception as exc:
                logger.error("Failed to upsert nodes to %s: %s", collection, exc)

        return total

    async def _create_edges(
        self,
        ctx: TenantContext,
        edges: list[UniversalEdge],
        node_kind_map: dict[str, str],
    ) -> int:
        """Route edges to per-kind edge collections and create.

        Args:
            ctx: Tenant context.
            edges: Edges to persist.
            node_kind_map: Mapping of node_id → kind string, used to build
                fully-qualified ``_from``/``_to`` ArangoDB references.

        Returns:
            Total number of edges created.
        """
        by_collection: dict[str, list[dict]] = defaultdict(list)
        for edge in edges:
            collection = EDGE_KIND_TO_COLLECTION.get(edge.kind.value)
            if not collection:
                logger.warning("Unknown edge kind '%s'", edge.kind)
                continue
            by_collection[collection].append(
                _edge_to_doc(edge, KIND_TO_COLLECTION, node_kind_map)
            )

        total = 0
        for collection, docs in by_collection.items():
            if not docs:
                continue
            try:
                count = await self.graph_store.create_edges(ctx, collection, docs)
                total += count
                logger.debug("Created %d edges in %s", count, collection)
            except Exception as exc:
                logger.error("Failed to create edges in %s: %s", collection, exc)

        return total
