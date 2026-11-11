---
id: FC-002
query_id: Q014, Q015
type: read
intent: "Compiler entry point and native compiler structure — can an accounting compiler plug in as an engine or must it stay parallel."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-002 — There is no engine seam: `engines.compile` is hard-wired to `NativeCompiler`, whose grammar is measures/dimensions/joins over a `SemanticQuery`

## Summary

`parrot.semantic.engines.compile(query, model, dialect, *, cache)` is the single entry point; it
instantiates `NativeCompiler(model)` directly inside `asyncio.to_thread` — no registry, no dispatch
("Sole native SQL AST compiler; no warehouse connection or engine dispatch"). The compiler builds sqlglot
`exp.*` nodes from a `LoadedModel` + `SemanticQuery`: metrics, dimensions, time-dimension grains, joins,
WHERE/HAVING filters, ORDER BY. Aggregations are a closed tuple (`sum, count, count_distinct, avg, min,
max`). Nothing in it expresses account sets (`SUM(CASE WHEN account IN (...))`), sign normalisation,
effective-dated membership, cumulative window totals or reconciliation assertions. An accounting compiler
therefore cannot be "an engine of" the existing entry point without changing it; it is a parallel
compiler that can share sqlglot, the dialect names and the `to_thread` + compile-cache pattern.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 14-26
  symbol: `_cache_key`
  excerpt: |
    return json.dumps(
        [model.model_digest, model.policy_digest, query.canonical_json(), dialect,
         model.compiler_version, model.policy.connection],
        separators=(",", ":"),
    )

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 29-46
  symbol: `compile`
  excerpt: |
    async def compile(query: SemanticQuery, model: LoadedModel, dialect: str, *,
                      cache: CompileCache | None = None) -> CompiledQuery:
        """Compile under to_thread, or return immutable pre-governance cache output."""
        ...
        compiled = await asyncio.to_thread(NativeCompiler(model).compile, query, dialect)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 1-20
  symbol: `NATIVE_AGGREGATIONS`
  excerpt: |
    """Sole native SQL AST compiler; no warehouse connection or engine dispatch."""
    from sqlglot import exp
    NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")
    _FILTER_DIALECTS = frozenset({"duckdb", "postgres"})

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 45-54
  symbol: `NativeCompiler`
  excerpt: |
    class NativeCompiler:
        """Compile the closed semantic grammar to deterministic dialect SQL."""
        def __init__(self, model: LoadedModel) -> None:
            self.model = model
            self._graph: dict[str, SemanticModel] = {model.name: model.model, **model.related_models}

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 72-129
  symbol: `NativeCompiler.compile`
  excerpt: |
    def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:
        if query.model != self.model.name:
            raise SemanticValidationError("unknown_model", ...)
        if query.timezone is not None:
            raise SemanticValidationError("unsupported_query", "Timezone conversion is not supported ...")
        ...
        select = exp.select(*projections).from_(self._table_expr(plan.base, plan))
        if query.metrics and groups:
            select.set("group", exp.Group(expressions=groups))

## Notes

- `_FILTER_DIALECTS = {"duckdb", "postgres"}` — the native compiler's typed filters target these two
  dialects; the old spec's golden set was duckdb / postgres / bigquery.
- Only lines 1-140 of `native.py` were read; window functions or `CASE` handling beyond line 140 were not
  inspected.
- [cross-lane: type=git_log, intent=confirm when the sidemantic engine was replaced by NativeCompiler and whether a FEAT-742 Rust compiler branch touches engines/]
