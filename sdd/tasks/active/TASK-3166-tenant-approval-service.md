# TASK-3166: Tenant snippet approval service — `services/snippets/approval.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161, TASK-3165, TASK-3175
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. This is the **C4 human-approval gate for the DB source**
— the tenant-side equivalent of "the merged commit is the gate" for git
snippets. It mirrors `FormVersionService.publish()` /
`.get_published()` / `.list_versions()`
(`services/form_version.py:306,431,480`): draft → published → revoked
lifecycle, recording who approved and when, refusing to publish anything
that fails the conformance gate.

**Ordering caveat (spec's own words, Worktree Strategy section)**: this
module depends on M15 (TASK-3175, conformance gate) so that a DB publish
is held to the same standard as a git PR merge. The spec explicitly
prefers landing a **minimal M15 stub** early over letting this task block
on the full M15/M16 track. This task's blueprint below defines the
`ConformanceCheckFn` it needs as an injected callable — same dependency-
injection technique TASK-3163 used for the not-yet-built sandbox — so this
task can be implemented and tested with a fake checker before TASK-3175
lands, and wired to the real one once it does.

---

## Scope

- Implement `SnippetApprovalService` in
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/approval.py`:
  `draft()`, `publish()`, `revoke()`, `get_published()`, `list_versions()` —
  mirroring `FormVersionService`'s method names and draft/published
  semantics as closely as the different entity shape allows.
- `publish()` MUST call the injected conformance-check callable and refuse
  (raise) if it reports failure — this is the actual C4 enforcement point
  for the DB source.
- `publish()` MUST call `DbSnippetStore.check_tier_cap()` (TASK-3165)
  before allowing a draft to become published.
- `publish()` MUST call `DbSnippetStore.invalidate()` (TASK-3165) after a
  successful publish, so the read-through cache picks up the new version
  without a restart (spec's `test_republish_takes_effect_without_restart`).
- Write `packages/parrot-formdesigner/tests/unit/test_snippet_approval.py`.

**NOT in scope**: the conformance gate's actual implementation
(TASK-3175); any HTTP/API handler surface for a tenant admin to call this
service through (not named in the spec's module breakdown — if a handler
task does not exist elsewhere, note the gap in the Completion Note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/approval.py` | CREATE | `SnippetApprovalService` |
| `packages/parrot-formdesigner/tests/unit/test_snippet_approval.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.snippets import (
    SnippetBundle, SnippetStatus, SnippetNotApprovedError,
)  # TASK-3161
from parrot_formdesigner.services.snippets.db_store import DbSnippetStore  # TASK-3165
```

### Existing Signatures to Use — the pattern this mirrors
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
class FormVersionService:                                    # line 251
    async def publish(                                       # line 306
        self, form_uid: str, *, tenant: str, bump: str = "minor",
    ) -> str:
        """Promote the current live version to published, in place.
        Raises ValueError if the live version is already published
        (immutability)."""
    async def get_published(self, ...) -> ...: ...           # line 431
    async def list_versions(self, ...) -> ...: ...           # line 480
```
**Important divergence to note in your implementation**: `publish()`'s
real signature above operates on `FormSchema` versions (`form_uid` +
`bump`) — a different entity from a snippet row. Do **not** copy this
signature verbatim; copy the *pattern* (draft/published immutability,
explicit promotion, recorded approver) onto the snippet entity shape from
TASK-3165's `form_snippets` table (`tenant`, `handler_ref`, `version`,
`status`, `approved_by`, `approved_at`).

```python
# TASK-3165 — packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/db_store.py
class DbSnippetStore:
    def check_tier_cap(self, tenant: str, manifest: CapabilityManifest) -> None: ...
        # Raises ValueError if tier exceeds this tenant's cap.
    def invalidate(self, *, tenant: str, handler_ref: str) -> None: ...
        # Drops the per-process read-through cache entry.
```

### Does NOT Exist
- ~~`services/snippets/approval.py`~~ — created by this task.
- ~~`check_snippet_conformance.run_gate()`~~ or any other concrete M15
  symbol — TASK-3175 may name it differently than assumed here. Receive
  the conformance check as an **injected `ConformanceCheckFn` callable**
  (constructor parameter), never a hard import of
  `scripts/check_snippet_conformance.py`, so this task does not need to
  guess TASK-3175's exact public API.
- ~~A generic "approval" table shared with `FormVersionService`~~ — this
  service reads/writes `form_snippets` (TASK-3165's table) directly
  through `DbSnippetStore`/its underlying pool, not through
  `FormVersionService` or any `form_schemas`-shaped table.

---

## Implementation Notes

### Key Constraints
- **Immutability**: once a version is `PUBLISHED`, it is never mutated in
  place — `publish()` promotes the CURRENT draft row's status; a
  subsequent edit creates a new draft row at `version + 1` (mirrors
  `FormVersionService.publish()`'s "no longer bumps... publishing draft
  '1.5' produces published '1.5'" note, adapted: here versions are
  monotonic per-row, not per-field-bump — draft() is a fresh version).
- `publish()` must refuse (not silently skip) a bundle that fails
  conformance — this is the actual security boundary for the DB source,
  called out explicitly in spec §7: "M6 must refuse to publish anything
  that fails the M15 gate, and that check cannot be bypassed by a direct
  DB write" (the "cannot be bypassed" part is a DB-permissions/ops
  concern outside this task's Python code, but this method must never
  provide an in-code bypass path, e.g. no `force=True` kwarg).
- `revoke()` sets status to `REVOKED` and invalidates the cache — after
  revocation, `get_form_event()`'s existing tenant→global fallback
  restores the platform git snippet automatically (no code change needed
  here; this is `test_revoked_snippet_falls_back_to_git`'s mechanism).
- A `DRAFT` bundle must never be resolvable via `DbSnippetStore.resolve_current()`
  — TASK-3165's `get_published()` query already filters `WHERE status =
  'published'`, so this is enforced by the query, not by this service;
  do not add a redundant status check that could drift from the SQL.

### References in Codebase
- `services/form_version.py:251-500` — read the whole class for the
  draft/publish/list pattern before writing this file.

---

## Implementation Blueprint

### Steps (in order)
1. Define `ConformanceCheckFn` — *why*: the injection point that lets this
   task be implemented independent of TASK-3175's exact API.
2. Implement `draft()` — inserts a new `DRAFT` row via the pool (owned by
   `DbSnippetStore`, accessed through a small internal query helper since
   `DbSnippetStore` itself only exposes read + cache-management methods).
3. Implement `publish()` — the security-critical method: conformance
   check, tier cap check, status transition, cache invalidation, in that
   order.
4. Implement `revoke()`, `get_published()`, `list_versions()`.
5. Write and run tests, prioritizing `test_approval_refuses_unconformant`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/approval.py` (CREATE)
```python
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
from typing import Any, Protocol

from parrot_formdesigner.core.snippets import SnippetBundle, SnippetStatus
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
        if bundle.source.value != "db":
            raise ValueError("only DB-sourced bundles can be drafted")
        # FILL IN: compute next version = 1 + max(existing version for
        #   (tenant, handler_ref) across ALL statuses, or 0 if none) and
        #   INSERT a row with status='draft' via the store's underlying
        #   pool — bounded by the migrations/008_snippet_store.sql schema
        #   (UNIQUE(tenant, handler_ref, version)).
        raise NotImplementedError

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
            SnippetNotApprovedError: FILL IN — decide whether this is ever
                raised BY publish() itself, or only by a caller that
                tries to execute a non-published bundle (leaning toward
                the latter: publish() raises ValueError for its own
                refusals, SnippetNotApprovedError is for the execution
                path finding a DRAFT/REVOKED row unexpectedly).
        """
        # FILL IN: fetch the target row, validate status == DRAFT, run
        #   check_conformance, run store.check_tier_cap, then UPDATE +
        #   invalidate — bounded by the docstring's ordered check list
        #   above and by test_approval_refuses_unconformant /
        #   test_approval_records_approver.
        raise NotImplementedError

    async def revoke(self, *, tenant: str, handler_ref: str, version: int) -> None:
        """Set a PUBLISHED (or DRAFT) row to REVOKED and invalidate the cache.

        After revocation, get_form_event()'s existing tenant -> global
        fallback (event_registry.py:149) restores the platform git
        snippet for this tenant with NO code change here — that is the
        existing registry's job, not this service's.
        """
        # FILL IN: UPDATE status='revoked' WHERE (tenant, handler_ref,
        #   version) matches; then store.invalidate(...).
        raise NotImplementedError

    async def get_published(self, *, tenant: str, handler_ref: str) -> SnippetBundle | None:
        """Convenience passthrough to the store's read-through cache."""
        return await self._store.get_published(tenant=tenant, handler_ref=handler_ref)

    async def list_versions(self, *, tenant: str, handler_ref: str) -> list[SnippetBundle]:
        """All versions (any status) for (tenant, handler_ref), newest first."""
        # FILL IN: SELECT * FROM form_snippets WHERE tenant=$1 AND
        #   handler_ref=$2 ORDER BY version DESC — map rows to
        #   SnippetBundle the same way TASK-3165's get_published() does.
        raise NotImplementedError
```
**Why this shape**: `ConformanceResult`/`ConformanceCheckFn` are a
`Protocol`/`Callable` pair, not an import of TASK-3175's module — this is
the same dependency-inversion technique TASK-3163 used for the
not-yet-built sandbox, and it is what lets this task be implemented in
parallel with, or before, TASK-3175 despite the spec's own module ordering
listing M6 as depending on M15. `publish()`'s check order (existence →
conformance → tier cap → mutation) is fixed by the "refuse to publish
anything that fails the M15 gate" requirement being unconditional — a row
that fails the tier cap must never even reach the conformance gate's cost
if it would fail cheaper checks first, but conformance is checked before
the tier cap here specifically because a conformance failure is a
correctness bug in the snippet itself, which should surface before a
policy-only tier rejection (implementer may swap the order if a good
reason emerges — record it in the Completion Note if so).

