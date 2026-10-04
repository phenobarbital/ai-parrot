"""Pydantic models for QuerysourceToolkit inputs and outputs (spec §2 Data Models)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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
    """A declared placeholder: name, cond_definition type, stored default, and describe semantics.

    ``required`` / ``accepts_keywords`` mirror ``querysource.queries.describe.build_variables`` exactly
    (describe.py:154 and :163 — FEAT-598 AC6).
    """

    name: str
    type: str | None = None
    default: Any = None
    required: bool = False
    accepts_keywords: bool = False


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
    variables_supported: bool = True  # False for JSON-dialect slugs (describe.py:116-118) — linked params stay empty


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


class DashboardSource(BaseModel):
    """One dashboard-owned data source (linked dashboards): fetched once, shared by any number of widgets."""

    slug: str
    request: dict[str, Any] | None = None  # qs grammar: placeholders/filter/fields/ordering/grouping/limit/offset
    tenant: str | None = None
    refresh: dict[str, Any] | None = None  # RefreshPolicy payload
    transform: dict[str, Any] | None = None  # source-level transform DSL (TransformSpec payload)


class DashboardWidget(BaseModel):
    """One widget of a linked dashboard: its key, unbound component and exactly ONE data origin.

    Origins (mutually exclusive):

    * ``slug`` — the widget owns a query-slug source (FEAT-610 shape; ``request``/``tenant``/``refresh`` apply).
    * ``source`` — the widget reads a dashboard-level source (``sources[<key>]``). Without ``transform`` it binds
      that source's rows directly; with ``transform`` (DSL ops) it becomes a *derived* view keyed by the widget
      key, computed from the parent's frame without another fetch.
    * ``data`` — inline rows baked into the dashboard's data model (no descriptor, never refreshed).
    """

    key: str  # component id + data-model root (JSON-pointer-safe)
    component: dict[str, Any]  # Chart | DataTable | KPICard, without its binding
    section: Literal["kpis", "charts", "table"] | None = None  # layout row; inferred from component when None
    slug: str | None = None
    request: dict[str, Any] | None = None  # only with `slug`
    tenant: str | None = None  # only with `slug`
    refresh: dict[str, Any] | None = None  # only with `slug`
    source: str | None = None  # dashboard source key
    transform: dict[str, Any] | None = None  # only with `source` → derived view
    data: list[dict[str, Any]] | None = None  # inline rows

    @model_validator(mode="after")
    def _one_origin(self) -> DashboardWidget:
        origins = [name for name in ("slug", "source", "data") if getattr(self, name) is not None]
        if len(origins) != 1:
            raise ValueError(f"widget {self.key!r} must declare exactly one of slug | source | data (got {origins})")
        if self.slug is None and any(getattr(self, name) is not None for name in ("request", "tenant", "refresh")):
            raise ValueError(f"widget {self.key!r}: request/tenant/refresh apply only to a widget with its own slug")
        if self.transform is not None and self.source is None:
            raise ValueError(f"widget {self.key!r}: transform requires `source` (a derived view of a dashboard source)")
        if self.data is not None and (not self.data or not all(isinstance(row, dict) for row in self.data)):
            raise ValueError(f"widget {self.key!r}: data must be a non-empty list of row objects")
        return self

    @property
    def origin(self) -> Literal["slug", "source", "data"]:
        """Which origin this widget declares."""
        return "slug" if self.slug is not None else "source" if self.source is not None else "data"


class DialectReference(BaseModel):
    """The QuerySource conditions dialect as shown to the LLM (spec §3 M3)."""

    verified_against: str
    option_keys: dict[str, str]
    placeholder_rules: list[str]
    where_grammar: list[str]
    operators_list_form: list[str]
    operators_dict_form: list[str]
    operators_jsonb: list[str] = Field(default_factory=list)  # querysource >= 5.1 JSONB operators (FEAT-610)
    examples: list[dict[str, Any]]
    variables: dict[str, str] = Field(default_factory=dict)  # '@name' → one-line doc (§8 Q2)
    notes: list[str]
