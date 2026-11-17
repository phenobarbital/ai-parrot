---
id: FC-003
query_id: Q015, Q016
type: read
intent: "Semantic compile entry point and NativeCompiler.compile: inputs, outputs, refusals."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-003 — Compile-only surface: `engines.compile(query, model, dialect)` returns pre-governance SQL, always LIMITed

## Summary

Compilation is a pure function of `(SemanticQuery, LoadedModel, dialect)`: `engines.compile()` wraps
`NativeCompiler(model).compile(query, dialect)` in `asyncio.to_thread` and returns a frozen
`CompiledQuery(sql, dialect, members, tables, cache_key)`. It needs no identity, guard or connection —
but its output is explicitly *pre-governance* (no RLS, no masks). The compiler requires a full
`SemanticQuery` (a model name plus at least one metric/dimension/time dimension), rejects saved queries
and timezones, and **always** appends `LIMIT min(query.limit or policy.limits.default,
policy.limits.max)`; the policy defaults are 1000 / 10000 rows.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 14-46
  symbol: `compile`
  excerpt: |
    async def compile(query: SemanticQuery, model: LoadedModel, dialect: str, *,
                      cache: CompileCache | None = None) -> CompiledQuery:
        """Compile under to_thread, or return immutable pre-governance cache output."""
        cache_key = _cache_key(query, model, dialect)
        ...
        compiled = await asyncio.to_thread(NativeCompiler(model).compile, query, dialect)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 14-26
  symbol: `_cache_key`
  excerpt: |
    return json.dumps([model.model_digest, model.policy_digest, query.canonical_json(),
                       dialect, model.compiler_version, model.policy.connection], ...)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 72-90
  symbol: `NativeCompiler.compile`
  excerpt: |
    if query.model != self.model.name:
        raise SemanticValidationError("unknown_model", ...)
    if query.saved_query is not None:
        raise SemanticValidationError("unsupported_query", "Saved queries must be expanded before compilation")
    if query.timezone is not None:
        raise SemanticValidationError("unsupported_query", "Timezone conversion is not supported ...")
    member_kinds, time_dimensions = self._member_universe()
    query.validate_against(member_kinds, time_dimensions)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 143-156
  symbol: `NativeCompiler.compile`
  excerpt: |
    limit = min(
        query.limit if query.limit is not None else self.model.policy.limits.default, self.model.policy.limits.max
    )
    select.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
    ...
    return CompiledQuery(sql=select.sql(dialect=dialect), dialect=dialect, members=tuple(selected_names),
        tables=tuple(self._graph[name].table for name in plan.models), cache_key=self._cache_key(query, dialect))

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 45-54
  symbol: `NativeCompiler.__init__`
  excerpt: |
    def __init__(self, model: LoadedModel) -> None:
        self.model = model
        self._graph: dict[str, SemanticModel] = {model.name: model.model, **model.related_models}

## Notes

- A `LoadedModel` only exists after `SemanticModelLoader(models_dir, driver=...).load()`, which requires
  a `<model>.policy.yaml` beside every model (loader.py:111-115, seen earlier in this session). So
  "a YAML file" is in practice "a models directory + policy side-files".
- Consequence for `add_semantic`: a dataset can only be a *query result* (metrics × dimensions ×
  filters), never "the whole model", and it is row-capped by the policy limits unless the policy raises
  `limits.max`.
- `engines.compile` and `NativeCompiler` are importable without instantiating `SemanticLayerToolkit`.
