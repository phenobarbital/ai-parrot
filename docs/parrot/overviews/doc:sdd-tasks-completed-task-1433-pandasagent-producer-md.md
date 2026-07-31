---
type: Wiki Overview
title: 'TASK-1433: PandasAgent producer — STRUCTURED_TABLE end-to-end'
id: doc:sdd-tasks-completed-task-1433-pandasagent-producer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 5 (reference producer #1). PandasAgent already sets `response.data`
  (DataFrame)'
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1433: PandasAgent producer — STRUCTURED_TABLE end-to-end

**Feature**: FEAT-218 — Structured Table Output Mode
**Spec**: `sdd/specs/structured-table.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1431, TASK-1432
**Assigned-to**: unassigned
**Parallel**: true (with TASK-1434)

---

## Context

Spec §3 Module 5 (reference producer #1). PandasAgent already sets `response.data` (DataFrame)
and `response.response` (prose explanation) before the formatter runs — the same path
STRUCTURED_CHART relies on. This task confirms/wires PandasAgent so selecting
`output_mode=STRUCTURED_TABLE` produces a valid structured-table payload end-to-end.

---

## Scope

- Ensure PandasAgent honors `output_mode=OutputMode.STRUCTURED_TABLE`: its existing
  `response.data` (DataFrame) + `response.response` (explanation) flow through the new
  renderer (TASK-1431) without special-casing.
- Add any minimal wiring needed (e.g. allowing STRUCTURED_TABLE through the agent's
  output-mode handling) WITHOUT altering other modes.
- Write an end-to-end-ish unit test: PandasAgent-style response + STRUCTURED_TABLE →
  payload with `columns`, rows in `response.data`, reused `explanation`, no HTML.

**NOT in scope**: DB/SQL agent (TASK-1434), full integration test suite (TASK-1435),
renderer internals (TASK-1431).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| PandasAgent source (locate under `packages/ai-parrot/src/parrot/bots/`) | MODIFY (if needed) | allow STRUCTURED_TABLE through output-mode handling |
| `packages/ai-parrot/tests/bots/test_pandasagent_structured_table.py` | CREATE | producer end-to-end test |

> Locate the exact PandasAgent module with `grep -rn "PandasAgent" packages/ai-parrot/src/parrot/bots/` before editing.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # STRUCTURED_TABLE from TASK-1429
```

### Existing Signatures to Use
```python
# The renderer (TASK-1431) reads, exactly as STRUCTURED_CHART does:
#   explanation = getattr(response, "response", None)   # PandasAgent sets response.response
#   rows        = TableRenderer._extract_data(response) # handles PandasAgentResponse / response.data
# packages/ai-parrot/src/parrot/outputs/formats/table.py:57  _extract_data already supports PandasAgentResponse
# packages/ai-parrot/src/parrot/bots/data.py:1411-1418, 1773-1776, 1786-1789  generic format path
```

### Does NOT Exist
- ~~a bespoke PandasAgent→structured-table serializer~~ — reuse the generic renderer path; the
  agent only needs to allow the mode and set `response.data` / `response.response` (already does).
- ~~`OutputMode.DATAFRAME` / `JSON_DATA`~~ — not routable.

---

## Implementation Notes

### Key Constraints
- Prefer ZERO new serialization logic in the agent — the renderer owns the transform.
- Do not regress existing PandasAgent output modes.
- Async-first; `self.logger`.

### References in Codebase
- `parrot/outputs/formats/table.py:57` — `_extract_data` already handles PandasAgentResponse.
- FEAT-215 STRUCTURED_CHART flow — the precedent for a PandasAgent-backed structured output.

---

## Acceptance Criteria

- [ ] PandasAgent with `output_mode=STRUCTURED_TABLE` returns a payload with `columns` + rows in `response.data`.
- [ ] `explanation` carries PandasAgent's prose (`response.response`).
- [ ] No HTML in the payload; other PandasAgent modes unchanged.
- [ ] Test pass: `pytest packages/ai-parrot/tests/bots/test_pandasagent_structured_table.py -v`.
- [ ] `ruff check` clean on modified files.

---

## Test Specification
```python
# packages/ai-parrot/tests/bots/test_pandasagent_structured_table.py
from parrot.models.outputs import OutputMode

async def test_pandasagent_structured_table():
    """PandasAgent result + STRUCTURED_TABLE → structured payload, no HTML."""
    # Build a PandasAgent-style response (DataFrame in response.data, prose in response.response),
    # run the formatter with STRUCTURED_TABLE, assert columns + rows + explanation present.
    ...
```

---

## Agent Instructions
1. Read the spec; confirm TASK-1431 and TASK-1432 are completed.
2. `grep` for the PandasAgent module and its output-mode handling before editing.
3. Verify the Codebase Contract.
4. Update index status → `in-progress`.
5. Implement the minimal wiring; make tests pass.
6. Move this file to `sdd/tasks/completed/`; update index → `done`; fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-06-03.

- Verified PandasAgent source (`bots/data.py`): no output-mode allow-list or blocking guard exists for STRUCTURED_TABLE. The generic `output_mode` handling path already forwards any `OutputMode` to the formatter, so PandasAgent honors STRUCTURED_TABLE with zero wiring changes.
- Created `tests/bots/test_pandasagent_structured_table.py` with 7 end-to-end tests verifying:
  - columns present, rows routed to response.data, explanation reused, no HTML, data excluded from output, datetimes as ISO-8601, deterministic column types.
- All 7 tests pass. No PandasAgent source modification was required.
