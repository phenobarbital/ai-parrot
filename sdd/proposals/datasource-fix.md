# FIX: DatasetManagerToolkit ↔ PythonPandasTool Variable Name Synchronization

**Priority:** High — causes agent to exhaust all tool-call iterations without producing a response.

## Problem Statement

When Gemini (or any LLM) uses the `DatasetManagerToolkit` tools (`get_metadata` → `fetch_dataset` → `get_dataframe`) followed by `python_repl_pandas`, the LLM invents variable names that don't exist in the PythonPandasTool execution environment. This causes `NameError` on every attempt, consuming all available iterations (typically 10) with zero useful output.

### Root Cause

Neither `fetch_dataset` nor `get_dataframe` communicate the **exact variable names** available in `python_repl_pandas`. The LLM sees a dataset name like `finance_visits_details` and generates code with invented variations (`finance_visits_details_final`, `df3` when the actual alias is `df1`, etc.).

### Reproduction (from logs)

```
Iteration 1: get_metadata        → OK (returns schema)
Iteration 2: fetch_dataset       → error in result (first attempt fails)
Iteration 3: fetch_dataset       → OK (materializes, _notify_change fires, sync runs)
Iteration 4: get_dataframe       → OK (returns {"name": "finance_visits_details", ...})
Iteration 5: python_repl_pandas  → print(finance_visits_details_final) → NameError
Iteration 6: python_repl_pandas  → print(df3) → NameError (alias is df1, not df3)
... iterations 7-10: same pattern, never recovers
```

---

## Changes

### CHANGE 1: Add variable name hints to `fetch_dataset` response

**File:** `parrot/tools/dataset_manager/tool.py`
**Method:** `DatasetManager.fetch_dataset()`
**Location:** Result dict construction (~line 1597-1610)

**Current code:**
```python
result: Dict[str, Any] = {
    "status": "materialized",
    "dataset": resolved,
    "shape": {"rows": df.shape[0], "columns": df.shape[1]},
    "column_schema": {
        str(col): str(dtype) for col, dtype in df.dtypes.items()
    },
    "eda_summary": self._generate_eda_summary(df),
    "sample_rows": sample_records,
}
if nan_warnings:
    result["warnings"] = nan_warnings
self._notify_change()
return result
```

**New code:**
```python
self._notify_change()

alias_map = self._get_alias_map()
alias = alias_map.get(resolved, "")

result: Dict[str, Any] = {
    "status": "materialized",
    "dataset": resolved,
    "python_variable": resolved,
    "python_alias": alias,
    "usage_hint": (
        f"In python_repl_pandas use `{resolved}` or `{alias}` as the "
        f"DataFrame variable. Do NOT modify or invent variable names."
    ),
    "shape": {"rows": df.shape[0], "columns": df.shape[1]},
    "column_schema": {
        str(col): str(dtype) for col, dtype in df.dtypes.items()
    },
    "eda_summary": self._generate_eda_summary(df),
    "sample_rows": sample_records,
}
if nan_warnings:
    result["warnings"] = nan_warnings
return result
```

**Rationale:** `_notify_change()` must fire before building the alias map so that the PythonPandasTool environment is synced before we read the alias. The `usage_hint` gives the LLM an explicit instruction that appears in the tool result.

---

### CHANGE 2: Add variable name hints to `get_dataframe` response

**File:** `parrot/tools/dataset_manager/tool.py`
**Method:** `DatasetManager.get_dataframe()`
**Location:** Return dict construction (~line 1495-1505)

**Current code:**
```python
alias_map = self._get_alias_map()
df = entry.df

return {
    "name": resolved_name,
    "alias": alias_map.get(resolved_name),
    "shape": {"rows": df.shape[0], "columns": df.shape[1]},
    "columns": df.columns.tolist(),
    "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
    "column_types": entry.column_types,
    "is_active": entry.is_active,
    "null_count": entry.null_count,
    "sample_rows": df.head(3).to_dict(orient='records'),
}
```

**New code:**
```python
alias_map = self._get_alias_map()
alias = alias_map.get(resolved_name, "")
df = entry.df

return {
    "name": resolved_name,
    "alias": alias,
    "python_variable": resolved_name,
    "python_alias": alias,
    "usage_hint": (
        f"In python_repl_pandas use `{resolved_name}` or `{alias}` "
        f"as the DataFrame variable. Do NOT modify or invent variable names."
    ),
    "shape": {"rows": df.shape[0], "columns": df.shape[1]},
    "columns": df.columns.tolist(),
    "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
    "column_types": entry.column_types,
    "is_active": entry.is_active,
    "null_count": entry.null_count,
    "sample_rows": df.head(3).to_dict(orient='records'),
}
```

**Rationale:** Same pattern as Change 1. Every tool that returns dataset info must include the exact variable names.

