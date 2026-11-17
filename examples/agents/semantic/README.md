# Governed Semantic Layer — example agents

Five runnable examples over one committed model fixture. Every example runs offline with
`--smoke`: no LLM call, no network, and nothing written outside a temporary directory.

| Example | What it proves |
|---|---|
| `agent_semantic_example.py` | The guarded dataset hand-off: a result is published and read only through a per-owner facade. |
| `llm_metrics_agent.py` | An LLM really drives the `sl_*` tools through `ask(permission_context=...)`; omitting either binding fails closed. |
| `mcp_local_agent.py` | The MCP-local path executes a real allow AND a real deny through `create_toolkit_mcp_server`. |
| `masked_policy_agent.py` | `masks:` redacts a projected column for roles that are not exempt, and `saved_queries:` runs a reviewed query by name. |
| `governed_joins_agent.py` | Time grains work; a governed cross-model query is DENIED; the same join compiles only under an explicitly ungoverned model. |

## Fixtures

The `models/` directory holds the governed model and its policy file. The
`models_ungoverned/` directory holds an identical model with `governed: false`.
Two named connections are configured: `warehouse` (governed) and `warehouse_ungoverned`
(ungoverned). Each model requires its own policy side-file; the second connection
demonstrates per-model isolation, not a cross-connection refusal.

## Run them

```bash
# Run each example with --smoke for offline deterministic mode
python examples/agents/semantic/agent_semantic_example.py --smoke
python examples/agents/semantic/llm_metrics_agent.py --smoke
python examples/agents/semantic/mcp_local_agent.py --smoke
python examples/agents/semantic/masked_policy_agent.py --smoke
python examples/agents/semantic/governed_joins_agent.py --smoke

# Pin tests keep each example honest
pytest packages/ai-parrot-semantic/tests/test_example_agent.py -q
pytest packages/ai-parrot-semantic/tests/test_llm_metrics_agent.py -q
pytest packages/ai-parrot-semantic/tests/test_mcp_local_agent.py -q
pytest packages/ai-parrot-semantic/tests/test_masked_policy_agent.py -q
pytest packages/ai-parrot-semantic/tests/test_governed_joins_agent.py -q
```

For production, replace `ExamplePolicyEvaluator` with the navigator-auth `PolicyEvaluator` loaded from your PBAC policies, and configure connections through the host environment. Bind `PermissionContext` and `SemanticRequestIdentity` at the HTTP/MCP/Agent boundary, create facades through a per-owner host factory, and send semantic audit records to durable storage. Never attach raw DatasetManager tools after a semantic hand-off.