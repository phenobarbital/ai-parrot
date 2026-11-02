# FC-003 — Three concordant copies of the model+policy YAML shape exist; new examples must mirror the loader's required keys exactly

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
