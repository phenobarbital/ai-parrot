# Feature Specification: Computed Columns & Composite Datasets

**Feature ID**: FEAT-062
**Date**: 2026-03-25
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

DatasetManager datasets often need derived columns that don't exist in the source data (e.g., EBITDA = revenue - expenses, display_name = first + " " + last). Today, the LLM must compute these in `python_repl_pandas` every time — wasting tokens and introducing inconsistency.

Similarly, datasets from different sources (different databases, APIs) cannot be JOINed at the database level. The LLM must manually fetch both and write pandas merge code, again wasting tokens and risking inconsistent results.

### Goals

- **Computed Columns**: Declarative, auto-applied derived columns computed post-materialization using the existing QuerySource function catalog. Transparent to the LLM — they appear as regular DataFrame columns.
- **Composite Datasets**: Virtual datasets that JOIN two or more existing datasets on-demand, with intelligent per-component filter propagation. Transparent to the LLM — they behave like any other dataset.
- **Runtime computed columns**: LLM can add computed columns at runtime, restricted to a safe function registry.

### Non-Goals (explicitly out of scope)

- AST/expression parser for arbitrary Python expressions (deferred — function registry covers current needs)
- YAML/JSON config file for defining composites (programmatic API only for now)
- Topological sort for computed column ordering (list order = execution order)
- Redis caching of composite JOIN results (components cached individually)

---

## 2. Architectural Design

### Overview

Two layered features that extend DatasetManager:

1. **Computed Columns** — A `ComputedColumnDef` model + function registry (`COMPUTED_FUNCTIONS`). Columns are applied post-materialization in `DatasetEntry._apply_computed_columns()`. Functions follow the QuerySource pattern: `fn(df, field, columns, **kwargs) -> df`.

2. **Composite Datasets** — A `CompositeDataSource` (extends `DataSource`) that references existing datasets by name, materializes them independently, applies per-component filters, and executes sequential JOINs via `pd.merge()`.

```
                    ┌──────────────────────┐
                    │   DatasetManager     │
                    │   (tool.py)          │
                    └──────┬───────────────┘
                           │
          ┌────────────────┼────────────────────┐
          │                │                    │
   ┌──────▼──────┐  ┌─────▼──────┐  ┌─────────▼──────────┐
   │ DatasetEntry │  │ computed.py│  │ sources/composite.py│
   │ +computed_   │  │ Registry   │  │ CompositeDataSource │
   │  columns     │  │ + builtins │  │ JoinSpec            │
   └──────────────┘  └────────────┘  └─────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatasetEntry` | extends | Add `computed_columns` param, `_apply_computed_columns()` method |
| `DataSource` (ABC) | implements | `CompositeDataSource` implements the interface |
| `DatasetManager.add_*` | modifies | All registration methods gain `computed_columns` param |
| `DatasetManager.fetch_dataset` | modifies | New branch for `CompositeDataSource` routing |
| `DatasetManager._generate_dataframe_guide` | modifies | New block for composite datasets |
| `DatasetInfo` | modifies | Add `"composite"` to `source_type` Literal |
| `DatasetManager.list_datasets` | modifies | Action_required for composite datasets |
| `DatasetManager.get_metadata` | modifies | Not-loaded guidance for composites |
| QuerySource functions | imports (lazy) | `math_operation`, `concatenate_columns`, etc. |

### Data Models

```python
# computed.py
class ComputedColumnDef(BaseModel):
    """Definition of a computed column applied post-materialization."""
    name: str = Field(description="Name of the new column")
    func: str = Field(description="Function name from COMPUTED_FUNCTIONS registry")
    columns: List[str] = Field(description="Source column names to operate on")
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", description="Human-readable description for LLM")

# sources/composite.py
class JoinSpec(BaseModel):
    """Specification for joining two datasets."""
    left: str = Field(description="Left dataset name")
    right: str = Field(description="Right dataset name")
    on: Union[str, List[str]] = Field(description="Join column(s)")
    how: str = Field(default="inner", description="Join type: inner, left, right, outer")
    suffixes: tuple = Field(default=("", "_right"))
```

### New Public Interfaces

```python
# DatasetManager new methods
def add_composite_dataset(
    self, name: str, joins: List[Dict[str, Any]], *,
    description: str = "", computed_columns: Optional[List[ComputedColumnDef]] = None,
    is_active: bool = True, metadata: Optional[Dict[str, Any]] = None,
) -> str: ...

async def add_computed_column(
    self, dataset_name: str, column_name: str, func: str,
    columns: List[str], description: str = "", **kwargs,
) -> str: ...

async def list_available_functions(self) -> List[str]: ...

# Registry API
def register_computed_function(name: str, fn: Callable) -> None: ...
def get_computed_function(name: str) -> Optional[Callable]: ...
def list_computed_functions() -> List[str]: ...
```

