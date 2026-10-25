---
id: F007
query_id: Q007
type: read
intent: "Read the branch engine dispatch, the native compiler and the sidemantic engine to size the swap"
executed_at: 2026-10-25T10:36:00Z
duration_ms: 5000
parent_id: null
depth: 0
---

# F007 — The native compiler exists (236 lines) but reads the sidemantic graph; dispatch is 54 lines; the sidemantic engine is 169 lines to delete

## Summary

`engines/__init__.py::compile()` is async, builds a `cache_key`, and dispatches on `model.policy.engine`: `"native"` → `NativeCompiler(model).compile(query, dialect)`, else `compile_sidemantic` under `asyncio.to_thread` (comment: 128-call/32-thread spike showed no lock needed). `engines/native.py::NativeCompiler` validates the query against `model.members`, supports `NATIVE_AGGREGATIONS = (sum, count, count_distinct, avg, min, max)`, `DATE_TRUNC` grains, declared one-to-many relationships via `layer.graph.find_relationship_path`, WHERE/HAVING split, order/limit — but reaches into `self.model.layer.graph.models[...]` at six call sites for tables, dimensions, metrics and relationships. `engines/sidemantic_engine.py` (169 lines: `filter_tree_to_sidemantic`, `compile_sidemantic`, helpers) is entirely sidemantic-specific.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/__init__.py`
  lines: 18-50
  symbol: `cache_key`, `compile` (branch)
  excerpt: |
    async def compile(...):
        if model.policy.engine == "native":
            from .native import NativeCompiler
        ...
            from .sidemantic_engine import compile_sidemantic
            # sidemantic 0.12.0 produced identical SQL in a 128-call, 32-thread spike; no lock is required.
            compiled = await asyncio.to_thread(compile_sidemantic, query, model, dialect)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 15-26
  symbol: `NATIVE_AGGREGATIONS`, `NativeCompiler.compile` (branch)
  excerpt: |
    NATIVE_AGGREGATIONS = ("sum", "count", "count_distinct", "avg", "min", "max")
    class NativeCompiler:
        """Compile a SemanticQuery against one LoadedModel without sidemantic's compiler."""
        def compile(self, query: SemanticQuery, dialect: str) -> CompiledQuery:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/native.py`
  lines: 57-60, 99, 111-156
  symbol: `_member_owners`, `_joins_for`, `_dimension_expr`, `_metric_expr` (branch)
  excerpt: |
    root_model = self.model.layer.graph.models[self.model.name]
    path = self.model.layer.graph.find_relationship_path(self.model.name, target)
    metric = next((item for item in self.model.layer.graph.models[owner].metrics if item.name == member), None)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/engines/sidemantic_engine.py`
  lines: 18-169
  symbol: `filter_tree_to_sidemantic`, `compile_sidemantic` (branch)
  excerpt: |
    def filter_tree_to_sidemantic(filters: FilterGroup | None, members: dict[str, ModelMember]) -> list[str]:
    def compile_sidemantic(query: SemanticQuery, model: "LoadedModel", dialect: str) -> CompiledQuery:

## Notes

Swapping the graph source behind `LoadedModel.layer` (F006) to a typed, frozen Pydantic graph re-points six call sites in `native.py` and four helpers in `loader.py`; the compiler's AST logic (`_grain_expr`, `_filter_expr`, `_literal`, fan-out rejection) is engine-neutral.
