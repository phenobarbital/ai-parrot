"""Persistence stage for GraphIndex.

Writes assembled graph nodes and edges to ArangoDB via
``OntologyGraphStore`` and embeddings to pgvector.  Supports atomic
per-document replacement for incremental refresh via soft-delete-then-upsert.

Also implements the **graph commit protocol** (``apply_update`` /
``load_graph`` / ``get_commit`` / ``list_commits`` / ``revert_commit``)
so :class:`~parrot.knowledge.graphindex.publish.GraphPublisher` can use
ArangoDB as the durable agent-memory backend, mirroring
``SQLitePersistence``. Commits live in two per-tenant collections:

- ``gi_commits`` — one doc per commit (``_key`` = commit id) carrying
  op/agent_id/run_id/asserted_by/reason/committed_at/payload/reverted_at
  and a monotonic ``seq`` (Arango has no rowid; ``seq`` orders commits
  for revert-conflict detection).
- ``gi_commit_items`` — one doc per touched node/edge with its
  ``collection`` and pre-image (``prior``), enabling revert.

ArangoDB exposes no multi-statement transactions through the store, so
``apply_update`` is serialized by the per-tenant ``asyncio.Lock`` (the
same single-writer expectation ``replace_document_slice`` already
carries) and records the commit + items BEFORE applying mutations, so a
crash mid-apply is at least visible in the audit trail.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.graphindex.meta_ontology import (
    EDGE_KIND_TO_COLLECTION,
    KIND_TO_COLLECTION,
)
from parrot.knowledge.graphindex.schema import (
    AssertionMeta,
    CommitReceipt,
    EdgeKind,
    GraphUpdate,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)

#: Per-tenant collection holding one document per graph write commit.
COMMITS_COLLECTION = "gi_commits"
#: Per-tenant collection holding one document per commit item (pre-image).
COMMIT_ITEMS_COLLECTION = "gi_commit_items"


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _edge_key(source_id: str, target_id: str, kind: str) -> str:
    """Compose the canonical ``item_key`` string for an edge."""
    return f"{source_id}|{target_id}|{kind}"


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
        "assertion": (
            node.assertion.model_dump(exclude_none=True)
            if node.assertion is not None
            else None
        ),
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
        "assertion": (
            edge.assertion.model_dump(exclude_none=True)
            if edge.assertion is not None
            else None
        ),
    }


def _doc_to_node(doc: dict[str, Any]) -> Optional[UniversalNode]:
    """Rehydrate a ``UniversalNode`` from an ArangoDB document.

    Returns ``None`` (with a warning) when the document carries enum
    values unknown to this code version — forward compatibility with
    graphs written by newer versions.
    """
    try:
        assertion = None
        raw_assertion = doc.get("assertion")
        if raw_assertion:
            assertion = AssertionMeta(**raw_assertion)
        return UniversalNode(
            node_id=doc["node_id"],
            kind=doc["kind"],
            title=doc.get("title") or doc["node_id"],
            source_uri=doc.get("source_uri") or "",
            content_ref=doc.get("content_ref"),
            summary=doc.get("summary"),
            embedding_ref=doc.get("embedding_ref"),
            domain_tags=doc.get("domain_tags") or {},
            parent_id=doc.get("parent_id"),
            provenance=doc.get("provenance", "extracted"),
            assertion=assertion,
        )
    except Exception as exc:  # noqa: BLE001 — skip-and-warn on unknown kinds
        logger.warning(
            "GraphIndexPersistence: skipping unreadable node doc %r: %s",
            doc.get("node_id", "?"),
            exc,
        )
        return None


def _doc_to_edge(doc: dict[str, Any]) -> Optional[UniversalEdge]:
    """Rehydrate a ``UniversalEdge`` from an ArangoDB edge document.

    Returns ``None`` (with a warning) on unknown enum values or
    validator failures (e.g. an INFERRED edge missing its confidence).
    """
    try:
        assertion = None
        raw_assertion = doc.get("assertion")
        if raw_assertion:
            assertion = AssertionMeta(**raw_assertion)
        return UniversalEdge(
            source_id=doc["source_id"],
            target_id=doc["target_id"],
            kind=doc["kind"],
            provenance=doc.get("provenance", "extracted"),
            confidence=doc.get("confidence"),
            assertion=assertion,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "GraphIndexPersistence: skipping unreadable edge doc (%r → %r): %s",
            doc.get("source_id", "?"),
            doc.get("target_id", "?"),
            exc,
        )
        return None


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
        # Tenants whose commit-log collections have been ensured.
        self._commit_ready: set[str] = set()

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

    # ------------------------------------------------------------------
    # Graph commit protocol (durable agent memory — GraphPublisher backend)
    # ------------------------------------------------------------------

    async def _ensure_commit_collections(self, ctx: TenantContext) -> None:
        """Ensure the commit-log and graph collections exist (cached).

        Args:
            ctx: Tenant context.
        """
        if ctx.tenant_id in self._commit_ready:
            return
        await self.graph_store.ensure_collection(ctx, COMMITS_COLLECTION)
        await self.graph_store.ensure_collection(ctx, COMMIT_ITEMS_COLLECTION)
        for collection in KIND_TO_COLLECTION.values():
            await self.graph_store.ensure_collection(ctx, collection)
        for collection in EDGE_KIND_TO_COLLECTION.values():
            await self.graph_store.ensure_collection(ctx, collection, edge=True)
        self._commit_ready.add(ctx.tenant_id)

    async def _find_node_doc(
        self,
        ctx: TenantContext,
        node_id: str,
        kind: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        """Locate a node document (collection, doc) by id.

        With a known ``kind`` only that collection is checked; otherwise
        every vertex collection is searched (bounded: ≤ 9 collections).

        Args:
            ctx: Tenant context.
            node_id: The node's id / ``_key``.
            kind: Optional kind string to target one collection.

        Returns:
            ``(collection, doc)`` — either may be ``None`` when absent.
        """
        if kind is not None:
            collection = KIND_TO_COLLECTION.get(kind)
            if collection is None:
                return None, None
            doc = await self.graph_store.get_document(ctx, collection, node_id)
            return collection, doc
        for collection in KIND_TO_COLLECTION.values():
            doc = await self.graph_store.get_document(ctx, collection, node_id)
            if doc is not None:
                return collection, doc
        return None, None

    async def _next_seq(self, ctx: TenantContext) -> int:
        """Next monotonic commit sequence number for the tenant.

        Arango documents have no rowid; ``seq`` provides the total order
        the revert-conflict check needs. Monotonicity is guaranteed only
        under the per-tenant lock (single-writer expectation).
        """
        rows = await self.graph_store.query_documents(
            ctx, COMMITS_COLLECTION, sort_desc="seq", limit=1
        )
        if not rows:
            return 1
        return int(rows[0].get("seq") or 0) + 1

    async def load_graph(
        self,
        ctx: TenantContext,
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Load and rehydrate the full tenant graph as schema models.

        Scans every vertex collection (active docs only — soft-deleted
        nodes are excluded) and every edge collection. Documents with
        enum values unknown to this code version are skipped with a
        warning. Returns ``([], [])`` when the store is unreachable —
        read parity with ``SQLitePersistence`` on a missing database.

        Args:
            ctx: Tenant context.

        Returns:
            ``(nodes, edges)`` lists of validated models.
        """
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []
        try:
            for collection in KIND_TO_COLLECTION.values():
                for doc in await self.graph_store.get_all_nodes(ctx, collection):
                    node = _doc_to_node(doc)
                    if node is not None:
                        nodes.append(node)
            for collection in EDGE_KIND_TO_COLLECTION.values():
                for doc in await self.graph_store.get_all_edges(ctx, collection):
                    edge = _doc_to_edge(doc)
                    if edge is not None:
                        edges.append(edge)
        except Exception as exc:  # noqa: BLE001 — unreachable store → empty
            logger.error("load_graph failed for tenant %s: %s", ctx.tenant_id, exc)
            return [], []
        return nodes, edges

    async def apply_update(
        self,
        ctx: TenantContext,
        update: GraphUpdate,
    ) -> CommitReceipt:
        """Apply a :class:`GraphUpdate` as one audited, revertible commit.

        Captures the pre-image of every touched document (including the
        implicit incident edges of ``removed_nodes``) into
        ``gi_commit_items``, records the commit doc, then applies the
        writes: node/edge upserts, soft-deletion of removed nodes (the
        store's tombstone convention), and hard removal of removed
        edges. The commit + items are written BEFORE the mutations so a
        mid-apply failure remains visible in the audit trail.

        Args:
            ctx: Tenant context.
            update: The validated update batch to apply.

        Returns:
            A :class:`CommitReceipt` describing the recorded commit.
        """
        commit_id = uuid.uuid4().hex[:16]
        committed_at = _now_iso()
        warnings: list[str] = []

        async with self._tenant_locks[ctx.tenant_id]:
            await self._ensure_commit_collections(ctx)
            seq = await self._next_seq(ctx)

            items: list[dict[str, Any]] = []

            # --- node pre-images (upserts) ----------------------------
            for node in update.nodes:
                collection = KIND_TO_COLLECTION.get(node.kind.value)
                if collection is None:
                    warnings.append(
                        f"node {node.node_id!r}: unknown kind {node.kind.value!r}"
                    )
                    continue
                prior = await self.graph_store.get_document(
                    ctx, collection, node.node_id
                )
                items.append({
                    "commit_id": commit_id,
                    "item_type": "node",
                    "item_key": node.node_id,
                    "collection": collection,
                    "prior": prior,
                })

            # --- node pre-images (removals) + implicit incident edges -
            implicit_removed: list[tuple[str, str, str]] = []
            removed_node_collections: dict[str, Optional[str]] = {}
            for node_id in update.removed_nodes:
                collection, prior = await self._find_node_doc(ctx, node_id)
                removed_node_collections[node_id] = collection
                items.append({
                    "commit_id": commit_id,
                    "item_type": "node_removed",
                    "item_key": node_id,
                    "collection": collection,
                    "prior": prior,
                })
                for edge_collection in EDGE_KIND_TO_COLLECTION.values():
                    for doc in await self.graph_store.edges_incident(
                        ctx, edge_collection, node_id
                    ):
                        implicit_removed.append((
                            doc.get("source_id"),
                            doc.get("target_id"),
                            doc.get("kind"),
                        ))

            removed_edge_set = {
                tuple(t) for t in update.removed_edges
            } | set(implicit_removed)

            # --- edge pre-images (upserts + removals) -----------------
            edge_triples = [
                (e.source_id, e.target_id, e.kind.value) for e in update.edges
            ] + sorted(removed_edge_set)
            seen_edge_items: set[str] = set()
            for src, tgt, kind in edge_triples:
                item_key = _edge_key(src, tgt, kind)
                if item_key in seen_edge_items:
                    continue
                seen_edge_items.add(item_key)
                collection = EDGE_KIND_TO_COLLECTION.get(kind)
                if collection is None:
                    warnings.append(f"edge {item_key!r}: unknown kind {kind!r}")
                    continue
                rows = await self.graph_store.query_documents(
                    ctx,
                    collection,
                    filters={"source_id": src, "target_id": tgt, "kind": kind},
                    limit=1,
                )
                items.append({
                    "commit_id": commit_id,
                    "item_type": (
                        "edge_removed"
                        if (src, tgt, kind) in removed_edge_set
                        else "edge"
                    ),
                    "item_key": item_key,
                    "collection": collection,
                    "prior": rows[0] if rows else None,
                })

            # --- record commit + items BEFORE mutating ----------------
            await self.graph_store.upsert_document(ctx, COMMITS_COLLECTION, {
                "_key": commit_id,
                "commit_id": commit_id,
                "seq": seq,
                "op": update.op,
                "agent_id": update.agent_id,
                "run_id": update.run_id,
                "asserted_by": update.asserted_by,
                "reason": update.reason,
                "committed_at": committed_at,
                "payload": update.model_dump(mode="json"),
                "reverted_at": None,
            })
            for item in items:
                await self.graph_store.insert_document(
                    ctx, COMMIT_ITEMS_COLLECTION, item
                )

            # --- apply writes -----------------------------------------
            if update.nodes:
                await self._upsert_nodes(ctx, update.nodes)
            if update.edges:
                # Resolve endpoint kinds for edges whose endpoints are
                # NOT part of this update (the common agent case:
                # link_nodes between pre-existing nodes) so _from/_to
                # get fully-qualified collection-prefixed ids.
                node_kind_map = {
                    n.node_id: n.kind.value for n in update.nodes
                }
                endpoints = {
                    e.source_id for e in update.edges
                } | {e.target_id for e in update.edges}
                for node_id in endpoints - set(node_kind_map):
                    _collection, doc = await self._find_node_doc(ctx, node_id)
                    if doc is not None and doc.get("kind"):
                        node_kind_map[node_id] = doc["kind"]
                await self._create_edges(ctx, update.edges, node_kind_map)
            for src, tgt, kind in sorted(removed_edge_set):
                collection = EDGE_KIND_TO_COLLECTION.get(kind)
                if collection is not None:
                    await self.graph_store.remove_edge_by_triple(
                        ctx, collection, src, tgt, kind
                    )
            removed_by_collection: dict[str, list[str]] = defaultdict(list)
            for node_id, collection in removed_node_collections.items():
                if collection is not None:
                    removed_by_collection[collection].append(node_id)
            for collection, keys in removed_by_collection.items():
                await self.graph_store.soft_delete_nodes(ctx, collection, keys)

        logger.info(
            "GraphIndexPersistence.apply_update: commit %s (%s) — %d nodes,"
            " %d edges, %d removed",
            commit_id,
            update.op,
            len(update.nodes),
            len(update.edges),
            len(removed_edge_set),
        )
        return CommitReceipt(
            commit_id=commit_id,
            op=update.op,
            node_ids=[n.node_id for n in update.nodes] + list(update.removed_nodes),
            edge_keys=[
                (e.source_id, e.target_id, e.kind.value) for e in update.edges
            ]
            + sorted(removed_edge_set),
            committed_at=committed_at,
            warnings=warnings,
        )

    @staticmethod
    def _public_commit(doc: dict[str, Any]) -> dict[str, Any]:
        """Strip ArangoDB internals from a commit document."""
        return {
            k: v for k, v in doc.items() if not k.startswith("_")
        }

    async def get_commit(
        self,
        ctx: TenantContext,
        commit_id: str,
    ) -> Optional[dict[str, Any]]:
        """Return a recorded commit with its payload and items.

        Args:
            ctx: Tenant context.
            commit_id: The commit to fetch.

        Returns:
            A dict with the commit fields, ``payload``, and ``items``,
            or ``None`` when unknown.
        """
        doc = await self.graph_store.get_document(
            ctx, COMMITS_COLLECTION, commit_id
        )
        if doc is None:
            return None
        commit = self._public_commit(doc)
        item_rows = await self.graph_store.query_documents(
            ctx, COMMIT_ITEMS_COLLECTION, filters={"commit_id": commit_id}
        )
        commit["items"] = [
            {
                "item_type": i.get("item_type"),
                "item_key": i.get("item_key"),
                "collection": i.get("collection"),
                "prior": i.get("prior"),
            }
            for i in item_rows
        ]
        return commit

    async def list_commits(
        self,
        ctx: TenantContext,
        run_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List recorded commits, newest first.

        Args:
            ctx: Tenant context.
            run_id: Optional filter on the producing run.
            agent_id: Optional filter on the producing agent.
            limit: Maximum rows returned.

        Returns:
            Commit summary dicts (payload omitted); ``[]`` when the
            commit collections are missing or the store is unreachable.
        """
        filters: dict[str, Any] = {}
        if run_id is not None:
            filters["run_id"] = run_id
        if agent_id is not None:
            filters["agent_id"] = agent_id
        try:
            rows = await self.graph_store.query_documents(
                ctx,
                COMMITS_COLLECTION,
                filters=filters,
                sort_desc="seq",
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001 — no commit log yet
            logger.debug("list_commits unavailable: %s", exc)
            return []
        commits = []
        for doc in rows:
            commit = self._public_commit(doc)
            commit.pop("payload", None)
            commits.append(commit)
        return commits

    async def revert_commit(
        self,
        ctx: TenantContext,
        commit_id: str,
    ) -> dict[str, Any]:
        """Restore the pre-images captured by a commit.

        Documents that had a pre-image are restored to it; documents the
        commit created (no pre-image) are hard-removed (so ``load_graph``
        never sees them). The revert is refused when a LATER commit
        (higher ``seq``, not itself reverted) touched any of the same
        item keys.

        Args:
            ctx: Tenant context.
            commit_id: The commit to revert.

        Returns:
            ``{"status": "reverted", ...}`` on success or
            ``{"error": ...}`` on refusal/unknown commit.
        """
        async with self._tenant_locks[ctx.tenant_id]:
            commit_doc = await self.graph_store.get_document(
                ctx, COMMITS_COLLECTION, commit_id
            )
            if commit_doc is None:
                return {"error": f"revert_commit: unknown commit {commit_id!r}"}
            if commit_doc.get("reverted_at"):
                return {"error": f"revert_commit: {commit_id!r} already reverted"}

            items = await self.graph_store.query_documents(
                ctx, COMMIT_ITEMS_COLLECTION, filters={"commit_id": commit_id}
            )
            if not items:
                return {
                    "error": f"revert_commit: commit {commit_id!r} has no items"
                }

            # Refuse when a later (non-reverted) commit touched the same keys.
            this_seq = int(commit_doc.get("seq") or 0)
            conflicts: list[str] = []
            commit_cache: dict[str, Optional[dict[str, Any]]] = {}
            for item in items:
                item_key = item.get("item_key")
                others = await self.graph_store.query_documents(
                    ctx, COMMIT_ITEMS_COLLECTION, filters={"item_key": item_key}
                )
                for other in others:
                    other_id = other.get("commit_id")
                    if not other_id or other_id == commit_id:
                        continue
                    if other_id not in commit_cache:
                        commit_cache[other_id] = await self.graph_store.get_document(
                            ctx, COMMITS_COLLECTION, other_id
                        )
                    other_commit = commit_cache[other_id]
                    if other_commit is None or other_commit.get("reverted_at"):
                        continue
                    if int(other_commit.get("seq") or 0) > this_seq:
                        conflicts.append(item_key)
                        break
            if conflicts:
                return {
                    "error": "revert_commit: later commits touched the same items",
                    "conflicts": sorted(set(conflicts)),
                }

            restored, deleted = 0, 0
            for item in items:
                collection = item.get("collection")
                prior = item.get("prior")
                item_key = item.get("item_key") or ""
                if collection is None:
                    continue
                if item.get("item_type") in ("node", "node_removed"):
                    if prior is None:
                        if await self.graph_store.remove_document(
                            ctx, collection, item_key
                        ):
                            deleted += 1
                    else:
                        await self.graph_store.upsert_document(
                            ctx, collection, prior
                        )
                        restored += 1
                else:  # edge / edge_removed
                    src, tgt, kind = item_key.split("|", 2)
                    if prior is None:
                        if await self.graph_store.remove_edge_by_triple(
                            ctx, collection, src, tgt, kind
                        ):
                            deleted += 1
                    else:
                        await self.graph_store.upsert_document(
                            ctx, collection, prior
                        )
                        restored += 1

            commit_doc["reverted_at"] = _now_iso()
            await self.graph_store.upsert_document(
                ctx, COMMITS_COLLECTION, commit_doc
            )

        logger.info(
            "GraphIndexPersistence.revert_commit: %s — %d restored, %d deleted",
            commit_id,
            restored,
            deleted,
        )
        return {
            "status": "reverted",
            "commit_id": commit_id,
            "restored": restored,
            "deleted": deleted,
        }
