# SDD Spec: Computed Columns & Composite Datasets

**Module:** `packages/ai-parrot/src/parrot/tools/dataset_manager/`
**Status:** Spec — ready for task decomposition
**Author:** Jesús / Claude brainstorm
**Date:** 2026-03-25

---

## 1. Overview

Two new features for `DatasetManager` that extend its capabilities as a data catalog:

1. **Computed Columns** — declarative, auto-applied derived columns that are computed post-materialization using the existing QuerySource function catalog.
2. **Composite Datasets** — virtual datasets that JOIN two or more existing datasets on-demand, with intelligent per-component filter propagation.

Both features are **transparent to the LLM** — computed columns appear as regular DataFrame columns, and composite datasets behave like any other dataset in `list_datasets()`, `fetch_dataset()`, `get_metadata()`, etc.

---

## 2. Feature 1: Computed Columns

### 2.1 Problem

Datasets often need derived columns that don't exist in the source data. Today, the LLM must compute these in `python_repl_pandas` every time. For stable, well-known transformations (EBITDA = revenue - expenses, display_name = first_name + " " + last_name), this wastes tokens and introduces inconsistency.

### 2.2 Design

Computed columns are defined at registration time via the `add_*` methods. They are applied **post-materialization, every time** the dataset is fetched or re-materialized. The LLM sees them as regular columns in the guide, metadata, and DataFrame.

### 2.3 Models

```python
# parrot/tools/dataset_manager/computed.py

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class ComputedColumnDef(BaseModel):
    """Definition of a computed column applied post-materialization.

    Computed columns are evaluated in list order after every fetch/materialize
    call. Each definition references a function from the COMPUTED_FUNCTIONS
    registry by name, plus the source columns and any extra kwargs.

    The function signature must follow the QuerySource pattern:
        fn(df: pd.DataFrame, field: str, columns: list, **kwargs) -> pd.DataFrame

    Attributes:
        name: Name of the new column to create in the DataFrame.
        func: Key in COMPUTED_FUNCTIONS registry (e.g. "math_operation").
        columns: Source column names from the DataFrame to pass to the function.
        kwargs: Extra keyword arguments for the function (e.g. operation="subtract",
                sep=" ").
        description: Human-readable description for LLM guide and metadata.
            When empty, defaults to auto-generated "{func}({columns})".
    """
    name: str = Field(description="Name of the new column")
    func: str = Field(description="Function name from COMPUTED_FUNCTIONS registry")
    columns: List[str] = Field(description="Source column names to operate on")
    kwargs: Dict[str, Any] = Field(default_factory=dict, description="Extra kwargs for the function")
    description: str = Field(default="", description="Human-readable description for LLM")
```

### 2.4 Function Registry

The registry maps string names to callables that follow the QuerySource pattern:
`fn(df, field, columns, **kwargs) -> pd.DataFrame`

