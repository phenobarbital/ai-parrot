---
type: Wiki Overview
title: 'TASK-1431: `StructuredTableRenderer` + dispatch wiring'
id: doc:sdd-tasks-completed-task-1431-structured-table-renderer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The heart of FEAT-218 (spec §2, §3 Module 3). Builds the renderer that turns
  an agent
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.table
  rel: mentions
- concept: mod:parrot.outputs.formats.table_types
  rel: mentions
---

# TASK-1431: `StructuredTableRenderer` + dispatch wiring

**Feature**: FEAT-218 — Structured Table Output Mode
**Spec**: `sdd/specs/structured-table.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1429, TASK-1430
**Assigned-to**: unassigned

---

## Context

The heart of FEAT-218 (spec §2, §3 Module 3). Builds the renderer that turns an agent
response into a `StructuredTableConfig`, mirroring the FEAT-215 `StructuredChartRenderer`
return/route/degradation contract. Ships from the `ai-parrot-visualizations` satellite, like
STRUCTURED_CHART.

---

## Scope

- Create `structured_table.py` in `ai-parrot-visualizations` with a renderer registered via
  `@register_renderer(OutputMode.STRUCTURED_TABLE, system_prompt=...)`.
- Renderer pipeline:
  1. Extract rows via `TableRenderer._extract_data(response)`.
  2. Build base column types via `base_column_types(df)` (TASK-1430); apply `row_limit`
     (default **1000**) via `canonical_records` → rows + `total_rows` + `truncated`.
  3. Reuse `explanation` from `getattr(response, "response", None)` (best-effort; absent → omit).
  4. **Optional, opt-out-able LLM-refine** of ambiguous (`string`/`integer`) columns to finer
     `format` hints (`currency`/`percent`/`id`/`code`). **Deterministic wins**: the LLM may NOT
     change a hard base type; conflicts are ignored; disagreements recorded best-effort.
  5. Build `StructuredTableConfig`; return `(out_without_data, explanation)` where
     `out = cfg.model_dump(by_alias=True, exclude={"data"})`; set `response.data = cfg.data`.
  6. Never raise — return `(None, msg)` on malformed input; on LLM-refine failure fall back to
     the deterministic-only schema.
- Wire dispatch: add `OutputMode.STRUCTURED_TABLE: ('.structured_table',)` to `_MODULE_MAP`.
- Write unit tests for routing, explanation reuse, deterministic-wins, row-limit, graceful
  degradation, and LLM-refine fallback.

**NOT in scope**: the `data.py` override-guard (TASK-1432), producer wiring (TASK-1433/1434),
integration tests (TASK-1435).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py` | CREATE | renderer (clone of structured_chart.py) |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | one `_MODULE_MAP` entry |
| `packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py` | CREATE | renderer unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn  # from TASK-1429
from parrot.outputs.formats import register_renderer  # outputs/formats/__init__.py:48
from parrot.outputs.formats.table import TableRenderer  # table.py:52 (reuse _extract_data)
from parrot.outputs.formats.table_types import base_column_types, canonical_records  # from TASK-1430
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
_MODULE_MAP: dict = { ...                                    # :20
    OutputMode.STRUCTURED_CHART: ('.structured_chart',),    # :29  <-- add STRUCTURED_TABLE entry like this
}
def register_renderer(mode: OutputMode, system_prompt=None): ...   # :48

# packages/ai-parrot/src/parrot/outputs/formats/table.py:52,57
class TableRenderer(BaseRenderer):
    def _extract_data(self, response: Any) -> pd.DataFrame: ...    # :57