---

## 3. Module Breakdown

### Module 1: Computed Columns Foundation
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/computed.py` (NEW)
- **Responsibility**: `ComputedColumnDef` model, `COMPUTED_FUNCTIONS` registry, built-in fallback functions (`_builtin_math_operation`, `_builtin_concatenate`), lazy-load bridge from QuerySource functions, public API (`register_computed_function`, `get_computed_function`, `list_computed_functions`)
- **Depends on**: `pydantic`, `pandas`; optional lazy import of `querysource.models.functions`

### Module 2: DatasetEntry Computed Column Integration
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY `DatasetEntry`)
- **Responsibility**: Add `computed_columns` parameter to `DatasetEntry.__init__`, implement `_apply_computed_columns()`, modify `materialize()` to apply post-fetch/pre-categorization, modify `columns` property to include computed names in prefetch state, modify `_column_metadata` to inject computed descriptions
- **Depends on**: Module 1

### Module 3: DatasetManager add_* Methods Update
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY `DatasetManager`)
- **Responsibility**: Add `computed_columns` param to all `add_*` methods (`add_dataframe`, `add_query`, `add_table_source`, `add_sql_source`, `add_airtable_source`, `add_smartsheet_source`, `add_iceberg_source`, `add_mongo_source`, `add_deltatable_source`, `add_dataset`), pass through to `DatasetEntry`
- **Depends on**: Module 2

### Module 4: LLM Runtime Computed Columns
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY `DatasetManager`)
- **Responsibility**: `add_computed_column()` LLM tool method, `list_available_functions()` LLM tool method, column/function validation, immediate application if dataset loaded, guide regeneration
- **Depends on**: Modules 1, 2

### Module 5: CompositeDataSource
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/composite.py` (NEW)
- **Responsibility**: `JoinSpec` model, `CompositeDataSource` class implementing `DataSource` ABC — `fetch()` with per-component filter propagation, `prefetch_schema()` from component schemas, `describe()`, `cache_key`, `has_builtin_cache=True`. MergeError → ValueError with descriptive messages.
- **Depends on**: `sources/base.py`, `DatasetManager` (back-reference for component access)

### Module 6: DatasetManager.add_composite_dataset
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY `DatasetManager`)
- **Responsibility**: `add_composite_dataset()` method, component existence validation, JoinSpec construction, integration with `computed_columns` param
- **Depends on**: Module 5, Module 2

