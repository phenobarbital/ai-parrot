# TASK-3165: Tenant snippet DB store & migration — `services/snippets/db_store.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-3161, TASK-3163
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. This is the tenant-scoped half of the hybrid dual-source
model (OQ-1): a versioned Postgres table for tenant-specific snippets,
approved in-app rather than by PR. It implements `SnippetSourceProtocol`
(TASK-3163) with a **read-through cache**, modeled directly on
`FormRegistry._read_through()` (`services/registry.py:1035`) — a cache
miss loads from storage and admits the result, fail-soft (never raises;
degrades to the pre-lookup answer).

DB snippets are capped at tier 2 (`helpers`) by default — tiers 3-4 remain
a platform-operator concern (Non-Goal, spec §1). This task enforces that
cap; TASK-3166 (approval service) is what actually gates publishing.

**Migration numbering note**: the spec's contract (verified 2026-08-24)
says "007 is next" — that is now **stale**. `migrations/` currently ends at
`007_dedupe_duplicate_field_ids.py` (verified at task-writing time,
2026-09-11). This task's migration is **`008_snippet_store.sql`**, not
`007_snippet_store.sql` as the spec text says. Trust this task file's
number, not the spec's.

---

## Scope

- Write `packages/parrot-formdesigner/migrations/008_snippet_store.sql` —
  a standalone, idempotent SQL script (no migration framework exists in
  this package — see `migrations/README.md`) creating the versioned
  tenant-snippet table.
- Implement `DbSnippetStore` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/db_store.py`:
  a read-through cache over that table, implementing
  `SnippetSourceProtocol.resolve_current()`, plus `on_startup`/`on_shutdown`
  hooks mirroring `FormRegistry.on_startup`/`on_shutdown`
  (`services/registry.py:711,750`).
- Enforce the tier-2 cap: `DbSnippetStore` refuses (raises) any write
  attempt for a bundle declaring tier `brokered`/`toolkit` unless the
  tenant is in an explicit operator-configured allowlist.
- Write `packages/parrot-formdesigner/tests/unit/test_db_snippet_store.py`
  (against an in-memory fake pool/connection — no live Postgres required
  for unit tests, matching this package's existing unit-test convention;
  a live-DB integration test is optional and out of scope for this task).

**NOT in scope**: the approval workflow / draft→published transitions
(TASK-3166 — this task's store is a dumb versioned table + cache; TASK-3166
is what decides *when* a row's status changes); any registration call
(the DB store implements `SnippetSourceProtocol` but does NOT call
`register_resolver()` itself — the server-boot wiring code that calls it
once per tenant/handler_ref combination is out of scope for both this task
and TASK-3166, and belongs to whatever future task wires server startup,
noted as a gap in Completion Notes if not otherwise covered).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/migrations/008_snippet_store.sql` | CREATE | Versioned tenant-snippet table |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/db_store.py` | CREATE | `DbSnippetStore` |
| `packages/parrot-formdesigner/tests/unit/test_db_snippet_store.py` | CREATE | Unit tests against a fake pool |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.snippets import (
    CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource, SnippetStatus,
)  # TASK-3161
from parrot_formdesigner.services.snippets.base import SnippetSourceProtocol  # TASK-3163
```

### Existing Signatures to Use — read-through cache pattern
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:                                          # line 240
    async def on_startup(self, app: "web.Application") -> None:   # line 711
        # Calls storage.initialize() if present, then load_from_storage().
        # Early-returns (no raise) when no storage is configured.
    async def on_shutdown(self, app: "web.Application") -> None:  # line 750
        # Calls storage.close() to release backend-held resources.
    async def _read_through(                                 # line 1035
        self, resolved: str, *, form_uid: uuid.UUID | None = None,
        form_id: str | None = None,
    ) -> FormSchema | None:
        # Fail-soft: a lookup degrades to None on ANY storage fault
        # (logged, swallowed), never raises. Every caller already treats
        # None as "not found" — this is the exact contract DbSnippetStore
        # must replicate for resolve_current().

class FormStorage(ABC):                                      # line 63 — storage ABC precedent
    ...
```

### Migration file convention (verified against `migrations/` at task-writing time)
```
packages/parrot-formdesigner/migrations/
    001_add_form_uid.sql
    002_add_form_uid_submissions.sql
    003_migrate_form_data.py
    004_form_uid_uuid_type.sql
    005_question_bank_question_id.sql
    006_backfill_element_uids.py
    007_dedupe_duplicate_field_ids.py   <- latest as of 2026-09-11
    008_snippet_store.sql                <- THIS TASK (spec text says 007 — stale, see Context)
