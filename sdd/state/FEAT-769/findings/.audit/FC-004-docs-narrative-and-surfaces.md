# FC-004 — `docs/tools/semantic-layer.md` is the canonical narrative: four surfaces, ten `sl_*` tools, and an MCP-local config block that is doc-tested

**Query**: Q009 · **Type**: read · **Depth**: 0

## Summary
The doc (157 lines) is organised as: clean-room model format → authorization/identity → tools+audit →
guarded hand-off → MCP-local configuration. It enumerates **ten** `sl_*` tools with signatures, and
it states the three delivery surfaces explicitly: **HTTP and agent surfaces receive a
host-authenticated context**, while the **local MCP surface** accepts only a host-configured
`static_subject` + `agent_id` + `guard_factory` and never lets a tool caller supply credentials.
The existing example covers only the agent surface and only two of the ten tools, so the doc itself
maps the gap a second example could fill: catalog/discovery tools, `compile_query`, `run_sql` (behind
`allow_raw_sql: true`), saved queries, the Postgres audit sink
(`postgres_audit_storage(dsn_or_pool, table="semantic_audit_events")`), and the
`parrot mcp-local semantic-layer` entrypoint. The doc's final paragraph warns that parsing or
listing configuration is *not* evidence the guard binds identity around execution — i.e. any
MCP-local example must actually execute an allow and a deny.

## Citations
- `docs/tools/semantic-layer.md:60-66` — the three surfaces: HTTP/agent get host-authenticated context; mcp-local uses `static_subject` + `agent_id` + `guard_factory`, fresh session id, fixed `mcp-local` channel, fails startup closed
- `docs/tools/semantic-layer.md:70-84` — the ten-tool table (`sl_list_models`, `sl_list_metrics`, `sl_get_dimensions`, `sl_get_dimension_values`, `sl_search_data_model`, `sl_list_saved_queries`, `sl_compile_query`, `sl_query_metrics`, `sl_run_sql` host-opt-in, `sl_save_result_as_dataset`)
- `docs/tools/semantic-layer.md:86-98` — audit ledger contents; `audit_required: null` resolves to "is a durable sink configured"; `postgres_audit_storage(...)` and `parrot/semantic/sql/semantic_audit_events.sql`
- `docs/tools/semantic-layer.md:100-112` — guarded hand-off contract: handles opaque/TTL-bounded/owner-bound; a bare `DatasetManager`, dataframe or plain factory is rejected; without a conforming sink the hand-off tool is **not exposed**
- `docs/tools/semantic-layer.md:114-146` — the MCP-local `.parrot/mcp-toolkits.yaml` block (`class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit`) and the matching `.mcp.json` `parrot mcp-local semantic-layer` entry
- `docs/tools/semantic-layer.md:148-157` — "Exercise both an explicit allow and an explicit deny policy against the real server factory"
- `docs/tools/semantic-layer.md:33-39` — compiler constraints: rejects ambiguous/fan-out-prone joins, grains `second`…`year`, emits DuckDB/Postgres/BigQuery, compilation runs off the event loop

## Notes
- Ledger issue `issue:d01c24f18770` (closed) made `packages/ai-parrot-semantic/tests/test_mcp_local.py`
  **parse the YAML/JSON blocks out of this doc**. So the doc's code blocks are load-bearing: a new
  example that changes the documented model format would break that test.
- `[cross-lane: type=docs, intent=decide whether the new examples get a section in docs/tools/semantic-layer.md or only an examples/agents/semantic/README.md]`
