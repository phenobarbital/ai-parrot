# Feature Specification: DatasetManager Multi-Dataset Response

**Feature ID**: FEAT-098
**Date**: 2026-04-14
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x

---

## 1. Motivation & Business Requirements

### Problem Statement

When a user asks a question that involves multiple datasets (e.g., "return users by Q3, tasks completed and list of tasks completed"), the PandasAgent currently populates `response.data` with only a **single** dataset — typically the last one materialized or the last `data_variable` resolved. The other datasets involved in answering the query are lost from the structured response, even though they were fetched and are available in the Python REPL context.

This means downstream consumers (REST API callers, Telegram/Teams integrations, front-end dashboards) only receive one table of data, forcing users to issue separate queries for each dataset.

### Current Behavior

1. `PandasAgentResponse.data` is `Optional[PandasTable]` — a single table.
2. `PandasAgentResponse.data_variable` is `Optional[str]` — a single variable name.
3. `_inject_data_from_variable()` overwrites `response.data` with a single DataFrame.
4. At serialization (`line ~1594`), `response.data` is converted to a single `list[dict]`.

When multiple datasets are involved, only the last assignment to `response.data` survives.

### Goals

- `response.data` must support returning **multiple named datasets** when a query involves more than one datasource.
- Backward compatibility: single-dataset responses must continue to work identically for existing consumers.
- The LLM must be able to declare multiple `data_variable` references in its structured output.
- Downstream integrations (REST API, Telegram, Teams) must be able to iterate over multiple result tables.

### Non-Goals (explicitly out of scope)