```
No migration framework (no Alembic, no schema-version table) — plain
standalone scripts, run once manually per physical Postgres schema
(`migrations/README.md`). Mixed `.sql`/`.py` numbering is the existing
convention; a pure-SQL `.sql` file (no data backfill needed) is
appropriate here since this is a brand-new table, not a transform of
existing rows.

### Does NOT Exist
- ~~A snippet table or migration~~ — does not exist; this task creates
  the first one, as `008_snippet_store.sql` (not `007` — see Context).
- ~~`services/snippets/db_store.py`~~ — created by this task.
- ~~`SnippetApprovalService`~~ — TASK-3166 creates it; this task's store
  has no publish/draft transition methods of its own beyond plain
  row reads/writes used internally.
- ~~A generic migration framework (Alembic, etc.)~~ — not used anywhere
  in `parrot-formdesigner`; do not introduce one for this table.

---

## Implementation Notes

### Key Constraints
- `resolve_current()` must be **fail-soft**, exactly like
  `FormRegistry._read_through()`: a storage fault logs and returns
  `None`, never raises. A snippet resolver treating "DB is down" as "no
  tenant override" (falling back to the platform git snippet via
  `get_form_event()`'s existing precedence) is the correct degraded
  behavior, not a 500.
- The tier-2 cap check happens on **write** (publish/draft-insert), not on
  read — `resolve_current()` trusts that anything already PUBLISHED in the
  table already passed the cap check. Do not re-validate tier on every
  read; that duplicates TASK-3166's job and doubles the hot-path cost.
- Cache invalidation is **per-process** (spec §7 "Cache coherence across
  processes" risk) — a `republish()`/`invalidate()` method must exist so
  TASK-3166 can call it after a successful publish, but multi-process
  broadcast (gunicorn `-w N`) is explicitly a "decision deferred to
  implementation" (spec §8) — implement the simplest per-process
  invalidation and leave a `# FILL IN` note for the cross-process
  mechanism rather than guessing one.
- `asyncpg` is already a dependency pattern in this package (see
  `migrations/003_migrate_form_data.py`) — use it for the store's actual
  Postgres access, but keep the connection/pool as an injected parameter
  (constructor arg) so unit tests can pass a fake.

### References in Codebase
- `services/registry.py:1035` — `_read_through()`, the fail-soft pattern
  to replicate exactly.
- `services/registry.py:711,750` — `on_startup`/`on_shutdown` shape.
- `migrations/006_backfill_element_uids.py` or `007_dedupe_duplicate_field_ids.py`
  — read one for this package's actual `asyncpg` connection-acquisition
  style before writing the store's queries.

---

## Implementation Blueprint

### Steps (in order)
1. Write the migration SQL — *why*: the store's queries are written
   against this exact schema, so the schema must be fixed first.
2. Implement `DbSnippetStore.__init__`, `get_published()` (the read-through
   core), and `resolve_current()` (thin wrapper matching
   `SnippetSourceProtocol`).
3. Implement `invalidate()` and the tier-cap check used by writes.
4. Implement `on_startup`/`on_shutdown`.
5. Write tests against a fake pool.

