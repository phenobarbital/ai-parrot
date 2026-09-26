# TASK-3780: Python executor — execute_sources + map_query_error + outcomes

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3769, TASK-3770, TASK-3773, TASK-3779
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (executor half) + §2 Data Models (`SourceOutcome`, `ExecutionOutcome`). The
Python reference executor fetches and transforms every source of a linked surface in-process:
it is used by the toolkit's mandatory execution (TASK-3785, `pctx=None`, trusted-service lane) and
by `LinkedSurfaceService` (TASK-3781, owner context → FEAT-150 principal). It must isolate
per-source failures, bound the fetch (S8), run pandas off the event loop (S8), route the
descriptor's tenant explicitly (AC4), select the MultiQuery frame (S4, via TASK-3779) and map
QuerySource errors to stable HTTP codes.

---

## Scope

- Create `linked/executor.py` with `SourceOutcome`, `ExecutionOutcome` (+ `data_model_patch()`),
  `execute_sources(...)`, `map_query_error(exc)` and the `ERROR_STATUS` code→status table.
- Order sources so `join.with` / `union.sources` siblings execute first (topological order;
  a cycle or unknown sibling → that source fails with `error="data_stage"`, others continue).
- Conditions per source = `derive_conditions(request, locked=…)` with non-locked overrides
  applied, plus `{"querylimit": max_fetch_rows}` (S8). Locked-key overrides are dropped and
  reported in `ignored_params`.
- Fetch via `QuerySlugSource(slug, tenant=src.tenant, is_multiquery=…, multi_output=…,
  principal=…)`; wrap in `AuthorizingDataSource(inner, guard, pctx_provider=lambda: pctx)` when
  a guard is given. `principal = to_qs_principal(pctx)` computed ONCE when `pctx` is not None.
- `apply_transform` runs in `asyncio.to_thread`; a `ref` transform is skipped (frame unchanged,
  warning logged).
- Rows serialised JSON-safe (`orient="records"`, ISO dates); `max_snapshot_rows` truncates and
  sets `truncated`; `snapshot_at` = UTC now per successful source.
- Unit tests with a fake `QuerySlugSource` layer (monkeypatch `query_slug._get_qs`/`_get_multiqs`).

