# F003 — Model + policy YAML shape, the connection env convention, and the policy keys no example demonstrates

**Merged from**: FC-003, FW-003

<!-- merged from FC-003 -->
**Query**: Q008 · **Type**: read · **Depth**: 0

## Summary
The model YAML is a `models:` list; each entry needs `name`, `table`, `columns` (a `{col: SQLTYPE}`
map), `primary_key`, `dimensions`, `metrics`, `relationships` (the example writes `relationships: []`
explicitly). Dimensions are `{name, kind: categorical|time, column, grain?}`; metrics are
`{name, agg, column?}` (`count` takes no column). The adjacent `<model>.policy.yaml` carries
`governed: true`, `connection: <name>`, `limits: {default, max}`, a `roles:` map of
`{metrics, dimensions, usage}` (each a list or `"*"`), and `rls:` entries of
`{driver, table, predicate_template, subject_attribute}`. The `connection:` value drives the env var
`PARROT_SEMANTIC_CONN_<UPPER>_DATABASE`. The test fixture additionally shows the **multi-model +
relationship** form (`customers` one_to_many `orders` with paired key columns), an `admin` wildcard
role, and a `time` dimension with `grain: month` — none of which the current example demonstrates.
`policy.py` also supports `masks:` and `saved_queries:` keys that appear in *no* YAML in the repo
outside unit tests.

## Citations
- `packages/ai-parrot-semantic/tests/fixtures/models/orders.yml:1-22` — two-model fixture: `customers` (dim.customers) with a `one_to_many` relationship to `orders`, and `orders` (sales.orders) with a `time` dimension `order_date` (`grain: month`) and metrics `revenue` (sum) / `order_count` (count)
- `packages/ai-parrot-semantic/tests/fixtures/models/orders.policy.yaml:1-8` — `connection: semantic_test`, `limits: {default: 1000, max: 10000}`, roles `analyst` (explicit lists) and `admin` (`"*"` wildcards), one duckdb RLS rule on `sales.orders`
- `examples/semantic/agent_semantic_example.py:241-263` — the single-model variant the example writes at runtime (`connection: semantic_example`, `limits: {default: 100, max: 100}`, only an `analyst` role)
- `docs/tools/semantic-layer.md:11-25` — the canonical documented `orders.yml`, incl. `count_distinct` agg and `grain: day`
- `docs/tools/semantic-layer.md:48-58` — the canonical documented `orders.policy.yaml`
- `packages/ai-parrot-semantic/src/parrot/semantic/policy.py:67-69` — `ModelPolicy.masks: dict[str, MaskRule]` and `saved_queries: list[SavedQuery]` — supported but undemonstrated policy keys
- `packages/ai-parrot-semantic/src/parrot/semantic/policy.py:203-227` — `_validate_masks` / `_validate_saved_queries` — masks bind to columns, saved queries validate member kinds and time dimensions
- `packages/ai-parrot-semantic/tests/fixtures/ossie/orders.ossie.json:1-12` — the alternative OSSIE import format (`version`, `dialects: ["ANSI_SQL"]`, `semantic_model[].datasets[].fields[].expression.dialects`)

## Notes
- Each referenced model in a relationship **must have its own policy side-file** (`docs/tools/semantic-layer.md:27-31`); a
  multi-model second example therefore needs two policy files or one covering both.

---

<!-- merged from FW-003 -->
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