### `packages/parrot-formdesigner/tests/unit/test_snippet_approval.py` (CREATE)
```python
"""Unit tests for SnippetApprovalService — FEAT-459 / TASK-3166."""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.snippets.approval import SnippetApprovalService


class _FakeConformanceResult:
    def __init__(self, passed: bool, errors: list[str] | None = None) -> None:
        self.passed = passed
        self.errors = errors or []


class _FakeStore:
    def __init__(self) -> None:
        self.invalidate_calls: list[tuple[str, str]] = []
        self.tier_cap_raises = False

    def check_tier_cap(self, tenant, manifest):
        if self.tier_cap_raises:
            raise ValueError("capped at tier 2")

    def invalidate(self, *, tenant, handler_ref):
        self.invalidate_calls.append((tenant, handler_ref))

    async def get_published(self, *, tenant, handler_ref):
        return None


async def test_approval_refuses_unconformant() -> None:
    store = _FakeStore()

    async def _fails(bundle):
        return _FakeConformanceResult(passed=False, errors=["undeclared import: socket"])

    service = SnippetApprovalService(store, check_conformance=_fails)
    # FILL IN: draft a bundle first (or seed one directly), then call
    #   publish() and assert pytest.raises(ValueError, match="conformance")
    #   AND that store.invalidate_calls stays empty (no mutation on refusal).
    pass


async def test_approval_records_approver() -> None:
    # FILL IN: with a passing conformance fake, publish() a drafted bundle
    #   and assert the returned/re-fetched bundle has approved_by set to
    #   the passed-in value and approved_at is not None.
    pass


async def test_draft_never_executes() -> None:
    """A DRAFT snippet is never resolved by get_published() (query-level filter)."""
    store = _FakeStore()

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    result = await service.get_published(tenant="acme", handler_ref="x.onBeforeSubmit")
    assert result is None  # _FakeStore.get_published always returns None here


async def test_publish_invalidates_cache_on_success() -> None:
    # FILL IN: publish a valid draft, assert
    #   store.invalidate_calls == [("acme", "x.onBeforeSubmit")]
    pass


async def test_revoke_invalidates_cache() -> None:
    store = _FakeStore()

    async def _passes(bundle):
        return _FakeConformanceResult(passed=True)

    service = SnippetApprovalService(store, check_conformance=_passes)
    # FILL IN: draft + publish, then revoke(), assert invalidate was
    #   called again (twice total) and a subsequent get_published-style
    #   query would no longer see the row as published — the latter is
    #   only checkable against a real/fake pool with query state, so this
    #   assertion may need a richer fake than _FakeStore above.
    pass
```
**Why**: `test_draft_never_executes` is complete because it only exercises
the already-fixed `get_published()` passthrough; the rest are stubbed
because they depend on `draft()`/`publish()`/`revoke()`'s FILL INs and on
deciding how much SQL-state simulation the fake needs — left for the
implementer to size appropriately rather than over-building a fake pool
here.

