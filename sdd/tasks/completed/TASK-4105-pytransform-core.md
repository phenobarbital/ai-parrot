# TASK-4105: `linked/pytransform.py` — validation gate, output selection, capped execution, `TransformStageError`

**Feature**: FEAT-636 — Linked A2UI surfaces — server-executed Python recipe transformers
**Spec**: `sdd/specs/linked-a2ui-recipes-transforms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4104
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 + §2 New Public Interfaces. ONE shared module that every Python lane calls (executor bake/refresh,
the service's `fetch_source`, the toolkit build gate) so all lanes produce identical frames by construction (AC4).
Codex design research folded in: S5 (alias vs manifest), S6 (result→rows contract), S7 (stable transform-stage
codes), S8 (shared gate), S9 (post-transform row cap).

---

## Scope

- Create `pytransform.py` with `TransformStageError`, `validate_python_transform`, `select_output_frame`,
  `apply_python_transform`, plus the three code constants.
- Write unit tests with a scoped, test-registered transformer.

**NOT in scope**: wiring into `executor.py` (TASK-4106), `service.py` (TASK-4107) or the toolkit (TASK-4109);
`ERROR_STATUS` edits (TASK-4106 owns `executor.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py` | CREATE | shared Python-transform core |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_pytransform.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.linked.models import PythonTransform          # created by TASK-4104 (linked/models.py)
from parrot.outputs.a2ui.recipes.transformers import transformer_registry  # verified: recipes/transformers.py (module-level instance)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py
TransformerFunc = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
class RegisteredTransformer:                     # frozen dataclass
    func: TransformerFunc
    manifest: TransformerManifest
    def __call__(self, inputs: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]
class TransformerRegistry:
    def get(self, name: str) -> RegisteredTransformer      # raises KeyError listing registered names
    def register(self, name, func, *, requires_columns=None, description="", params_schema=None) -> RegisteredTransformer
transformer_registry = TransformerRegistry()

# packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py:313
class TransformerManifest(BaseModel):
    name: str
    description: str
    requires_columns: dict[str, list[str]]   # keyed by INPUT ALIAS (not dataset name)
    params_schema: dict[str, Any]

# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py:521-541 — how recipes call a transformer:
#   step_inputs = {alias: frame}; result = transformer_registry.get(name)(step_inputs, params)

# TS twin of the output-selection rule: ui/.../a2ui/linked/fetch.ts:30-59 (selectFrame)
#   multi_output override → 'result' → sole key → FrameSelectionError (ambiguous)
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.linked.pytransform`~~ — created by this task.
- ~~`validate_inputs(spec, ...)` for linked descriptors~~ — `validate_inputs` takes a recipe `TransformStep`; do NOT call it. Its
  empty-frame rejection is WRONG for linked sources (an empty slug result is legitimate — spec §7).
- ~~`transformer_registry.has()` / `.exists()`~~ — only `get` (KeyError), `register`, `manifest`, `list` exist.
- ~~async transformers~~ — registered transformers are plain sync callables; run them with `asyncio.to_thread`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_pytransform.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#TransformerRegistry",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/transformers.py#RegisteredTransformer",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py#TransformerManifest"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `linked/` imports heavyweight siblings function-locally (`service.py:117` precedent) — import
  `transformer_registry` inside the functions, never at module top.
- Pure and deterministic: no I/O, no logging of row content (rows may hold PII) — log names/counts only.
- Gate (`validate_python_transform`) NEVER executes the transformer.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module below verbatim — *why*: names/signatures are fixed by spec §2 and consumed by three later tasks.
2. Complete the `FILL IN` markers — *why*: they hold the only judgement calls (alias check, value coercion).
3. Write the tests and run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/pytransform.py` (CREATE)
```python
"""Server-side Python transformers for linked sources (FEAT-636 M2).

One shared code path for every Python lane — executor bake/refresh, ``LinkedSurfaceService.fetch_source`` and
the toolkit build gate — so all lanes produce identical frames by construction. Transformers are resolved BY
REGISTERED NAME from ``transformer_registry`` (G1: never stored or dynamically imported code).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

    from parrot.outputs.a2ui.linked.models import PythonTransform

logger = logging.getLogger(__name__)

TRANSFORMER_NOT_REGISTERED = "transformer_not_registered"
TRANSFORM_FAILED = "transform_failed"
TRANSFORM_INVALID_OUTPUT = "transform_invalid_output"


class TransformStageError(Exception):
    """A transform-stage failure; ``code`` is a stable key of ``executor.ERROR_STATUS`` (all map to 422)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def validate_python_transform(spec: "PythonTransform") -> list[str]:
    """Build/persist-time gate: registry membership + ``input_alias`` vs manifest. Never executes.

    Returns:
        Human-readable problems; an empty list means the spec passes.
    """
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    try:
        registered = transformer_registry.get(spec.transformer)
    except KeyError as exc:
        return [str(exc)]
    aliases = list(registered.manifest.requires_columns)
    # FILL IN: when `aliases` is non-empty — more than one alias → problem "multi-input transformer {name!r} is
    #   not supported for linked sources in v1"; exactly one alias that differs from spec.input_alias → problem
    #   "transformer {name!r} expects input alias {alias!r}; set python.input_alias" — bounded by S5/AC9.
    #   No manifest aliases → no alias problem (the default "source" is accepted).
    return []