**NOT in scope**: the service / persistence boundary (TASK-3781); DSL op semantics (TASK-3773/TASK-3774);
QuerySlugSource changes (TASK-3779); HTTP handlers (TASK-3787).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` | CREATE | execute_sources, map_query_error, SourceOutcome, ExecutionOutcome, ERROR_STATUS |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_executor.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource, to_qs_principal   # query_slug.py:36; to_qs_principal from TASK-3779
from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource             # authorizing.py:41
from parrot.auth.permission import PermissionContext, build_principal_context                  # permission.py:81,166 (tests only for the latter)
# FEAT-598 net-new, fixed module paths:
from parrot.outputs.a2ui.linked.models import LinkedDataSource, TransformSpec                  # TASK-3769
from parrot.outputs.a2ui.linked.conditions import derive_conditions                            # TASK-3770
from parrot.outputs.a2ui.linked.dsl import apply_transform, TransformError                     # TASK-3773
# querysource 5.1.1 — LAZY import inside map_query_error only (optional extra "db"):
from querysource.exceptions import QueryAccessDenied   # exceptions.py:63 (code 404, generic "Query not available.")
from querysource.tenants import TenantError            # re-exported from tenant_errors.py:15; .error_code attr
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py
class AuthorizingDataSource(DataSource):                                   # L41
    def __init__(self, inner: DataSource, guard: "DataPlanePolicyGuard",
                 pctx_provider: Callable[[], Optional["PermissionContext"]]) -> None   # L58-63
    async def fetch(self, **params) -> pd.DataFrame                        # L74; ctx None → fail-open L121-123;
    # NOTE: resolve_physical_resources(QuerySlugSource) returns EMPTY PhysicalResources (resolver.py:163-166),
    # so for slugs the wrapper gates nothing today — the slug-level owner check lives in TASK-3781 (S2).

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py (after TASK-3779)
class QuerySlugSource:  __init__(slug, prefetch_schema_enabled=True, permanent_filter=None, *, tenant=None,
                                 is_multiquery=False, multi_output=None, principal=None, definition=None)
    async def fetch(self, **params) -> pd.DataFrame   # conditions passed as **params; QS errors propagate or are
                                                      # chained as RuntimeError(...) from <exc>
def to_qs_principal(pctx, *, channel="ui_surfaces") -> QSPrincipal

# querysource/tenant_errors.py:5-12  OWNERSHIP_STATUS = {"invalid_tenant": 400, "tenant_not_available": 404,
#   "query_not_found": 404, "tenant_store_unavailable": 503, "tenant_write_forbidden": 403, "tenant_worker_unsupported": 502}
# querysource/exceptions.py:63-71  class QueryAccessDenied(QueryException): code=404, message "Query not available."
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.linked.executor`~~ — created here.
- ~~`SourceOutcome.transform_skipped`~~ — not a field; a skipped `ref` transform is only logged (spec §2 fixes the field list).
- ~~`QuerySlugSource.fetch(conditions=…)`~~ — conditions are passed as `**params`.
- ~~any `slug:execute` gate inside `AuthorizingDataSource` / `DataPlanePolicyGuard`~~ — none (see note above).
- ~~a 403 from QuerySource~~ — every QuerySource denial is 404 (spec §7).
- ~~reading `pctx.tenant_id` to pick a store~~ — FORBIDDEN (AC4): the tenant comes from `LinkedDataSource.tenant` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_executor.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py#AuthorizingDataSource",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py#QuerySlugSource",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#PermissionContext"
  ]
}
```

---

## Implementation Notes

### map_query_error table (spec §3 M5 — binding)
| Exception | Result |
|---|---|
| `querysource.exceptions.QueryAccessDenied` | `(404, "query_not_found")` — FEAT-150: with a principal "missing" and "denied" collapse; NEVER surface "denied" |
| `TenantError` with `error_code == "tenant_not_available"` | `(404, "tenant_not_available")` |
| `TenantError` with `error_code == "query_not_found"` | `(404, "query_not_found")` |
| `TenantError` with `error_code == "tenant_store_unavailable"` | `(503, "tenant_store_unavailable")` |
| anything else | `(502, "data_stage")` |

Walk `exc`, then `exc.__cause__` / `exc.__context__` (bounded depth) because TASK-3779 chains
returned errors as `RuntimeError(...) from error`. Match by `isinstance` after a lazy import;
when querysource is not importable, fall back to `(502, "data_stage")`.

### Key Constraints
- **S8 bounded fetch**: `querylimit = max_fetch_rows` on EVERY fetch (default 5000); `apply_transform` in `asyncio.to_thread`.
- **AC4**: pass `tenant=source.tenant` explicitly, even when `None`… but TASK-3779 drops `None` kwargs — so the test asserts `tenant == "acme"` reaches QS for a tenant source and that no tenant is inferred from `pctx`.
- **AC18**: `pctx is None` ⇒ no principal (trusted-service lane, agent tool); `pctx` given ⇒ `principal=to_qs_principal(pctx)` on every source, computed once.
- **Never raise for data errors**: one failing source ⇒ `SourceOutcome(error=<code>)`, siblings continue; raise only on programming errors (e.g. bad argument types).
- Only `SourceOutcome.error` carries the **stable code** from `map_query_error`; the human message is logged via `self.logger`/module `logger`, never returned (no policy leakage).
- `datetime.now(timezone.utc)` for `snapshot_at`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the models and `ERROR_STATUS` — *why*: TASK-3781 maps `SourceOutcome.error` codes back to HTTP statuses without re-running `map_query_error`.
2. Write `map_query_error` with lazy querysource imports and cause-chain walk — *why*: the error may be chained by TASK-3779.
3. Write `_execution_order(sources)` — *why*: join/union need their sibling's ALREADY-executed frame (`apply_transform(frames=…)`).
4. Write `_conditions_for(key, src, overrides)` — *why*: single place implementing locked-wins + ignored_params + querylimit.
5. Write `execute_sources` — fetch, transform off-loop, serialise, isolate failures.
6. Tests.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` (CREATE) — models + error mapping
```python
"""Python reference executor for linked A2UI surfaces (FEAT-598 spec §3 M5).

Fetches every ``parrot_data_sources`` entry through ``QuerySlugSource`` (tenant-aware, optional FEAT-150
principal), applies the declarative DSL off the event loop and returns per-source outcomes. Never raises
for data errors: a failing source yields ``SourceOutcome(error=<stable code>)``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from pydantic import BaseModel, Field

from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import LinkedDataSource

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd
    from parrot.auth.permission import PermissionContext

logger = logging.getLogger(__name__)

ERROR_STATUS: dict[str, int] = {
    "query_not_found": 404,
    "tenant_not_available": 404,
    "tenant_store_unavailable": 503,
    "data_stage": 502,
}


class SourceOutcome(BaseModel):
    """Result of executing one linked source."""

    key: str
    rows: list[dict[str, Any]] | None = None
    snapshot_at: datetime | None = None
    truncated: bool = False
    error: str | None = None          # stable code from map_query_error (a key of ERROR_STATUS)
    ignored_params: list[str] = Field(default_factory=list)


class ExecutionOutcome(BaseModel):
    """Outcomes of every source of one surface, keyed by dataModel root key."""

    outcomes: dict[str, SourceOutcome]
    frames: dict[str, Any] = Field(default_factory=dict, exclude=True)  # key -> transformed pd.DataFrame (in-process only,
    #                                                                     never serialised); TASK-3785 hands these to
    #                                                                     build_linked_surface for dtype-aware axis checks

    def data_model_patch(self) -> dict[str, Any]:
        """``{root_key: {"rows": [...]}}`` for successful sources only (failed sources keep their old snapshot)."""
        return {key: {"rows": o.rows} for key, o in self.outcomes.items() if o.error is None and o.rows is not None}


def map_query_error(exc: BaseException) -> tuple[int, str]:
    """Map a fetch exception to ``(http_status, code)`` (spec §3 M5 table; walks __cause__/__context__)."""
    try:
        from querysource.exceptions import QueryAccessDenied
        from querysource.tenants import TenantError
    except ImportError:  # querysource absent → generic data-stage failure
        return 502, "data_stage"
    # FILL IN: walk exc → __cause__ → __context__ (max depth ~5, stop on cycles); first QueryAccessDenied →
    #          (404, "query_not_found"); first TenantError → by .error_code per the table (unknown code → 502
    #          "data_stage"); nothing matched → (502, "data_stage") — bounded by the §Implementation Notes table.
    raise NotImplementedError
```
**Why this shape**: the model field list is fixed by spec §2; `ERROR_STATUS` is additive and keeps status mapping in ONE module. The key in `data_model_patch` is the source key, which by the descriptor contract IS the dataModel root key (G2).

