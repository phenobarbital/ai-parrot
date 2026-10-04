---
id: F018
query_id: Q020
type: grep
intent: sqlglot 30.18.0 installed (pyproject >=20.0); used only for query validation/transpile — exp.Create appears once, in a DDL blocklist
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F018 — sqlglot 30.18.0 installed (pyproject >=20.0); used only for query validation/transpile — exp.Create appears once, in a DDL blocklist

## Summary

pyproject.toml L182 'sqlglot>=20.0'; installed 30.18.0. Importers: security/query_validator.py (L246 lists exp.Create, exp.Drop, exp.Alter as *forbidden* statement types), tools/databasequery/base.py, tools/dataset_manager/sources/resolver.py and authorizing.py. Zero occurrences of exp.ColumnDef / exp.ForeignKey / exp.PrimaryKey handling anywhere → DDL folding is greenfield.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 182
  excerpt: |
    "sqlglot>=20.0",
- path: `packages/ai-parrot/src/parrot/security/query_validator.py`
  lines: 246
  excerpt: |
    exp.Create, exp.Drop, exp.Alter,
- path: `packages/ai-parrot/src/parrot/tools/databasequery/base.py`
  lines: -
  excerpt: |
    import sqlglot
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py`
  lines: -
  excerpt: |
    import sqlglot
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`
  lines: -
  excerpt: |
    import sqlglot
