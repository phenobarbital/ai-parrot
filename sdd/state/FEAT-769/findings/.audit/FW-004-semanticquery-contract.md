# FW-004 — `SemanticQuery` is `extra="forbid"` and rejects empty / mixed-kind / offset-without-order queries

**Query**: Q005 (follow-up) · **Type**: source read · **Depth**: 1

## Summary
`SemanticQuery` is the single argument of both `sl_compile_query` and `sl_query_metrics`.
It forbids extra fields, so any guessed kwarg is a hard validation error. At least one of
`metrics` / `dimensions` / `time_dimensions` is required unless `saved_query` is set (which is
mutually exclusive with explicit members, filters and ordering). `limit` must be `>= 1` when given,
`offset >= 0`, and a non-zero `offset` requires `order_by`. Time dimensions always require a
`grain`. `SemanticQueryResult` is what comes back from a direct method call; through a tool the
`_post_execute` hook turns it into `model_dump(mode="json")`.

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:96-127` —
  `class SemanticQuery(BaseModel)` with `model_config = ConfigDict(extra="forbid")` and fields:
  `model: str`; `metrics: list[str] = Field(default_factory=list)`;
  `dimensions: list[str] = Field(default_factory=list)`;
  `time_dimensions: list[TimeDimension] = Field(default_factory=list)`;
  `filters: FilterGroup | None = None`; `order_by: list[OrderBy] = Field(default_factory=list)`;
  `limit: int | None = None`; `offset: int = 0`; `timezone: str | None = None`;
  `saved_query: str | None = None`. Plus `canonical_json()` and
  `validate_against(self, member_kinds: dict[str, str], time_dimensions: set[str]) -> None`.
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:30-41` —
  `class TimeDimension(BaseModel)`: `name: str`, `grain: Grain | None = None`,
  `date_range: tuple[str, str] | None = None`; validator requires a grain.
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:44-49` —
  `class FilterLeaf(BaseModel)`: `member: str`, `op: FilterOp`,
  `values: list[str | int | float | bool] = Field(default_factory=list)`; arity enforced per op.
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:78-84` —
  `class FilterGroup(BaseModel)`: `op: Literal["and", "or"]`, `items: list["FilterLeaf | FilterGroup"]`.
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:87-92` —
  `class OrderBy(BaseModel)`: `member: str`, `grain: Grain | None = None`, `desc: bool = False`.
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:11-28` — `Grain` and the 14-value
  `FilterOp` literal (`equals, not_equals, in, not_in, contains, gt, gte, lt, lte, between, is_set,
  not_set, in_date_range, before_date, after_date`).
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:217-227` —
  `class SemanticQueryResult(BaseModel)`: `columns: list[str]`, `rows: list[dict[str, Any]]`,
  `row_count: int`, `truncated: bool`, `duration_ms: int`, `compiled_sql: str`, `audit_id: str`,
  `result_id: str | None = None`.
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:230-241` —
  `class Limits(BaseModel)`: `default: int = 1000`, `max: int = 10000` (`1 <= default <= max`).
- `packages/ai-parrot-semantic/src/parrot/semantic/models.py:244-251` —
  `class ModelMember(BaseModel)`: `name`, `kind: Literal["metric","dimension","time_dimension","entity"]`,
  `description: str = ""`, `grain: Grain | None = None`, `sensitive: bool = False` — this is the shape
  `sl_list_metrics` / `sl_get_dimensions` return (`member.model_dump()`).

## Notes
A filter group cannot mix metric and dimension members (`mixed_filter_group`), so a WHERE/HAVING
split must be expressed as two queries or a single-kind group.