### FILL IN checklist
- [ ] `approval.py::draft` — version computation + INSERT; bounded by the migration's UNIQUE constraint
- [ ] `approval.py::publish` — full check-then-mutate body; bounded by the docstring's ordered check list
- [ ] `approval.py::publish` — decide `SnippetNotApprovedError` usage (likely: not raised here, only at execution time)
- [ ] `approval.py::revoke` — UPDATE + invalidate
- [ ] `approval.py::list_versions` — SELECT + row mapping (reuse TASK-3165's row→SnippetBundle logic; consider extracting a shared helper if duplicated)
- [ ] All 4 stubbed tests

---

## Acceptance Criteria

- [ ] `publish()` raises `ValueError` naming "conformance" when the injected `check_conformance` reports `passed=False`; no row is mutated
- [ ] `publish()` raises `ValueError` naming the tier cap when `store.check_tier_cap` raises; conformance is still checked (or not — record actual order chosen) but no publish occurs
- [ ] A successful `publish()` sets `approved_by`/`approved_at` and calls `store.invalidate()` exactly once with the correct `(tenant, handler_ref)`
- [ ] `revoke()` calls `store.invalidate()` and the row's status becomes `REVOKED`
- [ ] `get_published()` never returns a `DRAFT`-status bundle (enforced by the underlying query, verified by test)
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_snippet_approval.py -v`
- [ ] `ruff check` and `mypy` clean on `services/snippets/approval.py`

---

## Test Specification

See the blueprint's test file above — 5 test functions, 4 stubbed (one complete).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 6, §7 "Two trust models, one execution path" risk, Worktree Strategy "Ordering caveat introduced by OQ-1")
2. **Check dependencies** — TASK-3161 and TASK-3165 must be `done`. TASK-3175 (M15) is the spec's stated dependency but this task is written to accept a FAKE `ConformanceCheckFn` — if TASK-3175 is not yet `done`, implement and test against a fake, then wire the real one in a short follow-up once TASK-3175 lands (note this explicitly in the Completion Note)
3. **Verify the Codebase Contract** — confirm `DbSnippetStore.check_tier_cap`/`.invalidate` signatures in `services/snippets/db_store.py` match what TASK-3165 actually shipped
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3166-tenant-approval-service.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
