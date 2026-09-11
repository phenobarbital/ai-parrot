"""Tenant snippet approval service (FEAT-459 / M6).

Draft -> published -> revoked lifecycle for DB-sourced snippets, mirroring
FormVersionService.publish()/.get_published()/.list_versions()
(services/form_version.py:306,431,480) adapted onto the form_snippets
table (migrations/008_snippet_store.sql, TASK-3165).

This is the C4 human-approval gate for the DB source: publish() refuses
any bundle that fails the conformance gate (TASK-3175, injected as
`ConformanceCheckFn` to avoid a hard dependency on that module's exact
API while it is still being written — spec's Worktree Strategy prefers a
minimal M15 stub landing early over blocking this task).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from parrot_formdesigner.core.snippets import (
    CapabilityManifest,
    SnippetBundle,
    SnippetSource,
    SnippetStatus,
)
from parrot_formdesigner.services.snippets.db_store import DbSnippetStore

logger = logging.getLogger(__name__)


class ConformanceResult(Protocol):
    """Shape TASK-3175's gate result must satisfy — duck-typed, not imported."""

    passed: bool
    errors: list[str]


ConformanceCheckFn = Callable[[SnippetBundle], Awaitable[ConformanceResult]]


class SnippetApprovalService:
    """Draft/publish/revoke lifecycle for DB-sourced tenant snippets."""

    def __init__(
        self,
        store: DbSnippetStore,
        *,
        check_conformance: ConformanceCheckFn,
    ) -> None:
        """
        Args:
            store: The DbSnippetStore owning `form_snippets` reads/cache.
            check_conformance: Runs TASK-3175's tier-conformance +
                equivalence gate against a bundle. Injected so this
                service has no import-time dependency on
                scripts/check_snippet_conformance.py.
        """
        self._store = store
        self._check_conformance = check_conformance
        self.logger = logger

    async def draft(self, bundle: SnippetBundle, *, tenant: str) -> SnippetBundle:
        """Insert a new DRAFT version for (tenant, bundle.handler_ref).

        Does NOT run the conformance gate — a draft is allowed to be
        broken; only publish() enforces conformance (an author should be
        able to save work-in-progress).

        Returns:
            The bundle as stored, with `status=DRAFT` and its assigned
            `version` (current max version for this key, plus one).

        Raises:
            ValueError: `bundle.tenant != tenant`, or `bundle.source` is
                not DB (a GIT bundle has no draft concept).
        """
        if bundle.source != SnippetSource.DB:
            raise ValueError("only DB-sourced bundles can be drafted")
        if bundle.tenant != tenant:
            raise ValueError(f"bundle tenant {bundle.tenant!r} does not match expected tenant {tenant!r}")

        # Compute next version = 1 + max(existing version for (tenant, handler_ref) across ALL statuses, or 0 if none)
        row = await self._store._pool.fetchrow(
            "SELECT COALESCE(MAX(version), 0) as max_v FROM form_snippets WHERE tenant = $1 AND handler_ref = $2",
            tenant,
            bundle.handler_ref,
        )
        next_version = 1
        if row and row["max_v"] is not None:
            next_version = row["max_v"] + 1

        # Insert a row with status='draft'
        manifest_json = bundle.manifest.model_dump_json()
        event_val = bundle.event.value if hasattr(bundle.event, "value") else str(bundle.event)
        await self._store._pool.execute(
            """
            INSERT INTO form_snippets (
                tenant, handler_ref, event, version, status, manifest,
                python_source, python_sha256, client_source, client_sha256,
                approved_by, approved_at
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12)
            """,
            tenant,
            bundle.handler_ref,
            event_val,
            next_version,
            SnippetStatus.DRAFT.value,
            manifest_json,
            bundle.python_source,
            bundle.python_sha256,
            bundle.client_source,
            bundle.client_sha256,
            None,
            None,
        )

        # Return the bundle as stored
        stored_bundle = bundle.model_copy(
            update={
                "status": SnippetStatus.DRAFT,
                "version": next_version,
                "approved_by": None,
                "approved_at": None,
            }
        )
        return stored_bundle

    async def publish(self, *, tenant: str, handler_ref: str, version: int, approved_by: str) -> SnippetBundle:
        """Promote a DRAFT version to PUBLISHED. The C4 human-approval gate.

        Order of checks (all must pass before ANY row mutation):
        1. The (tenant, handler_ref, version) row exists and is DRAFT.
        2. `check_conformance(bundle)` passes.
        3. `store.check_tier_cap(tenant, bundle.manifest)` does not raise.

        Steps after checks pass:
        4. UPDATE the row: status='published', approved_by, approved_at=now().
        5. `store.invalidate(tenant=tenant, handler_ref=handler_ref)` so the
           NEXT resolve_current() call re-reads storage instead of serving
           a stale cached (possibly-absent) entry.

        Raises:
            ValueError: row not found, not DRAFT, fails conformance, or
                fails the tier cap. The error message MUST name which
                check failed (approvers and CI logs both depend on this).
        """
        # 1. Fetch the target row
        row = await self._store._pool.fetchrow(
            "SELECT * FROM form_snippets WHERE tenant = $1 AND handler_ref = $2 AND version = $3",
            tenant,
            handler_ref,
            version,
        )
        if row is None:
            raise ValueError(f"Snippet version {version} not found for tenant {tenant!r}, handler_ref {handler_ref!r}")

        if row["status"] != SnippetStatus.DRAFT.value:
            raise ValueError(f"Snippet version {version} is not in DRAFT status (current status: {row['status']!r})")

        # Map row to SnippetBundle to run checks
        bundle = SnippetBundle(
            source=SnippetSource.DB,
            status=SnippetStatus(row["status"]),
            version=row["version"],
            approved_by=row["approved_by"],
            approved_at=row["approved_at"],
            handler_ref=row["handler_ref"],
            event=row["event"],
            tenant=row["tenant"],
            manifest=CapabilityManifest.model_validate(row["manifest"]),
            python_source=row["python_source"],
            python_sha256=row["python_sha256"],
            client_source=row["client_source"],
            client_sha256=row["client_sha256"],
        )

        # 2. Run conformance check
        conformance_res = await self._check_conformance(bundle)
        if not conformance_res.passed:
            errors_str = ", ".join(conformance_res.errors)
            raise ValueError(f"Snippet failed conformance check: {errors_str}")

        # 3. Run tier cap check
        self._store.check_tier_cap(tenant, bundle.manifest)

        # 4. UPDATE the row
        now = datetime.now(UTC)
        await self._store._pool.execute(
            """
            UPDATE form_snippets
            SET status = $1, approved_by = $2, approved_at = $3
            WHERE tenant = $4 AND handler_ref = $5 AND version = $6
            """,
            SnippetStatus.PUBLISHED.value,
            approved_by,
            now,
            tenant,
            handler_ref,
            version,
        )

        # 5. Invalidate cache
        self._store.invalidate(tenant=tenant, handler_ref=handler_ref)

        # Return updated bundle
        return bundle.model_copy(
            update={
                "status": SnippetStatus.PUBLISHED,
                "approved_by": approved_by,
                "approved_at": now,
            }
        )

    async def revoke(self, *, tenant: str, handler_ref: str, version: int) -> None:
        """Set a PUBLISHED (or DRAFT) row to REVOKED and invalidate the cache.

        After revocation, get_form_event()'s existing tenant -> global
        fallback (event_registry.py:149) restores the platform git
        snippet for this tenant with NO code change here — that is the
        existing registry's job, not this service's.
        """
        await self._store._pool.execute(
            """
            UPDATE form_snippets
            SET status = $1
            WHERE tenant = $2 AND handler_ref = $3 AND version = $4
            """,
            SnippetStatus.REVOKED.value,
            tenant,
            handler_ref,
            version,
        )
        self._store.invalidate(tenant=tenant, handler_ref=handler_ref)

    async def get_published(self, *, tenant: str, handler_ref: str) -> SnippetBundle | None:
        """Convenience passthrough to the store's read-through cache."""
        return await self._store.get_published(tenant=tenant, handler_ref=handler_ref)

    async def list_versions(self, *, tenant: str, handler_ref: str) -> list[SnippetBundle]:
        """All versions (any status) for (tenant, handler_ref), newest first."""
        rows = await self._store._pool.fetch(
            "SELECT * FROM form_snippets WHERE tenant = $1 AND handler_ref = $2 ORDER BY version DESC",
            tenant,
            handler_ref,
        )
        bundles = []
        for row in rows:
            bundles.append(
                SnippetBundle(
                    source=SnippetSource.DB,
                    status=SnippetStatus(row["status"]),
                    version=row["version"],
                    approved_by=row["approved_by"],
                    approved_at=row["approved_at"],
                    handler_ref=row["handler_ref"],
                    event=row["event"],
                    tenant=row["tenant"],
                    manifest=CapabilityManifest.model_validate(row["manifest"]),
                    python_source=row["python_source"],
                    python_sha256=row["python_sha256"],
                    client_source=row["client_source"],
                    client_sha256=row["client_sha256"],
                )
            )
        return bundles
