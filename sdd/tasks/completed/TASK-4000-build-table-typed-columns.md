# TASK-4000: Typed table columns from DataFrame dtypes in `infographic_build_block`

**Feature**: FEAT-623 — Infographic → A2UI display hints
**Spec**: `sdd/specs/infographic-a2ui-display-hints.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3994
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, plus codex S9. `infographic_build_block(block_type="table")`
builds a table from a REPL DataFrame but emits bare string column names. The
DataFrame dtype is a **typed source**: an integer column is an integer, so
declaring it is not guessing (spec §5 "Never guess"). This task emits
`ColumnDef{header, type}` so the adapter (TASK-3995) can forward
`columns[].type` and renderers can right-align and sort numerically.

---

## Scope

- Make `_build_table_block` emit `ColumnDef` dicts (`{"header": str, "type": …}`) instead of bare strings, for **every** column, because `TableBlock.columns` is `Union[List[str], List[ColumnDef]]` and cannot mix the two.
- Add a pure module-level helper `_column_type_for(series) -> Optional[str]` using `pandas.api.types` predicates:
  - `is_bool_dtype` → `"boolean"`. Check this before integer, because bool is an integer subtype.
  - `is_integer_dtype`, including nullable `Int64`, → `"integer"`.
  - `is_float_dtype`, including `Float64`, → `"number"`.
  - `is_datetime64_any_dtype`, including tz-aware, → `"datetime"`.
  - Anything else (`object`, `category`, mixed, string) → `None`, and the `type` key is omitted.
- Never emit `format`: a dtype carries no currency or percent meaning.
- Update the two existing table tests and add dtype-map tests.

**NOT in scope**:
- Chart blocks (`_build_chart_block` is unchanged).
- The adapter (TASK-3995).
- HTML rendering (TASK-3997).
- Prompt text.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | `_build_table_block` emits typed `ColumnDef` dicts; new `_column_type_for` helper |
| `packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py` | MODIFY | update table assertions; add dtype-map tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd                       # verified: packages/ai-parrot/src/parrot/tools/infographic_toolkit.py:30
from pandas.api import types as pdt       # NEW import in this task — pandas public API
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):
    async def build_block(...)                                   # :1226 ; table path calls _build_table_block at :1300
    def _build_table_block(                                      # :1608
        self,
        repl_locals: Dict[str, Any],
        data_variable: Optional[str],
        table_columns: Optional[List[str]],
        max_rows: Optional[int],
        title: Optional[str],
    ) -> Dict[str, Any]:
        # df = self._require_dataframe(...); columns = table_columns or list(df.columns)
        # block = {"type": "table", "columns": [str(c) for c in columns],   # :1623
        #          "rows": df[columns].values.tolist()}
    def _coerce_single_block(self, block_dict) -> Dict[str, Any] # :1630 — InfographicResponse.model_validate
        # then model.model_dump(mode="json"): ColumnDef dicts come back with ALL keys
        # (header, width, align, color, type, format) — None where unset.

# packages/ai-parrot/src/parrot/models/infographic.py (after TASK-3994)
class ColumnDef(BaseModel): header: str; width; align; color; type: Optional[str]; format: Optional[str]
class TableBlock(BaseModel): columns: Union[List[str], List[ColumnDef]]   # :754 — no mixed lists

# packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py
# fixture `repl` (:52-62): DataFrame "rev" = date (object) / rev_dod (int64) / ebitda (float64)
# fixture `toolkit` (:65-78)
# TestBuildTable.test_table_from_dataframe (:137) asserts block["columns"] == ["date", "rev_dod"]  → MUST change
# test_table_defaults_to_all_columns (:149) asserts columns == ["date","rev_dod","ebitda"]          → MUST change
```

### Does NOT Exist
- ~~`InfographicToolkit._column_type_for`~~: created by this task, as a module-level function.
- ~~A `format` inferred from a dtype~~: never emitted (spec M6).
- ~~Mixed `columns` lists (`["a", {"header": "b"}]`)~~: `TableBlock` rejects them. Emit ColumnDef for every column.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/infographic_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/infographic_toolkit.py#InfographicToolkit._build_table_block",
    "sym:packages/ai-parrot/src/parrot/tools/infographic_toolkit.py#InfographicToolkit._coerce_single_block",
    "sym:packages/ai-parrot/src/parrot/models/infographic.py#ColumnDef"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use `pandas.api.types` predicates, not dtype-name strings. Strings miss
  the nullable (`Int64`, `Float64`, `boolean`) and tz-aware dtypes.
- Order matters: test bool first.
- The returned block still goes through `_coerce_single_block`. After
  `model_dump(mode="json")` each column dict carries `None` for unset keys.
  That is expected, and the assertions should compare `header`/`type`, not
  the whole dict.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `pdt` import and the `_column_type_for` helper — *why*: a pure
   function with a bounded, testable map (codex S9).