---

### CHANGE 3: Add `list_datasets` variable name hints

**File:** `parrot/tools/dataset_manager/tool.py`
**Method:** `DatasetManager.list_datasets()` (the LLM-facing tool)
**Location:** Where each dataset entry is built in the response

Find the method that builds the list of datasets for the LLM. For each dataset entry in the response, add:

```python
"python_variable": name,
"python_alias": alias,
```

**Rationale:** If the LLM calls `list_datasets` first (which is the intended discovery flow), it should already know the correct variable names before ever calling `python_repl_pandas`.

---

### CHANGE 4: Improve `fetch_dataset` docstring for LLM tool description

**File:** `parrot/tools/dataset_manager/tool.py`
**Method:** `DatasetManager.fetch_dataset()`
**Location:** Docstring

**Current docstring (abbreviated):**
```python
"""
Materialize a dataset by fetching data from its source.
...
"""
```

**Append to docstring:**
```python
"""
Materialize a dataset by fetching data from its source.

...existing content...

IMPORTANT: The response includes 'python_variable' and 'python_alias' fields.
These are the ONLY valid variable names in python_repl_pandas.
Always use one of these exact names — never modify or invent new names.
"""
```

**Rationale:** Many LLMs read tool docstrings as part of the function schema. This reinforces the contract.

---

### CHANGE 5: NameError recovery hint in `PythonPandasTool._execute`

**File:** `parrot/tools/pythonpandas.py`
**Method:** `PythonPandasTool._execute()`
**Location:** After `result = await super()._execute(...)` (~line 658), before the audit block

**Add after line 658:**
```python
# NameError recovery: tell the LLM which variables actually exist
if isinstance(result, str) and 'NameError' in result:
    available_names = list(self.dataframes.keys())
    available_aliases = [
        f"{self.df_prefix}{i + 1}"
        for i in range(len(self.dataframes))
    ]
    all_vars = available_names + available_aliases
    if all_vars:
        result += (
            f"\n\n💡 Available DataFrame variables: {all_vars}. "
            f"Use one of these exact names."
        )
    else:
        result += (
            "\n\n💡 No DataFrames are loaded. "
            "Call fetch_dataset first to materialize data."
        )
```

**Rationale:** Even with Changes 1-4, LLMs will occasionally hallucinate variable names. This gives immediate corrective feedback on the first NameError instead of letting the LLM guess blindly for 5+ iterations.

---

### CHANGE 6: Move `_notify_change()` before return in `fetch_dataset`

**File:** `parrot/tools/dataset_manager/tool.py`
**Method:** `DatasetManager.fetch_dataset()`
**Location:** Line ~1609

**Current order:**
```python
result: Dict[str, Any] = { ... }
if nan_warnings:
    result["warnings"] = nan_warnings
self._notify_change()  # <-- fires AFTER building result
return result
```

**New order:**
```python
self._notify_change()  # <-- fire FIRST so PythonPandasTool is synced

alias_map = self._get_alias_map()
alias = alias_map.get(resolved, "")

result: Dict[str, Any] = { ... }  # now alias_map is accurate
if nan_warnings:
    result["warnings"] = nan_warnings
return result
```

**Rationale:** `_notify_change()` triggers `_sync_dataframes_from_dm()` which calls `pandas_tool.register_dataframes()`. This must happen BEFORE we read `_get_alias_map()` to build the response, so the alias map reflects the post-sync state. It also ensures that by the time the LLM receives the tool result and calls `python_repl_pandas`, the execution environment is already up to date.

> **Note:** This is already reflected in the Change 1 code block above but called out explicitly because the ordering is the subtle part.

---

## Files Modified

| File | Changes |
|------|---------|
| `parrot/tools/dataset_manager/tool.py` | Changes 1, 2, 3, 4, 6 |
| `parrot/tools/pythonpandas.py` | Change 5 |

## Testing

1. **Unit test:** Call `fetch_dataset` on a TableSource-backed dataset. Assert response contains `python_variable` and `python_alias` keys with correct values matching `_get_alias_map()`.

2. **Unit test:** Call `get_dataframe` on a loaded dataset. Assert same keys present.

3. **Unit test:** Execute code with a wrong variable name in `PythonPandasTool._execute()`. Assert the result string contains "Available DataFrame variables" with the correct names.

4. **Integration test:** Full multi-turn flow with Gemini: `get_metadata` → `fetch_dataset` → `python_repl_pandas`. Assert the LLM uses the exact variable name from the `fetch_dataset` response and the code executes without NameError.

5. **Edge case:** Dataset with dots in name (e.g., `troc.finance_visits_details`). Verify the `python_variable` returned is the resolved name that's actually bound in `PythonPandasTool.locals` (not the raw table reference).