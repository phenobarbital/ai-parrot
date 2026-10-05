# TASK-4106: Executor — python-transform branch in `_run_source` + 422 transform-stage codes

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4105
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. `execute_sources` is the single Python execution engine behind bake, persist (`ensure_snapshot`),
server refresh and — after TASK-4107 — the per-source endpoint. Adding the python branch HERE is what makes Python-lane
parity intrinsic (AC4). Codex S7: today every exception is mapped by `map_query_error` to `data_stage` 502; transform
failures must map to their own stable 422 codes instead.

---

## Scope

- In `_run_source`, apply `apply_python_transform` when `src.transform.python` is set (before the existing `ref` branch).
- Add the three transform-stage codes to `ERROR_STATUS` with status 422.
- Make `map_query_error` return `(422, exc.code)` when the exception chain contains a `TransformStageError`.
- Write tests.

**NOT in scope**: `dependencies_of` changes (a python spec has `ops=None`, so it already contributes no edges — only
assert it); service/handler wiring (TASK-4107/4108).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` | MODIFY | python branch, ERROR_STATUS codes, `map_query_error` |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_executor_python.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.linked.pytransform import (  # created by TASK-4105
    TRANSFORM_FAILED, TRANSFORM_INVALID_OUTPUT, TRANSFORMER_NOT_REGISTERED, TransformStageError, apply_python_transform,
)
from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, dependencies_of, execute_sources, map_query_error  # verified: executor.py:27,100,298,74
from parrot.outputs.a2ui.linked import LinkedDataSource, TransformSpec  # verified: test_executor.py:13
from parrot.tools.dataset_manager.sources import query_slug as qsmod   # verified: test_executor.py:16
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py
ERROR_STATUS: dict[str, int] = {                     # line 27-32
    "query_not_found": 404, "tenant_not_available": 404, "tenant_store_unavailable": 503, "data_stage": 502,
}
def map_query_error(exc: BaseException) -> tuple[int, str]:     # line 74; walks __cause__/__context__ (depth 5)
    # line 76-80: try-import querysource; ImportError → (502, "data_stage") EARLY RETURN
def dependencies_of(src: LinkedSource) -> list[str]:            # line 100; reads src.transform.ops only
async def _run_source(key, src, overrides, frames, *, sources, principal, pctx, guard,
                      max_fetch_rows: int, probed=()) -> pd.DataFrame:   # line 231
    # line 283: frame = await source.fetch(**copy.deepcopy(conditions))
    # line 284-285: ref → logger.warning(... skipped in Python)
    # line 286-287: elif src.transform is not None → apply_transform(...)
# line 372-384 inside execute_sources: `except Exception` → status, code = map_query_error(exc) → SourceOutcome(error=code)

# tests: fake_qs fixture (test_executor.py:41-78; recorder.registry[slug] = DataFrame | exception),
#        _real_querysource autouse fixture (test_executor.py:21), linked_source (conftest.py:27, slug="epson_field_activity",
#        target="/activity/rows")
```

### Does NOT Exist
- ~~a separate transform error channel in `SourceOutcome`~~ — `SourceOutcome.error` is the one stable-code field (line 55); reuse it.
- ~~`apply_transform` handling `python`~~ — `dsl.apply_transform` handles `ops` only; never pass a python spec to it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_executor_python.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#map_query_error",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#_run_source",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#execute_sources",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py#dependencies_of"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Extend `ERROR_STATUS` — *why*: `service.refresh/ensure_snapshot` resolve HTTP status through it (`ERROR_STATUS.get(code, 502)`).
2. Add the `TransformStageError` check at the TOP of `map_query_error`, before the querysource try-import —
   *why*: the ImportError early return (line 79-80) would otherwise swallow transform errors as `data_stage`.