```python
# parrot/tools/dataset_manager/computed.py (continued)

# Registry of computed column functions.
# All functions MUST follow the QuerySource pattern:
#   fn(df: pd.DataFrame, field: str, columns: list, **kwargs) -> pd.DataFrame
#
# Functions are imported from querysource where available, with fallbacks
# for standalone use.
COMPUTED_FUNCTIONS: Dict[str, Callable[..., pd.DataFrame]] = {}


def register_computed_function(name: str, fn: Callable[..., pd.DataFrame]) -> None:
    """Register a function in the computed columns registry.

    Args:
        name: Registry key (used in ComputedColumnDef.func).
        fn: Callable following the QuerySource pattern.
    """
    COMPUTED_FUNCTIONS[name] = fn


def _load_querysource_functions() -> None:
    """Lazy-load functions from querysource.models.functions if available.

    Called once on first access. Populates COMPUTED_FUNCTIONS with
    known QuerySource functions. Falls back to built-in implementations
    for core operations when querysource is not installed.
    """
    try:
        from querysource.models.functions import (
            math_operation,
            concatenate_columns,
            # ... other functions from the catalog
        )
        COMPUTED_FUNCTIONS.update({
            "math_operation": math_operation,
            "concatenate": concatenate_columns,
            # ... register all available functions
        })
    except ImportError:
        logger.debug("querysource not available — using built-in computed functions only")

    # Built-in fallbacks (always available)
    if "math_operation" not in COMPUTED_FUNCTIONS:
        COMPUTED_FUNCTIONS["math_operation"] = _builtin_math_operation
    if "concatenate" not in COMPUTED_FUNCTIONS:
        COMPUTED_FUNCTIONS["concatenate"] = _builtin_concatenate
    # ... other built-in fallbacks


def _builtin_math_operation(
    df: pd.DataFrame, field: str, columns: list, operation: str = "add", **kwargs
) -> pd.DataFrame:
    """Built-in math operation following the QuerySource pattern."""
    if len(columns) != 2:
        raise ValueError("math_operation requires exactly 2 columns")
    col1, col2 = columns
    ops = {
        "add": lambda a, b: a + b,
        "sum": lambda a, b: a + b,
        "subtract": lambda a, b: a - b,
        "multiply": lambda a, b: a * b,
        "divide": lambda a, b: a / b.replace(0, float("nan")),
    }
    if operation not in ops:
        raise ValueError(f"Unsupported operation: {operation}. Available: {list(ops.keys())}")
    df[field] = ops[operation](df[col1], df[col2])
    return df


def _builtin_concatenate(
    df: pd.DataFrame, field: str, columns: list, sep: str = " ", **kwargs
) -> pd.DataFrame:
    """Built-in concatenation following the QuerySource pattern."""
    df[field] = df[columns[0]].astype(str)
    for col in columns[1:]:
        df[field] = df[field] + sep + df[col].astype(str)
    return df


def get_computed_function(name: str) -> Optional[Callable[..., pd.DataFrame]]:
    """Get a function from the registry, loading QS functions on first call."""
    if not COMPUTED_FUNCTIONS:
        _load_querysource_functions()
    return COMPUTED_FUNCTIONS.get(name)


def list_computed_functions() -> List[str]:
    """Return available function names (loads registry if needed)."""
    if not COMPUTED_FUNCTIONS:
        _load_querysource_functions()
    return sorted(COMPUTED_FUNCTIONS.keys())
```

### 2.5 Integration in DatasetEntry

```python
# Changes to DatasetEntry.__init__
class DatasetEntry:
    def __init__(
        self,
        ...,
        computed_columns: Optional[List[ComputedColumnDef]] = None,
    ) -> None:
        ...
        self._computed_columns: List[ComputedColumnDef] = computed_columns or []
        ...
        # If df is provided directly AND there are computed columns, apply them now
        if df is not None and self._computed_columns:
            self._apply_computed_columns()

    async def materialize(self, force: bool = False, **params) -> pd.DataFrame:
        """Fetch data from source if not already loaded (or if force=True).

        Computed columns are applied post-fetch, every time. Column type
        categorization runs AFTER computed columns so the new columns
        are included in the type map.
        """
        if self._df is None or force:
            self._df = await self.source.fetch(**params)
            # Apply computed columns BEFORE type categorization
            if self._df is not None and self._computed_columns:
                self._apply_computed_columns()
            if self.auto_detect_types and self._df is not None:
                self._column_types = DatasetManager.categorize_columns(self._df)
        return self._df

    def _apply_computed_columns(self) -> None:
        """Apply computed columns in list order.

        Order matters: if column B depends on column A (which is itself
        computed), A must appear before B in the list.

        Failures are logged but do not abort — the DataFrame is returned
        with whichever computed columns succeeded.
        """
        from .computed import get_computed_function
        for col_def in self._computed_columns:
            fn = get_computed_function(col_def.func)
            if fn is None:
                logger.warning(
                    "Computed column '%s': unknown function '%s' — skipping. "
                    "Available: %s",
                    col_def.name, col_def.func,
                    list_computed_functions(),
                )
                continue
            try:
                self._df = fn(
                    self._df, col_def.name, col_def.columns, **col_def.kwargs
                )
            except Exception as exc:
                logger.error(
                    "Computed column '%s' failed (func=%s, columns=%s): %s",
                    col_def.name, col_def.func, col_def.columns, exc,
                )

    @property
    def columns(self) -> List[str]:
        """Column names — includes computed columns when loaded."""
        if self._df is not None:
            return self._df.columns.tolist()
        # Schema from prefetch + computed column names
        schema = getattr(self.source, '_schema', {})
        base_cols = list(schema.keys())
        computed_names = [c.name for c in self._computed_columns]
        return base_cols + computed_names
```

