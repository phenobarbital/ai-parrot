# FW-003 — A model is `<name>.yml` + a mandatory `<name>.policy.yaml`; the connection comes from `PARROT_SEMANTIC_CONN_<NAME>_<KEY>`

**Query**: Q003 + follow-up · **Type**: wiki_query + wiki_page + source read · **Depth**: 1

## Summary
`models_dir` holds one or more model documents (`models:` list with `name`, `table`, `columns`,
`primary_key`, `dimensions`, `metrics`, `relationships`) and, for each, an adjacent
`<model>.policy.yaml` carrying `governed`, `connection`, `limits`, `roles`, `rls` and optional
`saved_queries`. Policy files are excluded from model discovery by the loader. The named
`connection:` is resolved **only from the environment** by `ConnectionResolver`: driver defaults
from `get_default_credentials(driver)` overlaid with any
`PARROT_SEMANTIC_CONN_<CONNECTION_UPPERCASED_NON_ALNUM_TO_UNDERSCORE>_<KEY>` variables; nothing
resolves → `SemanticExecutionError("no_credentials")`. For `duckdb` the resolver forces
`read_only=True` unless the host overrides it. Supported time grains:
`second|minute|hour|day|week|month|quarter|year`; dialects: DuckDB, Postgres, BigQuery.

## Citations
- wiki page `file:docs/tools/semantic-layer.md` (score=0.63) — the canonical `orders.yml` and
  `orders.policy.yaml` blocks, grain list, and the governed-by-default rule
  ("Only a policy with `governed: false` opts out explicitly").
- `packages/ai-parrot-semantic/src/parrot/semantic/execution.py:20-51` —
  `class ConnectionResolver` with `PREFIX = "PARROT_SEMANTIC_CONN_"`,
  `def __init__(self, env: Mapping[str, str] | None = None) -> None`,
  `def resolve(self, connection: str, driver: str) -> dict[str, Any]`. Prefix built as
  `self.PREFIX + re.sub(r"[^A-Za-z0-9]", "_", connection).upper() + "_"`; the suffix is lowercased
  into the creds key. `creds.setdefault("read_only", True)` when `driver == "duckdb"`.
- `packages/ai-parrot-semantic/src/parrot/semantic/execution.py:54-90` —
  `class Executor.__init__(self, toolkit: DatabaseQueryToolkit, resolver: ConnectionResolver)`;
  `async def run_with_columns(self, governed: GovernedQuery, *, connection: str) -> tuple[list[dict], int, bool, int, list[str]]`.
  Errors: `SemanticExecutionError` with codes `no_source`, `no_credentials`, `execution_failed`.
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:95` — the toolkit builds
  `Executor(database_toolkit or DatabaseQueryToolkit(), ConnectionResolver())`, i.e. execution goes
  through `parrot.tools.databasequery.toolkit.DatabaseQueryToolkit`, not a bespoke driver.
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:74` —
  `self._loader = SemanticModelLoader(models_dir, driver=dialect)` then `self._models = self._loader.load()`.
- wiki stub `sym:packages/ai-parrot-semantic/src/parrot/semantic/loader.py#SemanticModelLoader._load_documents`
  (score=0.63) — "Read model documents while excluding policy side-files."

## Notes
`loader.py` also has an Ossie path (`ossie.py`, 55 lines) — a second declaration format. I did not
read it; an example should stick to the own-format YAML the docs page shows.
[cross-lane: type=code_read, intent=confirm whether `ossie.py` offers a second model format worth a
second example]
