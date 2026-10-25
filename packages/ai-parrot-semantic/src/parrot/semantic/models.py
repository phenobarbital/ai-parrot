"""Semantic query and result contracts."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import SemanticValidationError

Grain = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]
FilterOp = Literal[
    "equals",
    "not_equals",
    "in",
    "not_in",
    "contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "is_set",
    "not_set",
    "in_date_range",
    "before_date",
    "after_date",
]


class TimeDimension(BaseModel):
    """A time dimension and its required aggregation grain."""

    name: str
    grain: Grain | None = None
    date_range: tuple[str, str] | None = None

    @model_validator(mode="after")
    def require_grain(self) -> "TimeDimension":
        """Require a grain for each selected time dimension."""
        if self.grain is None:
            raise ValueError("time dimensions require a grain")
        return self


class FilterLeaf(BaseModel):
    """A typed predicate over one semantic member."""

    member: str
    op: FilterOp
    values: list[str | int | float | bool] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_value_arity(self) -> "FilterLeaf":
        """Require the operator's defined number of filter values."""
        exact_arities = {
            "equals": 1,
            "not_equals": 1,
            "contains": 1,
            "gt": 1,
            "gte": 1,
            "lt": 1,
            "lte": 1,
            "before_date": 1,
            "after_date": 1,
            "between": 2,
            "in_date_range": 2,
            "is_set": 0,
            "not_set": 0,
        }
        expected = exact_arities.get(self.op)
        if expected is not None and len(self.values) != expected:
            raise ValueError(f"{self.op} requires exactly {expected} values")
        if self.op in {"in", "not_in"} and not self.values:
            raise ValueError(f"{self.op} requires at least one value")
        return self


class FilterGroup(BaseModel):
    """A nested boolean group of semantic filters."""

    op: Literal["and", "or"]
    items: list["FilterLeaf | FilterGroup"]

    @model_validator(mode="after")
    def require_items(self) -> "FilterGroup":
        """Reject empty boolean groups."""
        if not self.items:
            raise ValueError("filter groups require at least one item")
        return self


class OrderBy(BaseModel):
    """A semantic member ordering clause."""

    member: str
    grain: Grain | None = None
    desc: bool = False


class SemanticQuery(BaseModel):
    """Validated, credential-free request for a semantic query."""

    model_config = ConfigDict(extra="forbid")

    model: str
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_dimensions: list[TimeDimension] = Field(default_factory=list)
    filters: FilterGroup | None = None
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int | None = None
    offset: int = 0
    timezone: str | None = None
    saved_query: str | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> "SemanticQuery":
        """Validate structural query constraints before model resolution."""
        explicit_fields = self.metrics or self.dimensions or self.time_dimensions or self.filters or self.order_by
        if self.saved_query is not None:
            if explicit_fields:
                raise ValueError("saved_query is exclusive with explicit members, filters, and ordering")
        elif not (self.metrics or self.dimensions or self.time_dimensions):
            raise ValueError("a query requires at least one metric, dimension, or time dimension")
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be positive")
        if self.offset < 0:
            raise ValueError("offset cannot be negative")
        if self.offset > 0 and not self.order_by:
            raise ValueError("offset requires order_by")
        return self

    def canonical_json(self) -> str:
        """Return sorted-key, whitespace-free JSON for versioned cache keys."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def validate_against(self, member_kinds: dict[str, str], time_dimensions: set[str]) -> None:
        """Reject unknown members, mixed filter kinds, and invalid time grains.

        Args:
            member_kinds: Mapping from member name to its semantic kind.
            time_dimensions: Names of time dimensions exposed by the model.

        Raises:
            SemanticValidationError: If a referenced member or time grain is invalid.
        """
        referenced_members = set(self.metrics) | set(self.dimensions)
        referenced_members.update(dimension.name for dimension in self.time_dimensions)
        referenced_members.update(order.member for order in self.order_by)
        filter_members = self._filter_members(self.filters)
        referenced_members.update(filter_members)
        unknown = sorted(member for member in referenced_members if member not in member_kinds)
        if unknown:
            raise SemanticValidationError("unknown_member", "Query references an unknown member", details={"members": unknown})

        for dimension in self.time_dimensions:
            if dimension.name not in time_dimensions:
                raise SemanticValidationError(
                    "invalid_time_dimension", "Query references a non-time dimension as time", details={"member": dimension.name}
                )
            if dimension.grain is None:
                raise SemanticValidationError("missing_grain", "Time dimensions require a grain")
        for order in self.order_by:
            if order.member in time_dimensions and order.grain is None:
                raise SemanticValidationError("missing_grain", "Time dimensions require a grain")

        filter_kinds = {member_kinds[member] for member in filter_members}
        normalized_kinds = {"metric" if kind == "metric" else "dimension" for kind in filter_kinds}
        if len(normalized_kinds) > 1:
            raise SemanticValidationError("mixed_filter_group", "A filter group cannot mix WHERE and HAVING members")

    @staticmethod
    def _filter_members(group: FilterGroup | None) -> set[str]:
        """Return all leaf member names from a filter tree."""
        if group is None:
            return set()
        members: set[str] = set()
        for item in group.items:
            if isinstance(item, FilterLeaf):
                members.add(item.member)
            else:
                members.update(SemanticQuery._filter_members(item))
        return members


class CompiledQuery(BaseModel, frozen=True):
    """Pre-governance compiler output without subject-derived content."""

    sql: str
    dialect: str
    members: tuple[str, ...]
    tables: tuple[str, ...]
    cache_key: str


class GovernedQuery(BaseModel, frozen=True):
    """Governed executable query with provenance and physical lineage."""

    sql: str
    dialect: str
    driver: str
    tables: tuple[str, ...]
    rls_applied: tuple[str, ...]
    masked_columns: tuple[str, ...]
    limit: int
    subject_digest: str
    members: tuple[str, ...]
    physical_columns: tuple[str, ...]


class SemanticQueryResult(BaseModel):
    """Rows and execution metadata returned by the semantic layer."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    compiled_sql: str
    audit_id: str
    result_id: str | None = None


class Limits(BaseModel):
    """Default and maximum row caps with positive ordered values."""

    default: int = 1000
    max: int = 10000

    @model_validator(mode="after")
    def validate_ordering(self) -> "Limits":
        """Require positive defaults that do not exceed the maximum."""
        if self.default < 1 or self.max < 1 or self.default > self.max:
            raise ValueError("limits require 1 <= default <= max")
        return self


class ModelMember(BaseModel):
    """Catalog metadata whose access is determined by policy."""

    name: str
    kind: Literal["metric", "dimension", "time_dimension", "entity"]
    description: str = ""
    grain: Grain | None = None
    sensitive: bool = False
