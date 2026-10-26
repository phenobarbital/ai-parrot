# Semantic Agent example

Run `python examples/semantic/agent_semantic_example.py` with the DuckDB extra. The scripted mode requires no LLM call or network access.

The example creates a deterministic DuckDB warehouse and a governed model with an explicit fixture policy: an `analyst` may use only `revenue`, `region`, and `sales.orders.region`. It binds a trusted `SemanticRequestIdentity` around each call, publishes a result through `SemanticLayerToolkit`, then reads it only through a per-owner `GuardedDatasetFacade`.

The facade owns a private `DatasetManager`, but never attaches `DatasetManager.get_tools()` to the Agent. Its list, metadata, query, cache, derived, and export paths call the current read authorizer. A second user/session is denied, and a revoked, expired, or policy-stale handle is withheld by the semantic hand-off callback.

Smoke test the example contract with:

```bash
pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q
```

For production, replace `_FixtureGuard` with the application `DataPlanePolicyGuard` and a real PBAC evaluator; do not enable the example's local fixture switch. Bind `PermissionContext` and `SemanticRequestIdentity` at the HTTP/MCP/Agent boundary, create facades through a per-owner host factory, and send semantic audit records to durable storage. Never attach raw DatasetManager tools after a semantic hand-off.