3. Insert the python branch in `_run_source` — *why*: one branch serves every Python lane (AC4).
4. Write tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` (MODIFY — ERROR_STATUS)
```python
# occurrences: 1 (verified: grep -c 'ERROR_STATUS: dict\[str, int\] = {' linked/executor.py)
# REPLACE linked/executor.py:27-32 with:
ERROR_STATUS: dict[str, int] = {
    "query_not_found": 404,
    "tenant_not_available": 404,
    "tenant_store_unavailable": 503,
    "data_stage": 502,
    # FEAT-636: transform-stage failures (S7) — a bad transform is the caller's/author's problem, not the data's.
    "transformer_not_registered": 422,
    "transform_failed": 422,
    "transform_invalid_output": 422,
}
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` (MODIFY — map_query_error)
```python
# AFTER — insert as the FIRST statements of map_query_error's body, above `try:` (verified: executor.py:76)
    from parrot.outputs.a2ui.linked.pytransform import TransformStageError

    # FILL IN: walk exc → __cause__/__context__ (bounded by _MAX_CAUSE_DEPTH, `seen` id set like the loop below);
    #   on a TransformStageError return (ERROR_STATUS[found.code], found.code) — bounded by S7/AC5. Fall through
    #   to the existing logic when none is found.
```

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py` (MODIFY — _run_source)
```python
# occurrences: 1 (verified: grep -c 'if src.transform is not None and src.transform.ref is not None:' linked/executor.py)
# REPLACE the `if src.transform ... ref ...:` line (executor.py:284) so the chain reads:
    if src.transform is not None and src.transform.python is not None:
        from parrot.outputs.a2ui.linked.pytransform import apply_python_transform

        frame = await apply_python_transform(frame, src.transform.python, max_rows=max_fetch_rows)
    elif src.transform is not None and src.transform.ref is not None:
        logger.warning("linked source %r: ref transform %s skipped in Python", key, src.transform.ref.name)
    elif src.transform is not None:
        frame = await asyncio.to_thread(apply_transform, frame, src.transform, frames=dict(frames))
    return frame
```
**Why**: the python branch goes first and is exclusive (the XOR guarantees only one member is set). The derived branch
(line 252-266) is untouched — TASK-4104 already forbids `python` on a derived source.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_executor_python.py` (CREATE)
```python
"""FEAT-636 TASK-4106 — executor python branch and transform-stage codes."""

from __future__ import annotations

import pandas as pd
import pytest

from parrot.outputs.a2ui.linked import TransformSpec
from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, dependencies_of, execute_sources, map_query_error
from parrot.outputs.a2ui.linked.pytransform import TRANSFORM_FAILED, TransformStageError
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

from .test_executor import _real_querysource, fake_qs  # noqa: F401 — reuse the established fixtures


@pytest.fixture
def py_registry(monkeypatch):
    monkeypatch.setattr(transformer_registry, "_transformers", {})
    transformer_registry.register("t636_count", lambda inputs, params: {"result": [{"n": len(inputs["source"])}]})
    return transformer_registry


async def test_execute_sources_applies_python(fake_qs, linked_source, py_registry) -> None:
    fake_qs.registry["epson_field_activity"] = pd.DataFrame({"a": [1, 2, 3]})
    src = linked_source.model_copy(update={"transform": TransformSpec.model_validate({"python": {"transformer": "t636_count"}})})
    outcome = await execute_sources({"activity": src}, pctx=None, guard=None, max_snapshot_rows=500, max_fetch_rows=5000)
    assert outcome.outcomes["activity"].rows == [{"n": 3}]


def test_map_query_error_transform_stage() -> None:
    exc = RuntimeError("wrapped")
    exc.__cause__ = TransformStageError(TRANSFORM_FAILED, "boom")
    assert map_query_error(exc) == (422, TRANSFORM_FAILED)
    assert ERROR_STATUS[TRANSFORM_FAILED] == 422


# FILL IN: test_unregistered_transformer_outcome → outcome.error == "transformer_not_registered", sibling unaffected
# FILL IN: test_dependencies_of_python_none → dependencies_of(python src) == []
# FILL IN: test_ops_and_ref_branches_unchanged → an ops source still transforms; a ref source still logs+skips
```

### FILL IN checklist
- [ ] `map_query_error` transform-stage walk — S7/AC5
- [ ] three remaining tests

---

## Acceptance Criteria

- [ ] AC4 (spec, executor half): bake/persist/refresh all apply the python transformer through `_run_source`.
- [ ] AC5 (spec): transform-stage failures → stable 422 codes, distinct from `data_stage` 502.
- [ ] AC11 (spec): `test_executor.py` passes unchanged.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_executor_python.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_executor.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`), with `PYTHONPATH=packages/ai-parrot/src`.
2. Confirm TASK-4105 is `done` in the per-spec index.
3. Verify the Codebase Contract; start from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4106 linked-a2ui-recipes-transforms verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
