---
type: Wiki Overview
title: 'TASK-1454: StructuredOutputBase — extract the shared structured-output contract'
id: doc:sdd-tasks-completed-task-1454-structured-output-base-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of the spec. The deterministic-extraction + envelope-routing
  +
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats.chart
  rel: mentions
---

# TASK-1454: StructuredOutputBase — extract the shared structured-output contract

**Feature**: FEAT-223 — Structured Artifact Contract
**Spec**: `sdd/specs/structured-artifact-contract.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. The deterministic-extraction + envelope-routing +
graceful-degradation logic currently lives **inlined inside** `StructuredTableRenderer`. The chart
and map renderers each reimplement the envelope routing (`model_dump(..., exclude={"data"})` +
`response.data = ...`) and the JSON extraction independently. This task extracts that pattern into a
reusable base/mixin so every `structured_*` renderer conforms to ONE contract (Jesus's homologation
decision, Q1). This is the foundation; Modules 2 and 4 build on it.

Resolves **Impl-1** (base class vs mixin): decide here, document the choice in the completion note.

---

## Scope

- Create `StructuredOutputBase` in `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py`
  (or a mixin in the same module — your call per Impl-1), inheriting/co-operating with the existing
  `BaseChart` so all three renderers can adopt it without changing their registration.
- Provide `_extract_rows(self, response) -> pd.DataFrame` — deterministic row extraction that delegates
  to `TableRenderer._extract_data` (the SAME call `StructuredTableRenderer` uses today). Must never raise:
  on failure return an empty/None sentinel the caller can detect.
- Provide `_route_envelope(self, response, out, rows, explanation)` — the shared envelope contract:
  `data` excluded from `out`; rows routed to `response.data`; explanation surfaced as the `wrapped`
  return value; never raises.
- Refactor `StructuredTableRenderer` to use the base for extraction + envelope routing. **Behavior MUST
  be unchanged** — the existing `test_structured_table_renderer.py` / `test_structured_table.py` suites
  must pass without modification (other than imports if the helper moves).
- Keep the shared `_extract_json_code` JSON-extraction helper reachable from the base (it is currently
  duplicated identically across the three renderers) so Modules 2/4 can drop their copies.

**NOT in scope**: refactoring the chart renderer (TASK-1455), the map renderer or `ArtifactType.MAP`
(TASK-1457), chart-config convergence (TASK-1456), or any new tests beyond keeping the table suite green.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py` | CREATE | `StructuredOutputBase` (or mixin) — `_extract_rows`, `_route_envelope`, shared JSON extraction |
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py` | MODIFY | Adopt the base for extraction + envelope routing; behavior unchanged |
| `packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py` | MODIFY | Only if helper import paths change; tests must still pass |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFY each anchor with `grep`/`read` before coding — line numbers drift.

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn  # outputs.py:37/508/471
# Within ai-parrot-visualizations:
from parrot.outputs.formats.chart import BaseChart                                 # chart.py:20
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/base.py
class BaseRenderer(ABC):                                  # :54
    @classmethod
    def _get_content(cls, response: Any) -> Any: ...      # :69

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/chart.py
class BaseChart(BaseRenderer):                            # :20
    # abstractmethod _render_chart_content(chart_obj, **kwargs) -> str  (concrete renderers stub it)

# packages/ai-parrot/src/parrot/outputs/formats/table.py
class TableRenderer(BaseRenderer):                        # :52
    def _extract_data(self, response: Any) -> pd.DataFrame: ...   # :57  (deterministic; raises on bad input)

# packages/ai-parrot/src/parrot/outputs/formats/table_types.py
def base_column_types(df: pd.DataFrame) -> dict[str, str]: ...    # :42
def canonical_records(df, row_limit=None): ...                    # :70  (-> rows, total, truncated)

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py
class StructuredTableRenderer(BaseChart):                 # :88
    async def render(self, response, *, environment="html", row_limit=None, **kwargs): ...  # :117
    # Today: self._table_renderer._extract_data(response) -> base_column_types -> canonical_records
    #        -> TableColumn list -> _apply_llm_refine -> StructuredTableConfig
    #        -> out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})
    #        -> response.data = cfg.data ; returns (out, explanation)
    # _extract_json_code(...) static helper duplicated at ~:324
```

### Does NOT Exist
- ~~`StructuredOutputBase`~~ / any shared structured base or mixin — this task creates it.
- ~~A structured-specific intermediate between `BaseChart` and the three renderers~~ — they inherit `BaseChart` directly today.

---

## Implementation Notes

### Pattern to Follow
Mirror exactly what `StructuredTableRenderer.render` already does for extraction + envelope; the goal is a
behavior-preserving extraction, not a redesign. The envelope contract is literally:
```python
out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})  # data NEVER in output
response.data = rows                                                 # rows routed to envelope
return out, explanation                                             # explanation as `wrapped`
```

### Key Constraints
- Async throughout; `self.logger` at key points (extraction failure, degradation).
- `_extract_rows` and `_route_envelope` **must never raise** — graceful degradation is part of the contract.
- Do NOT change the registry wiring or `register_renderer` decorators.
- Pydantic models unchanged.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py` — the pattern source.
- `packages/ai-parrot/src/parrot/outputs/formats/table.py` — `_extract_data`.

---

## Acceptance Criteria

- [ ] `StructuredOutputBase` (or mixin) exists with `_extract_rows` and `_route_envelope`; never raises.
- [ ] `StructuredTableRenderer` uses the base; behavior unchanged.
- [ ] Existing table tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py packages/ai-parrot/tests/outputs/formats/test_structured_table.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-visualizations/src/parrot/outputs/formats/`
- [ ] Impl-1 decision (base class vs mixin) recorded in the completion note.

---

## Test Specification

```python
# extend packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py (or a new test_structured_base.py)
import pandas as pd
import pytest


class TestStructuredOutputBase:
    def test_extract_rows_dataframe(self):
        """_extract_rows returns a DataFrame for a DataFrame-bearing response."""
        ...

    def test_extract_rows_never_raises_on_garbage(self):
        """_extract_rows returns an empty/None sentinel, not an exception, for unusable input."""
        ...

    def test_route_envelope_excludes_data_and_routes_rows(self):
        """out has no 'data' key; response.data holds the rows; explanation returned as wrapped."""
        ...
```

---

## Completion Note

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-06-03
**Notes**: Created `structured_base.py` with `StructuredOutputBase` mixin. Moved `_extract_json_code` static helper into the base (was duplicated in table renderer). Refactored `StructuredTableRenderer(StructuredOutputBase, BaseChart)` — `render()` now calls `self._extract_rows()` and `self._route_envelope()`. All 48 existing table tests pass. Linting clean.
**Impl-1 decision (base class vs mixin)**: **Mixin**. `StructuredOutputBase` has no `__init__`, no abstract methods, and no mandatory base. Inserted via multiple inheritance `(StructuredOutputBase, BaseChart)` with correct MRO. This avoids diamond-inheritance issues, doesn't affect `@register_renderer` wiring, and lets chart/map renderers adopt it identically.
**Deviations from spec**: none
