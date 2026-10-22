# TASK-4107: `LinkedSurfaceService` — persist-time python gate + `fetch_source()` one-source lane

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4106
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Codex S1: one-source execution belongs in `LinkedSurfaceService` — it already owns the guard,
owner/principal authorization and error mapping — never in the HTTP handler. Codex S2: the caller supplies parameter
overrides only; conditions are rebuilt server-side from the persisted descriptor (`executor._conditions_for` already
does this and ignores `locked`/undeclared names). Spec AC9: an unregistered transformer is rejected at persist time.

---

## Scope

- In `validate_for_persistence`, run `validate_python_transform` on every source carrying `transform.python`;
  raise `CatalogValidationError(issues=[...])` on any problem.
- Add `SourceFetchOutcome` (Pydantic) and `async fetch_source(envelope, key, *, params, pctx)`.
- Write tests (service-level, `execute_sources` monkeypatched — the established pattern).

**NOT in scope**: the HTTP route/handler (TASK-4108); identity choice (the handler passes the pctx in).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` | MODIFY | persist gate + `SourceFetchOutcome` + `fetch_source` |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_service_python.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog.base import CatalogValidationError   # verified: test_service.py:14; ctor base.py:340 (message, *, code=None, issues=None, ...)
from parrot.outputs.a2ui.linked.models import DerivedDataSource, LinkedDataSource, LinkedSource, LinkedSources  # verified: service.py:21
from parrot.outputs.a2ui.linked.pytransform import validate_python_transform  # created by TASK-4105
from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources  # verified: service.py:127,162 (function-local imports)
from parrot.outputs.a2ui.linked import executor as executor_mod      # verified: test_service.py:15 (monkeypatch target)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py
def _sources(envelope: CreateSurface | dict[str, Any]) -> dict[str, LinkedSource]          # line 54
class RefreshOutcome(BaseModel): envelope; snapshot_at; warnings; error_status; error_code  # line 44-51 (pattern to mirror)
class LinkedSurfaceService:                                                                # line 67
    def __init__(self, *, guard: Any | None, max_fetch_rows: int = 5000, max_snapshot_rows: int = 500)  # line 76
    def _require_guard(self) -> Any                                                        # line 82 → LinkedGuardRequired
    async def _assert_sources_allowed(self, sources, owner_pctx) -> None                   # line 87; skips derived; raises AuthorizationRequired
    async def validate_for_persistence(self, envelope: CreateSurface, *, owner_pctx) -> None  # line 115
        # line 120-123: has_data_sources → validate_envelope(TOOL) → _assert_sources_allowed
    async def refresh(self, envelope, *, params, owner_pctx) -> RefreshOutcome             # line 158; execute_sources call shape at 184-191

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py
async def execute_sources(sources, *, param_overrides=None, pctx, guard, max_snapshot_rows=None, max_fetch_rows) -> ExecutionOutcome  # line 298
class SourceOutcome(BaseModel): key; rows; snapshot_at; truncated; error; ignored_params     # line 48-56
def _conditions_for(src, overrides, *, max_fetch_rows)   # line 168 — locked + undeclared overrides ignored (S2 for free)

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:584-587 — every persist caller already maps
#   CatalogValidationError → 422 {"message": "Invalid linked envelope", "errors": exc.issues}

# tests: _FakeGuard (test_service.py:23), owner fixture (test_service.py:37), _dict_envelope (test_service.py:71)
```

