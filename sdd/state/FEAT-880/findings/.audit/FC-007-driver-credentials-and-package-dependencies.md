---
id: FC-007
query_id: Q022, Q025, Q026, Q028
type: grep
intent: "Driver / dialect / credential resolution on both sides, and the package dependency direction between ai-parrot core, ai-parrot-tools and ai-parrot-semantic."
executed_at: 2026-11-11T22:12:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-007 — Two driver vocabularies, two credential resolvers, two executors; semantic depends on core, never the reverse

## Summary

`ai-parrot-semantic` declares `ai-parrot` as a dependency and already imports DatasetManager internals
(`parrot.tools.dataset_manager.sources.resolver`, `parrot.tools.databasequery.toolkit`). Nothing under
`packages/ai-parrot/src` or `packages/ai-parrot-tools/src` imports `parrot.semantic` (the only grep hits
are the unrelated text splitter `loaders/splitters/semantic.py`). So `DatasetManager`, which lives in
core, cannot hard-import the semantic layer: a semantic source must either live in `ai-parrot-semantic`
and be registered through `add_source()`, or be lazily imported the way `querysource` is. Drivers and
credentials are resolved differently on each side: DatasetManager normalizes to asyncdb names (`pg`)
and reads navconfig / querysource DSNs, executing through `AsyncDB` to a DataFrame; the semantic layer
uses the toolkit `dialect` as driver, reads `PARROT_SEMANTIC_CONN_<NAME>_<KEY>` env overlays, and
executes through `DatabaseQueryToolkit.get_source(driver).query(creds, sql)` to row dicts.

## Citations

- path: `packages/ai-parrot-semantic/pyproject.toml`
  lines: 6-30
  symbol: `dependencies`
  excerpt: |
    name = "ai-parrot-semantic"
    dependencies = ["ai-parrot", "sqlglot>=30.1,<31", "jsonschema>=4.20", "pyyaml>=6"]
    ai-parrot = {workspace = true}

- path: `packages/ai-parrot-semantic/src/parrot/semantic/handoff.py`
  lines: 11-11
  symbol: `PhysicalResources`
  excerpt: |
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

- path: `packages/ai-parrot/src/parrot/loaders/splitters/__init__.py`
  lines: 4-4
  symbol: `SemanticTextSplitter`
  excerpt: |
    from .semantic import SemanticTextSplitter   # unrelated: text splitter, not parrot.semantic

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py`
  lines: 50-52
  symbol: `_normalize_driver`
  excerpt: |
    def _normalize_driver(driver: str) -> str:
        """Normalize driver name to the canonical asyncdb driver string."""
        return _DRIVER_ALIASES.get(driver.lower(), driver.lower())

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/table.py`
  lines: 90-112
  symbol: `_resolve_credentials`
  excerpt: |
    def _resolve_credentials(driver: str) -> Tuple[Optional[Dict], Optional[str]]:
        """Resolve default credentials for a driver from navconfig."""
        from navconfig import config
        if driver == 'pg':
            # Prefer DSN from querysource if available
            _qs_conf = lazy_import("querysource.conf", package_name="querysource", extra="db")
            if _qs_conf.default_dsn:
                return None, _qs_conf.default_dsn

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/sql.py`
  lines: 45-84
  symbol: `SQLQuerySource.__init__`
  excerpt: |
    self.driver = _normalize_driver(driver)
    if dsn is None and credentials is None:
        default_creds = get_default_credentials(driver)
    ...
    def _get_connection_args(self): # 1. explicit DSN  2. explicit credentials  3. navconfig defaults

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  lines: 30-40
  symbol: `_get_qs`
  excerpt: |
    def _get_qs():
        """Lazily import QS from querysource. Returns None if not installed."""
        _qs_mod = lazy_import("querysource.queries.qs", package_name="querysource", extra="db")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 75-76
  symbol: `SemanticLayerToolkit.__init__`
  excerpt: |
    self._dialect = dialect
    self._loader = SemanticModelLoader(models_dir, driver=dialect)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py`
  lines: 117-124
  symbol: `_dialect_for`
  excerpt: |
    dialect = _DRIVER_DIALECTS.get(driver, driver)   # pg/postgresql/asyncpg -> postgres, bq -> bigquery
    sqlglot.Dialect.get_or_raise(dialect)

- path: `packages/ai-parrot/tests/test_semantic_duckdb_source.py`
  lines: 1-16
  symbol: `DuckDBSource`
  excerpt: |
    """Regression contract: Repair stock DuckDB source execution (M9D)."""
    from parrot.tools.databasequery.sources import duckdb as duckdb_source_module
    from parrot.tools.databasequery.sources.duckdb import DuckDBSource

## Notes

- `grep "parrot\.semantic|from \.+semantic"` over `packages/ai-parrot/src` and
  `packages/ai-parrot-tools/src`: 2 hits, both the text splitter. **No import of the semantic layer
  from core or tools.**
- Driver-name mismatch matters for PBAC resource ids, which are `"<driver>:<schema.table>"` on both
  sides: DatasetManager builds them from the asyncdb-canonical name (`pg:sales.orders`), the semantic
  layer from `model.schema.driver`, i.e. whatever string was passed as `dialect` (`postgres:sales.orders`
  when the host passes `dialect="postgres"`). The same grant would not match both unless the names are
  aligned.
- `ConnectionResolver.resolve(connection, driver)` (execution.py:26-49, read earlier in the session)
  starts from the same `get_default_credentials(driver)` that `SQLQuerySource` uses, then overlays the
  env keys — the credential dict shape is therefore compatible, only the overlay and naming differ.
- The semantic `Executor` returns `list[dict]` rows trimmed to the governed limit; DatasetManager
  sources must return `pd.DataFrame`. A semantic source needs one conversion, or a second execution of
  the governed SQL through AsyncDB.
- Supported sqlglot dialects on the DatasetManager side: 14 drivers in `_DRIVER_DIALECT_MAP`
  (dialects.py:23-38); the semantic spec restricts *execution* to Postgres / BigQuery / DuckDB.
- `table.py` was inspected by grep (definitions + the two helper bodies), not read in full; Q028's
  "schema prefetch" pattern is covered by `add_table_source` in FC-001.