### 2.6 Integration in add_* Methods

Every registration method gains an optional `computed_columns` parameter.
The pattern is identical across all methods:

```python
# DatasetManager — changes to add_dataframe (representative example)

def add_dataframe(
    self,
    name: str,
    df: pd.DataFrame,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    is_active: bool = True,
    computed_columns: Optional[List[ComputedColumnDef]] = None,  # ← NEW
) -> str:
    ...
    entry = DatasetEntry(
        name=name,
        source=source,
        ...,
        computed_columns=computed_columns,  # ← passed through
    )
    ...
```

Methods that gain `computed_columns`:
- `add_dataframe()`
- `add_query()`
- `add_table_source()`
- `add_sql_source()`
- `add_airtable_source()`
- `add_smartsheet_source()`
- `add_iceberg_source()`
- `add_mongo_source()`
- `add_deltatable_source()`
- `add_dataset()` (the eager-fetch method)
- `add_composite_dataset()` (Feature 2)

### 2.7 LLM-Exposed Tool: add_computed_column (Runtime)

The LLM can add computed columns at runtime, restricted to the function registry:

```python
async def add_computed_column(
    self,
    dataset_name: str,
    column_name: str,
    func: str,
    columns: List[str],
    description: str = "",
    **kwargs,
) -> str:
    """Add a computed column to a dataset using a registered function.

    The column is computed immediately if the dataset is loaded, and will
    be re-computed on every subsequent fetch/materialize.

    Only functions from the internal registry are allowed. Call
    list_computed_functions() to see available functions.

    Args:
        dataset_name: Name or alias of the target dataset.
        column_name: Name for the new computed column.
        func: Function name from the registry.
        columns: Source column names to pass to the function.
        description: Human-readable description of the column.
        **kwargs: Extra parameters for the function (e.g. operation="subtract").

    Returns:
        Confirmation message or error.
    """
    from .computed import get_computed_function, list_computed_functions

    # Validate function exists
    fn = get_computed_function(func)
    if fn is None:
        available = list_computed_functions()
        return (
            f"Unknown function '{func}'. "
            f"Available functions: {', '.join(available)}"
        )

    resolved = self._resolve_name(dataset_name)
    entry = self._datasets.get(resolved)
    if entry is None:
        return f"Dataset '{dataset_name}' not found."

    # Validate source columns exist (if dataset is loaded or has schema)
    known_cols = set(entry.columns)
    # Also consider already-defined computed columns as valid sources
    known_cols.update(c.name for c in entry._computed_columns)
    missing = [c for c in columns if c not in known_cols]
    if missing and known_cols:  # only warn if we have schema info
        return (
            f"Column(s) {missing} not found in dataset '{resolved}'. "
            f"Available: {sorted(known_cols)}"
        )

    col_def = ComputedColumnDef(
        name=column_name,
        func=func,
        columns=columns,
        kwargs=kwargs,
        description=description,
    )
    entry._computed_columns.append(col_def)

    # Apply immediately if loaded
    if entry.loaded:
        entry._apply_computed_columns()
        if self.auto_detect_types:
            entry._column_types = self.categorize_columns(entry._df)
        self._notify_change()

    if self.generate_guide:
        self.df_guide = self._generate_dataframe_guide()

    return (
        f"Computed column '{column_name}' added to '{resolved}' "
        f"(func={func}, columns={columns})."
    )


async def list_available_functions(self) -> List[str]:
    """List available functions for computed columns.

    Returns:
        List of function names that can be used in add_computed_column().
    """
    from .computed import list_computed_functions
    return list_computed_functions()
```

### 2.8 Guide Generation