# BLUEPRINT — mirror exactly:
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py
#   @register_renderer(...)                       :56
#   explanation = getattr(response, "response")   :118
#   out = cfg.model_dump(..., exclude={"data"})   :161
#   if cfg.data: response.data = cfg.data         :171-173  (NOTE pd.DataFrame truthiness comment)
#   return (out, explanation)                     :182
#   graceful (None, msg) on failure               :135-138, 184-187
```

### Does NOT Exist
- ~~`structured_table.py` / `StructuredTableRenderer`~~ — created by this task.
- ~~a non-satellite home for the renderer~~ — it MUST ship from `ai-parrot-visualizations` (PEP 420 namespace), like structured_chart.
- ~~`OutputMode.DATAFRAME` / `JSON_DATA`~~ — not routable.

---

## Implementation Notes

### Pattern to Follow
Clone `ai-parrot-visualizations/.../structured_chart.py` end to end: same registration,
same `(out, explanation)` return, same `response.data = cfg.data` routing, same graceful
`(None, msg)` degradation. Only the body that builds the config differs (columns + rows from
the deterministic helpers, not chart x/y from the LLM).

### Key Constraints
- Async-first where the base renderer is async; `self.logger`.
- **Deterministic wins**: never let the LLM-refine pass overwrite a base type — it may only
  add a `format` hint on `string`/`integer` columns.
- Use explicit `if cfg.data:` carefully (DataFrame truthiness — mirror the chart comment).
- `row_limit` configurable, default 1000; emit `total_rows` + `truncated`.

### References in Codebase
- `ai-parrot-visualizations/.../structured_chart.py` — full blueprint.
- `parrot/outputs/formatter.py:267` — `format()` calls the renderer and returns `(content, wrapped)`.

---

## Acceptance Criteria

- [ ] `get_renderer(OutputMode.STRUCTURED_TABLE)` resolves to the new renderer.
- [ ] Output dump excludes `data`; rows routed to `response.data`.
- [ ] `explanation` reused from `response.response`; absent → omitted (no raise).
- [ ] LLM-refine never changes a base type (deterministic wins); refine failure → deterministic-only schema.
- [ ] Row-limit (default 1000) applied; `total_rows`/`truncated` set.
- [ ] Malformed input → `(None, msg)`, never raises.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py -v`.
- [ ] `ruff check` clean on the new/modified files.

---

## Test Specification
```python
# packages/ai-parrot/tests/outputs/formats/test_structured_table_renderer.py
# Reuse the satellite-availability skipif + sys.path wiring from test_structured_chart.py:16-27
import pandas as pd
from parrot.outputs.formats import get_renderer
from parrot.models.outputs import OutputMode


def test_dispatch_resolves():
    assert get_renderer(OutputMode.STRUCTURED_TABLE) is not None


def test_routes_rows_and_excludes_data(make_response):
    resp = make_response(data=pd.DataFrame({"a": [1, 2]}), response="how it was built")
    out, wrapped = get_renderer(OutputMode.STRUCTURED_TABLE).render(resp)
    assert "data" not in out
    assert resp.data == [{"a": 1}, {"a": 2}]
    assert wrapped == "how it was built"


def test_graceful_on_bad_input():
    out, msg = get_renderer(OutputMode.STRUCTURED_TABLE).render(object())
    assert out is None and isinstance(msg, str)
```

---

## Agent Instructions
1. Read the spec for full context.
2. Confirm TASK-1429 and TASK-1430 are completed (`sdd/tasks/completed/`).
3. Verify the Codebase Contract before writing code.
4. Update index status → `in-progress`.
5. Implement per scope; make tests pass.
6. Move this file to `sdd/tasks/completed/`; update index → `done`; fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-06-03.

- Created `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py` with `StructuredTableRenderer(BaseChart)`:
  - Registered via `@register_renderer(OutputMode.STRUCTURED_TABLE, system_prompt=...)`.
  - 7-step pipeline: extract DataFrame, derive base types, serialize canonically, reuse explanation, optional LLM-refine, build config, route to response.data.
  - Deterministic wins: LLM can only add `format` hints to `string`/`integer` columns; hard types (`number`, `datetime`, `boolean`) are immutable.
  - Row-limit (default 1000) applied; `total_rows`/`truncated` emitted.
  - Returns `(None, msg)` on any error — never raises.
- Added `OutputMode.STRUCTURED_TABLE: ('.structured_table',)` to `_MODULE_MAP` in `outputs/formats/__init__.py`.
- All 16 unit tests pass. Pre-existing E402 in `__init__.py` is out of scope.
