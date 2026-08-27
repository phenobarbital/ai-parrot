"""Append-only suppression log (FEAT-449 §3 M4).

Persists ``SuppressionRecord``s produced by ``SpanVerifier`` into the
``span_suppressions`` collection declared by the legal ontology (TASK-2494).
Why not ``AuditLedger``: its ``append()`` requires ``credential_material``
and derives KMS fingerprints (``security/audit_ledger.py:338``) — a span
suppression has no credential. The *intent* (durable, append-only,
attributable record) is preserved here via the tenant's own
``span_suppressions`` collection instead.
"""

from __future__ import annotations

from typing import Any

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import TenantContext

from .models import SuppressionRecord


class SuppressionLog:
    """Append-only writer for ``SuppressionRecord``s.

    Exposes exactly ONE public method — ``append`` — by construction: no
    update, delete, or list method exists here. Reading the log back is
    an ops/AQL concern, not part of this API.

    Args:
        store: The tenant's graph store.
        ctx: Tenant context to write into.
    """

    def __init__(self, store: OntologyGraphStore, ctx: TenantContext) -> None:
        self._store = store
        self._ctx = ctx
        self._seq = 0

    async def append(self, record: SuppressionRecord) -> None:
        """Persist one suppression record.

        Args:
            record: The suppression record to append.
        """
        self._seq += 1
        suppression_id = f"{record.execution_id}:{self._seq}"
        doc: dict[str, Any] = {
            "_key": suppression_id,
            "suppression_id": suppression_id,
            **record.model_dump(mode="json"),
        }
        await self._store.insert_document(self._ctx, "span_suppressions", doc)