- Changing how DatasetManager fetches or materializes data — that machinery is fine.
- Changing the LLM prompting for single-dataset queries.
- Adding cross-dataset JOIN/merge capabilities at the response level (that's `CompositeDataSource`).
- Changing the `PandasTable` model itself — its structure is fine for individual tables.

---

## 2. Architectural Design

### Overview

Extend `PandasAgentResponse` to support multiple data outputs by adding a `datasets` field (a list of named data entries). When the LLM produces results from multiple datasources, each gets its own entry. `response.data` becomes a list of named dataset results instead of a single flat list of records.

### Component Diagram

```
LLM Response
    │
    ├─► PandasAgentResponse.data          (single table — unchanged, backward compat)
    ├─► PandasAgentResponse.data_variable (single var — unchanged, backward compat)
    └─► PandasAgentResponse.data_variables (NEW: list of named vars)
            │
            ▼
    PandasAgent._process_response()
            │
            ├─► Single data/data_variable → response.data = [single list of records]  (as today)
            └─► Multiple data_variables   → response.data = [{"name": ..., "data": [...]}, ...]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PandasAgentResponse` | extends | Add `data_variables` field |
| `PandasAgent._inject_data_from_variable` | modifies | Support list of variables |
| `PandasAgent` response processing (~L1428-1595) | modifies | Multi-dataset assembly |
| `AIMessage.data` | uses (unchanged) | Already `Optional[Any]` — accepts list of dicts |
| `DatasetManager.fetch_dataset` | uses (unchanged) | Already returns per-dataset results |

### Data Models

```python
class DatasetResult(BaseModel):
    """A single named dataset in a multi-dataset response."""
    name: str = Field(description="Dataset name or alias")
    variable: str = Field(description="Python variable name holding this DataFrame")
    data: List[Dict[str, Any]] = Field(description="Records (list of row dicts)")
    shape: Tuple[int, int] = Field(description="(rows, columns)")
    columns: List[str] = Field(description="Column names")

class PandasAgentResponse(BaseModel):
    # ... existing fields unchanged ...
    data_variables: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of variable names holding result DataFrames when the response "
            "involves multiple datasets. Each variable is resolved and included "
            "as a separate entry in the response data."
        )
    )
```

### New Public Interfaces

```python
# No new public classes — this is an extension of existing interfaces.
# The DatasetResult model is internal to the response assembly.
```

---

## 3. Module Breakdown

### Module 1: PandasAgentResponse Extension

- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`
- **Responsibility**: Add `data_variables: Optional[List[str]]` field to `PandasAgentResponse`. Add `DatasetResult` model for structured multi-dataset output.
- **Depends on**: nothing new

### Module 2: Multi-Dataset Injection Logic

- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`
- **Responsibility**: Extend `_inject_data_from_variable()` to handle a list of variable names. Add `_inject_multi_data_from_variables()` method. Modify the response processing block (~L1428-1595) to detect `data_variables` and assemble a list of `DatasetResult` entries into `response.data`.
- **Depends on**: Module 1

### Module 3: LLM Prompt Update

- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`
- **Responsibility**: Update `PANDAS_SYSTEM_PROMPT` to instruct the LLM that when a query involves multiple datasets, it should populate `data_variables` (a list) instead of a single `data_variable`. The prompt must explain when to use each.
- **Depends on**: Module 1

### Module 4: Serialization Guard

- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`
- **Responsibility**: Update the serialization block (~L1594) to handle the case where `response.data` is already a list of `DatasetResult` dicts (not a raw DataFrame). Ensure backward compatibility: if `response.data` is a DataFrame, serialize as today; if it's a list of `DatasetResult`, leave as-is.
- **Depends on**: Module 2

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_pandas_response_single_data_variable` | Module 1 | Existing behavior: single `data_variable` produces single dataset in `response.data` |
| `test_pandas_response_multi_data_variables` | Module 1 | New: `data_variables=["df1", "df2"]` field accepted and validated |
| `test_inject_multi_data_single` | Module 2 | When only one variable in `data_variables`, behaves like single `data_variable` |
| `test_inject_multi_data_multiple` | Module 2 | When multiple variables, `response.data` is a list of named dataset results |
| `test_inject_multi_data_missing_var` | Module 2 | When a variable doesn't exist in context, it's skipped with warning |
| `test_serialization_single_df` | Module 4 | DataFrame serialized as `list[dict]` (unchanged) |
| `test_serialization_multi_datasets` | Module 4 | List of DatasetResult dicts passes through unchanged |

### Integration Tests

| Test | Description |
|---|---|
| `test_multi_dataset_end_to_end` | PandasAgent processes a multi-dataset query and returns structured response with multiple named datasets |

### Test Data / Fixtures

```python
@pytest.fixture
def multi_dataset_context():
    """Simulates Python REPL context with multiple DataFrames."""
    return {
        "users_q3": pd.DataFrame({
            "user_id": [1, 2, 3],
            "name": ["Alice", "Bob", "Carol"],
            "joined": ["2024-07", "2024-08", "2024-09"],
        }),
        "tasks_completed": pd.DataFrame({
            "user_id": [1, 1, 2],
            "task": ["Deploy", "Review", "Test"],
            "completed_at": ["2024-07-15", "2024-08-01", "2024-09-10"],
        }),
    }
```

---

## 5. Acceptance Criteria

- [ ] Single-dataset responses (existing behavior) are unchanged — no regressions
- [ ] When LLM sets `data_variables=["var1", "var2"]`, `response.data` contains a list with both datasets
- [ ] Each dataset entry in the list includes `name`, `data` (records), `shape`, and `columns`
- [ ] Missing variables are skipped with a logged warning, not a crash
- [ ] `data_variable` (singular) still works as before when `data_variables` is not set
- [ ] REST API consumers receive the multi-dataset structure in JSON
- [ ] LLM prompt instructs the model to use `data_variables` for multi-dataset queries
- [ ] All unit tests pass (`pytest tests/ -v`)
- [ ] No breaking changes to existing public API

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.bots.data import PandasAgentResponse, PandasTable  # verified: packages/ai-parrot/src/parrot/bots/data.py:49,126
from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:72
from parrot.tools.dataset_manager import DatasetManager, DatasetInfo  # verified: packages/ai-parrot/src/parrot/tools/dataset_manager/__init__.py:12
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/data.py
class PandasTable(BaseModel):  # line 49
    columns: List[str]  # line 51
    rows: List[List[Scalar]]  # line 54

class PandasAgentResponse(BaseModel):  # line 126
    explanation: str  # line 156
    data: Optional[PandasTable]  # line 163
    data_variable: Optional[str]  # line 175
    code: Optional[Union[str, Dict[str, Any]]]  # line 179

    def to_dataframe(self) -> Optional[pd.DataFrame]:  # line 202

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):  # line 72
    data: Optional[Any]  # line 86 — already accepts any type

# packages/ai-parrot/src/parrot/bots/data.py — PandasAgent methods
class PandasAgent:
    async def _inject_data_from_variable(self, response: AIMessage, data_variable: str) -> None:  # line 1917
    def _get_python_pandas_tool(self) -> Optional[...]:  # used at line 1924
    def _extract_saved_variable_from_tool_calls(self, tool_calls) -> Optional[str]:  # line 1470
    def _infer_data_variable_from_tools(self, tool_calls) -> Optional[str]:  # line 1474
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PandasAgentResponse.data_variables` | `PandasAgent` response processing | field read at ~L1441 | `data.py:1441` |
| `_inject_multi_data_from_variables()` | `PythonPandasTool.locals` | dict lookup | `data.py:1930-1939` |
| Response serialization | `AIMessage.data` | assignment | `data.py:1594` |

### Does NOT Exist (Anti-Hallucination)

- ~~`PandasAgentResponse.data_variables`~~ — does not exist yet (this spec adds it)
- ~~`PandasAgentResponse.datasets`~~ — does not exist
- ~~`DatasetResult`~~ — does not exist yet (this spec adds it)
- ~~`PandasAgent._inject_multi_data_from_variables()`~~ — does not exist yet
- ~~`AIMessage.datasets`~~ — does not exist, use `AIMessage.data` which is `Optional[Any]`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Use Pydantic `BaseModel` for `DatasetResult`
- Follow async-first design — `_inject_multi_data_from_variables` should be async
- Use `self.logger` for all warnings/diagnostics
- Preserve backward compatibility: `data_variable` (singular) takes precedence if both are set

### Backward Compatibility Strategy

The key invariant: **existing single-dataset consumers must not break**.

1. If `data_variables` is `None` (or empty) and `data_variable` is set → existing single-dataset path.
2. If `data_variables` has exactly one entry → treat as single-dataset (same output format as today).
3. If `data_variables` has 2+ entries → multi-dataset path, `response.data` becomes `list[DatasetResult]`.
4. If `data_variable` (singular) AND `data_variables` (plural) are both set → `data_variables` wins if it has 2+ entries; otherwise fall back to `data_variable`.

### Known Risks / Gotchas

- **LLM compliance**: The LLM may not always populate `data_variables` correctly. The prompt must be very explicit about when to use it. Fallback: if the LLM uses `data_variable` for one dataset and ignores others, behavior is unchanged (no regression).
- **Downstream consumers**: REST API handlers that assume `response.data` is always `list[dict]` (flat records) will need to handle the new `list[DatasetResult]` shape. This should be documented.
- **Serialization order**: When multiple datasets are involved, the order in `data_variables` determines the order in `response.data`.

### External Dependencies

None — no new packages required.

---

## 8. Open Questions

- [ ] Should `DatasetResult` include an `eda_summary` field for large datasets, or is `shape` + `columns` sufficient? — *Owner: Jesus Lara*
- [ ] Should the REST API response format wrap multi-dataset results in a `{"datasets": [...]}` envelope, or keep `data` as the top-level key? — *Owner: Jesus Lara*
- [ ] Should the LLM prompt encourage the model to always use `data_variables` (even for single datasets) to simplify the code path, or keep the dual path? — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All 4 modules modify the same file (`data.py`), so they must run sequentially in one worktree.
- **Cross-feature dependencies**: None — this feature is self-contained within `parrot/bots/data.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-14 | Jesus Lara | Initial draft |
