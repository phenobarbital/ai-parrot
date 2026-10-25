---
id: F008
query_id: Q008
type: read
intent: "Read the engine Literal in models/policy, the model fixture format and which tests assume sidemantic"
executed_at: 2026-10-25T10:40:00Z
duration_ms: 4000
parent_id: null
depth: 0
---

# F008 — `engine` is a two-value Literal; fixtures are sidemantic YAML; three tests use sidemantic as the parity oracle

## Summary

`models.py:148` (`CompiledQuery.engine`) and `policy.py:56` (`ModelPolicy.engine`, default `"sidemantic"`) carry `Literal["sidemantic", "native"]`. The fixture `tests/fixtures/models/orders.yml` is a sidemantic-format document (`version: 1`, `models[].dimensions[] {name,type,granularity}`, `metrics[] {name, agg, sql}`, `primary_key`); `orders.policy.yaml` sets `engine: sidemantic`, roles, masks and an RLS rule with `predicate_template`. Tests that depend on sidemantic: `test_native_compiler.py::test_native_vs_sidemantic_parity`, `test_e2e_governed.py::test_e2e_native_engine_switch` (compares native to sidemantic rows), `test_sidemantic_engine.py` (whole file), `test_packaging.py::test_sidemantic_import_ban`. Native-only tests already exist: `test_native_compiler_subset`, `test_native_rejects_fan_out`, `test_native_dialect_snapshots`.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/models.py`
  lines: 147-150
  symbol: `CompiledQuery.engine` (branch)
  excerpt: |
    dialect: str
    engine: Literal["sidemantic", "native"]
    members: tuple[str, ...]
    tables: tuple[str, ...]

- path: `packages/ai-parrot-semantic/src/parrot/semantic/policy.py`
  lines: 55-58
  symbol: `ModelPolicy.engine` (branch)
  excerpt: |
    governed: bool = True
    engine: Literal["sidemantic", "native"] = "sidemantic"
    connection: str | None = None

- path: `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml`
  lines: 1-20
  symbol: sidemantic model format (branch)
  excerpt: |
    version: 1
    models:
      - name: orders
        table: sales.orders
        dimensions:
          - {name: order_date, type: time, granularity: day, metadata: {data_type: DATE}}
        metrics:
          - {name: revenue, agg: sum, sql: amount, description: Total order revenue, metadata: {data_type: DECIMAL}}

- path: `packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml`
  lines: 1-18
  symbol: policy side-file (branch)
  excerpt: |
    governed: true
    engine: sidemantic
    rls:
      - driver: pg
        table: sales.orders
        predicate_template: "region IN (:subject.programs)"

- path: `packages/ai-parrot-semantic/tests/test_native_compiler.py`
  lines: 15, 31, 51-64, 68
  symbol: `test_native_compiler_subset`, `test_native_rejects_fan_out`, `test_native_vs_sidemantic_parity`, `test_native_dialect_snapshots` (branch)
  excerpt: |
    async def test_native_vs_sidemantic_parity(loaded_models, duckdb_warehouse: str) -> None:
        """Native and sidemantic subset queries return identical DuckDB rows."""

- path: `packages/ai-parrot-semantic/tests/test_e2e_governed.py`
  lines: 168-186
  symbol: `test_e2e_native_engine_switch` (branch)
  excerpt: |
    _edit_policy(native_dir, engine="native")
    assert native._ledger.entries[-1].engine == "native"

## Notes

With sidemantic gone the parity oracle disappears; `test_native_dialect_snapshots` (golden SQL) and DuckDB execution against hand-computed expectations are the replacement oracles.
