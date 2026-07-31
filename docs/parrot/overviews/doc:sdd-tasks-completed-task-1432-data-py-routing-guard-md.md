---
type: Wiki Overview
title: 'TASK-1432: Extend `data.py` override-guard for STRUCTURED_TABLE'
id: doc:sdd-tasks-completed-task-1432-data-py-routing-guard-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 4. FEAT-215 added a guard so `data.py` does NOT overwrite
  `response.data`
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1432: Extend `data.py` override-guard for STRUCTURED_TABLE

**Feature**: FEAT-218 — Structured Table Output Mode
**Spec**: `sdd/specs/structured-table.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1429, TASK-1431
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. FEAT-215 added a guard so `data.py` does NOT overwrite `response.data`
with the raw tool-local DataFrame when the renderer owns that assignment via `cfg.data`.
STRUCTURED_TABLE has the same need — extend the guard to skip for it too. Small, surgical.

---

## Scope

- In `packages/ai-parrot/src/parrot/bots/data.py`, extend the FEAT-215 override-guard
  (~lines 1623-1629) so the condition that skips overwriting `response.data` ALSO skips when
  `output_mode == OutputMode.STRUCTURED_TABLE` (currently only `!= OutputMode.STRUCTURED_CHART`).
- Add/extend a unit test confirming `data.py` does not clobber `response.data` for STRUCTURED_TABLE.

**NOT in scope**: the renderer (TASK-1431), producers (TASK-1433/1434). Do not change any
other branch in `data.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | extend override-guard at ~:1629 |
| `packages/ai-parrot/tests/bots/test_data_structured_table_guard.py` | CREATE | guard regression test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # already imported in data.py at :28
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py
#   :1623  # FEAT-215: STRUCTURED_CHART routes data via cfg.data inside the renderer
#   :1629  and output_mode != OutputMode.STRUCTURED_CHART
#          ^-- extend: also `and output_mode != OutputMode.STRUCTURED_TABLE`
```

### Does NOT Exist
- ~~a separate routing function for STRUCTURED_TABLE~~ — reuse the SAME generic path; only the
  guard condition changes.
- ~~`OutputMode.DATAFRAME` / `JSON_DATA`~~ — not routable.

---

## Implementation Notes

### Key Constraints
- Minimal diff: only the boolean condition at the guard. Do not refactor surrounding code.
- Keep behavior identical for all other modes (including TABLE and STRUCTURED_CHART).

### References in Codebase
- `data.py:1623-1629` — the guard to extend.
- `data.py:1786-1789` — envelope writeback (unchanged; for context only).

---

## Acceptance Criteria

- [ ] The guard skips overwriting `response.data` for BOTH STRUCTURED_CHART and STRUCTURED_TABLE.
- [ ] No behavior change for other output modes.
- [ ] Test pass: `pytest packages/ai-parrot/tests/bots/test_data_structured_table_guard.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/data.py` clean.

---

## Test Specification
```python
# packages/ai-parrot/tests/bots/test_data_structured_table_guard.py
from parrot.models.outputs import OutputMode

def test_guard_skips_structured_table():
    """data.py must not overwrite response.data when mode is STRUCTURED_TABLE."""
    # Arrange a response whose .data was set by the renderer, run the guarded branch,
    # and assert the renderer-provided data survives. (Mirror the STRUCTURED_CHART guard test.)
    ...
```

---

## Agent Instructions
1. Read the spec for full context.
2. Confirm TASK-1429 and TASK-1431 are completed.
3. Verify the Codebase Contract (re-check the exact line of the guard — it may have shifted).
4. Update index status → `in-progress`.
5. Implement the minimal change; make tests pass.
6. Move this file to `sdd/tasks/completed/`; update index → `done`; fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-06-03.

- Extended the FEAT-215 override-guard in `bots/data.py` (~line 1629) to also skip for `STRUCTURED_TABLE`.
- Added 2 lines: a comment explaining FEAT-218's data-ownership contract, and `and output_mode != OutputMode.STRUCTURED_TABLE`.
- The guard now reads:
  ```python
  and output_mode != OutputMode.STRUCTURED_CHART
  and output_mode != OutputMode.STRUCTURED_TABLE
  ```
- All 4 tests pass; no regression to STRUCTURED_CHART or other modes. Pre-existing ruff F401 in data.py is out of scope.
