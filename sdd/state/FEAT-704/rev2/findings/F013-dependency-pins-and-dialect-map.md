---
id: F013
query_id: Q013
type: read
intent: "Record the sqlglot/duckdb/pyarrow pins on dev and the shared dialect-map symbols the compiler reuses"
executed_at: 2026-10-25T11:05:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F013 — Core pins `sqlglot>=20.0` and `pyarrow>=25.0`; venv has sqlglot 30.23.0, duckdb 1.5.6; dialect map lives in `knowledge/common/sql_dialects.py`

## Summary

`packages/ai-parrot/pyproject.toml` declares `sqlglot>=20.0` (line 182) and `pyarrow>=25.0` (line 180); the active venv resolves sqlglot 30.23.0, duckdb 1.5.6, pyarrow 26.0.0; sidemantic is not installed. The branch pins `sqlglot>=30.1,<31` in the satellite (F004). The shared driver→sqlglot alias map is `SQLGLOT_DIALECT_MAP` in `parrot/knowledge/common/sql_dialects.py` (relocated by TASK-4313, re-exported from `parrot/tools/sql_dialects.py`); `driver_to_dialect` lives in `dataset_manager/sources/dialects.py`.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 180-182
  symbol: `dependencies`
  excerpt: |
    "pyarrow>=25.0",
    "sqlglot>=20.0",

- path: `packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py`
  lines: 1-10
  symbol: `SQLGLOT_DIALECT_MAP`
  excerpt: |
    SQL dialect alias map shared by wiki schema and tools (FEAT-540 M4).   # wiki page file:packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py score=0.89

- path: `packages/ai-parrot/src/parrot/tools/sql_dialects.py`
  lines: 1-5
  symbol: compatibility re-export
  excerpt: |
    Compatibility exports for SQL dialect aliases.   # wiki score=0.99

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py`
  lines: 41
  symbol: `driver_to_dialect`
  excerpt: |
    def driver_to_dialect(driver)   # "pg" → "postgres"   (cited by TASK-4467 contract)

## Notes

Installed versions from `python -c "import sqlglot,duckdb,pyarrow"` in the activated venv (2026-10-25). The byte-level determinism contract requires an exact or narrow sqlglot pin in the satellite plus golden tests; core's `>=20.0` floor is too loose for the satellite.