2. Replace the `columns` line in `_build_table_block` — *why*: emit
   `ColumnDef` for every column so `TableBlock` never sees a mixed list.
3. Update the existing tests and add the dtype matrix — *why*: they pin the
   map, including the nullable, tz-aware and categorical cases.

### `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` (MODIFY) — import + helper
```python
# occurrences: 1 (verified: grep -cF 'import pandas as pd' packages/ai-parrot/src/parrot/tools/infographic_toolkit.py)
# AFTER — insert below `import pandas as pd` (verified: :30)
from pandas.api import types as pdt
```
Then add the helper at module level, just above `class InfographicToolkit` (FILL IN: locate the class line with `grep -n "^class InfographicToolkit" …`):
```python
def _column_type_for(series: pd.Series) -> Optional[str]:
    """Map a DataFrame column's dtype to a ``TableColumn.type`` value, or ``None``.

    The dtype is a typed source, not a guess. Bool is tested before integer because
    bool is an integer subtype; anything that is not clearly numeric/boolean/datetime
    (object, category, mixed, string) yields ``None`` so no ``type`` is declared.
    """
    if pdt.is_bool_dtype(series):
        return "boolean"
    if pdt.is_integer_dtype(series):
        return "integer"
    if pdt.is_float_dtype(series):
        return "number"
    if pdt.is_datetime64_any_dtype(series):
        return "datetime"
    return None
```

### `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` (MODIFY) — `_build_table_block`
```python
# occurrences: 1 (verified: grep -cF '"columns": [str(c) for c in columns],' packages/ai-parrot/src/parrot/tools/infographic_toolkit.py)
# REPLACE that line (verified: :1623) with:
            "columns": [_column_def(str(c), _column_type_for(df[c])) for c in columns],
```
and add next to `_column_type_for`:
```python
def _column_def(header: str, col_type: Optional[str]) -> Dict[str, Any]:
    """``ColumnDef`` dict; the ``type`` key is omitted when the dtype says nothing."""
    return {"header": header, "type": col_type} if col_type else {"header": header}
```

### `packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py` (MODIFY)
```python
# :137 test_table_from_dataframe — replace `assert block["columns"] == ["date", "rev_dod"]` with
#   assert [(c["header"], c.get("type")) for c in block["columns"]] == [("date", None), ("rev_dod", "integer")]
# :149 test_table_defaults_to_all_columns — same shape, ebitda → "number"
# ADD class TestColumnTypeFor (pure, no toolkit):
#   FILL IN: parametrize over pd.Series of int64, Int64 (nullable, with pd.NA), float64,
#   Float64, bool, "boolean", datetime64[ns], datetime64[ns, UTC], category, object,
#   mixed object → expected integer/integer/number/number/boolean/boolean/datetime/
#   datetime/None/None/None — bounded by spec M6 map.
#   Import it as `from parrot.tools.infographic_toolkit import _column_type_for` AFTER the
#   module-level sys.modules juggling at the top of the file (same as InfographicToolkit, :37).
# ADD test_table_never_emits_format — no column has a non-None "format".
```

### FILL IN checklist
- [ ] Locate the `class InfographicToolkit` line, and place both helpers above it.
- [ ] The `TestColumnTypeFor` parametrize matrix, with all 11 cases.
- [ ] `test_table_never_emits_format`.

---

## Acceptance Criteria

- [ ] AC-1: `build_block(block_type="table")` emits a `ColumnDef` dict for every column. `type` follows the M6 map, and is omitted when the map gives `None`.
- [ ] AC-2: nullable `Int64`/`Float64`/`boolean` and tz-aware datetimes map correctly. `category`/`object` give no type.
- [ ] AC-3: no column ever carries a non-None `format`.
- [ ] AC-4: the chart path and every other build_block test are unchanged and green.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/tools/test_infographic_build_block.py -q`
- `pytest packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py -q`

---

## Agent Instructions

1. Work in the feature worktree. TASK-3994 must be `done`, because `ColumnDef.type` must exist or `_coerce_single_block` rejects the block.
2. Re-run each `grep -cF` above. A count of `0` means drift: stop and report it.
3. Implement, complete every FILL IN, and run the Validation Commands.
4. Commit only the two listed files. Close with `scripts/sdd/close_task.sh TASK-4000 infographic-a2ui-display-hints verified`.

---

## Completion Note



**Completed by**: sdd-worker (Claude Sonnet 5.5, fallback sequential loop — parrot-sdd-coder unavailable)
**Date**: 2026-09-30
**Notes**: _column_type_for (pandas.api.types, bool first) + _column_def; every column emitted as ColumnDef dict, type omitted when unknown, format never. Duplicate column names (df[c] is a DataFrame) yield no type. 52 tests pass. Observed: running test_infographic_sections.py together with the whole unit/tools -k infographic set fails 5 tests (module-pop pollution from test_infographic_build_block's sys.modules juggling); the file passes alone (19) — not caused by this change.

**Deviations from spec**: none
