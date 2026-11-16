# ai-parrot-semantic

MIT satellite: native sqlglot compilation and ai-parrot governance.
Install: `uv pip install 'ai-parrot-semantic[duckdb]'`.

## Layering

Generic semantic queries and the accounting extension share this namespace. The accounting compile path (`parrot.semantic.accounting` models, grammar, loader, validation, compiler) imports without the governed stack; its toolkit and runtimes share this package's audit ledger, executor and compile cache.

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
[`wiki/tools/semantic-layer.md`](https://github.com/phenobarbital/ai-parrot/wiki/Tools-%26-Toolkits-Governed-semantic-layer) for the
user-facing semantic-layer documentation.