Computed columns are **invisible as a concept** to the LLM in the guide — they
appear as regular columns. However, their `description` from `ComputedColumnDef`
is injected into `_column_metadata` so `get_metadata()` returns meaningful
descriptions.

In `DatasetEntry._column_metadata`:
```python
@property
def _column_metadata(self) -> Dict[str, Dict[str, Any]]:
    ...
    result: Dict[str, Dict[str, Any]] = {}
    for col in self._df.columns:
        ...  # existing logic
        # Check if this column is computed — use its description
        computed_desc = next(
            (c.description for c in self._computed_columns if c.name == col),
            None,
        )
        if computed_desc:
            col_info['description'] = computed_desc
        ...
    return result
```

### 2.9 Transparency Rules

- Computed columns appear in `columns`, `column_types`, `_column_metadata`, `to_info()`, and the DataFrame guide exactly like native columns.
- The LLM does NOT need to know a column is computed. It uses it like any other column in `python_repl_pandas`.
- The only LLM-visible indicator is that `add_computed_column()` and `list_available_functions()` are available as tools — but these are for runtime use, not for understanding existing computed columns.

---

## 3. Feature 2: Composite Datasets

### 3.1 Problem

Datasets from different sources cannot be JOINed at the database level (different engines, databases, or APIs). Today, the LLM must fetch both datasets and write pandas merge code, wasting tokens and risking inconsistent results. A declarative JOIN definition solves this.

### 3.2 Design

A composite dataset is a virtual `DataSource` that references two or more existing datasets by name and defines how to JOIN them. When `fetch_dataset("composite_name")` is called:

1. Component datasets are materialized (using their own sources, caches, etc.)
2. Filters are applied per-component — only to columns that exist in each
3. JOINs are executed sequentially in list order
4. Computed columns (if defined) are applied on the result

The composite itself is **never cached in Redis** — only its components are cached individually.

### 3.3 Models

