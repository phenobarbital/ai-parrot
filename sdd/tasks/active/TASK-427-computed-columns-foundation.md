# TASK-427: Computed Columns Foundation

**Feature**: composite-datasets
**Spec**: `sdd/specs/composite-datasets.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the foundational module for computed columns: the `ComputedColumnDef` Pydantic model, the `COMPUTED_FUNCTIONS` registry, built-in fallback functions, and the lazy-load bridge from QuerySource functions.

Implements **Module 1** from the spec (Section 3).

---

## Scope

- Create `computed.py` with:
  - `ComputedColumnDef` Pydantic model (name, func, columns, kwargs, description)
  - `COMPUTED_FUNCTIONS: Dict[str, Callable]` registry
  - `register_computed_function(name, fn)` — add to registry
  - `get_computed_function(name)` — get from registry (lazy-loads on first call)
  - `list_computed_functions()` — sorted list of available function names
  - `_load_querysource_functions()` — lazy import from `querysource.models.functions`
  - `_builtin_math_operation(df, field, columns, operation, **kwargs)` — add/subtract/multiply/divide
  - `_builtin_concatenate(df, field, columns, sep, **kwargs)` — multi-column string concat
- Write unit tests for all public API and built-in functions

**NOT in scope**: Integration with DatasetEntry (TASK-428), add_* methods (TASK-429), LLM tools (TASK-430)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/computed.py` | CREATE | ComputedColumnDef model, function registry, built-in functions |
| `tests/tools/dataset_manager/test_computed.py` | CREATE | Unit tests for registry and built-in functions |

---

## Implementation Notes

### Pattern to Follow

All functions in the registry MUST follow the QuerySource pattern:
```python
def fn(df: pd.DataFrame, field: str, columns: list, **kwargs) -> pd.DataFrame:
    """
    Args:
        df: Input DataFrame
        field: Name of the new column to create
        columns: Source column names to operate on
        **kwargs: Extra parameters (e.g., operation="subtract", sep=" ")
    Returns:
        df with the new column added
    """
```

### Key Constraints
- `_load_querysource_functions()` must be lazy (called only on first `get_computed_function` or `list_computed_functions` call)
- Built-in fallbacks must always be available even without querysource installed
- Division by zero in `_builtin_math_operation` must produce NaN, not raise
- Use `pydantic.BaseModel` for `ComputedColumnDef`
- Use standard logging (`logging.getLogger(__name__)`)

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py` — DataSource ABC pattern
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — DatasetManager patterns
- Spec Section 2.3–2.5 for exact model and function signatures

---

## Acceptance Criteria

- [ ] `ComputedColumnDef` model validates correctly with Pydantic
- [ ] `register_computed_function()` adds functions to registry
- [ ] `get_computed_function()` returns function or None; lazy-loads on first call
- [ ] `list_computed_functions()` returns sorted list of names
- [ ] `_builtin_math_operation` handles add, sum, subtract, multiply, divide
- [ ] `_builtin_math_operation` produces NaN for division by zero
- [ ] `_builtin_math_operation` raises ValueError for unsupported operations
- [ ] `_builtin_math_operation` raises ValueError for != 2 columns
- [ ] `_builtin_concatenate` handles multiple columns with custom separator
- [ ] QuerySource import is optional (graceful fallback when not installed)
- [ ] All tests pass: `pytest tests/tools/dataset_manager/test_computed.py -v`
- [ ] Import works: `from parrot.tools.dataset_manager.computed import ComputedColumnDef, get_computed_function`

---

## Test Specification

```python
# tests/tools/dataset_manager/test_computed.py
import pytest
import pandas as pd
from parrot.tools.dataset_manager.computed import (
    ComputedColumnDef,
    register_computed_function,
    get_computed_function,
    list_computed_functions,
    COMPUTED_FUNCTIONS,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry between tests."""
    COMPUTED_FUNCTIONS.clear()
    yield
    COMPUTED_FUNCTIONS.clear()


class TestComputedColumnDef:
    def test_basic_creation(self):
        col = ComputedColumnDef(
            name="ebitda", func="math_operation",
            columns=["revenue", "expenses"],
            kwargs={"operation": "subtract"},
            description="EBITDA calculation",
        )
        assert col.name == "ebitda"
        assert col.func == "math_operation"

    def test_defaults(self):
        col = ComputedColumnDef(name="x", func="f", columns=["a"])
        assert col.kwargs == {}
        assert col.description == ""


class TestRegistry:
    def test_register_and_get(self):
        def dummy(df, field, columns, **kw):
            return df
        register_computed_function("dummy", dummy)
        assert get_computed_function("dummy") is dummy

    def test_get_unknown_returns_none(self):
        # Force load so registry isn't empty
        list_computed_functions()
        assert get_computed_function("nonexistent") is None

    def test_list_functions_sorted(self):
        fns = list_computed_functions()
        assert fns == sorted(fns)
        assert "math_operation" in fns
        assert "concatenate" in fns


class TestBuiltinMathOperation:
    def test_add(self):
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="add")
        assert list(result["c"]) == [4, 6]

    def test_subtract(self):
        df = pd.DataFrame({"a": [10, 20], "b": [3, 5]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="subtract")
        assert list(result["c"]) == [7, 15]

    def test_divide_by_zero(self):
        df = pd.DataFrame({"a": [10, 20], "b": [0, 5]})
        fn = get_computed_function("math_operation")
        result = fn(df, "c", ["a", "b"], operation="divide")
        assert pd.isna(result["c"].iloc[0])
        assert result["c"].iloc[1] == 4.0

    def test_invalid_operation(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        fn = get_computed_function("math_operation")
        with pytest.raises(ValueError, match="Unsupported operation"):
            fn(df, "c", ["a", "b"], operation="modulo")

    def test_wrong_column_count(self):
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        fn = get_computed_function("math_operation")
        with pytest.raises(ValueError, match="exactly 2 columns"):
            fn(df, "d", ["a", "b", "c"], operation="add")


class TestBuiltinConcatenate:
    def test_two_columns(self):
        df = pd.DataFrame({"first": ["John", "Jane"], "last": ["Doe", "Smith"]})
        fn = get_computed_function("concatenate")
        result = fn(df, "full", ["first", "last"], sep=" ")
        assert list(result["full"]) == ["John Doe", "Jane Smith"]

    def test_custom_separator(self):
        df = pd.DataFrame({"city": ["Miami"], "code": ["W01"]})
        fn = get_computed_function("concatenate")
        result = fn(df, "label", ["city", "code"], sep=" - ")
        assert result["label"].iloc[0] == "Miami - W01"

    def test_three_columns(self):
        df = pd.DataFrame({"a": ["x"], "b": ["y"], "c": ["z"]})
        fn = get_computed_function("concatenate")
        result = fn(df, "out", ["a", "b", "c"], sep=",")
        assert result["out"].iloc[0] == "x,y,z"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/composite-datasets.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-427-computed-columns-foundation.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
