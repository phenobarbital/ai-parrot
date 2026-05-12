"""Schema Overlay Service (FEAT-159 TASK-1095).

Sole SQL writer for ``ontology_schema_overlay``, ``ontology_schema_audit``, and
``ontology_schema_outbox``.  Implements the five-state machine with a mandatory
dry-run gate on every ``approve`` call.

State machine
--------------
::

    proposed ──[submit]──→ pending_review ──[approve]──→ approved ──[deprecate]──→ deprecated
         ↑                      ↓ [reject]                                 ↑
         └──────────────────── rejected ←──────────────────────────────────┘
                                 │ [restore]
                                 └──────────────────→ proposed

Mandatory dry-run gate
-----------------------
``approve`` always calls ``dry_run_overlay()`` before updating state.
If the dry-run fails, state stays at ``pending_review``, the
``dry_run_report`` column is updated, and ``DryRunFailedError`` is raised.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from parrot.knowledge.ontology.exceptions import (
    DryRunFailedError,
    InvalidTransitionError,
)
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema_overlay.models import DryRunReport, SchemaOverlayRow
from parrot.knowledge.ontology.schema_overlay.validator import dry_run_overlay
from parrot.knowledge.ontology.tenant import TenantOntologyManager

# Fields accepted by SchemaOverlayRow — used to strip extra DB columns
_OVERLAY_ROW_FIELDS = frozenset(SchemaOverlayRow.model_fields.keys())

# ── State machine ─────────────────────────────────────────────────────────────

_VALID_TRANSITIONS: dict[str, dict[str, str]] = {
    "proposed": {
        "submit": "pending_review",
        "approve": "approved",
        "reject": "rejected",
    },
    "pending_review": {
        "approve": "approved",
        "reject": "rejected",
    },
    "approved": {
        "deprecate": "deprecated",
    },
    "deprecated": {
        "restore": "proposed",
    },
    "rejected": {
        "restore": "proposed",
    },
}


def _validate_transition(action: str, current_state: str) -> str:
    """Return the next state or raise ``InvalidTransitionError``.

    Args:
        action: Requested action (``approve``, ``reject``, etc.).
        current_state: Current overlay state.

    Returns:
        Next state string.

    Raises:
        InvalidTransitionError: If the transition is not allowed.
    """
    allowed = _VALID_TRANSITIONS.get(current_state, {})
    next_state = allowed.get(action)
    if next_state is None:
        raise InvalidTransitionError(
            f"Action '{action}' is not allowed from state '{current_state}'.",
            current_state=current_state,
            requested_action=action,
        )
    return next_state


# ── Service class ─────────────────────────────────────────────────────────────

class SchemaOverlayService:
    """Operational truth for per-tenant schema overlays.

    Args:
        pg_pool: asyncpg connection pool.
        tenant_manager: ``TenantOntologyManager`` for dry-run YAML resolution.
        merger: ``OntologyMerger`` instance used in dry-runs.
    """

    def __init__(
        self,
        pg_pool: Any,
        tenant_manager: TenantOntologyManager,
        merger: OntologyMerger,
    ) -> None:
        self._pool = pg_pool
        self._tenant_manager = tenant_manager
        self._merger = merger
        self.logger = logging.getLogger("Parrot.Ontology.SchemaOverlay")

    # ── Proposal ─────────────────────────────────────────────────────────────

    async def propose(
        self,
        tenant_id: str,
        overlay_kind: str,
        name: str,
        definition: dict[str, Any],
        asserted_by: str,
        rationale: str | None = None,
    ) -> UUID:
        """Create a new schema overlay in ``proposed`` state.

        Args:
            tenant_id: Owning tenant.
            overlay_kind: One of ``entity_type``, ``relation_type``,
                ``traversal_pattern``.
            name: Unique name for the overlay item.
            definition: JSONB definition dict.
            asserted_by: Identity of the proposer.
            rationale: Optional free-text reason.

        Returns:
            UUID of the newly created overlay row.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                overlay_id: UUID = await conn.fetchval(
                    """
                    INSERT INTO ontology_schema_overlay
                        (tenant_id, overlay_kind, name, definition, state, asserted_by, rationale)
                    VALUES
                        ($1, $2, $3, $4::jsonb, 'proposed', $5, $6)
                    RETURNING id
                    """,
                    tenant_id,
                    overlay_kind,
                    name,
                    json.dumps(definition),
                    asserted_by,
                    rationale,
                )
                await self._insert_audit(
                    conn, overlay_id, "propose", None, "proposed", asserted_by
                )
                await self._insert_outbox(
                    conn, overlay_id, tenant_id, "invalidate_cache"
                )
                self.logger.info(
                    "Proposed schema overlay '%s' (%s) for tenant '%s'.",
                    name, overlay_kind, tenant_id,
                )
                return overlay_id

    # ── Submit for review ─────────────────────────────────────────────────────

    async def submit(self, overlay_id: UUID, actor: str) -> None:
        """Transition overlay to ``pending_review``.

        Args:
            overlay_id: UUID of the overlay row.
            actor: Identity of the submitter.
        """
        await self._transition(overlay_id, "submit", actor)

    # ── Approve (mandatory dry-run gate) ──────────────────────────────────────

    async def approve(
        self,
        overlay_id: UUID,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Approve a schema overlay — dry-run gate is mandatory.

        The dry-run runs *outside* the transaction so it can read the live YAML
        chain without holding locks. If it fails, the row's ``dry_run_report``
        column is updated inside a separate transaction and
        ``DryRunFailedError`` is raised.

        Args:
            overlay_id: UUID of the overlay to approve.
            actor: Identity of the reviewer.
            reason: Optional approval rationale.

        Raises:
            DryRunFailedError: If the dry-run validation fails.
            InvalidTransitionError: If the current state does not allow approve.
        """
        # C5 fix: Three-phase approve to avoid TOCTOU and long-lock during dry-run.
        # Phase 1: Read (no lock — just check existence and initial state).
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM ontology_schema_overlay WHERE id = $1",
                overlay_id,
            )
        if row is None:
            raise KeyError(f"SchemaOverlay {overlay_id} not found.")

        overlay = SchemaOverlayRow(**{k: v for k, v in dict(row).items() if k in _OVERLAY_ROW_FIELDS})
        _validate_transition("approve", overlay.state)

        # Phase 2: Mandatory dry-run — outside any DB connection (read-only, YAML-based).
        report: DryRunReport = await dry_run_overlay(
            overlay.tenant_id, overlay, self._tenant_manager, self._merger
        )

        if not report.ok:
            # Store report and raise without committing state change.
            async with self._pool.acquire() as conn2:
                async with conn2.transaction():
                    await conn2.execute(
                        "UPDATE ontology_schema_overlay "
                        "SET dry_run_report = $1::jsonb WHERE id = $2",
                        report.model_dump_json(),
                        overlay_id,
                    )
            raise DryRunFailedError(
                "Dry-run validation failed — overlay not approved.",
                report=report.model_dump(),
            )

        # Phase 3: Re-validate under lock and commit state change atomically.
        async with self._pool.acquire() as conn3:
            async with conn3.transaction():
                locked = await conn3.fetchrow(
                    "SELECT state FROM ontology_schema_overlay "
                    "WHERE id = $1 FOR UPDATE",
                    overlay_id,
                )
                if locked is None:
                    raise KeyError(f"SchemaOverlay {overlay_id} disappeared before approval.")
                # Re-check: another worker may have changed state since Phase 1.
                _validate_transition("approve", locked["state"])

                await conn3.execute(
                    """
                    UPDATE ontology_schema_overlay
                    SET state = 'approved',
                        reviewed_by = $1,
                        reviewed_at = now(),
                        rationale = COALESCE($2, rationale),
                        dry_run_report = $3::jsonb
                    WHERE id = $4
                    """,
                    actor,
                    reason,
                    report.model_dump_json(),
                    overlay_id,
                )
                await self._insert_audit(
                    conn3, overlay_id, "approve", overlay.state, "approved", actor
                )
                # S7 fix: emit outbox row so the pub/sub subscriber is notified.
                await self._insert_outbox(
                    conn3, overlay_id, overlay.tenant_id, "invalidate_cache"
                )
                self.logger.info(
                    "Approved schema overlay %s for tenant '%s' by '%s'.",
                    overlay_id, overlay.tenant_id, actor,
                )

    # ── Reject ────────────────────────────────────────────────────────────────

    async def reject(
        self,
        overlay_id: UUID,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Reject an overlay from proposed or pending_review.

        Args:
            overlay_id: UUID of the overlay.
            actor: Identity of the reviewer.
            reason: Optional rejection rationale.
        """
        await self._transition(overlay_id, "reject", actor, reason=reason)

    # ── Deprecate ─────────────────────────────────────────────────────────────

    async def deprecate(
        self,
        overlay_id: UUID,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Deprecate an approved overlay.

        Args:
            overlay_id: UUID of the overlay.
            actor: Identity of the actor.
            reason: Optional rationale.
        """
        await self._transition(overlay_id, "deprecate", actor, reason=reason)

    # ── Restore ───────────────────────────────────────────────────────────────

    async def restore(self, overlay_id: UUID, actor: str) -> None:
        """Restore a deprecated or rejected overlay to proposed.

        Args:
            overlay_id: UUID of the overlay.
            actor: Identity of the actor.
        """
        await self._transition(overlay_id, "restore", actor)

    # ── Queries ───────────────────────────────────────────────────────────────

    async def get_pending(self, tenant_id: str) -> list[SchemaOverlayRow]:
        """Return overlay rows in ``proposed`` or ``pending_review`` state.

        Args:
            tenant_id: Tenant to filter by.

        Returns:
            List of ``SchemaOverlayRow`` instances.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ontology_schema_overlay "
                "WHERE tenant_id = $1 AND state IN ('proposed', 'pending_review') "
                "ORDER BY created_at",
                tenant_id,
            )
            return [SchemaOverlayRow(**{k: v for k, v in dict(r).items() if k in _OVERLAY_ROW_FIELDS}) for r in rows]

    async def get_overlay_by_id(
        self, tenant_id: str, overlay_id: UUID
    ) -> SchemaOverlayRow | None:
        """Fetch a single schema overlay by primary key, scoped to tenant.

        S4 fix: efficient single-row lookup used by HTTP handlers instead of
        fetching all overlays and filtering in Python.

        Args:
            tenant_id: Owning tenant (used for access scoping).
            overlay_id: UUID primary key.

        Returns:
            ``SchemaOverlayRow`` if found, else None.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM ontology_schema_overlay "
                "WHERE id = $1 AND tenant_id = $2",
                overlay_id,
                tenant_id,
            )
            if row is None:
                return None
            return SchemaOverlayRow(
                **{k: v for k, v in dict(row).items() if k in _OVERLAY_ROW_FIELDS}
            )

    async def get_approved(self, tenant_id: str) -> list[SchemaOverlayRow]:
        """Return overlay rows in ``approved`` state for ontology composition.

        C6 fix: ``get_pending`` intentionally excludes approved rows. This method
        is for callers (such as ``TenantOntologyManager.resolve_with_overlay``)
        that need the approved overlays to compose into the merged ontology.

        Args:
            tenant_id: Tenant to filter by.

        Returns:
            List of approved ``SchemaOverlayRow`` instances.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ontology_schema_overlay "
                "WHERE tenant_id = $1 AND state = 'approved' "
                "ORDER BY created_at",
                tenant_id,
            )
            return [SchemaOverlayRow(**{k: v for k, v in dict(r).items() if k in _OVERLAY_ROW_FIELDS}) for r in rows]

    async def get_history(self, overlay_id: UUID) -> list[dict[str, Any]]:
        """Return the audit trail for an overlay, newest first.

        Args:
            overlay_id: UUID of the overlay.

        Returns:
            List of audit record dicts.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ontology_schema_audit "
                "WHERE overlay_id = $1 "
                "ORDER BY occurred_at DESC",
                overlay_id,
            )
            return [dict(r) for r in rows]

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _transition(
        self,
        overlay_id: UUID,
        action: str,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Generic state transition helper (no dry-run gate).

        Args:
            overlay_id: UUID of the overlay.
            action: Action name (``submit``, ``reject``, ``deprecate``,
                ``restore``).
            actor: Identity of the actor.
            reason: Optional rationale.
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM ontology_schema_overlay "
                    "WHERE id = $1 FOR UPDATE",
                    overlay_id,
                )
                if row is None:
                    raise KeyError(f"SchemaOverlay {overlay_id} not found.")

                current_state = row["state"]
                next_state = _validate_transition(action, current_state)

                await conn.execute(
                    """
                    UPDATE ontology_schema_overlay
                    SET state = $1,
                        reviewed_by = CASE WHEN $2 IN ('reject','deprecate','restore')
                                          THEN $3 ELSE reviewed_by END,
                        reviewed_at = CASE WHEN $2 IN ('reject','deprecate','restore')
                                          THEN now() ELSE reviewed_at END,
                        rationale = COALESCE($4, rationale)
                    WHERE id = $5
                    """,
                    next_state, action, actor, reason, overlay_id,
                )
                await self._insert_audit(
                    conn, overlay_id, action, current_state, next_state, actor
                )
                if action in ("deprecate", "restore"):
                    await self._insert_outbox(
                        conn, overlay_id, row["tenant_id"], "invalidate_cache"
                    )
                self.logger.info(
                    "Schema overlay %s: %s → %s (by %s).",
                    overlay_id, current_state, next_state, actor,
                )

    async def _insert_audit(
        self,
        conn: Any,
        overlay_id: UUID,
        action: str,
        from_state: str | None,
        to_state: str,
        actor: str,
    ) -> None:
        diff = json.dumps({"before": from_state, "after": to_state})
        await conn.execute(
            """
            INSERT INTO ontology_schema_audit
                (overlay_id, action, from_state, to_state, actor, diff)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            overlay_id, action, from_state, to_state, actor, diff,
        )

    async def _insert_outbox(
        self,
        conn: Any,
        overlay_id: UUID,
        tenant_id: str,
        operation: str,
    ) -> None:
        payload = json.dumps({"overlay_id": str(overlay_id)})
        await conn.execute(
            """
            INSERT INTO ontology_schema_outbox
                (tenant_id, operation, payload)
            VALUES ($1, $2, $3::jsonb)
            """,
            tenant_id, operation, payload,
        )
