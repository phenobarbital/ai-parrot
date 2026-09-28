# TASK-3781: LinkedSurfaceService — validate_for_persistence / ensure_snapshot / refresh

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3780, TASK-3777
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (service half), S1/S2/S11, AC14/AC18. Four call sites persist or refresh linked
surfaces (`_pin_save`, `_refresh` — TASK-3787; `PublishSurfaceTool`, `publish_surface` — TASK-3788).
Design-research S1 requires ONE core service they all delegate to, and S2 requires the
persistence boundary to be enforceable: server lanes execute as a trusted service, so a
hand-written descriptor for any `(tenant, slug)` would be an exfiltration path unless every
save is (a) validated as a TOOL-origin envelope and (b) checked against a **configured,
fail-closed** data-plane guard for the owner. This is deliberately unlike `RecipeRunner`, whose
data-plane guards fail OPEN on a falsy `pctx` (`tools/infographic_recipes/runner.py:262-264`).

---

## Scope

- Create `linked/service.py` with `LinkedGuardRequired`, `SnapshotError`, `RefreshOutcome` and
  `LinkedSurfaceService` (`validate_for_persistence`, `ensure_snapshot`, `refresh`).
- `validate_for_persistence`: for a linked envelope (`has_data_sources`), run
  `validate_envelope(envelope, origin=ProducerOrigin.TOOL)`, require `self.guard`, and authorise
  the owner on every `(tenant, slug)`. A non-linked envelope passes through untouched (see
  "Decision" below).
- `ensure_snapshot`: when any target lacks rows or `snapshot_at`, execute once in owner context
  (`execute_sources(pctx=owner_pctx, guard=self.guard, …)`), patch `dataModel` + each source's
  `snapshot_at`/`snapshot_truncated`; ANY failed source ⇒ `SnapshotError(status, code)` —
  nothing is returned for persistence.
- `refresh`: re-authorise, execute with param overrides, patch successful sources, report
  partial failures as warnings, and signal "every source failed" with status/code; the caller
  persists with `update_envelope(expected_updated_at=…)` (S11).
- Unit tests with a fake guard and a monkeypatched `execute_sources`.

**NOT in scope**: HTTP status wiring (TASK-3787/TASK-3788); the conditional store update (TASK-3786);
changing `DataPlanePolicyGuard` or `AuthorizingDataSource`.