### `packages/parrot-formdesigner/migrations/008_snippet_store.sql` (CREATE)
```sql
-- FEAT-459 / TASK-3165: versioned tenant-scoped snippet store.
-- Run once per physical Postgres schema, same convention as
-- 001-007 (see migrations/README.md). Idempotent via IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS form_snippets (
    id              BIGSERIAL PRIMARY KEY,
    tenant          TEXT NOT NULL,
    handler_ref     TEXT NOT NULL,
    event           TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'published', 'revoked')),
    manifest        JSONB NOT NULL,
    python_source   TEXT NOT NULL,
    python_sha256   TEXT NOT NULL,
    client_source   TEXT,
    client_sha256   TEXT,
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One row per (tenant, handler_ref, version) — republishing INSERTS a
    -- new version row rather than mutating history (audit trail, spec §7
    -- "Two audit trails" risk).
    UNIQUE (tenant, handler_ref, version)
);

-- Fast path for resolve_current(): "the currently published row for this
-- (tenant, handler_ref)". Partial index — only PUBLISHED rows matter here.
CREATE INDEX IF NOT EXISTS ix_form_snippets_published_lookup
    ON form_snippets (tenant, handler_ref)
    WHERE status = 'published';
```
**Why this shape**: append-only versioning (never `UPDATE` a published
row) gives the "two audit trails" requirement for free — every version a
tenant admin ever published stays queryable. The partial index keeps the
hot read path (`resolve_current`) cheap even as draft/revoked history
accumulates.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/db_store.py` (CREATE)
```python
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
        # FILL IN: map `row` (asyncpg.Record-shaped) to a SnippetBundle —
        #   bounded by the migration's column list above; construct
        #   CapabilityManifest.model_validate(row["manifest"]) since the
        #   column is JSONB (already deserialised by asyncpg's default
        #   codec, or via json.loads if the pool does not auto-decode).
        bundle: SnippetBundle = ...  # type: ignore[assignment]
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
```
**Why this shape**: `check_tier_cap` is a separate public method (not
buried inside a write path) so TASK-3166's approval service can call it
before ever inserting a draft row — the cap is enforced at the earliest
point data enters the table, not only at publish time. `invalidate()` is
intentionally narrow (per-process only) with the cross-process gap called
out explicitly rather than papered over, since guessing a broadcast
mechanism not yet chosen (spec §8) would be worse than an honest FILL IN.

### `packages/parrot-formdesigner/tests/unit/test_db_snippet_store.py` (CREATE)
```python
"""Unit tests for DbSnippetStore — FEAT-459 / TASK-3165 (fake pool, no live DB)."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier
from parrot_formdesigner.services.snippets.db_store import DbSnippetStore


class _FakePool:
    def __init__(self, row: dict | None = None, *, raise_on_fetch: bool = False) -> None:
        self._row = row
        self._raise_on_fetch = raise_on_fetch
        self.fetchrow_calls = 0

    async def fetchrow(self, query, *args):
        self.fetchrow_calls += 1
        if self._raise_on_fetch:
            raise ConnectionError("db unreachable")
        return self._row

    async def fetch(self, query, *args):
        return []

    async def execute(self, query, *args):
        return "OK"


def test_tier_cap_denies_brokered_by_default() -> None:
    store = DbSnippetStore(_FakePool())
    with pytest.raises(ValueError, match="capped at tier 2"):
        store.check_tier_cap("acme", CapabilityManifest(tier=CapabilityTier.BROKERED))


def test_tier_cap_allows_when_tenant_overridden() -> None:
    store = DbSnippetStore(_FakePool(), tier3_tier4_tenants=frozenset({"acme"}))
    store.check_tier_cap("acme", CapabilityManifest(tier=CapabilityTier.BROKERED))  # no raise


def test_tier_cap_allows_helpers_for_any_tenant() -> None:
    # FILL IN: check_tier_cap("any-tenant", CapabilityManifest(tier=CapabilityTier.HELPERS))
    #   does not raise — tier 2 is the default-allowed ceiling
    pass


async def test_db_store_read_through_cache() -> None:
    # FILL IN: construct a fake row dict matching the migration's columns,
    #   call get_published() twice, assert the second call does NOT hit
    #   pool.fetchrow again (fetchrow_calls stays at 1) — bounded by the
    #   read-through cache contract.
    pass


async def test_resolve_current_fails_soft_on_storage_error() -> None:
    store = DbSnippetStore(_FakePool(raise_on_fetch=True))
    result = await store.resolve_current(tenant="acme", handler_ref="x.onBeforeSubmit")
    assert result is None


async def test_resolve_current_returns_none_for_global_tenant() -> None:
    store = DbSnippetStore(_FakePool())
    result = await store.resolve_current(tenant=None, handler_ref="x.onBeforeSubmit")
    assert result is None


def test_invalidate_clears_cache_entry() -> None:
    # FILL IN: prime store._cache directly with a fake SnippetBundle,
    #   call invalidate(), assert the key is gone
    pass
```
**Why**: the tier-cap and fail-soft tests (the two security/reliability
invariants) are written in full; the read-through cache hit-counting test
and the row→SnippetBundle mapping are stubbed together since they depend
on the FILL IN in `get_published()` being resolved first.

### FILL IN checklist
- [ ] `db_store.py::get_published` — map an `asyncpg.Record`-shaped row to `SnippetBundle`; bounded by the migration's column list
- [ ] `db_store.py::invalidate` docstring already documents the deferred cross-process mechanism — no code FILL IN beyond the per-process drop, which is complete
- [ ] `test_tier_cap_allows_helpers_for_any_tenant` — one-line positive assertion
- [ ] `test_db_store_read_through_cache` — fake row + call-count assertion
- [ ] `test_invalidate_clears_cache_entry` — prime + assert

---

## Acceptance Criteria

- [ ] `008_snippet_store.sql` creates `form_snippets` with the `UNIQUE(tenant, handler_ref, version)` constraint and the partial published-lookup index
- [ ] `check_tier_cap()` raises `ValueError` for `BROKERED`/`TOOLKIT` unless the tenant is in `tier3_tier4_tenants`; allows `PURE`/`HELPERS` for any tenant
- [ ] `resolve_current(tenant=None, ...)` always returns `None` without querying storage
- [ ] A storage fault in `get_published()` is logged and returns `None`, never raises (`test_db_store_read_through_cache`'s error variant / `test_resolve_current_fails_soft_on_storage_error`)
- [ ] `get_published()` serves the cached value on a second call for the same key without a second `fetchrow`
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_db_snippet_store.py -v`
- [ ] `ruff check` and `mypy` clean on `services/snippets/db_store.py`

---

## Test Specification

See the blueprint's test file above — 7 test functions, 3 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "Dual-source storage" table, §3 Module 5, §7 "Cache coherence across processes" risk)
2. **Check dependencies** — TASK-3161 and TASK-3163 must be `done`
3. **Verify the Codebase Contract** — confirm `migrations/` still ends at `007_dedupe_duplicate_field_ids.py` before naming this migration `008`; if a newer migration has landed, bump the number accordingly and note it in the Completion Note
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3165-tenant-snippet-store-migration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