```python
# parrot/tools/dataset_manager/sources/composite.py

from __future__ import annotations
import hashlib
import logging
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING, Union

import pandas as pd
from pydantic import BaseModel, Field

from .base import DataSource

if TYPE_CHECKING:
    from ..tool import DatasetManager

logger = logging.getLogger(__name__)


class JoinSpec(BaseModel):
    """Specification for joining two datasets.

    Defines the left dataset, right dataset, join column(s), join type,
    and column suffixes for overlapping column names.

    For chained JOINs (A → B → C), the first JoinSpec defines
    left + right explicitly. Subsequent JoinSpecs use the accumulated
    result as the implicit left side, and only `right` is required.
    However, `left` is still set in subsequent specs for documentation
    and validation purposes.

    Attributes:
        left: Name of the left dataset (first join) or the accumulated
            result identifier (subsequent joins — set for documentation,
            the actual left is always the accumulated DataFrame).
        right: Name of the right dataset to join.
        on: Column name(s) used for the join. String for single column,
            list for composite keys.
        how: Join type — "inner", "left", "right", or "outer".
        suffixes: Tuple of suffixes for overlapping column names.
            Default ("", "_right") preserves left column names unchanged.
    """
    left: str = Field(description="Left dataset name")
    right: str = Field(description="Right dataset name")
    on: Union[str, List[str]] = Field(description="Join column(s)")
    how: str = Field(default="inner", description="Join type: inner, left, right, outer")
    suffixes: tuple = Field(default=("", "_right"), description="Column suffixes for overlapping names")


class CompositeDataSource(DataSource):
    """Virtual DataSource that JOINs existing datasets on demand.

    Does not own any data — delegates fetching to the DatasetManager's
    existing materialization infrastructure for each component dataset.

    Filter propagation: When fetch() receives a filter dict, each filter
    key is applied only to component datasets that contain that column.
    For lazy sources (TableSource, QuerySlugSource, etc.), column
    existence is checked against the source schema (prefetched or
    from metadata). For InMemorySource, checked against the DataFrame.

    Caching: Components are cached individually by their own DataSource
    cache_key. The composite JOIN result is NOT cached — it's recomputed
    from (potentially cached) components every time. pd.merge() is fast
    enough for typical dataset sizes that this is not a concern.

    Args:
        name: Name of the composite dataset.
        joins: List of JoinSpec defining the JOIN chain.
        dataset_manager: Reference to the owning DatasetManager (for
            accessing component datasets).
        description: Human-readable description.
    """

    def __init__(
        self,
        name: str,
        joins: List[JoinSpec],
        dataset_manager: 'DatasetManager',
        description: str = "",
    ) -> None:
        self._name = name
        self.joins = joins
        self._dm = dataset_manager
        self._description = description

    # ─────────────────────────────────────────────────────────────
    # Component introspection
    # ─────────────────────────────────────────────────────────────

    @property
    def component_names(self) -> Set[str]:
        """All unique dataset names involved in the joins."""
        names = {self.joins[0].left}
        for j in self.joins:
            names.add(j.right)
        return names

    def _get_component_columns(self, ds_name: str) -> Set[str]:
        """Get known columns for a component dataset.

        Checks (in priority order):
        1. Loaded DataFrame columns
        2. Source schema (prefetched, e.g. TableSource)
        3. Computed column names on the entry

        Returns:
            Set of known column names. Empty set if unknown.
        """
        entry = self._dm._datasets.get(ds_name)
        if entry is None:
            return set()
        cols = set(entry.columns)
        # Include computed column names (may not be in schema yet)
        cols.update(c.name for c in entry._computed_columns)
        return cols

    # ─────────────────────────────────────────────────────────────
    # DataSource interface
    # ─────────────────────────────────────────────────────────────

    async def prefetch_schema(self) -> Dict[str, str]:
        """Derive schema from component schemas + join logic.

        Returns a merged schema from all component datasets, preferring
        the left side's types for overlapping columns.
        """
        merged: Dict[str, str] = {}
        for ds_name in self.component_names:
            entry = self._dm._datasets.get(ds_name)
            if entry is None:
                continue
            # Use _column_types if loaded, else raw _schema
            col_types = entry._column_types
            if col_types is None:
                col_types = getattr(entry.source, '_schema', {})
            for col, dtype in col_types.items():
                merged.setdefault(col, dtype)  # left takes precedence
        return merged

    async def fetch(self, filter: Optional[Dict[str, Any]] = None, **params) -> pd.DataFrame:
        """Materialize component datasets and execute JOINs.

        Args:
            filter: Optional dict of equality filters. Each key-value pair
                is applied only to components that have that column.
                Scalar values use equality, list/tuple/set values use isin.
            **params: Passed through to component materialize() calls.

        Returns:
            Joined DataFrame.

        Raises:
            ValueError: If a component dataset is not found or a JOIN fails.
        """
        # 1. Materialize each component
        frames: Dict[str, pd.DataFrame] = {}
        for ds_name in self.component_names:
            entry = self._dm._datasets.get(ds_name)
            if entry is None:
                raise ValueError(
                    f"Composite '{self._name}': component dataset "
                    f"'{ds_name}' not found in DatasetManager. "
                    f"Available: {list(self._dm._datasets.keys())}"
                )

            # Materialize using the component's own source and cache
            df = await self._dm.materialize(ds_name, **params)

            # Apply filter — only columns that exist in this component
            if filter:
                applicable = {
                    k: v for k, v in filter.items()
                    if k in df.columns
                }
                if applicable:
                    df = self._dm._apply_filter(df, applicable)
                    logger.debug(
                        "Composite '%s': applied filter %s to component '%s'",
                        self._name, list(applicable.keys()), ds_name,
                    )

            frames[ds_name] = df

        # 2. Execute JOINs sequentially
        result = frames[self.joins[0].left]
        for i, join_spec in enumerate(self.joins):
            right_df = frames[join_spec.right]
            on = join_spec.on if isinstance(join_spec.on, list) else [join_spec.on]

            # Validate join columns exist
            missing_left = [c for c in on if c not in result.columns]
            missing_right = [c for c in on if c not in right_df.columns]
            if missing_left:
                raise ValueError(
                    f"Composite '{self._name}': JOIN column(s) {missing_left} "
                    f"not found in left side (accumulated result). "
                    f"Available: {result.columns.tolist()}"
                )
            if missing_right:
                raise ValueError(
                    f"Composite '{self._name}': JOIN column(s) {missing_right} "
                    f"not found in right dataset '{join_spec.right}'. "
                    f"Available: {right_df.columns.tolist()}"
                )

            try:
                result = result.merge(
                    right_df,
                    on=on,
                    how=join_spec.how,
                    suffixes=join_spec.suffixes,
                )
            except pd.errors.MergeError as exc:
                raise ValueError(
                    f"Composite '{self._name}': JOIN #{i+1} failed — "
                    f"'{join_spec.left}' {join_spec.how.upper()} JOIN "
                    f"'{join_spec.right}' ON {on}: {exc}. "
                    f"Left shape: {result.shape}, Right shape: {right_df.shape}. "
                    f"Check that the join columns have compatible types and "
                    f"that the cardinality matches the expected relationship."
                ) from exc

            logger.debug(
                "Composite '%s': JOIN #%d complete — %s %s JOIN %s ON %s → %s rows",
                self._name, i+1, join_spec.left, join_spec.how,
                join_spec.right, on, len(result),
            )

        return result

    def describe(self) -> str:
        """Human-readable description for the LLM guide."""
        parts = [f"Composite dataset"]
        if self._description:
            parts.append(f": {self._description}")
        parts.append(" — ")
        join_descs = []
        for j in self.joins:
            join_descs.append(f"{j.left} {j.how.upper()} JOIN {j.right} ON {j.on}")
        parts.append(", then ".join(join_descs))
        return "".join(parts)

    @property
    def has_builtin_cache(self) -> bool:
        """Composite datasets skip the Redis cache layer.

        Components are cached individually by their own sources.
        The JOIN result is recomputed from (cached) components every time.
        """
        return True

    @property
    def cache_key(self) -> str:
        """Stable key for interface compliance (not used for actual caching)."""
        join_sig = "|".join(
            f"{j.left}+{j.right}:{j.on}:{j.how}" for j in self.joins
        )
        return f"composite:{self._name}:{hashlib.md5(join_sig.encode()).hexdigest()[:8]}"
```