### `executor.py` (CREATE, continued) — ordering, conditions, execute_sources
```python
def _execution_order(sources: Mapping[str, LinkedDataSource]) -> tuple[list[str], dict[str, str]]:
    """Topological order (join.with / union.sources first). Returns (order, failed{key: code})."""
    # FILL IN: collect sibling refs from each source's transform.ops (join → its `with` sibling key, union → its
    #          `sources` list; attribute names exactly as TASK-3769's models define them); Kahn's algorithm with stable
    #          insertion order; a source in a cycle or referencing an unknown key goes to `failed` with "data_stage"
    #          and so does any source depending on a failed one — bounded by "a failing source does not fail others".
    raise NotImplementedError


def _conditions_for(src: LinkedDataSource, overrides: Mapping[str, Any], *,
                    max_fetch_rows: int) -> tuple[dict[str, Any], list[str]]:
    """derive_conditions(request, locked) with non-locked overrides + {'querylimit': min(request.limit or cap, cap)}.

    ``derive_conditions`` never emits ``limit`` (TASK-3770: ``build_conditions`` folds it into the lane-time ``querylimit``),
    so the executor re-applies ``request.limit`` here, bounded by ``max_fetch_rows`` (S8/AC17).
    """
    locked_values = {k: src.conditions[k] for k in src.locked if k in src.conditions}
    ignored = sorted(k for k in overrides if k in src.locked)
    allowed = {k: v for k, v in overrides.items() if k not in src.locked}
    # FILL IN: fold `allowed` into src.request.placeholders (model_copy(update=…)) for names declared in src.params;
    #          names not in params are ALSO ignored (add to `ignored`) — bounded by S5 (conditions are always DERIVED
    #          from request, never hand-merged) and "locked keys ignored → ignored_params".
    request = src.request
    conditions = derive_conditions(request, locked=locked_values)
    conditions["querylimit"] = min(request.limit or max_fetch_rows, max_fetch_rows)  # S8: QuerySource caps the fetch
    return conditions, ignored


async def execute_sources(
    sources: Mapping[str, LinkedDataSource],
    *,
    param_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    pctx: "PermissionContext | None" = None,
    guard: Any | None = None,
    max_snapshot_rows: int | None = None,
    max_fetch_rows: int = 5000,
) -> ExecutionOutcome:
    """Fetch + transform every source (siblings first); per-source failure isolation (spec §3 M5)."""
    from parrot.outputs.a2ui.linked.dsl import apply_transform
    from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
    from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource, to_qs_principal

    principal = to_qs_principal(pctx, channel="ui_surfaces") if pctx is not None else None  # mapped ONCE
    order, failed = _execution_order(sources)
    frames: dict[str, "pd.DataFrame"] = {}
    outcomes: dict[str, SourceOutcome] = {k: SourceOutcome(key=k, error=code) for k, code in failed.items()}
    for key in order:
        src = sources[key]
        conditions, ignored = _conditions_for(src, (param_overrides or {}).get(key, {}), max_fetch_rows=max_fetch_rows)
        inner = QuerySlugSource(src.slug, prefetch_schema_enabled=False, tenant=src.tenant,
                                is_multiquery=src.is_multiquery, multi_output=src.multi_output, principal=principal)
        source = AuthorizingDataSource(inner, guard, pctx_provider=lambda: pctx) if guard is not None else inner
        try:
            frame = await source.fetch(**conditions)
            if src.transform is not None and src.transform.ref is not None:
                logger.warning("linked source %r: ref transform %s skipped in Python", key, src.transform.ref.name)
            elif src.transform is not None:
                frame = await asyncio.to_thread(apply_transform, frame, src.transform, frames=dict(frames))
        except Exception as exc:  # noqa: BLE001 — data errors never fail siblings
            status, code = map_query_error(exc)
            logger.warning("linked source %r (%s, tenant=%s) failed: %s → %s", key, src.slug, src.tenant, exc, status)
            outcomes[key] = SourceOutcome(key=key, error=code, ignored_params=ignored)
            continue
        frames[key] = frame
        # FILL IN: rows = json.loads(frame.to_json(orient="records", date_format="iso")) (JSON-safe, ISO dates,
        #          numeric dtypes preserved); truncate to max_snapshot_rows when set → truncated=True;
        #          outcomes[key] = SourceOutcome(key, rows, snapshot_at=datetime.now(timezone.utc), truncated,
        #          ignored_params=ignored) — bounded by AC17/§7 "Row records are orient=records; dates ISO-8601".
    # FILL IN: a TransformError raised for a source must map to "data_stage" (it does via the generic branch) — keep it.
    return ExecutionOutcome(outcomes=outcomes, frames=frames)
```
**Why**: lazy imports keep `parrot.outputs.a2ui.linked` importable without pandas/querysource (one-way rule, spec §7 last bullet). `prefetch_schema_enabled=False` avoids a second round-trip. `frames=dict(frames)` hands the DSL an immutable snapshot of already-executed siblings. The `lambda: pctx` provider is evaluated at fetch time, matching `AuthorizingDataSource`'s contract.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_executor.py` (CREATE)
```python
"""FEAT-598 M5 — execute_sources / map_query_error (spec §4)."""
from __future__ import annotations

import pandas as pd
import pytest

from parrot.auth.permission import build_principal_context
from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources, map_query_error
from parrot.tools.dataset_manager.sources import query_slug as qsmod

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_qs(monkeypatch):
    """Patch both lazy slots; record constructor kwargs + conditions; per-slug canned frames/errors."""
    # FILL IN: fake class with query()/close() matching TASK-3779's QS vs MultiQS call shapes; `calls` list of
    #          (slug, conditions, kwargs); registry {slug: DataFrame | Exception}.
    raise NotImplementedError


async def test_execute_sources_tenant_passthrough(fake_qs, linked_source): ...   # FILL IN: tenant="acme" reaches QS; is_multiquery → MultiQS
async def test_execute_sources_querylimit_bound(fake_qs, linked_source): ...     # FILL IN: conditions["querylimit"] == max_fetch_rows
async def test_execute_sources_locked_override_ignored(fake_qs, linked_source): ...  # FILL IN: locked key → ignored_params
async def test_execute_sources_partial_failure(fake_qs, linked_source): ...      # FILL IN: one raises, sibling ok, error code set
async def test_execute_sources_passes_principal(fake_qs, linked_source): ...     # FILL IN: pctx → principal kwarg; pctx None → absent
async def test_apply_transform_off_loop(fake_qs, linked_source, monkeypatch): ...  # FILL IN: asyncio.to_thread invoked
async def test_join_sibling_executes_first(fake_qs): ...                          # FILL IN: order respects join.with
async def test_snapshot_rows_truncated(fake_qs, linked_source): ...               # FILL IN: max_snapshot_rows cut → truncated


def test_map_query_error_tenant_codes():
    # FILL IN: QueryAccessDenied → (404, "query_not_found") (never "denied"); TenantError codes per table
    #          (build with querysource.tenants.TenantError(msg, error_code=…)); chained RuntimeError(...) from TenantError;
    #          ValueError → (502, "data_stage"); every returned code ∈ ERROR_STATUS
    ...
```
`linked_source` comes from TASK-3769's `tests/outputs/a2ui/linked/conftest.py`; `fake_qs` stays local to this file (conftest is not edited).

