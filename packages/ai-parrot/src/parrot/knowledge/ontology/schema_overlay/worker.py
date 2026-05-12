"""Schema Overlay Sync Worker (FEAT-159 TASK-1096).

Drains ``ontology_schema_outbox`` using ``SELECT … FOR UPDATE SKIP LOCKED``
and publishes cache-invalidation messages to Redis pub/sub.

Unlike the concept catalog worker, the schema overlay worker does **not**
materialise data to ArangoDB — overlays are composed at resolve-time by
``TenantOntologyManager`` + ``OntologyMerger``.
"""
from __future__ import annotations

import logging
from typing import Any


class SchemaOverlaySyncWorker:
    """Drain ``ontology_schema_outbox`` and publish cache invalidation.

    Operation dispatch table:

    * ``invalidate_cache`` → ``_op_invalidate``
    * ``deprecate_invalidate`` → ``_op_invalidate``

    DLQ policy: after ``MAX_RETRIES`` attempts the row is left unprocessed.

    Args:
        pg_pool: asyncpg connection pool.
        redis_client: aioredis (or compatible) client.
    """

    OPERATIONS: dict[str, str] = {
        "invalidate_cache": "_op_invalidate",
        "deprecate_invalidate": "_op_invalidate",
    }
    INVALIDATE_CHANNEL_TEMPLATE = "ontology:invalidate:{tenant_id}"
    MAX_RETRIES: int = 5

    def __init__(self, pg_pool: Any, redis_client: Any) -> None:
        self._pool = pg_pool
        self._redis = redis_client
        self.logger = logging.getLogger("Parrot.Ontology.SchemaOverlay.Worker")

    async def run_once(self, batch_size: int = 50) -> int:
        """Drain up to *batch_size* outbox rows.

        Uses ``FOR UPDATE SKIP LOCKED`` so parallel workers process
        disjoint rows without double-processing.

        Args:
            batch_size: Maximum number of rows to process in this call.

        Returns:
            Number of rows fetched.
        """
        async with self._pool.acquire() as conn:
            # H1 fix: wrap SELECT FOR UPDATE SKIP LOCKED + updates in one transaction
            # so row locks persist across the entire processing loop.
            async with conn.transaction():
                rows = await conn.fetch(
                    "SELECT * FROM ontology_schema_outbox "
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
                            "Unknown schema outbox operation '%s' for row %s — skipping.",
                            operation, row["id"],
                        )
                        continue

                    handler = getattr(self, method_name)
                    try:
                        await handler(conn, row)
                        await conn.execute(
                            "UPDATE ontology_schema_outbox "
                            "SET processed_at = now() "
                            "WHERE id = $1",
                            row["id"],
                        )
                        self.logger.debug(
                            "Schema outbox row %s (%s) processed successfully.",
                            row["id"], operation,
                        )
                    except Exception as exc:
                        attempts: int = (row["attempts"] or 0) + 1
                        if attempts >= self.MAX_RETRIES:
                            self.logger.error(
                                "DLQ: schema outbox row %s after %d attempts — %s",
                                row["id"], attempts, exc,
                            )
                        else:
                            self.logger.warning(
                                "Schema outbox row %s attempt %d/%d failed: %s",
                                row["id"], attempts, self.MAX_RETRIES, exc,
                            )
                        await conn.execute(
                            "UPDATE ontology_schema_outbox "
                            "SET attempts = $1, last_error = $2 "
                            "WHERE id = $3",
                            attempts, str(exc), row["id"],
                        )

        return len(rows)

    async def _op_invalidate(self, conn: Any, row: Any) -> None:
        """Publish cache invalidation to Redis.

        Channel: ``ontology:invalidate:<tenant_id>``.

        Args:
            conn: Active asyncpg connection (unused).
            row: Outbox row dict with ``tenant_id``.
        """
        tenant_id: str = row["tenant_id"]
        channel = self.INVALIDATE_CHANNEL_TEMPLATE.format(tenant_id=tenant_id)
        payload = str(row.get("id", "invalidate"))
        await self._redis.publish(channel, payload)
        self.logger.debug(
            "Published schema invalidation to channel '%s'.", channel
        )
