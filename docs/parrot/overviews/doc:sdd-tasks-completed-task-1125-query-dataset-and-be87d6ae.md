---
type: Wiki Overview
title: 'TASK-1125: QueryDataset & QueryResponse Pydantic Models'
id: doc:sdd-tasks-completed-task-1125-query-dataset-and-response-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-164 (spec §3 "Module 1"). `DatabaseAgent`
relates_to:
- concept: mod:parrot.bots.data
  rel: mentions
- concept: mod:parrot.bots.database
  rel: mentions
---

# TASK-1125: QueryDataset & QueryResponse Pydantic Models

**Feature**: FEAT-164 — DatabaseAgent Homologation
**Spec**: `sdd/specs/database-agent-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-164 (spec §3 "Module 1"). `DatabaseAgent`
currently returns string-formatted blobs; `PandasAgent` returns a strict
`PandasAgentResponse`. This task adds the two Pydantic models that define
the new structured-output contract for `DatabaseAgent`:

- `QueryDataset` — wraps `PandasTable` with DB-specific metadata (row
  count, execution time, columns).
- `QueryResponse` — the LLM's structured output for `ask()` (explanation,
  query, optional inline dataset or variable name).

These models are the foundation that Module 5 (`DatabaseAgent` rewrite)
binds to `StructuredOutputConfig(output_type=QueryResponse)`.

---

## Scope

- Add `QueryDataset(BaseModel)` to `bots/database/models.py`.
- Add `QueryResponse(BaseModel)` to `bots/database/models.py`.
- Export both classes from `bots/database/__init__.py`'s `__all__`.
- Add unit tests covering serialisation and the `data_variable` path.

**NOT in scope**:
- Touching `QueryExecutionResponse` (existing toolkit-layer model).
- Wiring the models into `DatabaseAgent.ask()` (Module 5 / TASK-1128).
- Adding a `code` field — resolved Open Question #3 defers it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/models.py` | MODIFY | Append `QueryDataset` and `QueryResponse` Pydantic models. |
| `packages/ai-parrot/src/parrot/bots/database/__init__.py` | MODIFY | Add `"QueryDataset"`, `"QueryResponse"` to `__all__` and re-export. |
| `packages/ai-parrot/tests/bots/database/test_query_response_models.py` | CREATE | Unit tests for both models. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/bots/database/models.py — existing
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

# Wraps this type (re-verify still at this line):
from parrot.bots.data import PandasTable           # bots/data.py:44
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/data.py:44
class PandasTable(BaseModel):
    columns: List[str]            # line 45
    rows: List[List[Scalar]]      # line 47
    # has .to_dataframe() and serialises round-trip via Pydantic

# packages/ai-parrot/src/parrot/bots/database/models.py — current public surface
# (verify these still exist before editing):
class UserRole(str, Enum): ...                  # line 17
class OutputComponent(Flag): ...                # line 26
class QueryIntent(str, Enum): ...               # line 74
class QueryExecutionResponse(BaseModel): ...    # line 205
class RouteDecision: ...                        # line 266
class DatabaseResponse: ...                     # line 298
def get_default_components(user_role: UserRole) -> OutputComponent: ...  # line 446
```

### Does NOT Exist

- ~~`QueryResponse`~~ — does not exist anywhere; this task creates it.
- ~~`QueryDataset`~~ — does not exist anywhere; this task creates it.
- ~~`PandasTable.row_count`~~ — `PandasTable` carries only `columns` and
  `rows`; row-count metadata belongs on the wrapper, not on
  `PandasTable` itself.

---

## Implementation Notes

### Pattern to Follow

Mirror `PandasAgentResponse` (`bots/data.py:138`) for `QueryResponse`'s
overall shape and the `Field(description=…)` style (Pydantic descriptions
become the LLM's structured-output hints).

### Model Definitions (from spec §2 "Data Models")

```python
class QueryDataset(BaseModel):
    """Result dataset for a single executed query.

    Wraps PandasTable with DB-specific metadata so consumers can
    distinguish a 'no results' empty table from a non-tabular response.
    """

    data: Optional[PandasTable] = Field(
        default=None,
        description="Tabular result rows; null for non-tabular responses.",
    )
    columns: List[str] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: Optional[float] = None