### Does NOT Exist
- ~~`LinkedSurfaceService.fetch_source`~~ / ~~`SourceFetchOutcome`~~ — created by this task.
- ~~a "raw conditions" input anywhere in the service~~ — never accept conditions from the caller (S2).
- ~~persistence inside `fetch_source`~~ — it NEVER writes; the endpoint is read-only (spec §2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_service_python.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#LinkedSurfaceService",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#LinkedSurfaceService.validate_for_persistence",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py#RefreshOutcome",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#execute_sources",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#CatalogValidationError"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `SourceFetchOutcome` below `RefreshOutcome` — *why*: same shape family the handler already serializes.
2. Add the python gate at the end of `validate_for_persistence` — *why*: AC9; `CatalogValidationError` is already 422 at every caller.
3. Add `fetch_source` after `refresh` — *why*: S1/S2; it reuses `_assert_sources_allowed` and `execute_sources` unchanged.
4. Write tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` (MODIFY — model)
```python
# AFTER — insert below class RefreshOutcome (ends service.py:51)
class SourceFetchOutcome(BaseModel):
    """Result of LinkedSurfaceService.fetch_source — one source, never persisted (FEAT-636 S1)."""

    key: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    snapshot_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    error_status: int | None = None
    error_code: str | None = None
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` (MODIFY — persist gate)
```python
# occurrences: 1 (verified: grep -c 'async def validate_for_persistence(self, envelope: CreateSurface, *, owner_pctx: "PermissionContext") -> None:' linked/service.py)
# AFTER — append below `await self._assert_sources_allowed(_sources(envelope), owner_pctx)` (service.py:123), inside the method
        from parrot.outputs.a2ui.linked.pytransform import validate_python_transform

        issues: list[dict[str, Any]] = []
        for key, src in _sources(envelope).items():
            if src.transform is None or src.transform.python is None:
                continue
            # FILL IN: for each problem from validate_python_transform(src.transform.python) append
            #   {"code": "python_transform_invalid", "message": problem,
            #    "path": f"/metadata/extensions/parrot_data_sources/{key}/transform/python"} — bounded by AC9
        if issues:
            raise CatalogValidationError("invalid python transform", issues=issues)
```
Add `from parrot.outputs.a2ui.catalog.base import CatalogValidationError` function-locally next to the existing
`from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope` (service.py:118) — *because* `linked/` must
never import `catalog/` at module import time (service.py:117 comment).

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py` (MODIFY — fetch_source)
```python
# AFTER — insert below `refresh` (ends service.py:219), inside LinkedSurfaceService
    async def fetch_source(
        self, envelope: dict[str, Any], key: str, *, params: Mapping[str, Any], pctx: "PermissionContext"
    ) -> SourceFetchOutcome:
        """One-source guarded fetch (+ python transform) for ``POST …/sources/{key}/data`` (FEAT-636 S1/S2).

        ``params`` are placeholder overrides only — conditions are rebuilt from the persisted descriptor by
        ``execute_sources`` (locked/undeclared names ignored and reported). Executes under ``pctx`` (the handler
        chooses viewer or owner). Never persists.

        Raises:
            LinkedGuardRequired: no data-plane guard configured.
            AuthorizationRequired: ``pctx`` may not read this ``(tenant, slug)``.
        """
        from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, execute_sources

        sources = _sources(envelope)
        src = sources.get(key)
        if not isinstance(src, LinkedDataSource):
            # unknown key, or a derived view (it has no fetch of its own) → 404, no existence oracle
            return SourceFetchOutcome(key=key, error_status=404, error_code="source_not_found")
        single = {key: src}
        await self._assert_sources_allowed(single, pctx)
        outcome = await execute_sources(
            single,
            param_overrides={key: dict(params)},
            pctx=pctx,
            guard=self.guard,
            max_snapshot_rows=None,
            max_fetch_rows=self.max_fetch_rows,
        )
        # FILL IN: map outcome.outcomes[key] → SourceFetchOutcome: error → error_code + ERROR_STATUS.get(code, 502);
        #   success → rows, snapshot_at, truncated = len(rows) >= self.max_fetch_rows; ignored_params → a warning
        #   "ignored params [...]" (same wording as refresh, service.py:199-200) — bounded by AC6/AC7.
        raise NotImplementedError
```
**Why**: `max_snapshot_rows=None` because the endpoint returns the full (capped) frame, not a ≤500-row snapshot;
the post-transform cap is already inside `apply_python_transform` (TASK-4105). Single-source execution is safe because a
python source is terminal and depends on no sibling (TASK-4104 AC2). Add `LinkedDataSource` to the existing models import
at service.py:21.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_service_python.py` (CREATE)
```python
"""FEAT-636 TASK-4107 — persist-time python gate and fetch_source."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.linked import executor as executor_mod
from parrot.outputs.a2ui.linked.executor import ExecutionOutcome, SourceOutcome
from parrot.outputs.a2ui.linked.service import LinkedGuardRequired, LinkedSurfaceService
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

from .test_service import _dict_envelope, _envelope, _FakeGuard, owner  # noqa: F401 — established fixtures/helpers


async def test_fetch_source_passes_params_and_pctx(owner, linked_source, monkeypatch) -> None:
    seen: dict = {}

    async def _fake(sources, **kwargs):
        seen.update(kwargs, keys=list(sources))
        return ExecutionOutcome(outcomes={"activity": SourceOutcome(key="activity", rows=[{"a": 1}],
                                                                    snapshot_at=datetime.now(timezone.utc))})

    monkeypatch.setattr(executor_mod, "execute_sources", _fake)
    out = await LinkedSurfaceService(guard=_FakeGuard()).fetch_source(
        _dict_envelope(linked_source), "activity", params={"firstdate": "TODAY"}, pctx=owner
    )
    assert out.rows == [{"a": 1}] and out.error_status is None
    assert seen["keys"] == ["activity"] and seen["param_overrides"] == {"activity": {"firstdate": "TODAY"}}
    assert seen["pctx"] is owner and seen["max_snapshot_rows"] is None


async def test_fetch_source_requires_guard(owner, linked_source) -> None:
    with pytest.raises(LinkedGuardRequired):
        await LinkedSurfaceService(guard=None).fetch_source(_dict_envelope(linked_source), "activity", params={}, pctx=owner)


# FILL IN: test_fetch_source_unknown_key → error_status 404, code "source_not_found" (also for a derived key)
# FILL IN: test_fetch_source_transform_error → outcome error "transform_failed" → error_status 422
# FILL IN: test_fetch_source_ignored_params_warning
# FILL IN: test_persist_gate_unregistered → _envelope(linked_source) with transform python "nope" →
#   CatalogValidationError whose issues[0]["path"] ends with "/transform/python" (AC9); a registered
#   transformer (monkeypatched registry) passes
```

### FILL IN checklist
- [ ] persist gate issue building — AC9
- [ ] `fetch_source` outcome mapping — AC6/AC7
- [ ] four remaining tests

---

## Acceptance Criteria

- [ ] AC7 (spec): params only; conditions rebuilt server-side; locked ignored (reported as a warning).
- [ ] AC9 (spec, persist half): unregistered transformer / alias mismatch rejected at `validate_for_persistence` (→ 422 at callers).
- [ ] Guard fail-closed (`LinkedGuardRequired`) and `AuthorizationRequired` propagate unchanged.
- [ ] AC11 (spec): `test_service.py` passes unchanged.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_service_python.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_service.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`), with `PYTHONPATH=packages/ai-parrot/src`.
2. Confirm TASK-4106 is `done` in the per-spec index.
3. Verify the Codebase Contract; start from the blueprint; complete every `FILL IN` (remove the `raise NotImplementedError`).
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4107 linked-a2ui-recipes-transforms verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: codex gpt-5.6-terra, attempt 1
**Date**: 2026-10-06
**Notes**: Diff reviewed by the orchestrator against the task. Evidence: linked suite 238 passed (incl. test_service_python.py)

**Deviations from spec**: none