### 3.4 Registration Method

```python
# DatasetManager.add_composite_dataset()

def add_composite_dataset(
    self,
    name: str,
    joins: List[Dict[str, Any]],
    *,
    description: str = "",
    computed_columns: Optional[List[ComputedColumnDef]] = None,
    is_active: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Register a virtual dataset that JOINs existing datasets on demand.

    Component datasets are materialized independently (using their own
    sources and caches), filters are applied per-component, and JOINs
    execute in list order. Computed columns (if provided) are applied
    on the JOIN result.

    Args:
        name: Name/identifier for the composite dataset.
        joins: List of join specifications. Each dict must contain:
            - left (str): Left dataset name.
            - right (str): Right dataset name.
            - on (str | list[str]): Join column(s).
            - how (str, optional): "inner", "left", "right", "outer".
              Default "inner".
            - suffixes (tuple, optional): Column suffixes for overlaps.
              Default ("", "_right").
        description: Human-readable description.
        computed_columns: Optional computed columns applied post-JOIN.
        is_active: Whether the dataset is active (default True).
        metadata: Optional metadata dict.

    Returns:
        Confirmation message.

    Raises:
        ValueError: If component datasets are not found or join specs
            are invalid.
    """
    from .sources.composite import JoinSpec, CompositeDataSource

    join_specs = [JoinSpec(**j) for j in joins]

    # Validate all component datasets exist
    all_ds = {join_specs[0].left}
    for j in join_specs:
        all_ds.add(j.right)
    missing = all_ds - set(self._datasets.keys())
    if missing:
        raise ValueError(
            f"Component datasets not registered: {missing}. "
            f"Available: {list(self._datasets.keys())}. "
            f"Register them before creating the composite."
        )

    source = CompositeDataSource(
        name=name,
        joins=join_specs,
        dataset_manager=self,
        description=description,
    )

    entry = DatasetEntry(
        name=name,
        description=description,
        source=source,
        metadata=metadata or {},
        is_active=is_active,
        auto_detect_types=self.auto_detect_types,
        computed_columns=computed_columns,
    )
    self._datasets[name] = entry

    if self.generate_guide:
        self.df_guide = self._generate_dataframe_guide()

    join_desc = " → ".join(
        f"{j.left} {j.how.upper()} JOIN {j.right} ON {j.on}"
        for j in join_specs
    )
    self.logger.debug("Composite dataset '%s' registered: %s", name, join_desc)
    return f"Composite dataset '{name}' registered ({len(join_specs)} join(s): {join_desc})."
```