class QueryResponse(BaseModel):
    """Structured LLM output for DatabaseAgent.ask()."""

    explanation: str = Field(
        description="Human-readable summary of the query and its result."
    )
    query: Optional[str] = Field(
        default=None,
        description="The SQL/DSL the agent generated and executed.",
    )
    data: Optional[QueryDataset] = Field(
        default=None,
        description="Inline dataset; populated when row_count <= inline_threshold.",
    )
    data_variable: Optional[str] = Field(
        default=None,
        description="Variable name holding the result DataFrame (for large datasets).",
    )
    data_variables: Optional[List[str]] = Field(
        default=None,
        description="Multi-dataset variant; list of variable names.",
    )
```

### Key Constraints

- Pydantic v2 (`BaseModel`, `Field`, `model_json_schema`).
- Type hints: `Optional[...]` for nullable fields, `List[str]` for
  collections (project convention — do not switch to `list[str]` style
  unless every other module already uses PEP 604/585).
- Field `description=` strings are exposed to the LLM via the JSON
  schema — keep them clear and short.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/data.py:138` — `PandasAgentResponse`
  is the closest analog; mirror its `Field(description=...)` style.
- `packages/ai-parrot/src/parrot/bots/database/models.py:205` —
  `QueryExecutionResponse` lives here; place the new models after it.

---

## Acceptance Criteria

- [ ] `QueryDataset` and `QueryResponse` defined in `bots/database/models.py`.
- [ ] Both classes added to `bots/database/__init__.py:__all__` and
      re-exported at the package level.
- [ ] `from parrot.bots.database import QueryDataset, QueryResponse`
      succeeds at import time.
- [ ] `QueryResponse.model_json_schema()` returns a schema containing
      properties `explanation`, `query`, `data`, `data_variable`,
      `data_variables` and lists `explanation` as required.
- [ ] All three new unit tests pass:
      `pytest packages/ai-parrot/tests/bots/database/test_query_response_models.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/database/models.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/database/test_query_response_models.py
import pytest
from parrot.bots.data import PandasTable
from parrot.bots.database import QueryDataset, QueryResponse


def test_query_dataset_serialises_pandas_table():
    """Round-trip PandasTable -> QueryDataset -> JSON -> QueryDataset
    preserves rows/columns/row_count."""
    table = PandasTable(columns=["id", "name"], rows=[[1, "a"], [2, "b"]])
    ds = QueryDataset(
        data=table, columns=["id", "name"], row_count=2, execution_time_ms=12.5
    )
    payload = ds.model_dump_json()
    restored = QueryDataset.model_validate_json(payload)
    assert restored.row_count == 2
    assert restored.columns == ["id", "name"]
    assert restored.data is not None
    assert restored.data.rows == [[1, "a"], [2, "b"]]


def test_query_response_pydantic_schema_includes_explanation_query_data():
    """QueryResponse.model_json_schema() exposes the three required fields."""
    schema = QueryResponse.model_json_schema()
    props = schema["properties"]
    for field in ("explanation", "query", "data", "data_variable", "data_variables"):
        assert field in props, f"missing field {field} in schema"
    # explanation is the only required field
    assert "explanation" in schema.get("required", [])


def test_query_response_data_variable_path():
    """QueryResponse accepts data=None + data_variable='result_df' without errors."""
    response = QueryResponse(
        explanation="Returned a large result set.",
        query="SELECT * FROM events",
        data=None,
        data_variable="result_df",
    )
    assert response.data is None
    assert response.data_variable == "result_df"
```

---

## Agent Instructions

1. Read the spec (§2 "Data Models", §3 "Module 1", §5 "Acceptance Criteria").
2. Verify nothing in the contract has drifted (re-`grep` line numbers if
   unsure — Pydantic class line numbers can shift).
3. Add the two models below `QueryExecutionResponse` in `models.py`.
4. Add the re-exports in `__init__.py`.
5. Write tests and run `pytest`.
6. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-13
**Notes**: Added `QueryDataset` and `QueryResponse` after `QueryExecutionResponse` in `models.py`. Added `PandasTable` import (runtime, not TYPE_CHECKING) so Pydantic v2 can resolve the type. Created `tests/bots/database/` directory with `__init__.py`. All 3 tests pass, ruff clean.
**Deviations from spec**: none