def select_output_frame(result: Any, output: str | None) -> "pd.DataFrame":
    """Reduce a transformer's returned dict to ONE frame (rule twin of ``fetch.ts::selectFrame``).

    ``output`` override → ``"result"`` key → sole key → ambiguous. The selected value must be a DataFrame
    or a list of row mappings.

    Raises:
        TransformStageError: ``transform_invalid_output`` on a non-mapping result, a missing/ambiguous key,
            or a value that is neither a DataFrame nor a list of mappings.
    """
    import pandas as pd

    if not isinstance(result, Mapping):
        raise TransformStageError(TRANSFORM_INVALID_OUTPUT, f"transformer returned {type(result).__name__}, not a dict")
    # FILL IN: pick the value — `output` set and absent → error naming sorted(result) keys; else "result" key;
    #   else the sole key; else ambiguous error naming sorted keys — bounded by OQ-C (same wording family as
    #   fetch.ts FrameSelectionError).
    selected: Any = None
    if isinstance(selected, pd.DataFrame):
        return selected
    # FILL IN: list whose items are all Mapping → pd.DataFrame(selected) (an empty list → empty DataFrame);
    #   anything else (scalar, nested dict, list of scalars) → TransformStageError(TRANSFORM_INVALID_OUTPUT, ...)
    #   — bounded by S6.
    raise TransformStageError(TRANSFORM_INVALID_OUTPUT, "selected output is not a frame or a list of rows")


async def apply_python_transform(frame: "pd.DataFrame", spec: "PythonTransform", *, max_rows: int) -> "pd.DataFrame":
    """Run the registered transformer off-thread on ``{spec.input_alias: frame}`` and cap the result.

    Raises:
        TransformStageError: ``transformer_not_registered`` | ``transform_failed`` | ``transform_invalid_output``.
    """
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    try:
        registered = transformer_registry.get(spec.transformer)
    except KeyError as exc:
        raise TransformStageError(TRANSFORMER_NOT_REGISTERED, str(exc)) from exc
    try:
        result = await asyncio.to_thread(registered, {spec.input_alias: frame}, dict(spec.params))
    except Exception as exc:  # noqa: BLE001 — any transformer failure is transform-stage (S7)
        raise TransformStageError(TRANSFORM_FAILED, f"{spec.transformer}: {exc}") from exc
    out = select_output_frame(result, spec.output)
    if len(out) > max_rows:
        logger.warning("python transformer %r produced %d rows; capped at %d", spec.transformer, len(out), max_rows)
        out = out.head(max_rows)
    return out
```
**Why this shape**: the three code strings are module constants so `executor.ERROR_STATUS` (TASK-4106) and the tests
reference one spelling. The cap lives here (S9) so no caller can forget it; it truncates with `head` (stable order),
never samples.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_pytransform.py` (CREATE)
```python
"""FEAT-636 TASK-4105 — pytransform gate, output selection, capped execution."""

import pandas as pd
import pytest

from parrot.outputs.a2ui.linked.models import PythonTransform
from parrot.outputs.a2ui.linked.pytransform import (
    TRANSFORM_FAILED, TRANSFORM_INVALID_OUTPUT, TRANSFORMER_NOT_REGISTERED,
    TransformStageError, apply_python_transform, select_output_frame, validate_python_transform,
)
from parrot.outputs.a2ui.recipes.transformers import transformer_registry


@pytest.fixture
def registered(monkeypatch):
    """Isolate the process-wide registry: tests register into a private dict."""
    monkeypatch.setattr(transformer_registry, "_transformers", {})

    def double(inputs, params):
        df = inputs["source"]
        return {"result": pd.concat([df, df], ignore_index=True)}

    transformer_registry.register("t636_double", double)
    return transformer_registry


async def test_apply_runs_and_caps(registered) -> None:
    frame = pd.DataFrame({"a": [1, 2, 3]})
    out = await apply_python_transform(frame, PythonTransform(transformer="t636_double"), max_rows=4)
    assert len(out) == 4


async def test_apply_unregistered(registered) -> None:
    with pytest.raises(TransformStageError) as info:
        await apply_python_transform(pd.DataFrame(), PythonTransform(transformer="nope"), max_rows=10)
    assert info.value.code == TRANSFORMER_NOT_REGISTERED


# FILL IN: test_apply_failure → a raising transformer → TRANSFORM_FAILED
# FILL IN: test_select_output_frame_rule → override / "result" / sole key / ambiguous / missing override /
#   records list / empty list / scalar → TRANSFORM_INVALID_OUTPUT where applicable (S6)
# FILL IN: test_validate_gate → unregistered name; single manifest alias mismatch; multi-alias manifest;
#   no manifest aliases → [] (S5/S8) — register with requires_columns={...}
```

### FILL IN checklist
- [ ] `validate_python_transform` alias rules — S5/AC9
- [ ] `select_output_frame` key selection + value coercion — OQ-C/S6
- [ ] three remaining test groups

---

## Acceptance Criteria

- [ ] AC4 (spec, core half): one shared helper set (`apply_python_transform` + `select_output_frame`).
- [ ] AC5 (spec, codes): three stable transform-stage codes defined as constants.
- [ ] AC6 (spec, cap): output capped at `max_rows` post-transform.
- [ ] AC9 (spec, gate): unregistered name / alias mismatch / multi-input manifest reported without executing.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_pytransform.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug linked-a2ui-recipes-transforms --feature-id FEAT-636`), with `PYTHONPATH=packages/ai-parrot/src`.
2. Confirm TASK-4104 is `done` in `sdd/tasks/index/linked-a2ui-recipes-transforms.json`.
3. Verify the Codebase Contract; start from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands; commit only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-4105 linked-a2ui-recipes-transforms verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: codex gpt-5.6-terra, attempt 1
**Date**: 2026-10-06
**Notes**: Diff reviewed by the orchestrator against the task. Evidence: tests/outputs/a2ui/linked 225 passed (incl. test_pytransform.py)

**Deviations from spec**: none
