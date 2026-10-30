# ai-parrot-semantic

MIT satellite: native sqlglot compilation and ai-parrot governance.
Install: `uv pip install 'ai-parrot-semantic[duckdb]'`.

## Layering

Generic semantic queries and the future accounting extension share this namespace.
The accounting extension must remain independently importable.

## Governance

Models are governed by default and require a trusted `PermissionContext` plus an
available PBAC evaluator; a policy may explicitly set `governed: false` for an
ungoverned model. Hosts provide the PBAC factory and may opt in to a guarded,
subject/session-scoped dataset sink. A plain dataset manager is not a valid
sink.

The current native compiler supports declared metrics, dimensions, time grains,
declared one-to-many joins with fan-out rejection, filtered measures, and
derived metrics. The `duckdb` extra provides the local execution backend; the
`bigquery` extra provides BigQuery integration. See
[`docs/tools/semantic-layer.md`](../../docs/tools/semantic-layer.md) for the
user-facing semantic-layer documentation.
