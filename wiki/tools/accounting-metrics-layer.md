---
title: Accounting metrics layer
summary: Chart-of-accounts rollups compiled to deterministic queries, with exact evaluation, audit, and governance.
---

# Accounting metrics layer

## Purpose

The accounting metrics layer (`parrot.semantic.accounting`) compiles finance questions over a chart of accounts into deterministic SQL queries. The LLM selects `metric + grain + filters + period`; the compiler produces the query. The layer supports exact numeric evaluation, multi-tenant PBAC filtering, and a shared audit ledger.

## Public API

- [`AccountingToolkit`](ref:parrot.semantic.accounting.toolkit.AccountingToolkit) — finance tools (`finance_list_metrics`, `finance_explain_metric`, `finance_query_metric`, `finance_validate_model`)
- [`DuckDBEngine`](ref:parrot.interfaces.duckdb_engine.DuckDBEngine) — in-process DuckDB over Arrow (core, `ai-parrot[duckdb]`)
- [`load_model`](ref:parrot.semantic.accounting.loader.load_model) — load and validate a model from YAML
- [`compile_metric`](ref:parrot.semantic.accounting.compiler.compile_metric) — compile a metric request to SQL
- [`AccountingAuditEntry`](ref:parrot.semantic.accounting.audit.AccountingAuditEntry) — signed audit entry for the shared ledger

## Configuration & Parameters

### Model YAML

Models live in `<models_dir>/<tenant>/<model>.yaml`. The file declares a chart of accounts, account sets, metrics, and assertions.

```yaml
# troc/troc_pnl.yaml
model: troc_pnl
version: "1.0"
tenant: troc
chart_of_accounts:
  source:
    table: gl.accounts
    account_key: account_id
    posting_date: posting_date
    amount_convention: debit_positive
    amount: amount
    nature:
      from_column: nature
  dimensions: [entity, product_line, cost_center]
sets:
  revenue:
    accounts: [4100, 4200, 4300]
  expenses:
    accounts: [5100, 5200, 5300]
metrics:
  gross_margin:
    expr: sum(revenue) - sum(expenses)
    description: Gross margin = revenue - expenses
  ebitda:
    expr: sum(revenue) - sum(expenses) - sum(depreciation) - sum(amortization)
    description: EBITDA
assertions:
  - expr: gross_margin == ebitda
    tolerance: "0.01"
    on_failure: flag
```

### `amount_convention`

The `amount_convention` field is **required** and determines how amounts are normalised for aggregation.

| convention | source shape | normalised amount |
|---|---|---|
| `debit_positive` | one `amount` column, debits > 0 | `amount` if nature = debit else `-amount` |
| `credit_positive` | one `amount` column, credits > 0 | `amount` if nature = credit else `-amount` |
| `debit_credit_columns` | two columns `debit`, `credit` | `debit - credit` if nature = debit else `credit - debit` |
| `natural_balance` | `amount` already in natural-balance sign | `amount` (nature optional) |

### Selectors

Account sets can be defined by explicit accounts or by selectors:

```yaml
sets:
  # Explicit list
  revenue:
    accounts: [4100, 4200, 4300]

  # Prefix selector
  sales:
    select:
      prefix: "41"

  # Range selector
  salaries:
    select:
      range: ["5100", "5199"]

  # Tag selector
  marketing:
    select:
      tag: "marketing"

  # Except selector
  opex:
    accounts: [5100, 5200, 5300, 5400]
    except: [5900]  # exclude from-cogs
```

### Intervals and Retained Natures

Each account can have a `valid_from`/`valid_to` date. The loader partitions the chart into membership intervals and validates completeness per interval. The resolved natures are retained in the model and never fetched from the snapshot during compilation.

### Request contract

A metric request is a JSON object:

```json
{
  "kind": "metric",
  "metric": "gross_margin",
  "grain": "month",
  "dimensions": ["entity", "product_line"],
  "filters": {
    "entity": ["TROC", "TROC-INTL"],
    "product_line": ["hardware", "software"]
  },
  "period": {
    "from": "2025-01-01",
    "to": "2025-12-31",
    "cumulative": null
  }
}
```

- `grain`: `day`, `week`, `month`, `quarter`, `year` (or `null` for one row per dimension combination)
- `cumulative`: `mtd`, `qtd`, `ytd` (or `null` for non-cumulative)
- `filters`: equality or `IN` on declared dimensions only

### Allowed cumulative/grain matrix

