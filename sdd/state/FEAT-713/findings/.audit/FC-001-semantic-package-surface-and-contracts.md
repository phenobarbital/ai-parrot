---
id: FC-001
query_id: Q010, Q011, Q012
type: read
intent: "Public surface, layering statement and contract names of parrot.semantic as it exists on dev."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-001 — `parrot.semantic` today: 4 exports, a README that already reserves the accounting extension, and contract names an accounting layer would collide with

## Summary

`parrot.semantic.__init__` eagerly imports `SemanticLayerToolkit` (and through it the whole governed
stack), so `import parrot.semantic.accounting` executes that import chain first — the old spec's
"`__init__.py` exports only `__version__`" no longer holds. The README has a **Layering** section that
names "the future accounting extension" and requires it to "remain independently importable".
`models.py` already defines `Grain` (8 values, second…year), `SemanticQuery`, `CompiledQuery`
(pre-governance: sql, dialect, members, tables, cache_key), `GovernedQuery`, `SemanticQueryResult`,
`Limits` (default 1000 / max 10000) and `ModelMember` (kind: metric | dimension | time_dimension | entity).
`CompiledQuery` exists as the old spec anticipated, so `CompiledMetricQuery` stays a non-colliding name;
`Grain` and a top-level `Metric` (in `model.py`) would collide if re-declared at the same level.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/__init__.py`
  lines: 1-7
  symbol: `__all__`
  excerpt: |
    """Governed semantic queries using the native sqlglot compiler."""
    from .version import __version__
    from .models import SemanticQuery, SemanticQueryResult
    from .toolkit import SemanticLayerToolkit
    __all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]

- path: `packages/ai-parrot-semantic/README.md`
  lines: 6-9
  symbol: `Layering`
  excerpt: |
    ## Layering
    Generic semantic queries and the future accounting extension share this namespace.
    The accounting extension must remain independently importable.

- path: `packages/ai-parrot-semantic/README.md`
  lines: 19-22
  symbol: `Governance`
  excerpt: |
    The current native compiler supports declared metrics, dimensions, time grains,
    declared one-to-many joins with fan-out rejection, filtered measures, and
    derived metrics. The `duckdb` extra provides the local execution backend; the
    `bigquery` extra provides BigQuery integration.

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 12-12
  symbol: `Grain`
  excerpt: |
    Grain = Literal["second", "minute", "hour", "day", "week", "month", "quarter", "year"]

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 102-137
  symbol: `SemanticQuery`
  excerpt: |
    class SemanticQuery(BaseModel):
        model_config = ConfigDict(extra="forbid")
        model: str
        metrics: list[str] = Field(default_factory=list)
        dimensions: list[str] = Field(default_factory=list)
        time_dimensions: list[TimeDimension] = Field(default_factory=list)
        filters: FilterGroup | None = None
        order_by: list[OrderBy] = Field(default_factory=list)
        limit: int | None = None
        def canonical_json(self) -> str:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 192-199
  symbol: `CompiledQuery`
  excerpt: |
    class CompiledQuery(BaseModel, frozen=True):
        """Pre-governance compiler output without subject-derived content."""
        sql: str
        dialect: str
        members: tuple[str, ...]
        tables: tuple[str, ...]
        cache_key: str

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 202-214
  symbol: `GovernedQuery`
  excerpt: |
    class GovernedQuery(BaseModel, frozen=True):
        sql: str
        dialect: str
        driver: str
        tables: tuple[str, ...]
        rls_applied: tuple[str, ...]
        masked_columns: tuple[str, ...]
        limit: int
        subject_digest: str

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 217-227
  symbol: `SemanticQueryResult`
  excerpt: |
    class SemanticQueryResult(BaseModel):
        columns: list[str]
        rows: list[dict[str, Any]]
        row_count: int
        truncated: bool
        duration_ms: int
        compiled_sql: str
        audit_id: str
        result_id: str | None = None

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 230-234
  symbol: `Limits`
  excerpt: |
    class Limits(BaseModel):
        default: int = 1000
        max: int = 10000

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 244-251
  symbol: `ModelMember`
  excerpt: |
    class ModelMember(BaseModel):
        name: str
        kind: Literal["metric", "dimension", "time_dimension", "entity"]

## Notes

- Results are `list[dict]` rows, not Arrow tables; there is no Decimal handling in the contracts.
- "Independently importable" in the README is not enforced by code: any `parrot.semantic.accounting`
  import runs `parrot/semantic/__init__.py`, which imports `toolkit.py` (and with it `parrot.auth`,
  `parrot.tools.databasequery`, `jsonschema` via `ossie`). No test asserts the independence.
- Package module list (from the parent's tree listing): `audit, bootstrap, cache, catalog, context, errors,
  execution, handoff, loader, model, models, ossie, policy, results, toolkit, version`, sub-packages
  `engines/`, `governance/`, `schemas/`, `sql/`. No `accounting/` directory.
