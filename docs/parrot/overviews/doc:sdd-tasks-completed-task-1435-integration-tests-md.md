---
type: Wiki Overview
title: 'TASK-1435: Integration tests + envelope parity + full cloned suite'
id: doc:sdd-tasks-completed-task-1435-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 6 / §4 Test Specification. Closes FEAT-218 by cloning the
  comprehensive
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
---

# TASK-1435: Integration tests + envelope parity + full cloned suite

**Feature**: FEAT-218 — Structured Table Output Mode
**Spec**: `sdd/specs/structured-table.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1433, TASK-1434
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / §4 Test Specification. Closes FEAT-218 by cloning the comprehensive
STRUCTURED_CHART test suite for STRUCTURED_TABLE and adding the two reference-producer
end-to-end integration tests plus the HTTP envelope-parity regression.

---

## Scope

- Clone `tests/outputs/formats/test_structured_chart.py` (521 lines) → `test_structured_table.py`,
  adapting assertions: enum member, model/validator, dispatch resolution, system-prompt schema
  embedding, data-exclusion + routing, explanation-as-wrapped, graceful degradation, and the
  envelope-serialization regression.
- Add integration tests:
  - PandasAgent + STRUCTURED_TABLE end-to-end (valid payload, zero HTML).
  - DB/SQL agent + STRUCTURED_TABLE end-to-end (reused SQL provenance).
  - HTTP envelope parity with STRUCTURED_CHART (`output`/`data`/`response`/`code` shape).
- Ensure the full FEAT-218 suite is green.

**NOT in scope**: changing implementation behavior — if a test reveals a bug, file it; fix only
trivial wiring. Behavioral changes belong to the relevant module task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/outputs/formats/test_structured_table.py` | CREATE | clone of the chart suite, adapted |
| `packages/ai-parrot/tests/integration/test_structured_table_e2e.py` | CREATE | producer e2e + envelope parity |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn
from parrot.outputs.formats import get_renderer
```

### Existing Signatures to Use
```python
# TEMPLATE TO CLONE — copy its structure verbatim, rename chart→table:
# packages/ai-parrot/tests/outputs/formats/test_structured_chart.py  (521 lines)
#   :16-27   satellite-availability skipif + sys.path wiring  (REUSE AS-IS)
#   :34-39   enum member test
#   :47-137  model / validator tests
#   :180-198 dispatch resolution + system-prompt schema embedding
#   :201-310 data-exclusion + routing
#   :313-336 explanation-as-wrapped
#   :339-450 graceful degradation on malformed input
#   :458-521 envelope serialization regression

# HTTP envelope (mode-agnostic; assert parity, do not change):
# packages/ai-parrot-server/src/parrot/handlers/agent.py:2591-2626
```

### Does NOT Exist
- ~~a STRUCTURED_TABLE test file~~ — created here.
- ~~handler changes for the new mode~~ — the envelope at `handlers/agent.py:2591-2626` is already generic; assert parity, do not modify it.

---

## Implementation Notes

### Key Constraints
- Reuse the `satellite_available` skipif marker + sys.path wiring from the chart test verbatim
  (the renderer ships from `ai-parrot-visualizations`).
- Integration tests must assert: columns present, rows in `response.data`, `data` excluded from
  `output`, reused `explanation`, `total_rows`/`truncated` honored, and no HTML.

### References in Codebase
- `tests/outputs/formats/test_structured_chart.py` — the full template.
- `handlers/agent.py:2591-2626` — envelope shape to assert parity against.

---

## Acceptance Criteria

- [ ] `test_structured_table.py` mirrors every behavioral case of the chart suite, all green.
- [ ] PandasAgent and DB/SQL agent e2e integration tests pass.
- [ ] Envelope parity with STRUCTURED_CHART asserted.
- [ ] Full feature suite green: `pytest packages/ai-parrot/tests/outputs/formats/test_structured_table.py packages/ai-parrot/tests/integration/test_structured_table_e2e.py -v`.
- [ ] `ruff check` clean on new test files.

---

## Test Specification
```python
# See Scope — the file is itself the test deliverable.
# Minimum gate:
from parrot.models.outputs import OutputMode

def test_suite_covers_core_contract():
    assert OutputMode.STRUCTURED_TABLE == "structured_table"
```

---

## Agent Instructions
1. Read the spec; confirm TASK-1433 and TASK-1434 are completed.
2. Verify the Codebase Contract; open the chart test file and clone its structure.
3. Update index status → `in-progress`.
4. Implement per scope; make the full suite green.
5. Move this file to `sdd/tasks/completed/`; update index → `done`; fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-06-03.

- Created `tests/outputs/formats/test_structured_table.py` (39 tests): cloned from test_structured_chart.py structure with satellite skipif+sys.path wiring, covering:
  - enum member, TableColumn model, StructuredTableConfig model+validators+dump exclusion
  - dispatch resolution, system prompt, data routing, explanation, graceful degradation
  - dtype vocabulary map, deterministic-wins conflict, row-limit/truncation
  - envelope serialization parity, TABLE regression guard
- Created `tests/integration/test_structured_table_e2e.py` (13 tests): e2e integration covering:
  - PandasAgent + STRUCTURED_TABLE: valid payload, zero HTML, ISO datetimes, deterministic types
  - DB agent + STRUCTURED_TABLE: valid payload, provenance reuse
  - HTTP envelope parity: same keys as STRUCTURED_CHART, same data/output routing
- All 39 tests pass. Ruff clean.
