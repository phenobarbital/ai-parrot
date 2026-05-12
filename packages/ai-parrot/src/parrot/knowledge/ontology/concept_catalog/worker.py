"""Concept Catalog Sync Worker (FEAT-159 TASK-1089).

Drains ``ontology_concept_outbox`` rows using ``SELECT … FOR UPDATE SKIP LOCKED``,
materialises concept/is_a data to ArangoDB via ``OntologyGraphStore``, and
publishes cache-invalidation messages to Redis pub/sub.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext

# Minimal shared MergedOntology used when the worker builds a lightweight
# TenantContext for graph store calls (no ontology data needed for sync ops).
_EMPTY_ONTOLOGY = MergedOntology(
    name="_worker",
    version="0",
    entities={},
    relations={},
    traversal_patterns={},
    layers=[],
    merge_timestamp=datetime(2000, 1, 1, tzinfo=timezone.utc),
)


class ConceptCatalogSyncWorker:
    """Drain ``ontology_concept_outbox``, sync to ArangoDB, publish invalidation.

    Operation dispatch table (class-level) maps outbox ``operation`` values to
    private method names so new operations can be registered without branching.

    DLQ policy: after ``MAX_RETRIES`` attempts the row is left with
    ``processed_at IS NULL`` and ``attempts >= MAX_RETRIES``; a monitoring
    query can surface these rows. They are NOT re-enqueued.

    Args:
        pg_pool: asyncpg connection pool.
        graph_store: OntologyGraphStore instance for ArangoDB I/O.
        redis_client: aioredis (or compatible) client for pub/sub publish.
    """

    OPERATIONS: dict[str, str] = {
        "publish_to_graph": "_op_publish",
        "deprecate_in_graph": "_op_deprecate",
        "invalidate_cache": "_op_invalidate",
    }
    GRAPH_NODE_COLLECTION = "concepts"
    GRAPH_EDGE_COLLECTION = "concept_isa"
    INVALIDATION_CHANNEL_PREFIX = "ontology:invalidate:"
    MAX_RETRIES: int = 5

    def __init__(
        self,
        pg_pool: Any,
        graph_store: OntologyGraphStore,
        redis_client: Any,
    ) -> None:
        self._pool = pg_pool
        self._graph_store = graph_store
        self._redis = redis_client
        self.logger = logging.getLogger("Parrot.Ontology.ConceptCatalog.Worker")

    # ── Public API ───────────────────────────────────────────────────────────

    async def run_once(self, batch_size: int = 50) -> int:
        """Drain up to *batch_size* outbox rows.

        Uses ``FOR UPDATE SKIP LOCKED`` so two parallel workers process
        disjoint rows without double-processing.

        Args:
            batch_size: Maximum number of rows to process in this call.

        Returns:
            Number of rows fetched (not necessarily all successfully processed).
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ontology_concept_outbox "
                "WHERE processed_at IS NULL "
                "ORDER BY enqueued_at "
                "LIMIT $1 "
                "FOR UPDATE SKIP LOCKED",
                batch_size,
            )

            for row in rows:
                operation = row["operation"]
                method_name = self.OPERATIONS.get(operation)
                if method_name is None:
                    self.logger.warning(
                        "Unknown outbox operation '%s' for row %s — skipping.",
                        operation, row["id"],
                    )
                    continue

                handler = getattr(self, method_name)
                try:
                    await handler(conn, row)
                    await conn.execute(
                        "UPDATE ontology_concept_outbox "
                        "SET processed_at = now() "
                        "WHERE id = $1",
                        row["id"],
                    )
                    self.logger.debug(
                        "Outbox row %s (%s) processed successfully.",
                        row["id"], operation,
                    )
                except Exception as exc:
                    attempts: int = (row["attempts"] or 0) + 1
                    if attempts >= self.MAX_RETRIES:
                        self.logger.error(
                            "DLQ: outbox row %s after %d attempts — %s",
                            row["id"], attempts, exc,
                        )
                    else:
                        self.logger.warning(
                            "Outbox row %s attempt %d/%d failed: %s",
                            row["id"], attempts, self.MAX_RETRIES, exc,
                        )
                    await conn.execute(
                        "UPDATE ontology_concept_outbox "
                        "SET attempts = $1, last_error = $2 "
                        "WHERE id = $3",
                        attempts, str(exc), row["id"],
                    )

            return len(rows)

    # ── Operation handlers ────────────────────────────────────────────────────

    async def _op_publish(self, conn: Any, row: Any) -> None:
        """Upsert a concept or is_a edge node into ArangoDB.

        Every ArangoDB document carries the Postgres primary key so the
        reconciler can cross-reference sources.

        Args:
            conn: Active asyncpg connection (unused directly but passed for
                uniformity).
            row: Outbox row dict with ``payload`` and ``tenant_id``.
        """
        payload: dict[str, Any] = dict(row["payload"]) if row["payload"] else {}
        tenant_id: str = row["tenant_id"]

        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=f"{tenant_id}_ontology",
            pgvector_schema=tenant_id,
            ontology=_EMPTY_ONTOLOGY,
        )

        target_kind: str = payload.get("target_kind", "concept")

        if target_kind == "isa_edge":
            # Edge document for is_a hierarchy
            pg_edge_id = str(payload.get("isa_edge_id", ""))
            edge_doc = {
                "_key": pg_edge_id,
                "pg_isa_edge_id": pg_edge_id,
                "child_id": str(payload.get("child_id", "")),
                "parent_ref": payload.get("parent_ref", ""),
                "parent_tier": payload.get("parent_tier", "tenant"),
                "tenant_id": tenant_id,
            }
            await self._graph_store.create_edges(
                ctx,
                self.GRAPH_EDGE_COLLECTION,
                [edge_doc],
            )
            self.logger.info(
                "Published is_a edge %s for tenant '%s'.", pg_edge_id, tenant_id
            )
        else:
            # Concept node
            pg_concept_id = str(payload.get("concept_id", ""))
            node_doc = {
                "_key": pg_concept_id,
                "pg_concept_id": pg_concept_id,
                "slug": payload.get("slug", ""),
                "label": payload.get("label", ""),
                "synonyms": payload.get("synonyms", []),
                "description": payload.get("description"),
                "domain": payload.get("domain"),
                "state": "approved",
                "tenant_id": tenant_id,
            }
            await self._graph_store.upsert_nodes(
                ctx,
                self.GRAPH_NODE_COLLECTION,
                [node_doc],
                key_field="_key",
            )
            self.logger.info(
                "Published concept %s ('%s') for tenant '%s'.",
                pg_concept_id, payload.get("slug"), tenant_id,
            )

        # After any publish, also invalidate cache
        await self._op_invalidate(conn, row)

    async def _op_deprecate(self, conn: Any, row: Any) -> None:
        """Soft-delete a concept or edge in ArangoDB.

        Args:
            conn: Active asyncpg connection.
            row: Outbox row with ``payload`` and ``tenant_id``.
        """
        payload: dict[str, Any] = dict(row["payload"]) if row["payload"] else {}
        tenant_id: str = row["tenant_id"]

        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=f"{tenant_id}_ontology",
            pgvector_schema=tenant_id,
            ontology=_EMPTY_ONTOLOGY,
        )

        target_kind: str = payload.get("target_kind", "concept")

        if target_kind == "isa_edge":
            key = str(payload.get("isa_edge_id", ""))
            await self._graph_store.soft_delete_nodes(
                ctx, self.GRAPH_EDGE_COLLECTION, [key]
            )
            self.logger.info(
                "Deprecated is_a edge %s for tenant '%s'.", key, tenant_id
            )
        else:
            key = str(payload.get("concept_id", ""))
            await self._graph_store.soft_delete_nodes(
                ctx, self.GRAPH_NODE_COLLECTION, [key]
            )
            self.logger.info(
                "Deprecated concept %s for tenant '%s'.", key, tenant_id
            )

        # After deprecation, also invalidate cache
        await self._op_invalidate(conn, row)

    async def _op_invalidate(self, conn: Any, row: Any) -> None:
        """Publish an invalidation message on the Redis pub/sub channel.

        Channel pattern: ``ontology:invalidate:<tenant_id>``.

        Args:
            conn: Active asyncpg connection (unused).
            row: Outbox row with ``tenant_id``.
        """
        tenant_id: str = row["tenant_id"]
        channel = f"{self.INVALIDATION_CHANNEL_PREFIX}{tenant_id}"
        payload: dict[str, Any] = dict(row["payload"]) if row["payload"] else {}
        message = payload.get("concept_id") or payload.get("isa_edge_id") or "invalidate"
        await self._redis.publish(channel, str(message))
        self.logger.debug(
            "Published invalidation to channel '%s'.", channel
        )
