---
type: Wiki Overview
title: 'TASK-1430: Deterministic dtype→vocabulary map + canonical value serialization'
id: doc:sdd-tasks-completed-task-1430-dtype-vocabulary-map-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The deterministic half of the HYBRID producer (spec §2, §3 Module 2). Maps
  the existing
relates_to:
- concept: mod:parrot.outputs.formats.table_types
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1430: Deterministic dtype→vocabulary map + canonical value serialization

**Feature**: FEAT-218 — Structured Table Output Mode
**Spec**: `sdd/specs/structured-table.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The deterministic half of the HYBRID producer (spec §2, §3 Module 2). Maps the existing
`DatasetManager.categorize_columns` categories onto the FEAT-218 storage vocabulary, and
serializes cell values canonically so the JSON boundary preserves type fidelity. Kept as a
standalone, independently-testable util so it can be built in parallel with the contract
(TASK-1429).

---

## Scope

- Create a small util module exposing two pure functions:
  - `base_column_types(df) -> dict[str, str]`: run `DatasetManager.categorize_columns(df)` and
    map its output to the storage vocabulary:
    `integer→integer`, `float→number`, `datetime→datetime`, `boolean→boolean`,
    `categorical|categorical_text|text→string`, anything unknown→`any`.
  - `canonical_records(df, row_limit) -> tuple[list[dict], int, bool]`: return
    `(rows, total_rows, truncated)` where values are canonical — datetimes as **ISO-8601 UTC**
    strings, integers beyond 2^53 as strings, NaN/None as `null`, mixed-type columns left as
    strings; truncation applied at `row_limit`.
- Write unit tests covering the mapping and the serialization edges.

**NOT in scope**: the finer semantic vocabulary (`currency`/`percent`/`id`/`code`) — that is
the LLM-refine step in TASK-1431. This task produces ONLY deterministic base types + canonical
values.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/formats/table_types.py` | CREATE | `base_column_types` + `canonical_records` |
| `packages/ai-parrot/tests/outputs/formats/test_table_types.py` | CREATE | mapping + serialization tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.dataset_manager.tool import DatasetManager  # categorize_columns is a @staticmethod
import pandas as pd
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:625
class DatasetManager:
    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]:
        # returns per-column: integer | float | datetime | boolean | categorical | categorical_text | text
```

### Does NOT Exist
- ~~a dtype→`currency`/`percent`/`id`/`code` mapper~~ — `categorize_columns` stops at the coarse
  categories above; the finer vocabulary is NOT produced here (it is the LLM-refine in TASK-1431).
- ~~`parrot.outputs.formats.table_types`~~ — created by this task.

---

## Implementation Notes

### Key Constraints
- Pure functions, no I/O, no LLM — fully deterministic and unit-testable.
- `categorize_columns` is a `@staticmethod` — call it without instantiating `DatasetManager`.
- Datetime → ISO-8601 with explicit UTC (`...Z` or `+00:00`); never locale-formatted.
- Big ints (> 2**53) → `str` to avoid IEEE-754 precision loss.
- Null / mixed columns → fall back to `any` type and stringified/`null` values.

### References in Codebase
- `parrot/tools/dataset_manager/tool.py:625` — `categorize_columns` source.
- `parrot/outputs/formats/table.py:57` — `TableRenderer._extract_data` (how rows are obtained; used by TASK-1431, not here).

---

## Acceptance Criteria

- [ ] `base_column_types` maps float→number, int→integer, datetime→datetime, bool→boolean, text/categorical→string, unknown→any.
- [ ] `canonical_records` emits ISO-8601 UTC datetimes, big-ints-as-strings, None→null.
- [ ] `canonical_records(df, row_limit=N)` truncates and reports `total_rows` + `truncated=True`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/formats/test_table_types.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/formats/table_types.py` clean.

---

## Test Specification
```python
# packages/ai-parrot/tests/outputs/formats/test_table_types.py
import pandas as pd
from parrot.outputs.formats.table_types import base_column_types, canonical_records


def test_base_types_mapping():
    df = pd.DataFrame({"i": [1], "f": [1.5], "b": [True],
                       "d": pd.to_datetime(["2026-01-01"]), "s": ["x"]})
    t = base_column_types(df)
    assert t == {"i": "integer", "f": "number", "b": "boolean", "d": "datetime", "s": "string"}


def test_canonical_truncation_and_total():
    df = pd.DataFrame({"a": list(range(5))})
    rows, total, truncated = canonical_records(df, row_limit=2)
    assert total == 5 and truncated is True and len(rows) == 2


def test_iso_datetime():
    df = pd.DataFrame({"d": pd.to_datetime(["2026-01-01T00:00:00"])})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert rows[0]["d"].startswith("2026-01-01")
```

---

## Agent Instructions
1. Read the spec for full context.
2. Verify the Codebase Contract before writing code.
3. Update index status → `in-progress`.
4. Implement per scope; make tests pass.
5. Move this file to `sdd/tasks/completed/`; update index → `done`; fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker on 2026-06-03.

- Created `packages/ai-parrot/src/parrot/outputs/formats/table_types.py` with:
  - `base_column_types(df)` → maps DatasetManager.categorize_columns output to FEAT-218 storage vocabulary.
  - `canonical_records(df, row_limit=1000)` → returns (rows, total_rows, truncated) with ISO-8601 UTC datetimes, big-ints-as-strings (>2^53), NaN/NaT→None.
  - `_canonical_value(value)` — internal helper for per-cell serialization.
- Fixed NaT handling by checking `value is pd.NaT` explicitly before Timestamp branch.
- All 15 unit tests pass. Ruff clean.
