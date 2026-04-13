# TASK-663: Multi-Dataset Injection Logic

**Feature**: datasetmanager-more-data
**Spec**: `sdd/specs/datasetmanager-more-data.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-662
**Assigned-to**: unassigned

---

## Context

This is the core logic task for FEAT-098. It adds the `_inject_multi_data_from_variables()`
method and modifies the response processing block in `PandasAgent` to detect
`data_variables` (plural) and assemble multiple `DatasetResult` entries into `response.data`.

Implements **Module 2** from the spec.

---

## Scope

- Add `_inject_multi_data_from_variables(self, response: AIMessage, data_variables: List[str]) -> None` async method to `PandasAgent`
- Modify the response processing block (~L1428-1549) to:
  1. Check if `data_response.data_variables` is set and has 2+ entries
  2. If yes, call `_inject_multi_data_from_variables()` instead of `_inject_data_from_variable()`
  3. If `data_variables` has exactly 1 entry, fall back to existing single-variable path
  4. If `data_variables` is None/empty, use existing `data_variable` path (unchanged)
- The new method must:
  1. Resolve each variable from `PythonPandasTool.locals`
  2. For each resolved DataFrame, build a `DatasetResult` dict
  3. Set `response.data` to a list of `DatasetResult` dicts
  4. Skip missing variables with a logged warning
- Write unit tests for the injection logic

**NOT in scope**:
- Model changes (TASK-662 — already done)
- Prompt changes (TASK-664)
- Serialization changes (TASK-665)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Add `_inject_multi_data_from_variables()`, modify response processing block |
| `tests/unit/test_multi_dataset_injection.py` | CREATE | Unit tests for injection logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/bots/data.py
from parrot.bots.data import DatasetResult, PandasAgentResponse  # DatasetResult added by TASK-662
from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:72
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py

class PandasAgentResponse(BaseModel):  # line 126
    explanation: str  # line 156
    data: Optional[PandasTable]  # line 163
    data_variable: Optional[str]  # line 175
    data_variables: Optional[List[str]]  # ADDED BY TASK-662
    code: Optional[Union[str, Dict[str, Any]]]  # line 179

# PandasAgent response processing — key lines:
# line 1428: data_response extraction from response.output
# line 1431: if data_response:
# line 1433:     response.data = data_response.to_dataframe()
# line 1441:     if data_response.data_variable:
# line 1446:         await self._inject_data_from_variable(response, data_response.data_variable)

# PandasAgent existing injection method:
async def _inject_data_from_variable(self, response: AIMessage, data_variable: str) -> None:  # line 1917
    # Gets PythonPandasTool via self._get_python_pandas_tool()  # line 1924
    # Checks pandas_tool.locals for the variable  # line 1930-1932
    # Falls back to pandas_tool.locals['execution_results']  # line 1936-1939
    # Copies df, resets index, converts columns to str  # line 1947-1953
    # Sets response.data = df  # line 1954

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):  # line 72
    data: Optional[Any]  # line 86 — already accepts any type
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_inject_multi_data_from_variables()` | `PythonPandasTool.locals` | dict lookup | `data.py:1930-1939` |
| `_inject_multi_data_from_variables()` | `DatasetResult` | model construction | Added by TASK-662 |
| Response processing block | `data_response.data_variables` | field check | `data.py:~1441` |

### Does NOT Exist
- ~~`PandasAgent._inject_multi_data_from_variables()`~~ — does not exist yet (this task adds it)
- ~~`AIMessage.datasets`~~ — does not exist, use `AIMessage.data`
- ~~`response.datasets`~~ — does not exist, use `response.data`
- ~~`PythonPandasTool.get_variable()`~~ — no such method, use `pandas_tool.locals[var_name]`

---

## Implementation Notes

