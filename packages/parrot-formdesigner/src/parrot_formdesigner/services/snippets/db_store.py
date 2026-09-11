"""Tenant-scoped, versioned snippet store with a read-through cache.

Mirrors FormRegistry._read_through() (services/registry.py:1035): a cache
miss loads from storage and admits the result; ANY storage fault degrades
to None (logged, swallowed) rather than raising — resolve_current()'s
caller (the resolver closure, TASK-3163) treats None as "no tenant
override", which correctly falls back to the platform git snippet via
get_form_event()'s existing (tenant, ref) -> (None, ref) precedence.

See spec sdd/specs/formbuilder-custom-code.spec.md §3 Module 5.

Migration: migrations/008_snippet_store.sql (NOTE: the spec's own §3 text
says "007" — that number is stale; 007 was already taken by
007_dedupe_duplicate_field_ids.py before this feature's tasks were
written. Trust this file, not the spec prose, for the migration number.)
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from parrot_formdesigner.core.snippets import (
    CapabilityManifest,
    CapabilityTier,
    SnippetBundle,
    SnippetSource,
    SnippetStatus,
)

logger = logging.getLogger(__name__)

# Tenants explicitly allowed to publish tier BROKERED/TOOLKIT snippets.
# Non-Goal (spec §1): "Tenant snippets escalating to tiers 3-4 by default"
# is out of scope — this is the operator-controlled override.
TenantTierCapOverrides = frozenset[str]


class _ConnectionPool(Protocol):
    """Minimal asyncpg.Pool-shaped protocol — lets unit tests inject a fake."""

    async def fetchrow(self, query: str, *args: Any) -> Any | None: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def execute(self, query: str, *args: Any) -> str: ...


class DbSnippetStore:
    """Read-through cache over the `form_snippets` table (migration 008)."""

    def __init__(
        self,
        pool: _ConnectionPool,
        *,
        tier3_tier4_tenants: TenantTierCapOverrides = frozenset(),
    ) -> None:
        """
        Args:
            pool: An asyncpg-pool-shaped connection object (injected —
                never constructed here, matching FormRegistry's storage
                injection pattern).
            tier3_tier4_tenants: Tenants explicitly allowed to publish
                tier BROKERED/TOOLKIT bundles. Empty by default (spec
                Non-Goal: DB snippets capped at tier 2 unless raised).
        """
        self._pool = pool
        self._tier3_tier4_tenants = tier3_tier4_tenants
        self._cache: dict[tuple[str, str], SnippetBundle] = {}
        self.logger = logger

    def check_tier_cap(self, tenant: str, manifest: CapabilityManifest) -> None:
        """Raise if `manifest.tier` exceeds this tenant's allowed cap.

        Raises:
            ValueError: tier is BROKERED/TOOLKIT and `tenant` is not in
                `tier3_tier4_tenants`.
        """
        if manifest.tier in (CapabilityTier.BROKERED, CapabilityTier.TOOLKIT):
            if tenant not in self._tier3_tier4_tenants:
                raise ValueError(
                    f"tenant {tenant!r} is not authorized for tier={manifest.tier!r} "
                    "(DB-sourced snippets are capped at tier 2 'helpers' by default; "
                    "an operator must explicitly raise this tenant's cap)"
                )

    async def get_published(self, *, tenant: str, handler_ref: str) -> SnippetBundle | None:
        """Read-through cache lookup for the current PUBLISHED row.

        Fail-soft, mirroring FormRegistry._read_through(): any storage
        fault is logged and this returns None — never raises.
        """
        cache_key = (tenant, handler_ref)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            row = await self._pool.fetchrow(
                "SELECT * FROM form_snippets "
                "WHERE tenant = $1 AND handler_ref = $2 AND status = 'published' "
                "ORDER BY version DESC LIMIT 1",
                tenant,
                handler_ref,
            )
        except Exception:
            self.logger.error(
                "DbSnippetStore: storage fault resolving (%r, %r)",
                tenant, handler_ref, exc_info=True,
            )
            return None
        if row is None:
            return None
        # Map asyncpg.Record-shaped row to SnippetBundle. The row's columns
        # match the migration's table definition (008_snippet_store.sql).
        bundle: SnippetBundle = SnippetBundle(
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
        self._cache[cache_key] = bundle
        return bundle

    async def resolve_current(
        self, *, tenant: str | None, handler_ref: str
    ) -> SnippetBundle | None:
        """SnippetSourceProtocol implementation.

        `tenant=None` never resolves here — DB snippets are always
        tenant-scoped by construction; a None tenant is a caller bug.
        """
        if tenant is None:
            return None
        return await self.get_published(tenant=tenant, handler_ref=handler_ref)

    def invalidate(self, *, tenant: str, handler_ref: str) -> None:
        """Drop this key from the PER-PROCESS cache after a publish/revoke.

        FILL IN: cross-process invalidation under multi-worker gunicorn is
        an explicit "decision deferred to implementation" (spec §8) — this
        method only handles the current process. TASK-3166 (approval
        service) must call this after every publish/revoke; a follow-up
        task should add the cross-process broadcast (listen/notify, TTL,
        or explicit fan-out) once a deployment topology is chosen.
        """
        self._cache.pop((tenant, handler_ref), None)

    async def on_startup(self, app: Any) -> None:
        """aiohttp on_startup — mirrors FormRegistry.on_startup (registry.py:711)."""
        self.logger.info("DbSnippetStore: ready")

    async def on_shutdown(self, app: Any) -> None:
        """aiohttp on_shutdown — mirrors FormRegistry.on_shutdown (registry.py:750)."""
        self._cache.clear()
