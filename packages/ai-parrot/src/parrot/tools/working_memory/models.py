"""Enums and Pydantic input models for WorkingMemoryToolkit DSL."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# DSL Enums
# ─────────────────────────────────────────────────────────────


class OperationType(str, Enum):
    """Allowed deterministic operations the agent can request."""

    FILTER = "filter"
    AGGREGATE = "aggregate"
    JOIN = "join"
    MERGE = "merge"
    CORRELATE = "correlate"
    PIVOT = "pivot"
    RANK = "rank"
    WINDOW = "window"
    SORT = "sort"
    SELECT = "select"
    RENAME = "rename"
    FILLNA = "fillna"
    DROP_DUPLICATES = "drop_duplicates"
    GROUP_CORRELATE = "group_correlate"
    DESCRIBE = "describe"


class JoinHow(str, Enum):
    """Join type options for JOIN and MERGE operations."""

    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    OUTER = "outer"
    CROSS = "cross"


class AggFunc(str, Enum):
    """Aggregation function options for AGGREGATE, PIVOT, WINDOW, and SUMMARIZE operations."""

    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    STD = "std"
    VAR = "var"
    FIRST = "first"
    LAST = "last"
    NUNIQUE = "nunique"


# ─────────────────────────────────────────────────────────────
# Pydantic Input Models (for @tool_schema validation)
# ─────────────────────────────────────────────────────────────


class FilterSpec(BaseModel):
    """A single filter condition."""

    column: str = Field(description="Column name to filter on")
    op: str = Field(
        description="Filter operator: ==, !=, >, >=, <, <=, in, not_in, "
                    "contains, startswith, is_null, not_null, between"
    )
    value: Any = Field(default=None, description="Value to compare against")


class JoinOnSpec(BaseModel):
    """Join key specification."""

    left: str = Field(description="Column name in left DataFrame")
    right: str = Field(description="Column name in right DataFrame")


class OperationSpecInput(BaseModel):
    """
    Declarative operation specification — the DSL contract.

    The agent sends this as JSON; Pydantic validates it before execution.
    No free-form code allowed.
    """

    op: OperationType = Field(description="The operation to perform")
    source: str = Field(description="Key of the source DataFrame in working memory")
    store_as: str = Field(description="Key to store the result under")

    # Filter
    filters: list[FilterSpec] = Field(default_factory=list, description="Filter conditions to apply")

    # Aggregate
    group_by: list[str] = Field(default_factory=list, description="Columns to group by")
    agg_rules: dict[str, AggFunc] = Field(
        default_factory=dict,
        description="Aggregation rules: {column: agg_function}"
    )

    # Join / Merge
    right_source: Optional[str] = Field(default=None, description="Key of right DataFrame for joins")
    join_on: Optional[JoinOnSpec] = Field(default=None, description="Join key mapping")
    join_how: JoinHow = Field(default=JoinHow.INNER, description="Join type")

    # Correlate
    columns: list[str] = Field(default_factory=list, description="Columns to operate on")
    method: str = Field(default="pearson", description="Correlation method: pearson, spearman, kendall")

    # Pivot
    pivot_index: Optional[str] = Field(default=None, description="Pivot table index column")
    pivot_columns: Optional[str] = Field(default=None, description="Pivot table columns")
    pivot_values: Optional[str] = Field(default=None, description="Pivot table values column")
    pivot_aggfunc: AggFunc = Field(default=AggFunc.MEAN, description="Pivot aggregation function")

    # Rank / Window
    rank_column: Optional[str] = Field(default=None, description="Column to rank or apply window on")
    rank_ascending: bool = Field(default=True, description="Rank in ascending order")
    window_size: Optional[int] = Field(default=None, description="Rolling window size")
    window_func: Optional[AggFunc] = Field(default=None, description="Window aggregation function")

    # Sort
    sort_by: list[str] = Field(default_factory=list, description="Columns to sort by")
    sort_ascending: bool = Field(default=True, description="Sort ascending")

    # Select / Rename
    select_columns: list[str] = Field(default_factory=list, description="Columns to select")
    rename_map: dict[str, str] = Field(default_factory=dict, description="Column rename mapping")

    # Fill NA
    fillna_value: Any = Field(default=None, description="Value to fill NAs with")
    fillna_method: Optional[str] = Field(default=None, description="Fill method: ffill or bfill")


# ── Tool Input Models (one per public method) ──


class StoreInput(BaseModel):
    """Input for storing a DataFrame directly."""

    key: str = Field(description="Unique name for this entry in working memory")
    description: str = Field(default="", description="Human-readable description")
    turn_id: Optional[str] = Field(default=None, description="Conversation turn identifier")


class DropStoredInput(BaseModel):
    """Input for removing a stored DataFrame."""

    key: str = Field(description="Key of the entry to remove")


class GetStoredInput(BaseModel):
    """Input for retrieving a summary of a stored DataFrame."""

    key: str = Field(description="Key of the entry to retrieve")
    max_rows: Optional[int] = Field(default=None, description="Max rows in preview")
    max_cols: Optional[int] = Field(default=None, description="Max columns in preview")


class ListStoredInput(BaseModel):
    """Input for listing all stored entries."""

    turn_id: Optional[str] = Field(default=None, description="Filter by conversation turn")


class ComputeAndStoreInput(BaseModel):
    """Input for executing a declarative operation and storing the result."""

    spec: OperationSpecInput = Field(description="The operation specification (DSL)")
    description: str = Field(default="", description="Description of this computation")
    turn_id: Optional[str] = Field(default=None, description="Conversation turn identifier")


class MergeStoredInput(BaseModel):
    """Input for merging multiple stored DataFrames."""

    keys: list[str] = Field(description="Keys of DataFrames to merge")
    store_as: str = Field(description="Key for the merged result")
    merge_on: Optional[str] = Field(default=None, description="Common column for join")
    merge_how: str = Field(default="outer", description="Merge type: inner, left, right, outer")
    turn_id: Optional[str] = Field(default=None, description="Conversation turn identifier")


class SummarizeStoredInput(BaseModel):
    """Input for merging + aggregating stored DataFrames."""

    keys: list[str] = Field(description="Keys of DataFrames to merge and summarize")
    store_as: str = Field(description="Key for the summarized result")
    agg_rules: dict[str, str] = Field(
        description='Aggregation rules: {"column": "agg_func"} '
                    'where agg_func is sum|mean|median|min|max|count|std|var|first|last|nunique'
    )
    group_by: Optional[list[str]] = Field(default=None, description="Group by columns")
    merge_on: Optional[str] = Field(default=None, description="Common column for merge step")
    turn_id: Optional[str] = Field(default=None, description="Conversation turn identifier")


class ImportFromToolInput(BaseModel):
    """Input for importing a DataFrame from another tool's namespace."""

    tool_name: str = Field(description="Name of the source tool (e.g., PythonPandasTool)")
    variable_name: str = Field(description="Variable name in the tool's locals")
    store_as: str = Field(description="Key to store under in working memory")
    description: str = Field(default="", description="Description of the imported data")
    turn_id: Optional[str] = Field(default=None, description="Conversation turn identifier")


class ListToolDataFramesInput(BaseModel):
    """Input for listing DataFrames available in other tools."""

    tool_name: Optional[str] = Field(default=None, description="Filter by tool name")