| cumulative | day | week | month | quarter | year |
|---|---|---|---|---|---|
| `mtd` | ✅ | ❌ | ✅ | ❌ | ❌ |
| `qtd` | ✅ | ❌ | ✅ | ✅ | ❌ |
| `ytd` | ✅ | ❌ | ✅ | ✅ | ✅ |
| `null` | ✅ | ✅ | ✅ | ✅ | ✅ |

`week` with any cumulative mode is rejected. Non-cumulative `week` is allowed.

### Partial buckets

The output includes the bucket containing `period.from_`, even if its label precedes that date. The final bucket is partial through inclusive `period.to`. Empty buckets are not synthesized.

### Exact evaluation / rounding / overflow

- Source amounts must fit `DECIMAL(38,6)` without rounding. `allow_float` is the sole explicit exception.
- SQL returns dimensions/buckets and exact per-set sums. Cast exact inputs before aggregation.
- `evaluate_rows` uses `fractions.Fraction` for exact intermediates. Final outputs are quantized once to scale 6 with half-even rounding.
- Overflow raises `AccountingExecutionError`. Float aggregates are rejected.

### Determinism and golden-file policy

- Same `model_hash` + same canonical request + same dialect ⇒ byte-identical SQL.
- `IN` lists are sorted. Model-derived aliases are deterministic.
- Golden `.sql` files are the review artifact for sqlglot bumps. Golden plan `.json` files are the FEAT-742 parity fixtures.
- Run golden tests with `REGENERATE_GOLDENS=1` to update them.

### Audit entry fields and `lineage_ref` replay

Every executed query appends a signed `AccountingAuditEntry` to the shared `SemanticAuditLedger`. The entry contains:

- `entry_id`, `created_at`, `user_id`, `tenant_id`, `model`, `version`, `model_hash`, `snapshot_hash`, `sql_hash`, `plan_hash`, `dialect`, `target`, `tool`, `request_canonical`, `lineage_ref`, `assertion_status`, `outcome`, `row_count`, `duration_ms`, `signature`

`tenant_id` is the *queried* tenant; the caller is identified by `user_id` and `subject_digest` (so a user of tenant A querying tenant B is audited against B). Only executed queries are audited: `outcome` is `ok` or `execution_error`; an authorization denial raises before any entry exists.

`lineage_ref` is a string of the form `{model_hash}:{plan_hash}:{sql_hash}`. It is never inline. To rebuild lineage, parse the discriminated `request_canonical`, verify the hashes, and call `compile_metric` or `compile_assertion`.

### Governance posture

Metrics are governed by default. Visibility is filtered through `DatasetPolicyGuard` with resource names `accounting:<tenant>:<model>:<metric>`. With no guard or no permission context, every metric is allowed. Pass `require_context=True` to `AccountingToolkit` to make a configured guard refuse (with `AuthorizationRequired`) any call that carries no permission context instead of degrading to allow-all; it is off by default, and has no effect without a guard.

The `sl_*` tools of the semantic layer fail closed instead.

### `DatasetPolicyGuard` and `__validate__` privilege

- Per-metric `DatasetPolicyGuard` controls visibility.
- The reserved model resource `accounting:<tenant>:<model>:__validate__` grants permission to run `validate_model`.
- Actual policy YAML keys are `dataset:accounting:...` with action `dataset:read` (the guard adds the prefix).

### `DuckDBEngine` API

```python
from parrot.interfaces.duckdb_engine import DuckDBEngine, to_arrow

# Create the engine (requires ai-parrot[duckdb])
engine = DuckDBEngine(threads=4, database=":memory:")

# Register a long-lived Arrow table
await engine.register("journal", journal_table, replace=True)

# Execute a query (per-call frames are isolated)
result = await engine.execute(
    "SELECT SUM(amount) FROM journal WHERE posting_date >= ?",
    frames={"journal": journal_table},
    parameters=["2025-01-01"]
)

# Close the engine
await engine.close()
```

### MCP-local configuration

Operator configuration is local. Add this to `.parrot/mcp-toolkits.yaml`:

```yaml
toolkits:
  finance:
    class: parrot.semantic.accounting.toolkit.AccountingToolkit
    kwargs:
      models_dir: /path/to/models
      snapshot_provider: myapp.accounting_provider
      database_toolkit: myapp.database_toolkit
      frame_provider: myapp.frame_provider
      engine: myapp.duckdb_engine
      policy_guard: myapp.dataset_guard
      signer: myapp.signer
      audit_storage: myapp.audit_storage
      audit_mode: required
      default_tenant: troc
      duckdb_threads: 4
      result_limit: 10000
    env: {}
```

