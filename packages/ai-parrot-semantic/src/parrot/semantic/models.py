"""Pydantic request and response contracts for semantic-layer queries (spec §2)."""

from __future__ import annotations

import json
from typing import Literal

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


class Limits(BaseModel):
    """Row limits supplied by a model policy."""

    default: int = 1000
    max: int = 10000


class ModelMember(BaseModel):
    """A metric, dimension, time dimension, or entity exposed by a loaded model."""

    name: str
    kind: Literal["metric", "dimension", "time_dimension", "entity"]
    description: str = ""
    grain: Grain | None = None
    sensitive: bool = False


class TimeDimension(BaseModel):
    """A time-dimension projection with optional grain and inclusive ISO-8601 bounds."""

    name: str
    grain: Grain | None = None
    date_range: tuple[str, str] | None = None


class FilterLeaf(BaseModel):
    """A filter operation for one metric or dimension."""

    member: str
    op: FilterOp
    values: list[str | int | float | bool] = Field(default_factory=list)


class FilterGroup(BaseModel):
    """A recursively nested conjunction or disjunction of filter predicates."""

    op: Literal["and", "or"]
    items: list[FilterLeaf | FilterGroup]


FilterGroup.model_rebuild()


class OrderBy(BaseModel):
    """One semantic member ordering, optionally at a specified time grain."""

    member: str
    grain: Grain | None = None
    desc: bool = False


class SemanticQuery(BaseModel):
    """Structured metric query whose unknown and credential-like fields are rejected."""

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
    def _check_shape(self) -> SemanticQuery:
        """Validate query shape before model-dependent member checks."""
        if bool(self.saved_query) == bool(self.metrics):
            raise ValueError("exactly one of saved_query or metrics is required")
        if self.offset > 0 and not self.order_by:
            raise ValueError("offset requires order_by")
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be at least 1")
        return self

    def canonical_json(self) -> str:
        """Return sorted-key, whitespace-free JSON used in a compiled-query cache key."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def validate_against(self, member_kinds: dict[str, str], time_dimensions: set[str]) -> None:
        """Validate referenced members, filter placement, and time grains against a model catalog.

        Args:
            member_kinds: Mapping from catalog member names to their kinds.
            time_dimensions: Names that must specify a grain when selected as time dimensions.

        Raises:
            SemanticValidationError: If a member is unknown, a filter group mixes placement
                kinds, or a selected time dimension lacks grain.
        """
        members = [*self.metrics, *self.dimensions]
        members.extend(time_dimension.name for time_dimension in self.time_dimensions)
        members.extend(order.member for order in self.order_by)
        if self.filters is not None:
            members.extend(_filter_members(self.filters))

        for member in members:
            if member not in member_kinds:
                raise SemanticValidationError("unknown_member", details={"member": member})

        for time_dimension in self.time_dimensions:
            if time_dimension.name in time_dimensions and time_dimension.grain is None:
                raise SemanticValidationError("grain_required", details={"member": time_dimension.name})

        if self.filters is not None:
            _validate_filter_group(self.filters, member_kinds)


class CompiledQuery(BaseModel, frozen=True):
    """Immutable pre-governance compiler output with no subject-derived content."""

    sql: str
    dialect: str
    engine: Literal["sidemantic", "native"]
    members: tuple[str, ...]
    tables: tuple[str, ...]
    cache_key: str


class GovernedQuery(BaseModel, frozen=True):
    """Immutable SQL and governance decisions ready for execution."""

    sql: str
    dialect: str
    driver: str
    tables: tuple[str, ...]
    rls_applied: tuple[str, ...]
    masked_columns: tuple[str, ...]
    limit: int
    subject_digest: str


class SemanticQueryResult(BaseModel):
    """Rows and metadata returned from an executed governed semantic query."""

    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool
    duration_ms: int
    compiled_sql: str
    audit_id: str
    result_id: str | None = None


def _filter_members(filters: FilterGroup) -> list[str]:
    """Collect filter-member names in source order from a recursive filter group."""
    members: list[str] = []
    for item in filters.items:
        if isinstance(item, FilterLeaf):
            members.append(item.member)
        else:
            members.extend(_filter_members(item))
    return members


def _validate_filter_group(filters: FilterGroup, member_kinds: dict[str, str]) -> set[str]:
    """Return placement kinds in a group and reject groups mixing metrics and dimensions."""
    kinds: set[str] = set()
    for item in filters.items:
        if isinstance(item, FilterLeaf):
            kind = member_kinds[item.member]
            kinds.add("metric" if kind == "metric" else "dimension")
        else:
            kinds.update(_validate_filter_group(item, member_kinds))
    if len(kinds) > 1:
        raise SemanticValidationError("mixed_filter_group")
    return kinds
