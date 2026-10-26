# Semantic Agent example

Run `python examples/semantic/agent_semantic_example.py` with the DuckDB extra. The scripted mode requires no LLM call or network access.

The example creates a deterministic DuckDB warehouse and a governed model in a temporary directory that is removed afterwards; nothing is written under the current directory. PBAC is enforced through the core `DataPlanePolicyGuard` with an explicit `ExamplePolicyEvaluator`: only an `analyst` may connect to DuckDB and read `sales.orders`, and the model policy grants only `revenue`, `region`, and `sales.orders.region`. No gate is forced open. The warehouse connection is exposed through `connection_env()`, which restores the environment on exit. It binds a trusted `SemanticRequestIdentity` around each call, publishes a result through `SemanticLayerToolkit`, then reads it only through a per-owner `GuardedDatasetFacade`.

The facade owns a private `DatasetManager`, but never attaches `DatasetManager.get_tools()` to the Agent. Its list, metadata, query, cache, derived, and export paths call the current read authorizer. Each published result keeps its own read authorizer, and the facade rejects any identity that is not its owner before calling it. A second user/session is denied (the demo raises if it is not), and a PBAC-revoked, expired, or policy-stale handle is withheld by the semantic hand-off callback.

Smoke test the example contract with:

```bash
pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q
```

For production, replace `ExamplePolicyEvaluator` with the navigator-auth `PolicyEvaluator` loaded from your PBAC policies, and configure connections through the host environment. Bind `PermissionContext` and `SemanticRequestIdentity` at the HTTP/MCP/Agent boundary, create facades through a per-owner host factory, and send semantic audit records to durable storage. Never attach raw DatasetManager tools after a semantic hand-off.