The host must supply the factory; missing configuration fails closed.

### CLI

```bash
# Validate a model
parrot finance validate troc_pnl.yaml --snapshot /path/to/manifest.yaml

# Explain a metric
parrot finance explain troc_pnl.yaml gross_margin --snapshot /path/to/manifest.yaml

# Live validation (requires --journal-arrow for dataframe sources)
parrot finance validate troc_pnl.yaml --live --snapshot /path/to/manifest.yaml --journal-arrow /path/to/journal.arrow
```

### Host scheduler wiring

The host registers the daily validation job on its scheduler:

```python
from parrot.scheduler.base import SchedulerManager
from parrot.scheduler.accounting_jobs import register_accounting_schedules

scheduler: SchedulerManager = app["scheduler_manager"]
toolkit_factory: Callable[[], AccountingToolkit] = lambda: my_toolkit

register_accounting_schedules(scheduler, toolkit_factory)
```

The factory must return the same toolkit instance that serves queries, so its catalog flags persist.

### Required snapshot provider/manifests

Models require exactly one of `snapshot_provider` or `snapshot_manifests` at construction:

- `snapshot_provider(tenant, model, spec)` is an async callable returning `ChartSnapshot`. The host owns the account-master connection/table, column mapping, and credentials.
- `snapshot_manifests` is a YAML-safe nested map `{tenant: {model: manifest_path}}`. It is adapted to the same provider and re-read on refresh.

Missing configuration/keys or provider failure fail closed. A failed refresh never clears previous flags or reports successful validation.

### `FINANCE_*` settings

- `FINANCE_AUDIT_MODE`: `required` (default) or `best_effort`. `parrot finance validate --live` has no audit sink, so it defaults to `best_effort` unless `FINANCE_AUDIT_MODE` is set explicitly. When `required`, a missing or failing audit sink prevents the result from being returned.
- `FINANCE_MODELS_DIR`: root of the `<tenant>/<model>.yaml` specs when `models_dir` is not passed to the toolkit (default `./models`).

The default tenant is not an environment setting: pass `default_tenant=` to `AccountingToolkit` (it is used when neither the tool argument nor the permission context names a tenant).

## Usage Examples

### Query a metric

```python
from parrot.semantic.accounting import AccountingToolkit, MetricRequest

toolkit = AccountingToolkit(
    models_dir=Path("/models"),
    snapshot_provider=my_provider,
    database_toolkit=my_db_toolkit,
    policy_guard=my_guard,
)

request = MetricRequest(
    kind="metric",
    metric="gross_margin",
    grain="month",
    dimensions=["entity", "product_line"],
    filters={"entity": ["TROC"]},
    period={"from": "2025-01-01", "to": "2025-12-31"},
)

result = await toolkit.query_metric(**request.model_dump())
print(result["rows"])
print(result["lineage"])
print(result["sql_hash"])
print(result["audit_id"])
```

### Validate a model

```python
result = await toolkit.validate_model("troc_pnl", live=False)
print(result["problems"])
print(result["assertion_results"])
```

### Rebuild lineage from an audit entry

```python
from parrot.semantic.accounting.audit import rebuild_lineage

entry = await ledger.get(entry_id)
lineage = rebuild_lineage(entry, model)
print(lineage.formula)
print(lineage.sets)
```

## Gotchas

- **Import isolation**: The compile path (`parrot.semantic.accounting`) imports without the governed stack. Do not import `parrot.semantic.toolkit` or `parrot.semantic.governance` when compiling.
- **Exact precision**: Source amounts must fit `DECIMAL(38,6)`. Float inputs require `allow_float=True` and are warned as `float_cast`.
- **Cumulative windows**: A cumulative request that spans a membership change is refused with `PeriodSpansMembershipChange`.
- **Golden files**: Regenerate them only deliberately with `REGENERATE_GOLDENS=1`, review the diff of every changed `.sql`/`.json` file, and commit them together with the compiler change that caused it; a normal test run compares byte-for-byte and never rewrites them.
- **Audit mode**: When `FINANCE_AUDIT_MODE=required`, a missing audit sink fails closed. Use `postgres_audit_storage` to write entries to Postgres.

## Related

- [Semantic layer](../semantic-layer.md) — governed semantic queries and the two governance postures (fail-closed `sl_*` vs. per-metric `finance_*`).
- [DuckDB engine](https://duckdb.org/docs/) — in-process DuckDB over Arrow.
- [Parrot CLI](https://github.com/phenobarbital/ai-parrot/wiki/CLI) — `parrot finance` commands.
