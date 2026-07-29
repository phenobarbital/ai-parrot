---
type: Wiki Overview
title: 'TASK-1411: Add `OutputMode.STRUCTURED_CHART` enum member'
id: doc:sdd-tasks-completed-task-1411-outputmode-structured-chart-enum-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 1. Everything downstream (the model's `type="map"` correlation,
  the dispatch
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1411: Add `OutputMode.STRUCTURED_CHART` enum member

**Feature**: FEAT-215 — Structured Chart Output Mode
**Spec**: `sdd/specs/structured-chart-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Everything downstream (the model's `type="map"` correlation, the dispatch
entry, the renderer registration, the prompt) keys off this enum member. It must land first.

---

## Scope

- Add `STRUCTURED_CHART = "structured_chart"` to the `OutputMode` enum.
- Add a unit test asserting the member exists and round-trips from its string value.

**NOT in scope**: the pydantic model (TASK-1412), dispatch/renderer (TASK-1413), integration
tests (TASK-1414). Do NOT touch ECHARTS/ALTAIR/MAP members.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | Add the enum member after `INFOGRAPHIC` (~line 70) |
| `packages/ai-parrot/tests/outputs/formats/test_structured_chart.py` | CREATE | Add `test_outputmode_has_structured_chart` (file shared with later tasks) |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` 2026-06-02.

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # verified: models/outputs.py:39
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/outputs.py:39
class OutputMode(str, Enum):     # str-Enum: member value MUST be the string "structured_chart"
    ALTAIR = "altair"            # line 53
    MAP = "map"                  # line 59
    ECHARTS = "echarts"          # line 62
    INFOGRAPHIC = "infographic"  # line 70  ← add STRUCTURED_CHART right after this block
    SQL_ANALYSIS = "sql_analysis"  # line 71
```

### Does NOT Exist
- ~~`OutputMode.STRUCTURED_CHART`~~ — being added by THIS task.
- ~~`OutputMode.STRUCTUREDCHART` / `OutputMode.CHART_STRUCTURED`~~ — wrong names; the value is
  exactly `"structured_chart"`.

---

## Implementation Notes

### Pattern to Follow
```python
# In class OutputMode(str, Enum), append alongside the other chart modes:
    STRUCTURED_CHART = "structured_chart"  # Library-agnostic chart config (AppChartConfig mirror)
```

### Key Constraints
- `OutputMode` is a `str, Enum` — the value is the wire string; keep it `"structured_chart"`.
- Purely additive: do not reorder or modify existing members.

### References in Codebase
- `packages/ai-parrot/src/parrot/models/outputs.py:39-71` — the enum.

---

## Acceptance Criteria

- [ ] `OutputMode.STRUCTURED_CHART` exists with value `"structured_chart"`.
- [ ] `OutputMode("structured_chart") is OutputMode.STRUCTURED_CHART`.
- [ ] Test passes: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_chart.py -v`.
- [ ] No existing `OutputMode` member changed (additive only).

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/formats/test_structured_chart.py
from parrot.models.outputs import OutputMode


def test_outputmode_has_structured_chart():
    assert OutputMode.STRUCTURED_CHART.value == "structured_chart"
    assert OutputMode("structured_chart") is OutputMode.STRUCTURED_CHART
```

---

## Agent Instructions

When you pick up this task:
1. **Read the spec** for full context.
2. **Verify the Codebase Contract** (re-`grep` the enum).
3. **Update index** → `in-progress`.
4. **Implement** the single enum line + test.
5. **Verify** acceptance criteria.
6. **Move** to `sdd/tasks/completed/` and update index → `done`.
7. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-02
**Notes**: Added `STRUCTURED_CHART = "structured_chart"` after `SQL_ANALYSIS` in `OutputMode` enum. Created shared test file `test_structured_chart.py`. Test passes.
**Deviations from spec**: none