### Decision (resolves a spec/AC11 conflict — record it in the Completion Note)
Spec AC14 says every save path runs `validate_for_persistence` = `validate_envelope(origin=TOOL)`.
Verified at task time: `validate_envelope` on the `components=[]` sample envelopes that the
EXISTING handler/tool/mixin tests persist raises `CatalogValidationError(MISSING_ROOT)`, which
would break AC11 ("existing tests unchanged and green"). Therefore: every save path CALLS
`validate_for_persistence`, but structural validation + guard run **only when
`has_data_sources(envelope)`**; baked envelopes keep today's `model_validate`-only behaviour.
This still closes S2 (the exfiltration path exists only for linked envelopes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` | CREATE | the one persistence/refresh entry point (S1) |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_service.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope        # catalog/__init__.py:499 (validate_envelope)
from parrot.outputs.a2ui.catalog.base import CatalogValidationError               # catalog/base.py:307 (.issues list[dict])
from parrot.outputs.a2ui.models import CreateSurface                              # models.py:446
from parrot.auth.permission import PermissionContext, build_principal_context     # permission.py:81,166
from parrot.auth.exceptions import AuthorizationRequired                          # auth/exceptions.py:12
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources       # resolver.py:47 (driver, tables, source_type, source_id)
# FEAT-598 net-new, fixed module paths:
from parrot.outputs.a2ui.linked import has_data_sources                           # TASK-3769 (linked/__init__.py)
from parrot.outputs.a2ui.linked.models import LinkedSources, LinkedDataSource     # TASK-3769
from parrot.outputs.a2ui.linked.executor import execute_sources, ERROR_STATUS, ExecutionOutcome   # TASK-3780
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def validate_envelope(envelope, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None      # L499; raises CatalogValidationError(issues=[…]) L719
                                                                          # after TASK-3777: includes the surface-level linked pass

# packages/ai-parrot/src/parrot/auth/dataplane_guard.py
class DataPlanePolicyGuard:                                               # L45
    async def authorize_source(self, ctx: Optional[PermissionContext], resources: PhysicalResources) -> None   # L193
    # ctx None → fail-open (L216); navigator_auth ImportError → fail-open (L219-222);
    # source_type + source_id set → check_access(eval_ctx, "source", f"{source_type}:{source_id}", "source:read") L286-311;
    # denial / evaluator error → AuthorizationRequired(tool_name="dataplane_authz", message=…)

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:250-264 — fail-OPEN precedent this service must NOT copy.

# Envelope dict shape (CreateSurface.model_dump(by_alias=True, mode="json")): keys "surfaceId", "components",
#   "dataModel", "metadata": {"extensions": {"parrot_data_sources": {<key>: {…LinkedDataSource…}}}}
```

### Does NOT Exist
- ~~a `slug:execute` check anywhere in parrot~~ — `DataPlanePolicyGuard` gates `driver:connect` / `table:read` / `source:read` only, and `resolve_physical_resources(QuerySlugSource)` returns EMPTY resources (resolver.py:163-166). This task's owner check therefore uses `authorize_source` with an explicit `PhysicalResources(source_type=…, source_id=…)` (see FILL IN) — do not invent a guard method.
  **Resource naming CONFIRMED by owner (2026-09-26)**: `source_type="query_slug"`, `source_id=f"{tenant or 'public'}:{slug}"` — PBAC policies key on `query_slug:<tenant|public>:<slug>` under the existing `source:read` gate, matching the opaque source_type convention (`mongo`/`iceberg`/`delta`, opaque.py). Not `dataset:<slug>` (no tenant dimension, separate guard) and no new `slug:execute` action. The Scope § Decision (AC14 vs AC11: validate + guard only when `has_data_sources`) is also owner-CONFIRMED. Default guard wiring is TASK-3805 — this task still treats `guard=None` as fail-closed.
- ~~`LinkedSurfaceService`, `LinkedGuardRequired`, `SnapshotError`, `RefreshOutcome`~~ — created here.
- ~~`validate_envelope` returning issues~~ — it raises `CatalogValidationError`; it never returns a list.
- ~~`UISurfaceRecord` / `PgUISurfaceStore` in core~~ — server-only; this service takes and returns envelope DICTS and never touches the store (one-way import rule).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_service.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#CatalogValidationError",
    "sym:packages/ai-parrot/src/parrot/auth/dataplane_guard.py#DataPlanePolicyGuard.authorize_source",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py#PhysicalResources",
    "sym:packages/ai-parrot/src/parrot/auth/exceptions.py#AuthorizationRequired"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Fail CLOSED (AC14)**: linked envelope + `guard is None` ⇒ `LinkedGuardRequired` (HTTP 403 at the caller), for `validate_for_persistence`, `ensure_snapshot` AND `refresh`. A denied source ⇒ `AuthorizationRequired` propagates (403 at the caller) and nothing is persisted.
- **Owner context (AC18)**: every call receives `owner_pctx` and passes it to `execute_sources(pctx=…)`, which maps it to `QSPrincipal`; the guard remains mandatory regardless — the principal is additive (QuerySource PBAC no-ops when its bootstrap is absent).
- **Tenant from the descriptor (AC4)**: `(tenant, slug)` come from each `parrot_data_sources` entry; never from `owner_pctx.tenant_id` or any record.
- **Atomic snapshot (S1)**: `ensure_snapshot` returns a patched COPY; on any failure it raises and the input dict is left untouched.
- **S11**: `refresh` never persists; it returns the patched envelope + the new `snapshot_at` so the caller can do the conditional update.
- The guard's own ImportError fail-open (no navigator-auth) is a platform property; document it in the class docstring, do not paper over it.

---

## Implementation Blueprint

### Steps (in order)
1. Define the three small types — *why*: callers map them to HTTP (`LinkedGuardRequired`→403, `SnapshotError.status`, `RefreshOutcome`).
2. Write `_sources(envelope)` parsing `metadata.extensions.parrot_data_sources` via `LinkedSources` — *why*: one parser for all three methods.
3. Write `_assert_sources_allowed(sources, owner_pctx)` — *why*: S2 owner check on every `(tenant, slug)`; shared by all three methods.
4. Write the three public methods.
5. Tests.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` (CREATE) — types + helpers
```python
"""LinkedSurfaceService — the ONE persistence/refresh entry point for linked surfaces (FEAT-598 S1/S2/S11).

Every save path (REST pin/save, PublishSurfaceTool, InfographicAuthoringMixin.publish_surface) and the refresh
lane delegate here. Unlike RecipeRunner (fail-open on a falsy pctx), this service FAILS CLOSED: a linked
envelope is never validated, snapshotted or refreshed without a configured data-plane guard. Note: the guard
itself fails open when navigator-auth is not installed (DataPlanePolicyGuard.authorize_source) — deployments
exposing linked surfaces must ship navigator-auth.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping

from pydantic import BaseModel, Field

from parrot.outputs.a2ui.linked import has_data_sources
from parrot.outputs.a2ui.linked.models import LinkedDataSource, LinkedSources
from parrot.outputs.a2ui.models import CreateSurface

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.permission import PermissionContext

_EXT_KEY = "parrot_data_sources"


class LinkedGuardRequired(Exception):
    """A linked envelope reached persistence/refresh with no data-plane guard configured (→ HTTP 403)."""


class SnapshotError(Exception):
    """Save-time snapshot failed; nothing may be persisted. Carries the HTTP status + stable code."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"linked snapshot failed: {code}")
        self.status = status
        self.code = code


class RefreshOutcome(BaseModel):
    """Result of LinkedSurfaceService.refresh — the caller persists `envelope` conditionally (S11)."""

    envelope: dict[str, Any]
    snapshot_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    error_status: int | None = None   # set only when EVERY source failed
    error_code: str | None = None


def _sources(envelope: CreateSurface | dict[str, Any]) -> dict[str, LinkedDataSource]:
    """Parse metadata.extensions.parrot_data_sources (dict or model envelope) into LinkedDataSource objects."""
    # FILL IN: read the extension from either shape (CreateSurface.metadata.extensions root / dict["metadata"]
    #          ["extensions"]); LinkedSources.model_validate(...).root — bounded by TASK-3769's models (extra="forbid").
    raise NotImplementedError
```

### `service.py` (CREATE, continued) — the service
```python
class LinkedSurfaceService:
    """Validate, snapshot and refresh linked surfaces with owner context and a mandatory guard (spec §3 M5)."""

    def __init__(self, *, guard: Any | None, max_fetch_rows: int = 5000, max_snapshot_rows: int = 500) -> None:
        self.guard = guard
        self.max_fetch_rows = max_fetch_rows
        self.max_snapshot_rows = max_snapshot_rows
        self.logger = logging.getLogger(__name__)

    def _require_guard(self) -> Any:
        if self.guard is None:
            raise LinkedGuardRequired("linked surfaces require a configured data-plane guard")
        return self.guard

    async def _assert_sources_allowed(self, sources: Mapping[str, LinkedDataSource], owner_pctx: "PermissionContext") -> None:
        """Owner must be allowed to execute every (tenant, slug) — raises AuthorizationRequired on denial (S2)."""
        from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

        guard = self._require_guard()
        for key, src in sources.items():
            # FILL IN: resource identity — bounded by S2 and DataPlanePolicyGuard's existing source:read gate:
            #          await guard.authorize_source(owner_pctx, PhysicalResources(source_type="query_slug",
            #          source_id=f"{src.tenant or 'public'}:{src.slug}")); dedupe identical (tenant, slug) pairs;
            #          log key/slug/tenant on denial at WARNING and re-raise. Document the resource naming in the
            #          docstring (T28 copies it into docs/outputs/a2ui-linked-surfaces.md).
            raise NotImplementedError

    async def validate_for_persistence(self, envelope: CreateSurface, *, owner_pctx: "PermissionContext") -> None:
        """No-op for baked envelopes (AC11); for linked ones: TOOL-origin validation + guard + owner check (AC14)."""
        # function-local: linked/ must never import catalog/ at module import time (spec §7 one-way rule)
        from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope

        if not has_data_sources(envelope):
            return
        validate_envelope(envelope, origin=ProducerOrigin.TOOL)   # raises CatalogValidationError (→ 422 at caller)
        await self._assert_sources_allowed(_sources(envelope), owner_pctx)

    async def ensure_snapshot(self, envelope: dict[str, Any], *, owner_pctx: "PermissionContext") -> dict[str, Any]:
        """Execute once (owner ctx) when any target lacks rows/snapshot_at; raise SnapshotError on any failure."""
        from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources

        if not has_data_sources(envelope):
            return envelope
        sources = _sources(envelope)
        self._require_guard()
        # FILL IN: skip execution when EVERY source has snapshot_at set AND dataModel[<root>]["rows"] is a list;
        #          otherwise outcome = await execute_sources(sources, pctx=owner_pctx, guard=self.guard,
        #          max_snapshot_rows=self.max_snapshot_rows, max_fetch_rows=self.max_fetch_rows); first failed source
        #          → raise SnapshotError(ERROR_STATUS.get(code, 502), code); else return _patch(copy.deepcopy(envelope),
        #          outcome) — bounded by AC8 ("executes once … or answers 404/503/502 and persists nothing") and S1.
        raise NotImplementedError

    async def refresh(self, envelope: dict[str, Any], *, params: Mapping[str, Any],
                      owner_pctx: "PermissionContext") -> RefreshOutcome:
        """Re-authorise, execute with overrides, patch successful sources; never persists (S11)."""
        from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources

        sources = _sources(envelope)
        await self._assert_sources_allowed(sources, owner_pctx)
        # FILL IN: overrides shape — `params` is the flat RefreshSurfaceRequest.params dict: when a key names a
        #          source and its value is a mapping, it is that source's overrides; every other key is broadcast to
        #          every source (execute_sources ignores names a source does not declare / has locked). Execute,
        #          patch successful sources into a deepcopy, collect "source <key>: <code>" warnings (plus
        #          ignored_params), set error_status/error_code only when ALL sources failed; snapshot_at = max of the
        #          new per-source stamps — bounded by spec §3 M8 `_refresh` docstring and S11.
        raise NotImplementedError


def _patch(envelope: dict[str, Any], outcome: "ExecutionOutcome") -> dict[str, Any]:
    """Write rows into dataModel[<root>] and stamp snapshot_at/snapshot_truncated on each successful source."""
    # FILL IN: dataModel.update(outcome.data_model_patch()); for each successful key set
    #          metadata.extensions.parrot_data_sources[key]["snapshot_at"] = o.snapshot_at.isoformat() and
    #          ["snapshot_truncated"] = o.truncated; failed sources keep their previous rows — bounded by the
    #          by_alias JSON envelope shape (keys "dataModel", "metadata").
    raise NotImplementedError
```
Add `from parrot.outputs.a2ui.linked.executor import ExecutionOutcome` under `TYPE_CHECKING` for the `_patch` annotation.
**Why this shape**: all executor AND catalog imports are function-local (catalog imports linked.models for TASK-3777's pass — importing catalog at module level here would create the forbidden reverse edge) so `import parrot.outputs.a2ui.linked.service` stays cheap and pandas-free. `_assert_sources_allowed` runs BEFORE any fetch on every lane, so a descriptor the owner cannot run never reaches QuerySource, even with trusted-service credentials. `refresh` also re-authorises because an owner can lose access after saving.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_service.py` (CREATE)
```python
"""FEAT-598 S1/S2/S11 — LinkedSurfaceService (spec §4)."""
from __future__ import annotations

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService, SnapshotError

pytestmark = pytest.mark.asyncio


class _FakeGuard:
    """Records authorize_source calls; denies the (source_type, source_id) pairs in `deny`."""
    # FILL IN: async authorize_source(ctx, resources) → append; raise AuthorizationRequired(tool_name="dataplane_authz",
    #          message="denied") when f"{resources.source_type}:{resources.source_id}" in self.deny


@pytest.fixture
def owner():
    return build_principal_context("owner-1", channel="ui_surfaces")


async def test_persist_validates_envelope(owner): ...              # FILL IN: linked + invalid → CatalogValidationError
async def test_persist_requires_guard_fail_closed(owner): ...      # FILL IN: guard=None + linked → LinkedGuardRequired
async def test_persist_baked_envelope_passthrough(owner): ...      # FILL IN: no sources + guard=None → no error, no validation
async def test_persist_owner_slug_execute_denied(owner): ...       # FILL IN: one denied (tenant, slug) → AuthorizationRequired
async def test_ensure_snapshot_executes_once(owner, monkeypatch): ...   # FILL IN: patch execute_sources; called once; rows + snapshot_at
async def test_ensure_snapshot_failure_raises(owner, monkeypatch): ...  # FILL IN: error "tenant_store_unavailable" → SnapshotError(503)
async def test_ensure_snapshot_input_untouched_on_failure(owner, monkeypatch): ...
async def test_refresh_partial_failure_warnings(owner, monkeypatch): ...  # FILL IN: warnings; error_status None
async def test_refresh_all_failed_status(owner, monkeypatch): ...          # FILL IN: error_status/error_code set
async def test_refresh_passes_owner_pctx(owner, monkeypatch): ...          # FILL IN: execute_sources(pctx=owner, guard=…) (AC18)
```
Build envelopes with a valid root component + `metadata.extensions.parrot_data_sources` using TASK-3769's `linked_source` fixture
(its `conditions` already equal `derive_conditions(request)`, so TASK-3777's surface pass accepts it). Monkeypatch
`parrot.outputs.a2ui.linked.executor.execute_sources` (the service imports it function-locally, so patch the module attribute).

### FILL IN checklist
- [ ] `_sources` — parse both envelope shapes; bounded by TASK-3769 models.
- [ ] `_assert_sources_allowed` — resource identity + dedupe; bounded by S2 and the existing `source:read` gate.
- [ ] `ensure_snapshot` — skip rule, SnapshotError mapping; bounded by AC8/S1.
- [ ] `refresh` — overrides shape, warnings, all-failed signal; bounded by S11 / §3 M8.
- [ ] `_patch` — dataModel + snapshot stamps; bounded by the by_alias dict shape.
- [ ] tests — every body.

---

## Acceptance Criteria

- [ ] Linked envelope + no guard ⇒ `LinkedGuardRequired` on all three methods (AC14, fail closed).
- [ ] Linked envelope ⇒ `validate_envelope(origin=TOOL)` runs; baked envelope ⇒ no validation, no guard needed (AC11).
- [ ] Owner denied on one `(tenant, slug)` ⇒ `AuthorizationRequired`, no execution (S2).
- [ ] `ensure_snapshot` executes at most once and raises `SnapshotError(status, code)` on any failure, input untouched.
- [ ] `refresh` passes `owner_pctx` + guard to `execute_sources` and never persists (AC18, S11).
- [ ] Tenant always from the descriptor (AC4).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_service.py -q`

---

## Test Specification

See the CREATE test block (spec §4: `test_persist_validates_envelope`, `test_persist_requires_guard_fail_closed`,
`test_persist_owner_slug_execute_denied`; save-time snapshot rows of M8 are exercised through the service here and
through the handler in TASK-3787).

---

## Agent Instructions

1. Read spec §3 Module 5, §7 Known Risks (S2 exfiltration, fail-closed guard), §9 S1/S2/S11.
2. Check TASK-3777 and TASK-3780 are done.
3. Verify the Codebase Contract (especially `authorize_source` and `PhysicalResources`).
4. Index → `"in-progress"`; implement; complete every `# FILL IN:`.
5. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src`).
6. Move to `sdd/tasks/completed/`, index → `"done"`, Completion Note (record the AC11 Decision above).

---

## Completion Note


- Task: TASK-3781
- Feature: a2ui-linked-surfaces
- Implementation SHA: 750c69256fb4a3c3150df754fe3a482f0bdc68af
- Closed at (UTC): 2026-09-26T01:27:15+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| flagged_judgment_call | Coder followed the literal code skeleton: ensure_snapshot() does not re-call _assert_sources_allowed (only validate_for_persistence and refresh do), even though task prose said the owner check is 'shared by all three methods'. No test in the Test Specification exercises owner-denial via ensure_snapshot directly. Flagged for final feature review to confirm intent. |
| merge_validation_outcome | failed: same systemic pre-existing failures already characterized (parrot-formdesigner version/schema drift, ai-parrot-embeddings wheel-layout conftest collision), unrelated to this task's diff. Task's own scoped tests: 103 passed (packages/ai-parrot/tests/outputs/a2ui/linked). See issue:181bd0c01bb4. |
| seat_summary | Seat: sonnet - Backend: native - Model: sonnet - Attempts: 1 - Duration: n/a - Tokens: n/a |
