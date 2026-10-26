# Governed semantic layer

## Installation and clean-room format

Install the optional `ai-parrot-semantic` distribution and use its native,
`sqlglot`-based compiler. It has no third-party semantic-engine dependency or
adapter: the model format is clean-room work informed only by public format
documentation. Model files declare a physical schema, dimensions, metrics, and
relationships; an adjacent `<model>.policy.yaml` supplies governance.

```yaml
# orders.yml
name: orders
connection: warehouse
tables: {orders: sales.orders}
dimensions:
  - {name: region, sql: orders.region}
  - {name: ordered_at, sql: orders.order_date, kind: time_dimension}
metrics:
  - {name: revenue, sql: orders.amount, aggregate: sum}
  - {name: orders, sql: orders.id, aggregate: count_distinct}
relationships:
  - {from_model: customers, to_model: orders,
     primary_key: [id, tenant_id], foreign_key: [customer_id, tenant_id]}
```

Aggregates accept declared input columns and can be filtered; derived metrics
may reference declared metrics. Joins require paired keys from the one side to
the many side. The supported time grains are `second`, `minute`, `hour`, `day`,
`week`, `month`, `quarter`, and `year`. The compiler rejects ambiguous or
fan-out-prone paths rather than applying symmetric aggregates. It emits native
SQL for DuckDB, Postgres, and BigQuery; compilation is CPU work and runs off
the event loop.

## Authorization and identity

Models are governed by default. A governed model requires both a trusted
`PermissionContext` and an available PBAC evaluator; missing context,
evaluator, manifest authorization, lineage, or RLS validation denies the
request. Only a policy with `governed: false` opts out explicitly.

```yaml
# orders.policy.yaml
governed: true
connection: warehouse
roles:
  analyst: {metrics: [revenue, orders], dimensions: [region, ordered_at], usage: []}
rls:
  - {driver: duckdb, table: sales.orders,
     predicate_template: "tenant_id = '{{ tenant_id }}'", subject_attribute: tenant_id}
```

The HTTP and agent surfaces receive a host-authenticated context. The local MCP
surface is different: it accepts only a host-configured `static_subject`,
`agent_id`, and `guard_factory`. Tool callers cannot supply credentials or
override this identity. Each local instance uses a fresh session id and the
fixed `mcp-local` channel; every call is logged and audited. Invalid factories,
missing evaluator modules, malformed subjects, and policy-load errors fail
startup closed.

## Tools and audit

`SemanticLayerToolkit` exposes these `sl_*` tools (the prefix is added by the
toolkit):

| Tool | Signature |
| --- | --- |
| `sl_list_models` | `list_models()` |
| `sl_list_metrics` | `list_metrics(model: str)` |
| `sl_get_dimensions` | `get_dimensions(model: str, metrics: list[str] | None = None)` |
| `sl_get_dimension_values` | `get_dimension_values(model: str, dimension: str, metrics: list[str] | None = None, limit: int = 50)` |
| `sl_search_data_model` | `search_data_model(text: str, model: str | None = None)` |
| `sl_list_saved_queries` | `list_saved_queries(model: str)` |
| `sl_compile_query` | `compile_query(query: SemanticQuery)` |
| `sl_query_metrics` | `query_metrics(query: SemanticQuery)` |
| `sl_run_sql` | `run_sql(model: str, sql: str)` — host opt-in only |
| `sl_save_result_as_dataset` | `save_result_as_dataset(result_id: str, name: str, description: str | None = None)` |

Saved queries are policy-owned and receive the same governance as an explicit
query. Raw SQL is absent unless the trusted constructor setting
`allow_raw_sql: true` enables it; it still uses model-manifest authorization,
lineage, RLS, limits, and audit. The audit ledger signs each entry and records
the structured query, subject digest, model/policy digests, native engine,
compiled and governed SQL, exact member provenance (including dependencies),
dialect, row count, duration, PBAC decision, and outcome.

The default `audit_required: null` resolves to whether a durable audit sink is
configured. A required missing or failed sink fails the operation. Use
`postgres_audit_storage(dsn_or_pool, table="semantic_audit_events")` to write
the signed payload to Postgres; the target table is
`parrot/semantic/sql/semantic_audit_events.sql`.

## Guarded dataset hand-off

Result retention is disabled as a public capability until a host supplies a
conforming `GovernedDatasetSink`. Handles are opaque, bounded by TTL, and bound
to agent, user, tenant, session, model/policy versions, and subject digest.
`sl_save_result_as_dataset` rechecks ownership, expiry, current policy, and
PBAC before publishing. Every downstream read invokes the registered read
authorizer, so policy changes and revocation take effect immediately.

A bare `DatasetManager`, dataframe, or plain manager factory is rejected. The
host adapter must declare guarded reads, immutable owner scope, async publish,
and pass the sink conformance tests; without it the hand-off tool is not
exposed.

## MCP-local configuration

Operator configuration is intentionally local. Copy this section into the
operator's ignored `.parrot/mcp-toolkits.yaml`; substitute only host-owned
paths and factory names, and do not commit private settings or secrets.

```yaml
toolkits:
  semantic-layer:
    class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit
    kwargs:
      models_dir: /path/to/models
      dialect: duckdb
      agent_id: local-semantic
      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}
      guard_factory: myapp.semantic_auth.build_guard
      guard_factory_kwargs: {policy_dir: /path/to/policies}
    env: {}
# Host must supply the factory; missing configuration fails closed.
```

Add the matching operator-local `.mcp.json` entry:

```json
{
  "mcpServers": {
    "parrot-semantic-layer": {
      "command": "parrot",
      "args": ["mcp-local", "semantic-layer"]
    }
  }
}
```

For a deterministic local check, write those blocks to a temporary directory,
replace the placeholder model and policy paths with fixture paths, and run:

```bash
parrot mcp-local semantic-layer --config /tmp/semantic-mcp/toolkits.yaml
```

Exercise both an explicit allow and an explicit deny policy against the real
server factory. Parsing or listing configuration alone is not evidence that
the configured PBAC guard binds the static identity around tool execution.
