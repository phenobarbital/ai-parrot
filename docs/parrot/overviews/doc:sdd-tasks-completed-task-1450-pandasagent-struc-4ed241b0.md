---
type: Wiki Overview
title: 'TASK-1450: PandasAgent STRUCTURED_MAP wiring'
id: doc:sdd-tasks-completed-task-1450-pandasagent-structured-map-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 6 (G9). Wires `OutputMode.STRUCTURED_MAP` into `PandasAgent`
  so a
---

# TASK-1450: PandasAgent STRUCTURED_MAP wiring

**Feature**: FEAT-221 — Structured Map Output Mode (`STRUCTURED_MAP`)
**Spec**: `sdd/specs/structured-map-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1445, TASK-1446, TASK-1449
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (G9). Wires `OutputMode.STRUCTURED_MAP` into `PandasAgent` so a
natural-language spatial request produces a `StructuredMapConfig`. The agent calls
`DatasetManager.spatial_filter` as a tool; the per-dataset `SpatialResult` must
land in `response.data`, where `StructuredMapRenderer` (TASK-1449) reads it. This
parallels the existing `STRUCTURED_CHART` branch (`bots/data.py:1499–1680`).

---

## Scope

- In `packages/ai-parrot/src/parrot/bots/data.py`, add a `STRUCTURED_MAP` branch
  paralleling the `STRUCTURED_CHART` handling:
  - Ensure the `spatial_filter` tool result (`SpatialResult`) is placed in
    `response.data` for the renderer to consume (G9).
  - Set `response.output_mode = OutputMode.STRUCTURED_MAP`.
  - Thread the originating `SpatialFilterSpec` so the renderer can populate
    `MapQuery` (e.g. via `response` attribute/artifact the renderer can read).
  - Append the `STRUCTURED_MAP` system prompt addon where the other modes do
    (the existing `OUTPUT_SYSTEM_PROMPT` / `formatter.get_system_prompt` path).
- Confirm `Formatter._get_renderer(OutputMode.STRUCTURED_MAP)` dispatches correctly
  (no change expected — verify only).

**NOT in scope**: the renderer (TASK-1449), DB agent support (Non-Goal — deferred),
config models, spatial backend.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | add `STRUCTURED_MAP` branch (parallels `STRUCTURED_CHART`) |
| `packages/ai-parrot/tests/bots/test_pandasagent_structured_map.py` | CREATE | branch/routing tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# bots/data.py already imports (line 28):
from ..models.outputs import OutputMode, StructuredOutputConfig, StructuredChartConfig
# add StructuredMapConfig to this import (post TASK-1445)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py  (STRUCTURED_CHART template)
#   ask(..., structured_output=None, output_mode=None, return_structured=True, ...)  # line ~1302
#   if output_mode != OutputMode.DEFAULT:                                            # line 1411
#       _mode = output_mode if isinstance(output_mode, str) else getattr(output_mode,'value','default')
#       system_prompt += OUTPUT_SYSTEM_PROMPT.format(output_mode=_mode)              # line 1413
#   _forced_output_type = StructuredChartConfig if output_mode == OutputMode.STRUCTURED_CHART else PandasAgentResponse  # line 1506
#   llm_kwargs["structured_output"] = StructuredOutputConfig(output_type=_forced_output_type)  # line 1511
#   if output_mode == OutputMode.STRUCTURED_CHART and data_response is None:         # line 1559
#       response.code = _cfg_out.model_dump(mode="json", by_alias=True)  ...         # line 1563
#   # FEAT-218: STRUCTURED_TABLE ownership contract guard                            # line 1676-1680

# packages/ai-parrot/src/parrot/outputs/formatter.py
#   Formatter._get_renderer(mode) → get_renderer(mode)   # lines 218, 229, 284

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
async def spatial_filter(self, spec, cap_per_dataset=1000) -> "SpatialResult"  # line 4186 (post TASK-1446)
```

### Does NOT Exist
- ~~existing spatial/map handling in `data.py`~~ — there is NONE today; this is the first.
- ~~a `response.map_config` attribute~~ — route via `response.data` (renderer builds the config), not a bespoke attribute.
- ~~STRUCTURED_MAP support in `bots/database/agent.py`~~ — explicitly out of scope (Non-Goal).

### Dependency note
- TASK-1445 (models), TASK-1446 (`SpatialResult`), TASK-1449 (renderer) MUST be in
  `sdd/tasks/completed/` first.

---

## Implementation Notes

### Pattern to Follow
- Follow the STRUCTURED_CHART branch (data.py:1499–1680) but note the KEY
  DIFFERENCE: STRUCTURED_CHART routes a pre-emitted config to `response.code`;
  STRUCTURED_MAP instead routes the **spatial data** to `response.data` and lets
  `StructuredMapRenderer` BUILD the config (table-style ownership — deterministic).
- Reuse the FEAT-218 STRUCTURED_TABLE ownership guard (data.py:1676-1680) as the
  closer template, since map is data-owned like table, not LLM-config-owned like chart.

### Key Constraints
- Async; `self.logger`; no blocking I/O.
- Do NOT force `StructuredMapConfig` as the LLM `structured_output` (the renderer
  builds it). The LLM's job is to emit the `SpatialFilterSpec` / call the tool.

### References in Codebase
- `bots/data.py:1499–1680` — structured branches.
- `bots/database/agent.py:587-593` — how DB agent sets `response.output_mode = STRUCTURED_TABLE`.

---

## Acceptance Criteria

- [ ] `ask(..., output_mode=OutputMode.STRUCTURED_MAP)` places the `SpatialResult` in `response.data` and sets `response.output_mode`.
- [ ] `StructuredMapRenderer` (TASK-1449) produces a valid config from that `response.data` end-to-end.
- [ ] No regression to STRUCTURED_CHART / STRUCTURED_TABLE branches.
- [ ] `pytest packages/ai-parrot/tests/bots/test_pandasagent_structured_map.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/data.py` clean.

---

## Test Specification

```python
async def test_structured_map_routes_data(pandas_agent, spatial_query):
    resp = await pandas_agent.ask(spatial_query, output_mode=OutputMode.STRUCTURED_MAP)
    assert resp.output_mode == OutputMode.STRUCTURED_MAP
    # response.data carries the SpatialResult for the renderer
    assert resp.data is not None


async def test_chart_branch_unaffected(pandas_agent, chart_query):
    resp = await pandas_agent.ask(chart_query, output_mode=OutputMode.STRUCTURED_CHART)
    assert resp.output_mode == OutputMode.STRUCTURED_CHART
```

---

## Agent Instructions

1. Read spec §3 Module 6 and the STRUCTURED_CHART/STRUCTURED_TABLE branches in `data.py`.
2. Confirm TASK-1445/1446/1449 completed.
3. Update index → `in-progress`.
4. Implement; run tests; `ruff check`.
5. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Added `STRUCTURED_MAP` branch in `bots/data.py`:
- Pre-LLM block: calls `_extract_spatial_result_from_tools` to route SpatialResult to `response.data`
- Added `_extract_spatial_result_from_tools` helper method
- Added STRUCTURED_MAP to the override guard (alongside STRUCTURED_CHART/STRUCTURED_TABLE)
- Added STRUCTURED_MAP to the `response.data` serialization branch to skip the DataFrame conversion warning
Tests test the extraction logic standalone (not the full PandasAgent.ask() path which
requires a full project build with compiled Cython extensions). 8 tests pass.
**Deviations from spec**: Tests are standalone logic tests rather than full end-to-end
agent tests (which require compiled Cython). The integration tests in TASK-1451 cover
the full pipeline.
