"""Pydantic models for QuerysourceToolkit inputs and outputs (spec §2 Data Models)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

FilterScalar = str | int | float | bool | None
FilterValue = FilterScalar | list[FilterScalar] | dict[str, FilterScalar]  # scalar | IN list | {op: v} | [op, v]


class SlugSummary(BaseModel):
    """One row of public.queries as shown by qs_list_slugs."""

    slug: str
    description: str | None = None
    program_slug: str
    provider: str
    is_multiquery: bool
    placeholders: list[str] = Field(default_factory=list)  # keys of cond_definition ∪ stored conditions


class PlaceholderInfo(BaseModel):
    """A declared placeholder: name, cond_definition type, stored default."""

    name: str
    type: str | None = None
    default: Any = None


class SlugDetail(SlugSummary):
    """Full, redacted description of a slug (never source/params/attributes/dwh_*/cache_options)."""

    placeholders_detail: list[PlaceholderInfo] = Field(default_factory=list)
    filtering: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    ordering: list[str] = Field(default_factory=list)
    grouping: list[str] = Field(default_factory=list)
    is_cached: bool
    cache_timeout: int
    sql: str | None = None  # query_raw when include_sql=True and not multiquery
    pipeline: dict[str, Any] | None = None  # parsed query_raw when is_multiquery
    rendered_query: str | None = None  # QS.dry_run() output when dry_run=True


class ExecutionResult(BaseModel):
    """Bounded, JSON-safe result of a slug execution (S8 naming)."""

    status: Literal["success", "empty"]
    slug: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    returned_rows: int
    total_rows: int | None = None
    truncated: bool = False
    columns: list[str] = Field(default_factory=list)
    applied_conditions: dict[str, Any] = Field(default_factory=dict)
    rejected_inputs: list[str] = Field(default_factory=list)
    duration_ms: int


class MultiQueryResult(BaseModel):
    """Result of a MultiQuery run: one ExecutionResult per returned frame ('result' when single)."""

    status: Literal["success", "empty"]
    results: dict[str, ExecutionResult]
    duration_ms: int


class PipelineIssue(BaseModel):
    """One validation problem (mirrors querysource ValidationError(step, field, message))."""

    step: str
    field: str
    message: str


class PipelineValidation(BaseModel):
    """Outcome of qs_validate_pipeline (structural rules + toolkit policy)."""

    valid: bool
    issues: list[PipelineIssue] = Field(default_factory=list)
    referenced_slugs: list[str] = Field(default_factory=list)
    has_raw_nodes: bool = False
    has_external_sources: bool = False
    destination_steps: list[str] = Field(default_factory=list)


class ComponentAttribute(BaseModel):
    """Mirror of querysource AttributeInfo (registry.py:24)."""

    name: str
    type: str
    default: Any = None
    required: bool = False
    description: str = ""


class ComponentDoc(BaseModel):
    """Mirror of querysource ComponentInfo (registry.py:34) — the /api/v3/qs/components payload."""

    name: str
    category: str
    description: str
    usage: str
    attributes: list[ComponentAttribute] = Field(default_factory=list)
    json_schema: dict[str, Any] | None = None
    example: str = ""
    icon: str = ""


class SavedSlug(BaseModel):
    """Outcome of qs_save_multiquery."""

    slug: str
    program_slug: str
    action: Literal["inserted", "updated"]


class DialectReference(BaseModel):
    """The QuerySource conditions dialect as shown to the LLM (spec §3 M3)."""

    verified_against: str
    option_keys: dict[str, str]
    placeholder_rules: list[str]
    where_grammar: list[str]
    operators_list_form: list[str]
    operators_dict_form: list[str]
    examples: list[dict[str, Any]]
    variables: dict[str, str] = Field(default_factory=dict)  # '@name' → one-line doc (§8 Q2)
    notes: list[str]
