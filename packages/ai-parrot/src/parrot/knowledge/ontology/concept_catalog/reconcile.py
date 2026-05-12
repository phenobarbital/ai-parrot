"""Concept Catalog Reconciliation Job (FEAT-159 TASK-1091).

Detects drift between Postgres (source of truth) and ArangoDB (materialized
view).  The reconciler is **read-only**: it reports discrepancies but does not
auto-repair them.

Drift categories
-----------------
* **missing_in_arango** — approved PG row has no matching ArangoDB document.
* **orphans_in_arango** — ArangoDB document has no corresponding approved PG
  row (or the PG row is deprecated/rejected).

In-flight rows (``updated_at > now() - outbox_drain_interval × 10``) are
excluded from forward-scan results to prevent false positives during outbox
processing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext

logger = logging.getLogger("Parrot.Ontology.ConceptCatalog.Reconciler")

# Default drain interval used when none is configured.
_DEFAULT_DRAIN_INTERVAL_SECONDS = 30

# Minimal ontology used for TenantContext construction (reconciler does not
# need ontology content; graph_store only uses arango_db and tenant_id).
_EMPTY_ONTOLOGY = MergedOntology(
    name="_reconciler",
    version="0",
    entities={},
    relations={},
    traversal_patterns={},
    layers=[],
    merge_timestamp=datetime(2000, 1, 1, tzinfo=timezone.utc),
)


@dataclass
class ReconciliationReport:
    """Summary of one reconciliation run for a tenant.

    Attributes:
        tenant_id: Tenant that was reconciled.
        missing_in_arango: Count of approved PG concepts absent from ArangoDB.
        orphans_in_arango: Count of ArangoDB docs with no matching approved PG row.
        missing_isa_in_arango: Count of approved PG edges absent from ArangoDB.
        orphan_edges_in_arango: Count of ArangoDB edges with no matching PG row.
        discrepancies: Human-readable detail strings for each discrepancy.
    """

    tenant_id: str
    missing_in_arango: int = 0
    orphans_in_arango: int = 0
    missing_isa_in_arango: int = 0
    orphan_edges_in_arango: int = 0
    discrepancies: list[str] = field(default_factory=list)

    @property
    def has_discrepancies(self) -> bool:
        """Return True if any drift was detected."""
        return (
            self.missing_in_arango > 0
            or self.orphans_in_arango > 0
            or self.missing_isa_in_arango > 0
            or self.orphan_edges_in_arango > 0
        )


class ConceptCatalogReconciler:
    """Detect drift between Postgres and ArangoDB for a tenant's concept catalog.

    The reconciler performs two scans per collection:

    1. **Forward scan** — for each approved PG row, verify an ArangoDB document
       with matching ``pg_concept_id`` / ``pg_isa_edge_id`` exists.
    2. **Reverse scan** — for each ArangoDB document, verify a corresponding
       approved PG row exists.

    Only discrepancies are logged (at WARNING level).  No writes are made.

    Args:
        pg_pool: asyncpg connection pool.
        graph_store: OntologyGraphStore instance.
        outbox_drain_interval: Seconds to wait before flagging an in-flight row.
            Rows updated within ``outbox_drain_interval × 10`` seconds are
            excluded from forward-scan results.
    """

    CONCEPT_COLLECTION = "concepts"
    ISA_COLLECTION = "concept_isa"

    def __init__(
        self,
        pg_pool: Any,
        graph_store: OntologyGraphStore,
        outbox_drain_interval: int = _DEFAULT_DRAIN_INTERVAL_SECONDS,
    ) -> None:
        self._pool = pg_pool
        self._graph_store = graph_store
        self._drain_cutoff_delta = timedelta(
            seconds=outbox_drain_interval * 10
        )
        self.logger = logging.getLogger(
            "Parrot.Ontology.ConceptCatalog.Reconciler"
        )

    async def reconcile(self, tenant_id: str) -> ReconciliationReport:
        """Run a full reconciliation for *tenant_id*.

        Args:
            tenant_id: Tenant to reconcile.

        Returns:
            ``ReconciliationReport`` with discrepancy counts and details.
        """
        report = ReconciliationReport(tenant_id=tenant_id)
        ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=f"{tenant_id}_ontology",
            pgvector_schema=tenant_id,
            ontology=_EMPTY_ONTOLOGY,
        )
        cutoff = datetime.now(timezone.utc) - self._drain_cutoff_delta

        async with self._pool.acquire() as conn:
            await self._reconcile_concepts(conn, ctx, cutoff, report)
            await self._reconcile_isa_edges(conn, ctx, cutoff, report)

        if report.has_discrepancies:
            self.logger.warning(
                "Reconciliation for tenant '%s': %d concept(s) missing in ArangoDB, "
                "%d orphan(s) in ArangoDB, %d isa edge(s) missing, %d orphan edges.",
                tenant_id,
                report.missing_in_arango,
                report.orphans_in_arango,
                report.missing_isa_in_arango,
                report.orphan_edges_in_arango,
            )
        else:
            self.logger.info(
                "Reconciliation for tenant '%s': no drift detected.", tenant_id
            )

        return report

    # ── Concept reconciliation ───────────────────────────────────────────────

    async def _reconcile_concepts(
        self,
        conn: Any,
        ctx: TenantContext,
        cutoff: datetime,
        report: ReconciliationReport,
    ) -> None:
        # ── Forward scan ─────────────────────────────────────────────────────
        pg_rows = await conn.fetch(
            "SELECT id, slug, updated_at "
            "FROM ontology_concept "
            "WHERE tenant_id = $1 AND state = 'approved' AND updated_at < $2",
            ctx.tenant_id,
            cutoff,
        )

        arango_docs = await self._graph_store.get_all_nodes(
            ctx, self.CONCEPT_COLLECTION
        )
        arango_pg_ids: set[str] = {
            str(d["pg_concept_id"]) for d in arango_docs if d.get("pg_concept_id")
        }

        for row in pg_rows:
            pg_id = str(row["id"])
            if pg_id not in arango_pg_ids:
                msg = (
                    f"[MISSING_IN_ARANGO] concept id={pg_id} "
                    f"slug='{row['slug']}' not found in ArangoDB."
                )
                report.missing_in_arango += 1
                report.discrepancies.append(msg)
                self.logger.warning(msg)

        # ── Reverse scan ─────────────────────────────────────────────────────
        pg_approved_ids: set[str] = {str(r["id"]) for r in pg_rows}

        for doc in arango_docs:
            pg_id = str(doc.get("pg_concept_id", ""))
            if pg_id and pg_id not in pg_approved_ids:
                msg = (
                    f"[ORPHAN_IN_ARANGO] ArangoDB concept pg_concept_id={pg_id} "
                    f"has no approved PG row."
                )
                report.orphans_in_arango += 1
                report.discrepancies.append(msg)
                self.logger.warning(msg)

    # ── is_a edge reconciliation ─────────────────────────────────────────────

    async def _reconcile_isa_edges(
        self,
        conn: Any,
        ctx: TenantContext,
        cutoff: datetime,
        report: ReconciliationReport,
    ) -> None:
        pg_edges = await conn.fetch(
            "SELECT id, updated_at "
            "FROM ontology_concept_isa "
            "WHERE tenant_id = $1 AND state = 'approved' AND updated_at < $2",
            ctx.tenant_id,
            cutoff,
        )

        arango_edges = await self._graph_store.get_all_nodes(
            ctx, self.ISA_COLLECTION
        )
        arango_edge_ids: set[str] = {
            str(e["pg_isa_edge_id"])
            for e in arango_edges
            if e.get("pg_isa_edge_id")
        }

        # Forward scan
        for row in pg_edges:
            pg_id = str(row["id"])
            if pg_id not in arango_edge_ids:
                msg = (
                    f"[MISSING_ISA_IN_ARANGO] isa edge id={pg_id} "
                    f"not found in ArangoDB."
                )
                report.missing_isa_in_arango += 1
                report.discrepancies.append(msg)
                self.logger.warning(msg)

        # Reverse scan
        pg_edge_ids: set[str] = {str(r["id"]) for r in pg_edges}
        for edge in arango_edges:
            pg_id = str(edge.get("pg_isa_edge_id", ""))
            if pg_id and pg_id not in pg_edge_ids:
                msg = (
                    f"[ORPHAN_ISA_IN_ARANGO] ArangoDB isa edge pg_isa_edge_id={pg_id} "
                    f"has no approved PG row."
                )
                report.orphan_edges_in_arango += 1
                report.discrepancies.append(msg)
                self.logger.warning(msg)