### Module 7: DatasetInfo, Guide & Fetch Integration
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY)
- **Responsibility**: Add `"composite"` to `DatasetInfo.source_type` Literal, add `CompositeDataSource` to `_source_type_map`, add composite branch to `_generate_dataframe_guide()`, add composite branch to `fetch_dataset()`, add composite branch to `list_datasets()` action_required, add composite branch to `get_metadata()` guidance
- **Depends on**: Modules 5, 6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_registry_load_builtins` | 1 | Registry loads built-in math_operation and concatenate |
| `test_registry_querysource_bridge` | 1 | Lazy import from querysource (mock if unavailable) |
| `test_register_custom_function` | 1 | `register_computed_function()` adds to registry |
| `test_builtin_math_operations` | 1 | add, subtract, multiply, divide with edge cases (div-by-zero) |
| `test_builtin_concatenate` | 1 | Multi-column concat with custom separator |
| `test_entry_computed_columns_init` | 2 | DatasetEntry accepts computed_columns, applies on df= |
| `test_materialize_applies_computed` | 2 | Computed columns applied post-fetch, pre-categorization |
| `test_computed_column_ordering` | 2 | Column B depends on computed A — order matters |
| `test_computed_column_failure_resilience` | 2 | One failing column doesn't abort others |
| `test_columns_property_includes_computed` | 2 | Prefetch state includes computed names |
| `test_column_metadata_computed_description` | 2 | `_column_metadata` injects computed descriptions |
| `test_add_dataframe_with_computed` | 3 | Registration with computed_columns flows to entry |
| `test_add_query_with_computed` | 3 | Same for add_query |
| `test_add_computed_column_runtime` | 4 | LLM tool adds column, applied immediately |
| `test_add_computed_column_invalid_func` | 4 | Unknown function returns error message |
| `test_add_computed_column_missing_cols` | 4 | Missing source columns returns error |
| `test_list_available_functions` | 4 | Returns sorted list of registered functions |
| `test_join_spec_validation` | 5 | JoinSpec model validates fields |
| `test_composite_single_join` | 5 | Two datasets inner-joined correctly |
| `test_composite_chained_joins` | 5 | A → B → C sequential joins |
| `test_composite_filter_propagation` | 5 | Filter applied only to components with matching columns |
| `test_composite_missing_component` | 5 | ValueError for non-existent component dataset |
| `test_composite_missing_join_column` | 5 | ValueError for missing join column |
| `test_composite_merge_error` | 5 | MergeError captured with descriptive message |
| `test_composite_has_builtin_cache` | 5 | `has_builtin_cache` returns True |
| `test_add_composite_dataset` | 6 | Registration validates components, creates entry |
| `test_add_composite_with_computed` | 6 | Computed columns on composite JOIN result |
| `test_dataset_info_composite_type` | 7 | `to_info()` returns `source_type="composite"` |
| `test_guide_composite_block` | 7 | Guide includes join description for composites |
| `test_fetch_dataset_composite` | 7 | `fetch_dataset()` routes composite correctly |

### Integration Tests

| Test | Description |
|---|---|
| `test_composite_end_to_end` | Register 2 datasets, create composite, fetch with filter, verify joined result |
| `test_composite_with_computed_end_to_end` | Full pipeline: register → composite → computed columns → fetch → verify KPIs |
| `test_runtime_computed_column_end_to_end` | Register dataset → add_computed_column → fetch → verify column exists |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_kiosks_history():
    return pd.DataFrame({
        "kiosk_id": [1, 2, 3],
        "year": [2025, 2025, 2024],
        "revenue": [100.0, 200.0, 150.0],
        "expenses": [60.0, 80.0, 90.0],
    })

@pytest.fixture
def sample_kiosks_locations():
    return pd.DataFrame({
        "kiosk_id": [1, 2, 3],
        "city": ["Miami", "NYC", "LA"],
        "warehouse_code": ["W01", "W02", "W03"],
    })

@pytest.fixture
def dm_with_datasets(sample_kiosks_history, sample_kiosks_locations):
    dm = DatasetManager()
    dm.add_dataframe("kiosks_history", sample_kiosks_history)
    dm.add_dataframe("kiosks_locations", sample_kiosks_locations)
    return dm
```

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest tests/tools/dataset_manager/ -v`)
- [ ] All integration tests pass
- [ ] No breaking changes to existing `add_*` methods (computed_columns is optional with default None)
- [ ] Computed columns are transparent to LLM — appear as regular columns in guide, metadata, DataFrame
- [ ] Composite datasets appear in `list_datasets()`, `fetch_dataset()`, `get_metadata()` like any other dataset
- [ ] Filter propagation applies filters only to components that have the column
- [ ] Computed column failures are logged but don't abort materialization
- [ ] Registry loads QuerySource functions when available, falls back to built-ins
- [ ] `add_computed_column()` and `list_available_functions()` work as LLM tools
- [ ] No new external dependencies required (querysource is optional)

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Follow the existing `DataSource` ABC pattern for `CompositeDataSource`
- Follow the existing `add_*` method pattern (return confirmation string, update guide)
- Use `self.logger` for all logging (never print)
- Pydantic `BaseModel` for `ComputedColumnDef` and `JoinSpec`
- Async methods where I/O is involved; sync where pure computation
- Built-in fallbacks for core functions (math_operation, concatenate) so the feature works without querysource installed

### Known Risks / Gotchas

- **Circular reference**: `CompositeDataSource` holds a back-reference to `DatasetManager`. Use `TYPE_CHECKING` for the import, runtime string annotation.
- **Computed column ordering**: List order = execution order. If column B depends on computed column A, A must appear first. No topological sort — document this constraint.
- **Filter propagation ambiguity**: If a filter column exists in multiple components, the filter is applied to ALL of them. This is the intended behavior for equality filters.
- **Composite re-fetch**: Composites always re-fetch (components may have changed). The `force_refresh=True` flag is set in `fetch_dataset()`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `querysource` | optional | Lazy import of function catalog; built-in fallbacks if absent |
| `pandas` | existing | `pd.merge()` for JOINs, DataFrame operations |
| `pydantic` | existing | Models for `ComputedColumnDef`, `JoinSpec` |

---

## 7. Open Questions

All design decisions have been settled in the brainstorm phase — no open questions remain.

| Decision | Resolution |
|----------|------------|
| Function source | QuerySource via lazy import + built-in fallbacks |
| Expression parser | Deferred — function registry covers current needs |
| Computed column ordering | List order = execution order |
| LLM runtime computed columns | Allowed, restricted to registry |
| Composite cache strategy | Components cached individually; JOIN recomputed |
| Composite source_type | `"composite"` literal in DatasetInfo |
| Filter propagation | Column-existence check per component |
| Chained JOINs | Sequential — accumulated result as implicit left |
| MergeError handling | Captured as ValueError with descriptive message |

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All 7 modules build on each other linearly (Module N depends on Module N-1), so they must run sequentially in a single worktree.
- **Cross-feature dependencies**: None. This spec is self-contained within `dataset_manager/`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-25 | Jesús / Claude | Initial draft from brainstorm |
