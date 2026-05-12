"""Concept Catalog Service — sole SQL writer for ontology_concept* tables.

Implements the five-state machine for Concept entities and is_a edges.
All state-changing operations follow strict transactional discipline:
    1. SELECT ... FOR UPDATE row lock.
    2. Validate transition (state machine + invariants).
    3. UPDATE row.
    4. INSERT audit row.
    5. INSERT outbox row.
All within a single transaction.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

import networkx as nx

from parrot.knowledge.ontology.concept_catalog.models import (
    CascadeAlert,
    ConceptRow,
    IsaEdgeRow,
)
from parrot.knowledge.ontology.exceptions import (
    CycleError,
    InvalidTransitionError,
    SynonymConflictError,
)

logger = logging.getLogger("Parrot.Ontology.ConceptCatalog")

# Valid transitions for the five-state machine.
_VALID_TRANSITIONS: dict[str, dict[str, list[str]]] = {
    "concept": {
        "submit": ["proposed"],
        "approve": ["proposed", "pending_review"],
        "reject": ["proposed", "pending_review"],
        "deprecate": ["approved"],
        "restore": ["deprecated", "rejected"],
    },
    "isa_edge": {
        "submit": ["proposed"],
        "approve": ["proposed", "pending_review"],
        "reject": ["proposed", "pending_review"],
        "deprecate": ["approved"],
        "restore": ["deprecated", "rejected"],
    },
}

_ACTION_TO_STATE: dict[str, str] = {
    "submit": "pending_review",
    "approve": "approved",
    "reject": "rejected",
    "deprecate": "deprecated",
    "restore": "proposed",
}


def _validate_transition(target_kind: str, action: str, current_state: str) -> str:
    """Validate a state machine transition and return the new state.

    Args:
        target_kind: 'concept' or 'isa_edge'.
        action: Requested action ('approve', 'reject', etc.).
        current_state: Current state of the entity.

    Returns:
        New state string after the transition.

    Raises:
        InvalidTransitionError: If the transition is not permitted.
    """
    allowed = _VALID_TRANSITIONS.get(target_kind, {}).get(action, [])
    if current_state not in allowed:
        raise InvalidTransitionError(
            f"Cannot perform '{action}' on {target_kind} in state '{current_state}'. "
            f"Allowed from: {allowed}",
            current_state=current_state,
            requested_action=action,
        )
    return _ACTION_TO_STATE[action]


class ConceptCatalogService:
    """Operational truth for per-tenant Concept entities and is_a edges.

    All state-changing calls follow strict transactional discipline:
      1. SELECT ... FOR UPDATE row lock.
      2. Validate transition (state machine + invariants).
      3. UPDATE row.
      4. INSERT audit row.
      5. INSERT outbox row.
    All within a single transaction.

    Args:
        pg_pool: asyncpg connection pool.
    """

    def __init__(self, pg_pool: Any) -> None:
        self.logger = logging.getLogger("Parrot.Ontology.ConceptCatalog")
        self._pool = pg_pool

    # ── Concept operations ──

    async def propose_concept(
        self,
        tenant_id: str,
        slug: str,
        label: str,
        asserted_by: str,
        synonyms: list[str] | None = None,
        description: str | None = None,
        domain: str | None = None,
        rationale: str | None = None,
    ) -> UUID:
        """Propose a new Concept entity.

        Args:
            tenant_id: Tenant owning this concept.
            slug: Tenant-local slug identifier.
            label: Human-readable display label.
            asserted_by: Who is asserting this concept.
            synonyms: Optional synonym list.
            description: Optional description.
            domain: Optional domain tag.
            rationale: Optional rationale.

        Returns:
            UUID of the newly created concept row.

        Raises:
            SynonymConflictError: If any synonym conflicts with an approved concept.
        """
        synonyms = synonyms or []
        now = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Check synonym collision against approved concepts.
                if synonyms:
                    await self._check_synonym_collision(conn, tenant_id, synonyms, None)

                concept_id: UUID = await conn.fetchval(
                    """
                    INSERT INTO ontology_concept
                        (tenant_id, slug, label, synonyms, description, domain,
                         state, asserted_by, rationale, effective_from)
                    VALUES ($1, $2, $3, $4, $5, $6, 'proposed', $7, $8, $9)
                    RETURNING id
                    """,
                    tenant_id, slug, label, synonyms, description, domain,
                    asserted_by, rationale, now,
                )

                await self._insert_concept_audit(
                    conn, concept_id, "concept", "propose", asserted_by,
                    before={}, after={"slug": slug, "label": label, "state": "proposed"},
                    reason=rationale,
                )
                await self._insert_concept_outbox(
                    conn, concept_id, "concept", "invalidate_cache",
                    {"tenant_id": tenant_id, "concept_id": str(concept_id)},
                )

                self.logger.info(
                    "Proposed concept '%s' (%s) for tenant '%s'",
                    slug, concept_id, tenant_id,
                )
                return concept_id

    async def propose_isa_edge(
        self,
        tenant_id: str,
        child_id: UUID,
        parent_tier: Literal["framework", "tenant"],
        parent_ref: str,
        asserted_by: str,
        rationale: str | None = None,
    ) -> UUID:
        """Propose a new is_a (sub-class) edge.

        Args:
            tenant_id: Tenant owning this edge.
            child_id: FK to ontology_concept.id (the sub-concept).
            parent_tier: 'framework' or 'tenant'.
            parent_ref: Framework concept name or tenant UUID as str.
            asserted_by: Who is asserting this edge.
            rationale: Optional rationale.

        Returns:
            UUID of the newly created isa_edge row.

        Raises:
            CycleError: If this edge would create a cycle in the is_a DAG.
            InvalidTransitionError: If parent_tier='tenant' pointing at a framework item.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Run cycle detection before inserting.
                await self._check_isa_cycle(
                    conn, tenant_id, child_id, parent_tier, parent_ref
                )

                edge_id: UUID = await conn.fetchval(
                    """
                    INSERT INTO ontology_concept_isa
                        (tenant_id, child_id, parent_tier, parent_ref, state, asserted_by, rationale)
                    VALUES ($1, $2, $3, $4, 'proposed', $5, $6)
                    RETURNING id
                    """,
                    tenant_id, child_id, parent_tier, parent_ref, asserted_by, rationale,
                )

                await self._insert_concept_audit(
                    conn, edge_id, "isa_edge", "propose", asserted_by,
                    before={},
                    after={
                        "child_id": str(child_id),
                        "parent_tier": parent_tier,
                        "parent_ref": parent_ref,
                        "state": "proposed",
                    },
                    reason=rationale,
                )
                await self._insert_concept_outbox(
                    conn, edge_id, "isa_edge", "invalidate_cache",
                    {"tenant_id": tenant_id, "edge_id": str(edge_id)},
                )

                return edge_id

    async def submit_for_review(
        self, target_id: UUID, target_kind: str, actor: str
    ) -> None:
        """Submit a proposed concept or edge for review.

        Args:
            target_id: UUID of the concept or isa_edge.
            target_kind: 'concept' or 'isa_edge'.
            actor: Who is submitting.

        Raises:
            InvalidTransitionError: If not in 'proposed' state.
        """
        await self._transition(target_id, target_kind, "submit", actor)

    async def approve(
        self,
        target_id: UUID,
        target_kind: str,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Approve a proposed or pending_review concept/edge.

        For is_a edges, runs cycle detection on approve to protect against
        concurrent proposals.

        Args:
            target_id: UUID of the concept or isa_edge.
            target_kind: 'concept' or 'isa_edge'.
            actor: Who is approving.
            reason: Optional rationale.

        Raises:
            InvalidTransitionError: If not in a state that allows approval.
            CycleError: If approving this is_a edge would create a cycle.
        """
        await self._transition(
            target_id, target_kind, "approve", actor, reason=reason
        )

    async def reject(
        self,
        target_id: UUID,
        target_kind: str,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Reject a proposed or pending_review concept/edge.

        Args:
            target_id: UUID of the concept or isa_edge.
            target_kind: 'concept' or 'isa_edge'.
            actor: Who is rejecting.
            reason: Optional rationale.
        """
        await self._transition(
            target_id, target_kind, "reject", actor, reason=reason
        )

    async def deprecate(
        self,
        target_id: UUID,
        target_kind: str,
        actor: str,
        reason: str | None = None,
    ) -> CascadeAlert | None:
        """Deprecate an approved concept or edge.

        For concepts, queries the operational topic_authority table for any
        edges referencing this concept and returns a CascadeAlert. If the
        operational table doesn't exist yet (FEAT-topic-authority-operational
        not landed), returns None.

        Args:
            target_id: UUID of the concept or isa_edge.
            target_kind: 'concept' or 'isa_edge'.
            actor: Who is deprecating.
            reason: Optional rationale.

        Returns:
            CascadeAlert if target_kind == 'concept', else None.
        """
        await self._transition(
            target_id, target_kind, "deprecate", actor, reason=reason
        )

        if target_kind != "concept":
            return None

        # Query for cascade effects in the operational service.
        return await self._build_cascade_alert(target_id)

    async def restore(
        self,
        target_id: UUID,
        target_kind: str,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Restore a deprecated or rejected concept/edge to proposed state.

        Args:
            target_id: UUID of the concept or isa_edge.
            target_kind: 'concept' or 'isa_edge'.
            actor: Who is restoring.
            reason: Optional rationale.
        """
        await self._transition(
            target_id, target_kind, "restore", actor, reason=reason
        )

    async def modify_metadata(
        self,
        concept_id: UUID,
        actor: str,
        synonyms: list[str] | None = None,
        description: str | None = None,
        domain: str | None = None,
    ) -> None:
        """Update mutable metadata on an approved concept (synonyms, description, domain).

        Slug and label are immutable after approval.

        Args:
            concept_id: UUID of the concept.
            actor: Who is making the change.
            synonyms: New synonym list (replaces existing).
            description: New description.
            domain: New domain tag.

        Raises:
            InvalidTransitionError: If concept is not in 'approved' state.
            SynonymConflictError: If new synonyms conflict with other approved concepts.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM ontology_concept WHERE id = $1 FOR UPDATE",
                    concept_id,
                )
                if not row:
                    raise ValueError(f"Concept {concept_id} not found")

                if row["state"] != "approved":
                    raise InvalidTransitionError(
                        f"modify_metadata only allowed on approved concepts, "
                        f"got state='{row['state']}'",
                        current_state=row["state"],
                        requested_action="modify_metadata",
                    )

                before: dict[str, Any] = {}
                updates: dict[str, Any] = {}

                if synonyms is not None:
                    await self._check_synonym_collision(
                        conn, row["tenant_id"], synonyms, concept_id
                    )
                    before["synonyms"] = list(row["synonyms"] or [])
                    updates["synonyms"] = synonyms

                if description is not None:
                    before["description"] = row["description"]
                    updates["description"] = description

                if domain is not None:
                    before["domain"] = row["domain"]
                    updates["domain"] = domain

                if not updates:
                    return

                set_clauses = [
                    f"{col} = ${i + 2}"
                    for i, col in enumerate(updates)
                ]
                set_clauses.append(f"updated_at = ${len(updates) + 2}")

                values = list(updates.values()) + [datetime.now(timezone.utc), concept_id]
                await conn.execute(
                    f"UPDATE ontology_concept SET {', '.join(set_clauses)} "
                    f"WHERE id = ${len(values)}",
                    *values,
                )

                await self._insert_concept_audit(
                    conn, concept_id, "concept", "modify_metadata", actor,
                    before=before, after=updates, reason=None,
                )
                await self._insert_concept_outbox(
                    conn, concept_id, "concept", "invalidate_cache",
                    {"tenant_id": row["tenant_id"], "concept_id": str(concept_id)},
                )

    # ── Query operations ──

    async def get_live_concepts(
        self,
        tenant_id: str,
        domain: str | None = None,
    ) -> list[ConceptRow]:
        """Return all approved concepts for a tenant.

        Args:
            tenant_id: Tenant to query.
            domain: Optional domain filter.

        Returns:
            List of ConceptRow objects with state='approved'.
        """
        async with self._pool.acquire() as conn:
            if domain:
                rows = await conn.fetch(
                    """
                    SELECT * FROM ontology_concept
                    WHERE tenant_id = $1 AND state = 'approved' AND domain = $2
                    ORDER BY slug
                    """,
                    tenant_id, domain,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM ontology_concept
                    WHERE tenant_id = $1 AND state = 'approved'
                    ORDER BY slug
                    """,
                    tenant_id,
                )

            return [ConceptRow(**dict(r)) for r in rows]

    async def get_isa_subgraph(
        self, tenant_id: str, concept_id: UUID
    ) -> dict[str, Any]:
        """Return the is_a ancestor/descendant subgraph for a concept.

        Args:
            tenant_id: Tenant to query.
            concept_id: Root concept UUID.

        Returns:
            Dict with 'concept_id', 'ancestors', and 'descendants' lists.
        """
        async with self._pool.acquire() as conn:
            edges = await conn.fetch(
                """
                SELECT id, child_id, parent_ref, parent_tier
                FROM ontology_concept_isa
                WHERE tenant_id = $1 AND state = 'approved'
                """,
                tenant_id,
            )

        ancestors = [
            {"edge_id": str(e["id"]), "parent_ref": e["parent_ref"], "parent_tier": e["parent_tier"]}
            for e in edges if str(e["child_id"]) == str(concept_id)
        ]
        descendants = [
            {"edge_id": str(e["id"]), "child_id": str(e["child_id"])}
            for e in edges if e["parent_ref"] == str(concept_id) and e["parent_tier"] == "tenant"
        ]

        return {
            "concept_id": str(concept_id),
            "ancestors": ancestors,
            "descendants": descendants,
        }

    async def get_history(
        self, target_id: UUID, target_kind: str
    ) -> list[dict[str, Any]]:
        """Return the audit trail for a concept or isa_edge.

        Args:
            target_id: UUID of the concept or isa_edge.
            target_kind: 'concept' or 'isa_edge'.

        Returns:
            List of audit entries ordered by occurred_at DESC.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, action, actor, diff, reason, occurred_at
                FROM ontology_concept_audit
                WHERE target_id = $1 AND target_kind = $2
                ORDER BY occurred_at DESC
                """,
                target_id, target_kind,
            )
            return [dict(r) for r in rows]

    # ── Internal helpers ──

    async def _transition(
        self,
        target_id: UUID,
        target_kind: str,
        action: str,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Execute a state machine transition within a single transaction.

        Args:
            target_id: UUID of the concept or isa_edge.
            target_kind: 'concept' or 'isa_edge'.
            action: State machine action.
            actor: Who is performing the action.
            reason: Optional rationale.
        """
        table = (
            "ontology_concept" if target_kind == "concept" else "ontology_concept_isa"
        )
        now = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"SELECT * FROM {table} WHERE id = $1 FOR UPDATE", target_id
                )
                if not row:
                    raise ValueError(f"{target_kind} {target_id} not found")

                new_state = _validate_transition(target_kind, action, row["state"])

                # For is_a edge approve: run cycle detection again.
                if target_kind == "isa_edge" and action == "approve":
                    await self._check_isa_cycle(
                        conn,
                        row["tenant_id"],
                        row["child_id"],
                        row["parent_tier"],
                        row["parent_ref"],
                        exclude_edge_id=target_id,
                    )

                # Determine outbox operation.
                outbox_op = _action_to_outbox_operation(target_kind, action)
                tenant_id = row.get("tenant_id", "")

                await conn.execute(
                    f"UPDATE {table} SET state = $1, reviewed_by = $2, "
                    f"reviewed_at = $3, rationale = COALESCE($4, rationale), "
                    f"updated_at = $3 WHERE id = $5",
                    new_state, actor, now, reason, target_id,
                )

                await self._insert_concept_audit(
                    conn, target_id, target_kind, action, actor,
                    before={"state": row["state"]},
                    after={"state": new_state},
                    reason=reason,
                )
                await self._insert_concept_outbox(
                    conn, target_id, target_kind, outbox_op,
                    {"tenant_id": tenant_id, "target_id": str(target_id)},
                )

    async def _check_synonym_collision(
        self,
        conn: Any,
        tenant_id: str,
        synonyms: list[str],
        exclude_concept_id: UUID | None,
    ) -> None:
        """Check if any synonym conflicts with an approved concept in this tenant.

        Args:
            conn: Active database connection.
            tenant_id: Tenant to search within.
            synonyms: Synonyms to check.
            exclude_concept_id: Concept to exclude from collision (for updates).

        Raises:
            SynonymConflictError: If any synonym is already owned by another concept.
        """
        query = """
            SELECT slug, synonyms FROM ontology_concept
            WHERE tenant_id = $1 AND state = 'approved'
            AND synonyms && $2
        """
        params: list[Any] = [tenant_id, synonyms]

        if exclude_concept_id:
            query += " AND id != $3"
            params.append(exclude_concept_id)

        rows = await conn.fetch(query, *params)
        if rows:
            existing = rows[0]
            # Find which synonym caused the conflict.
            existing_syns = set(existing["synonyms"] or [])
            conflict = next((s for s in synonyms if s in existing_syns), synonyms[0])
            raise SynonymConflictError(
                f"Synonym '{conflict}' already belongs to concept '{existing['slug']}'",
                synonym=conflict,
                existing_slug=existing["slug"],
            )

    async def _check_isa_cycle(
        self,
        conn: Any,
        tenant_id: str,
        child_id: UUID,
        parent_tier: str,
        parent_ref: str,
        exclude_edge_id: UUID | None = None,
    ) -> None:
        """Check that adding this is_a edge would not create a cycle.

        Builds a DiGraph from all approved + pending is_a edges for the tenant,
        adds the candidate edge, and checks for cycles using networkx.

        Args:
            conn: Active database connection.
            tenant_id: Tenant to check cycles within.
            child_id: Child concept UUID.
            parent_tier: 'framework' or 'tenant'.
            parent_ref: Parent concept reference.
            exclude_edge_id: Edge to exclude (for re-validation on approve).

        Raises:
            CycleError: If adding this edge would create a cycle.
        """
        # Only tenant-tier edges can form cycles.
        if parent_tier != "tenant":
            return

        # Fetch all active is_a edges.
        query = """
            SELECT child_id, parent_ref, parent_tier FROM ontology_concept_isa
            WHERE tenant_id = $1
            AND state IN ('proposed', 'pending_review', 'approved')
            AND parent_tier = 'tenant'
        """
        params: list[Any] = [tenant_id]
        if exclude_edge_id:
            query += " AND id != $2"
            params.append(exclude_edge_id)

        rows = await conn.fetch(query, *params)

        g: nx.DiGraph = nx.DiGraph()
        for r in rows:
            g.add_edge(str(r["child_id"]), r["parent_ref"])

        # Add candidate edge.
        g.add_edge(str(child_id), parent_ref)

        try:
            cycle = nx.find_cycle(g, orientation="original")
            cycle_path = [n for n, _, _ in cycle] + [cycle[0][0]]
            raise CycleError(
                f"Adding is_a edge {child_id} → {parent_ref} would create a cycle: "
                f"{' → '.join(cycle_path)}",
                cycle_path=cycle_path,
            )
        except nx.NetworkXNoCycle:
            pass  # No cycle — we're good.

    async def _build_cascade_alert(
        self, concept_id: UUID
    ) -> CascadeAlert | None:
        """Build a CascadeAlert for a deprecated concept.

        Queries the operational topic_authority table if it exists. Returns
        None if the table doesn't exist (FEAT-topic-authority-operational
        not yet landed).

        Args:
            concept_id: UUID of the deprecated concept.

        Returns:
            CascadeAlert or None.
        """
        async with self._pool.acquire() as conn:
            # Check if the operational table exists.
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'topic_authority'
                )
                """
            )
            if not table_exists:
                return None

            # Fetch the concept details.
            concept_row = await conn.fetchrow(
                "SELECT tenant_id, slug FROM ontology_concept WHERE id = $1",
                concept_id,
            )
            if not concept_row:
                return None

            # Query operational edges referencing this concept.
            edge_rows = await conn.fetch(
                "SELECT id FROM topic_authority WHERE concept_ref = $1",
                str(concept_id),
            )

            return CascadeAlert(
                tenant_id=concept_row["tenant_id"],
                concept_id=concept_id,
                concept_slug=concept_row["slug"],
                affected_edge_ids=[r["id"] for r in edge_rows],
                notified_at=datetime.now(timezone.utc),
            )

    @staticmethod
    async def _insert_concept_audit(
        conn: Any,
        target_id: UUID,
        target_kind: str,
        action: str,
        actor: str,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str | None,
    ) -> None:
        """Insert an audit row for a concept or isa_edge operation."""
        await conn.execute(
            """
            INSERT INTO ontology_concept_audit
                (target_id, target_kind, action, actor, diff, reason)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            target_id,
            target_kind,
            action,
            actor,
            json.dumps({"before": before, "after": after}),
            reason,
        )

    @staticmethod
    async def _insert_concept_outbox(
        conn: Any,
        target_id: UUID,
        target_kind: str,
        operation: str,
        payload: dict[str, Any],
    ) -> None:
        """Insert an outbox row for async processing."""
        await conn.execute(
            """
            INSERT INTO ontology_concept_outbox
                (target_id, target_kind, operation, payload)
            VALUES ($1, $2, $3, $4)
            """,
            target_id,
            target_kind,
            operation,
            json.dumps(payload),
        )


def _action_to_outbox_operation(target_kind: str, action: str) -> str:
    """Map a state machine action to the appropriate outbox operation."""
    if action == "approve":
        return "publish_to_graph"
    if action == "deprecate":
        return "deprecate_in_graph"
    return "invalidate_cache"
