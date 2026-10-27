"""Metric definition models (FEAT-756 §2). Pure Pydantic — no a2ui / tools imports."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.skills.tenancy import validate_tenant_id

MetricId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")]
Visibility = Literal["private", "tenant", "public"]
Grain = Literal["day", "week", "month", "quarter", "year"]
PeriodPreset = Literal[
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "mtd",
    "qtd",
    "ytd",
    "last_7d",
    "last_30d",
    "last_90d",
    "this_year",
    "last_year",
]
_STRICT = ConfigDict(extra="forbid")


class DimensionSpec(BaseModel):
    """A breakdown axis ("by cost center")."""

    model_config = _STRICT
    name: str
    column: str
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)


class PeriodBinding(BaseModel):
    """How a resolved period reaches the source."""

    model_config = _STRICT
    start_placeholder: str | None = None
    end_placeholder: str | None = None
    date_column: str | None = None

    @model_validator(mode="after")
    def _exactly_one_mode(self) -> "PeriodBinding":
        """Require either a complete placeholder pair or a date column."""
        has_placeholders = self.start_placeholder is not None and self.end_placeholder is not None
        has_partial_placeholders = (self.start_placeholder is None) != (self.end_placeholder is None)
        has_date_column = self.date_column is not None
        if has_partial_placeholders or has_placeholders == has_date_column:
            raise ValueError("PeriodBinding requires either both placeholders or date_column, but not both")
        return self


class TimeSpec(BaseModel):
    """Time configuration for a metric."""

    model_config = _STRICT
    grain: Grain = "month"
    default_period: PeriodPreset = "this_month"
    binding: PeriodBinding
    series_grain: Grain | None = "day"


class ComparisonPolicy(BaseModel):
    """Comparison configuration for a metric."""

    model_config = _STRICT
    mode: Literal["previous_period", "same_period_last_year", "none"] = "previous_period"
    label: str | None = None


class KPICardShape(BaseModel):
    """Configuration for a KPI card."""

    model_config = _STRICT
    component: Literal["KPICard"] = "KPICard"
    value_column: str
    aggregate: Literal["sum", "avg", "min", "max", "count", "last", "first", "none"] = "sum"
    icon: str | None = None
    color: str | None = None


class ChartShape(BaseModel):
    """Configuration for a chart."""

    model_config = _STRICT
    component: Literal["Chart"] = "Chart"
    chart_type: Literal["line", "bar", "area", "pie"] = "line"
    x: str
    y: list[str]
    title: str | None = None


class DataTableShape(BaseModel):
    """Configuration for a data table."""

    model_config = _STRICT
    component: Literal["DataTable"] = "DataTable"
    columns: list[dict[str, Any]]
    title: str | None = None


class MapShape(BaseModel):
    """Configuration for a map."""

    model_config = _STRICT
    component: Literal["Map"] = "Map"
    lat: str
    lon: str
    label: str | None = None


ShapeSpec = Annotated[KPICardShape | ChartShape | DataTableShape | MapShape, Field(discriminator="component")]


class QuerySlugSource(BaseModel):
    """A QuerySource slug, including routing-only QuerySource tenant."""

    model_config = _STRICT
    kind: Literal["query_slug"] = "query_slug"
    slug: str
    tenant: str | None = Field(default=None, description="QuerySource store tenant used for routing, not security.")
    placeholders: dict[str, Any] = Field(default_factory=dict)
    filter: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] = Field(default_factory=list)
    ordering: list[str] = Field(default_factory=list)
    grouping: list[str] = Field(default_factory=list)
    limit: int | None = None


class TransformerSource(BaseModel):
    """A single-input registered Python transformer over a query slug."""

    model_config = _STRICT
    kind: Literal["transformer"] = "transformer"
    input: QuerySlugSource
    transformer: str
    params: dict[str, Any] = Field(default_factory=dict)
    input_alias: str = "source"
    output: str | None = None


class RecipeSource(BaseModel):
    """A published recipe and data-model pointer."""

    model_config = _STRICT
    kind: Literal["recipe"] = "recipe"
    recipe_name: str
    recipe_owner: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    data_model_path: str
    param_map: dict[str, str] = Field(default_factory=dict)


class SemanticMetricSource(BaseModel):
    """A reserved FEAT-704 semantic metric declaration."""

    model_config = _STRICT
    kind: Literal["semantic_metric"] = "semantic_metric"
    model: str
    metric: str


MetricSource = Annotated[
    QuerySlugSource | TransformerSource | RecipeSource | SemanticMetricSource,
    Field(discriminator="kind"),
]


class MetricDefinition(BaseModel):
    """A tenant-scoped metric: vocabulary, semantics, default shape and executable source."""

    model_config = _STRICT
    id: MetricId
    name: str
    description: str = ""
    tenant: str | None = Field(default=None, description="Auth and namespace tenant; None identifies a global metric.")
    program: str | None = None
    aliases: list[str] = Field(default_factory=list)
    example_phrases: list[str] = Field(default_factory=list)
    unit: str | None = None
    format: Literal["percent", "currency", "number"] | None = None
    higher_is_better: bool | None = True
    dimensions: list[DimensionSpec] = Field(default_factory=list)
    time: TimeSpec
    comparison: ComparisonPolicy = Field(default_factory=ComparisonPolicy)
    default_shape: ShapeSpec
    source: MetricSource
    owner: str | None = None
    visibility: Visibility = "tenant"
    allowed_groups: list[str] = Field(default_factory=list)
    global_only: bool = False
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "MetricDefinition":
        """Validate tenant visibility and declared source-field references."""
        if self.tenant is not None:
            self.tenant = validate_tenant_id(self.tenant)
        if self.visibility == "public" and self.tenant is not None:
            raise ValueError("Public metric definitions cannot have a tenant")

        fields = self.source.fields if isinstance(self.source, QuerySlugSource) else []
        if isinstance(self.source, TransformerSource):
            fields = self.source.input.fields
        if fields:
            if isinstance(self.default_shape, KPICardShape):
                required_fields = [self.default_shape.value_column]
            elif isinstance(self.default_shape, ChartShape):
                required_fields = [self.default_shape.x, *self.default_shape.y]
            else:
                required_fields = []
            missing = [field for field in required_fields if field not in fields]
            if missing:
                raise ValueError(f"Default shape references source fields not declared by source: {missing}")
        return self

    def matching_terms(self) -> list[str]:
        """Return ``[name] + aliases + example_phrases`` de-duplicated, lower-cased, order-preserving."""
        terms: list[str] = []
        seen: set[str] = set()
        for value in [self.name, *self.aliases, *self.example_phrases]:
            term = value.strip().lower()
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
        return terms

    def dimension(self, name_or_alias: str) -> DimensionSpec | None:
        """Return a dimension matching its name or alias, case-insensitively."""
        target = name_or_alias.casefold()
        for dimension in self.dimensions:
            if dimension.name.casefold() == target or any(alias.casefold() == target for alias in dimension.aliases):
                return dimension
        return None

    def shadow_key(self) -> str:
        """Return the key a tenant definition shadows globally by."""
        return self.id

    @classmethod
    def json_schema_v1(cls) -> dict[str, Any]:
        """Return the JSON Schema served by the metric schema endpoint and docs."""
        return cls.model_json_schema()


class MetricMatch(BaseModel):
    """Result of metric resolution."""

    model_config = _STRICT
    metric: MetricDefinition
    score: float
    lane: Literal["alias", "embedding"]
    ambiguous: bool = False
    tenant: str | None = None
    requested_period: PeriodPreset | None = None
    requested_dimension: str | None = None


class ResolvedPeriod(BaseModel):
    """Concrete dates for one resolved period."""

    model_config = _STRICT
    preset: PeriodPreset
    start: date
    end: date
    label: str
    udf_keywords: dict[str, str] | None = None