### 3.5 Integration with DatasetInfo

Add `"composite"` to `DatasetInfo.source_type`:

```python
class DatasetInfo(BaseModel):
    source_type: Literal[
        "dataframe", "query_slug", "sql", "table", "airtable", "smartsheet",
        "iceberg", "mongo", "deltatable", "composite",  # ← NEW
    ] = Field(...)
```

Add to `DatasetEntry.to_info()._source_type_map`:

```python
from .sources.composite import CompositeDataSource

_source_type_map: Dict[type, str] = {
    ...
    CompositeDataSource: "composite",  # ← NEW
}
```

### 3.6 Integration with fetch_dataset

`fetch_dataset` needs a new branch for `CompositeDataSource`:

```python
# In fetch_dataset, add to the source-type dispatch block:

from .sources.composite import CompositeDataSource

if isinstance(entry.source, CompositeDataSource):
    # Composites accept 'conditions' as filter dict (equality filters
    # applied per-component to columns that exist). No sql needed.
    if conditions:
        params['filter'] = conditions
    # Composites ALWAYS re-fetch: components may have changed, and
    # filters are applied per-fetch.
    force_refresh = True
```

### 3.7 Integration with _generate_dataframe_guide

Add a guide block for composite datasets (not loaded state):

```python
elif info.source_type == "composite":
    source = entry.source
    if isinstance(source, CompositeDataSource):
        guide_parts.append(f"- **Components**: {', '.join(source.component_names)}")
        for j in source.joins:
            guide_parts.append(
                f"  - {j.left} {j.how.upper()} JOIN {j.right} ON {j.on}"
            )
    guide_parts.append(
        f'\n- **To use**: `fetch_dataset("{ds_name}")` or '
        f'`fetch_dataset("{ds_name}", conditions={{"column": "value"}})` '
        f'to filter components before joining.'
    )
```

### 3.8 Composite + Computed Columns: The Full Story

The intended use case — computing KPIs that span datasets:

```python
dm.add_composite_dataset(
    name="kiosks_history_locations",
    description="Kiosk activity with warehouse distances for replenishment analysis",
    joins=[
        {
            "left": "kiosks_history",
            "right": "kiosks_locations",
            "on": "kiosk_id",
            "how": "inner",
        }
    ],
    computed_columns=[
        ComputedColumnDef(
            name="ebitda",
            func="math_operation",
            columns=["revenue", "expenses"],
            kwargs={"operation": "subtract"},
            description="Earnings before interest, taxes, depreciation, and amortization",
        ),
        ComputedColumnDef(
            name="display_name",
            func="concatenate",
            columns=["city", "warehouse_code"],
            kwargs={"sep": " - "},
            description="Human-readable warehouse-city identifier",
        ),
    ],
)
```

Execution flow when LLM calls `fetch_dataset("kiosks_history_locations", conditions={"year": 2025})`:

1. `CompositeDataSource.fetch(filter={"year": 2025})`:
   - Materializes `kiosks_history` → applies `year=2025` (column exists)
   - Materializes `kiosks_locations` → skips `year` filter (column doesn't exist)
   - `pd.merge()` on `kiosk_id` (inner join)
2. `DatasetEntry._apply_computed_columns()`:
   - Computes `ebitda = revenue - expenses`
   - Computes `display_name = city + " - " + warehouse_code`
3. `categorize_columns()` runs on the final result
4. LLM receives the DataFrame with all columns — native, joined, and computed

---

## 4. File Structure

```
parrot/tools/dataset_manager/
├── __init__.py
├── tool.py                      # DatasetManager (modified)
├── computed.py                  # NEW: ComputedColumnDef, COMPUTED_FUNCTIONS, registry
└── sources/
    ├── __init__.py
    ├── base.py                  # DataSource ABC (unchanged)
    ├── memory.py                # InMemorySource (unchanged)
    ├── query_slug.py            # QuerySlugSource (unchanged)
    ├── sql.py                   # SQLQuerySource (unchanged)
    ├── table.py                 # TableSource (unchanged)
    ├── composite.py             # NEW: JoinSpec, CompositeDataSource
    ├── airtable.py              # (unchanged)
    ├── smartsheet.py            # (unchanged)
    ├── iceberg.py               # (unchanged)
    ├── mongo.py                 # (unchanged)
    └── deltatable.py            # (unchanged)
```

---

## 5. Task Breakdown

### Task 1: Computed Columns Foundation
- Create `computed.py` with `ComputedColumnDef`, `COMPUTED_FUNCTIONS` registry, built-in fallbacks, and `register_computed_function()`
- Add lazy-load bridge from QuerySource functions
- Unit tests for registry, built-in math_operation, concatenate

### Task 2: DatasetEntry Computed Column Integration
- Add `computed_columns` to `DatasetEntry.__init__`
- Implement `_apply_computed_columns()` in `DatasetEntry`
- Modify `materialize()` to apply computed columns post-fetch, pre-categorization
- Modify `columns` property to include computed column names (prefetch state)
- Modify `_column_metadata` to inject computed column descriptions
- Unit tests for materialize → computed flow, ordering, failure resilience

### Task 3: DatasetManager add_* Methods
- Add `computed_columns` param to all `add_*` methods (add_dataframe, add_query, add_table_source, add_sql_source, add_airtable_source, add_smartsheet_source, add_iceberg_source, add_mongo_source, add_deltatable_source, add_dataset)
- Unit tests for registration with computed columns

### Task 4: LLM Runtime Computed Columns
- Implement `add_computed_column()` LLM tool on DatasetManager
- Implement `list_available_functions()` LLM tool on DatasetManager
- Column validation, function validation, immediate application
- Unit tests

### Task 5: CompositeDataSource
- Create `sources/composite.py` with `JoinSpec`, `CompositeDataSource`
- Implement `fetch()` with per-component filter propagation
- Implement `prefetch_schema()` from component schemas
- Implement `describe()`, `cache_key`, `has_builtin_cache`
- MergeError capture and descriptive error messages
- Unit tests for single JOIN, chained JOINs, filter propagation, error cases

### Task 6: DatasetManager.add_composite_dataset
- Implement `add_composite_dataset()` method
- Component existence validation
- Integration with `computed_columns` parameter
- Unit tests

### Task 7: DatasetInfo & Guide Integration
- Add `"composite"` to `DatasetInfo.source_type` Literal
- Add `CompositeDataSource` to `to_info()._source_type_map`
- Add composite branch to `_generate_dataframe_guide()`
- Add composite branch to `fetch_dataset()` source-type dispatch
- Add composite branch to `list_datasets()` action_required
- Add composite branch to `get_metadata()` not-loaded guidance
- Unit tests for guide output, fetch_dataset routing

---

## 6. Open Decisions (Settled)

| Decision | Resolution |
|----------|------------|
| Function source | QuerySource functions via lazy import + built-in fallbacks |
| Expression parser | Deferred — function registry covers current needs; AST parser for future |
| Computed column ordering | List order = execution order (no topological sort) |
| LLM runtime computed columns | Allowed, restricted to registry functions |
| Composite cache strategy | Components cached individually; JOIN recomputed every time |
| Composite source_type | `"composite"` literal in DatasetInfo |
| YAML/JSON config for composites | Deferred — programmatic API only for now |
| Filter propagation | Column-existence check per component; skip filters for missing columns |
| Chained JOINs | Sequential — accumulated result as implicit left |
| MergeError handling | Captured as ValueError with descriptive message for LLM |