### Pattern to Follow
```python
# Model the new method after _inject_data_from_variable (line 1917-1958)
async def _inject_multi_data_from_variables(
    self,
    response: AIMessage,
    data_variables: List[str],
) -> None:
    """Inject multiple DataFrames from PythonPandasTool context into response.data."""
    pandas_tool = self._get_python_pandas_tool()
    if not pandas_tool:
        self.logger.warning("PythonPandasTool not available for multi-dataset injection")
        return

    results: List[Dict[str, Any]] = []
    for var_name in data_variables:
        df = None
        if hasattr(pandas_tool, "locals"):
            if var_name in pandas_tool.locals:
                df = pandas_tool.locals.get(var_name)
            if df is None and 'execution_results' in pandas_tool.locals:
                exec_results = pandas_tool.locals['execution_results']
                if isinstance(exec_results, dict) and var_name in exec_results:
                    df = exec_results.get(var_name)

        if isinstance(df, pd.DataFrame):
            df = df.copy()
            df.reset_index(inplace=True)
            df.columns = df.columns.astype(str)
            results.append(
                DatasetResult(
                    name=var_name,
                    variable=var_name,
                    data=self._clean_records(df),
                    shape=(len(df), df.shape[1]),
                    columns=df.columns.tolist(),
                ).model_dump()
            )
        else:
            self.logger.warning(
                "Multi-dataset injection: variable '%s' not found or not a DataFrame",
                var_name,
            )

    if results:
        response.data = results
```

### Key Constraints
- The method is `async` (consistent with `_inject_data_from_variable`)
- Use `self._clean_records(df)` for serialization (existing helper that handles NaN/Inf)
- Set `response.data` to a list of dicts (serialized `DatasetResult`), NOT raw DataFrames
- Place the new method right after `_inject_data_from_variable` (~line 1958)
- In the response processing block, check `data_variables` BEFORE falling back to `data_variable`

### Response Processing Block Modification
In the `if data_response:` block (~L1431), add after line 1440:
```python
# Multi-dataset path: data_variables (plural) with 2+ entries
if data_response.data_variables and len(data_response.data_variables) >= 2:
    await self._inject_multi_data_from_variables(
        response, data_response.data_variables
    )
elif data_response.data_variable:
    # Existing single-variable path (unchanged)
    ...
```

### `_clean_records` Reference
Grep for `_clean_records` in data.py to find the exact signature before using it.
It converts a DataFrame to a list of dicts with NaN/Inf handling.

---

## Acceptance Criteria

- [ ] `_inject_multi_data_from_variables()` method exists on `PandasAgent`
- [ ] When `data_variables=["var1", "var2"]`, `response.data` contains 2 `DatasetResult` dicts
- [ ] When `data_variables=["var1"]` (single entry), falls back to single-variable behavior
- [ ] Missing variables are skipped with a warning, other variables still included
- [ ] Existing `data_variable` (singular) path is unchanged
- [ ] Tests pass: `pytest tests/unit/test_multi_dataset_injection.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_multi_dataset_injection.py
import pytest
import pandas as pd
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.bots.data import DatasetResult


@pytest.fixture
def mock_pandas_tool():
    tool = MagicMock()
    tool.locals = {
        "users_q3": pd.DataFrame({
            "user_id": [1, 2, 3],
            "name": ["Alice", "Bob", "Carol"],
        }),
        "tasks_completed": pd.DataFrame({
            "user_id": [1, 1, 2],
            "task": ["Deploy", "Review", "Test"],
        }),
    }
    return tool


class TestMultiDatasetInjection:
    @pytest.mark.asyncio
    async def test_multiple_variables_resolved(self, mock_pandas_tool):
        """Two valid variables produce two DatasetResult entries."""
        # Setup mock agent and response, call _inject_multi_data_from_variables
        # Assert response.data is a list of 2 dicts with correct names
        pass

    @pytest.mark.asyncio
    async def test_missing_variable_skipped(self, mock_pandas_tool):
        """A missing variable is skipped, others are still included."""
        pass

    @pytest.mark.asyncio
    async def test_single_variable_fallback(self):
        """Single entry in data_variables behaves like data_variable."""
        pass

    @pytest.mark.asyncio
    async def test_no_pandas_tool_warns(self):
        """If PythonPandasTool is unavailable, logs warning and returns."""
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-more-data.spec.md` for full context
2. **Check dependencies** — verify TASK-662 is in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_inject_data_from_variable` still exists at ~line 1917
   - Confirm `_get_python_pandas_tool` method exists
   - Confirm `DatasetResult` was added by TASK-662
   - Grep for `_clean_records` to find its exact signature
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-663-multi-dataset-injection.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
