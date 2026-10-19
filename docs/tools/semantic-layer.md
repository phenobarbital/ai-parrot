# Semantic Layer (`ai-parrot-semantic`)

Governed metric queries for agents: sidemantic compiles, while AI-Parrot applies PBAC, RLS push-down,
column lineage, masking, a positive SQL guard, and signed audit records. This integration is part of FEAT-704.

## Install

Add the satellite package with the extra for the warehouse you use:

```bash
uv add 'ai-parrot-semantic[duckdb]'
# or
uv add 'ai-parrot-semantic[bigquery]'
```

Postgres support uses the database dependencies already provided by `ai-parrot`.

## Tools (`sl_*`)

| Tool | Purpose |
|---|---|
| `sl_list_models` | List models visible to the current subject. |
| `sl_list_metrics` | List the metrics the subject may use in one model. |
| `sl_get_dimensions` | List permitted dimensions, optionally constrained by metrics. |
| `sl_get_dimension_values` | Query governed values for a dimension. |
| `sl_search_data_model` | Search the role-filtered model catalog. |
| `sl_list_saved_queries` | List reviewed saved queries visible to the subject. |
| `sl_compile_query` | Compile and govern a semantic query without executing it. |
| `sl_query_metrics` | Compile, govern, execute, and audit a metric query. |
| `sl_run_sql` | Run raw SQL through the same governance pipeline. Exposed only with `allow_raw_sql: true`. |
| `sl_save_result_as_dataset` | Save an owned, unexpired result handle. Exposed only when a subject-scoped `dataset_manager_factory` is configured. |

Catalog operations are governed too: a governed model does not reveal member names until its subject and physical
resources have been authorized. Raw SQL is disabled by default, and result hand-off is unavailable by default.

## Models directory and `<model>.policy.yaml`

Set `models_dir` to a directory containing semantic model documents and a sidecar policy for each model. Models are
governed by default; `governed: false` is an explicit opt-out from PBAC, RLS, and role checks.

```yaml
governed: true
engine: sidemantic              # or: native
connection: warehouse_pg        # resolved from host configuration/environment
limits: {default: 1000, max: 10000}
roles:
  analyst:
    metrics: [revenue, orders]
    dimensions: [region, order_month]
    usage: [region]
  admin: {metrics: "*", dimensions: "*", usage: "*"}
masks:
  customers.email:
    strategy: hash
    projection_roles: [analyst]
    usage_roles: []
rls:
  - driver: pg
    table: sales.orders
    predicate_template: "region IN (:subject.programs)"
    subject_attribute: programs
saved_queries:
  - name: monthly_revenue
    verified_by: jesus@example.com
    verified_at: 2026-10-19
    query:
      model: orders
      metrics: [revenue]
      time_dimensions: [{name: order_date, grain: month}]
allowed_functions: [STDDEV]
```

Role grants are unions across the subject's roles. `usage` controls whether a **restricted** column may participate in
a filter, join, group, order, window or derived expression, independently of projection rights. A column is restricted
when it is masked (`masks:`) or backs a member declared `sensitive: true`; masked columns are governed by the mask's
`usage_roles`. Unrestricted columns — for example the `amount` behind a granted `revenue` metric — need no usage grant.
Unknown members, tables, or unsafe RLS expressions reject the policy.

`allowed_functions` is additive. The effective allowlist is
`DEFAULT_ALLOWED_FUNCTIONS ∪ toolkit allowed_functions ∪ policy allowed_functions`; a model can add a function but
cannot remove a default. DDL, DML, commands, and non-`SELECT` statements remain denied regardless of this setting.

## Audit

Every operation creates a signed `SemanticAuditEntry`. It records the entry schema/version and timestamp; user,
tenant, channel, agent, roles, subject digest, and whether a static subject was used; model and policy digests; engine
and tool; the structured query or raw-SQL flag; compiled and governed SQL; dialect and driver; applied RLS and masks;
PBAC decision; outcome and error code; row count and duration; and the signature.

The default ledger is bounded in-memory storage. `audit_required` is resolved when the toolkit is constructed:

- `None` becomes `True` when `audit_storage` is configured and `False` for the in-memory ledger.
- An explicit `True` or `False` always wins.
- When it is `True`, a sink failure raises `audit_unavailable` and the governed result is withheld. Set
  `audit_required: false` only as an explicit operational opt-out from that fail-closed behavior.

For the Postgres sink, apply the packaged DDL at `parrot/semantic/sql/semantic_audit_events.sql`, then pass the async
callable returned by `postgres_audit_storage` as `audit_storage`:

```python
from parrot.semantic.audit import postgres_audit_storage

audit_storage = postgres_audit_storage(
    "postgresql://audit-writer@db.example/observability",
    table="semantic_audit_events",
)
```

The DSN is illustrative; obtain it from the host's secret/configuration system rather than committing it.

## HTTP API

When `ai-parrot-server` and the semantic satellite are installed, the aiohttp surface is rooted at
`/api/v1/agents/semantic/{agent_id}`. `GET` returns the subject-filtered catalog. The tail routes accept `POST` requests
for `compile`, `query`, and `results/{result_id}/dataset`. The server derives `PermissionContext` from the authenticated
navigator session; clients cannot submit their own identity or warehouse credentials in a semantic query.

## `parrot mcp-local semantic-layer`

Both files below are operator-local and git-ignored. Copy the following section into `.parrot/mcp-toolkits.yaml` and
replace the models path:

```yaml
toolkits:
  semantic-layer:
    class: parrot.semantic.toolkit.SemanticLayerToolkit
    kwargs:
      models_dir: /path/to/models
      dialect: duckdb
      static_subject: {user_id: operator, tenant_id: local, roles: [admin]}
    env: {}
```

Then add this server to the existing `mcpServers` object in `.mcp.json`:

```json
{
  "mcpServers": {
    "parrot-semantic-layer": {
      "command": "parrot",
      "args": ["mcp-local", "semantic-layer"],
      "env": {}
    }
  }
}
```

`static_subject` is one fixed operator identity for the entire local MCP process. Its use is logged on every call and
every audit entry is flagged with `static_subject: true`; do not use it as a multi-user identity boundary. See
[Expose Toolkits as Local MCP](../mcp-local-toolkits.md) for configuration, filtering, and credential guidance.

## License notice

The `ai-parrot-semantic` package is MIT-licensed, but sidemantic is AGPL-3.0. Its network clause applies when the
semantic layer is offered over a hosted API, MCP server, or another remote interface: operators must provide the
corresponding sidemantic source, including their modifications, to those users. Sign-off: Jesus Lara, 2026-10-19.
