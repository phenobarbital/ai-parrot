---
type: Wiki Overview
title: 'TASK-1429: Contract — `OutputMode.STRUCTURED_TABLE` + `StructuredTableConfig`'
id: doc:sdd-tasks-completed-task-1429-contract-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation of FEAT-218 (spec §2 Data Models, §3 Module 1). Adds the routable
  enum member
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
---

# TASK-1429: Contract — `OutputMode.STRUCTURED_TABLE` + `StructuredTableConfig`

**Feature**: FEAT-218 — Structured Table Output Mode
**Spec**: `sdd/specs/structured-table.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of FEAT-218 (spec §2 Data Models, §3 Module 1). Adds the routable enum member
and the Pydantic contract that the renderer (TASK-1431) and producers (TASK-1433/1434)
build. Mirrors the FEAT-215 `StructuredChartConfig` pattern exactly.

---

## Scope

- Add `STRUCTURED_TABLE = "structured_table"` to `OutputMode` (adjacent to STRUCTURED_CHART).
- Add `TableColumn(BaseModel)`: `name: str`, `type: str`, `title: str`, `format: str | None = None`.
- Add `StructuredTableConfig(BaseModel)` mirroring `StructuredChartConfig`:
  - `model_config = ConfigDict(populate_by_name=True)`.
  - `columns: list[TableColumn]`.
  - `data: list[dict]` — **INPUT-ONLY**, excluded from output dump (same contract as
    `StructuredChartConfig.data`).
  - `explanation: str | None = None`, `total_rows: int | None = None`, `truncated: bool = False`.
  - `@model_validator(mode="after")`: every `column.name` must exist in `data[0].keys()`
    when `data` is non-empty (mirror the chart validator).
- Write unit tests for the model + enum member.

**NOT in scope**: the renderer, the dtype→vocabulary map (TASK-1430), data.py routing
(TASK-1432), or any producer wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/outputs.py` | MODIFY | add enum member + `TableColumn` + `StructuredTableConfig` |
| `packages/ai-parrot/tests/models/test_structured_table_config.py` | CREATE | model + validator + dump-exclusion tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # direct import; NOT re-exported from parrot/models/__init__.py
# In outputs.py the file already imports pydantic BaseModel/Field/ConfigDict/model_validator (used by StructuredChartConfig)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):                       # :39
    JSON = "json"                                  # :42
    TABLE = "table"                                # :63
    SQL_ANALYSIS = "sql_analysis"                  # :71
    STRUCTURED_CHART = "structured_chart"          # :72  <-- add STRUCTURED_TABLE adjacent

class StructuredChartConfig(BaseModel):            # :309-392  (MIRROR THIS)
    model_config = ConfigDict(populate_by_name=True)   # :332
    # data: List[dict] is INPUT-ONLY, excluded from output via model_dump(exclude={"data"})  :366-372
    # @model_validator(mode="after") validates declared columns vs data[0].keys()  :374-392
```

### Does NOT Exist
- ~~`OutputMode.STRUCTURED_TABLE` / `StructuredTableConfig` / `TableColumn`~~ — created by this task.
- ~~`OutputMode.DATAFRAME` / `OutputMode.JSON_DATA`~~ — only `OutputType.*` (`outputs.py:26,35`), not routable.
- ~~re-export from `parrot/models/__init__.py`~~ — does not exist; import from `parrot.models.outputs`.

---

## Implementation Notes

### Pattern to Follow
Copy the structure of `StructuredChartConfig` (`models/outputs.py:309-392`) verbatim,
swapping `x`/`y` encodings for `columns: list[TableColumn]`. Keep `data` INPUT-ONLY with the
exact exclusion contract so the renderer can `model_dump(by_alias=True, exclude={"data"})`.

### Key Constraints
- Pydantic v2 only; strict types; Google-style docstrings.
- `data` MUST be excluded from the serialized output (it is routed to `response.data` by the
  renderer — never duplicated into `output`).
- `title` defaults to the column `name` as-is (no renaming here; refinement is TASK-1431).

---

## Acceptance Criteria

- [ ] `OutputMode.STRUCTURED_TABLE == "structured_table"`.
- [ ] `StructuredTableConfig(...).model_dump(by_alias=True, exclude={"data"})` omits rows.
- [ ] Validator raises when a `column.name` is absent from non-empty `data[0]`.
- [ ] `from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn` works.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/models/test_structured_table_config.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/models/outputs.py` clean.

---

## Test Specification
```python
# packages/ai-parrot/tests/models/test_structured_table_config.py
import pytest
from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn


def test_enum_member():
    assert OutputMode.STRUCTURED_TABLE == "structured_table"


def test_data_excluded_on_dump():
    cfg = StructuredTableConfig(
        columns=[TableColumn(name="a", type="number", title="A")],
        data=[{"a": 1}],
    )
    out = cfg.model_dump(by_alias=True, exclude={"data"})
    assert "data" not in out
    assert out["columns"][0]["name"] == "a"


def test_validator_rejects_unknown_column():
    with pytest.raises(Exception):
        StructuredTableConfig(
            columns=[TableColumn(name="missing", type="string", title="X")],
            data=[{"a": 1}],
        )
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

- Added `OutputMode.STRUCTURED_TABLE = "structured_table"` adjacent to `STRUCTURED_CHART` in `models/outputs.py`.
- Added `TableColumn(BaseModel)` with `name`, `type`, `title`, `format` fields (Pydantic v2, Google docstrings).
- Added `StructuredTableConfig(BaseModel)` mirroring `StructuredChartConfig`:
  - `model_config = ConfigDict(populate_by_name=True)`
  - `columns: List[TableColumn]`, `data: List[dict]` (INPUT-ONLY, excluded from dump)
  - `explanation: Optional[str]`, `total_rows: Optional[int]`, `truncated: bool = False`
  - `@model_validator(mode="after")` validates column names against `data[0].keys()` when data is non-empty.
- All 12 unit tests pass. Pre-existing ruff F401 issues in `outputs.py` are out of scope.