### FILL IN checklist
- [ ] `map_query_error` — cause-chain walk + table; bounded by §Implementation Notes table.
- [ ] `_execution_order` — Kahn + failure propagation; bounded by partial-failure isolation.
- [ ] `_conditions_for` — override folding + ignored names; bounded by S5.
- [ ] `execute_sources` — row serialisation, truncation, snapshot_at; bounded by AC17 / §7.
- [ ] tests — every body; bounded by spec §4 M5/M6 rows.

---

## Acceptance Criteria

- [ ] `querylimit == min(request.limit or max_fetch_rows, max_fetch_rows)` on every fetch (AC17); `ExecutionOutcome.frames` carries the transformed DataFrames and is excluded from `model_dump`.
- [ ] Tenant routed from the descriptor only; `MultiQS` for `is_multiquery` (AC4/AC5).
- [ ] `pctx` ⇒ `principal=` on every source; `pctx=None` ⇒ no principal (AC18).
- [ ] Partial failure isolated; `error` holds a stable `ERROR_STATUS` key.
- [ ] `map_query_error` matches the table; `QueryAccessDenied` never yields a "denied" wording.
- [ ] `apply_transform` runs in `asyncio.to_thread`; `ref` transforms skipped with a warning.
- [ ] `import parrot.outputs.a2ui.linked.executor` does not import pandas or querysource at module import time.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_executor.py -q`

---

## Test Specification

See the CREATE test block above (spec §4: `test_execute_sources_querylimit_bound`, `test_apply_transform_off_loop`,
`test_execute_sources_tenant_passthrough`, `test_execute_sources_locked_override_ignored`,
`test_execute_sources_partial_failure`, `test_map_query_error_tenant_codes`, `test_execute_sources_passes_principal`).

---

## Agent Instructions

1. Read spec §2 Data Models, §3 Module 5, §7 Known Risks.
2. Check TASK-3769, TASK-3770, TASK-3773, TASK-3779 are done; read their final signatures (op attribute names, `derive_conditions`, `apply_transform`).
3. Verify the Codebase Contract.
4. Index → `"in-progress"`; implement; complete every `# FILL IN:`.
5. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src`).
6. Move to `sdd/tasks/completed/`, index → `"done"`, Completion Note.

---

## Completion Note


- Task: TASK-3780
- Feature: a2ui-linked-surfaces
- Implementation SHA: 40c4ac17921bb5f313063bdae6dc5cca0e40d4d9
- Closed at (UTC): 2026-09-26T01:07:57+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| coder_record_review | NOT recorded - coder_record_review MCP tool rejects every payload including {} (systemic tool outage, confirmed also on coder_record_feedback and coder_record_native_observation) |
| merge_validation_outcome | failed: same systemic pre-existing failures already characterized (parrot-formdesigner version/schema drift, ai-parrot-embeddings wheel-layout conftest collision), unrelated to this task's diff. Task's own scoped tests: 84 passed (packages/ai-parrot/tests/outputs/a2ui/linked). See issue:181bd0c01bb4. |
| seat_summary | Seat: sonnet - Backend: native - Model: sonnet - Attempts: 1 - Duration: n/a - Tokens: n/a |
