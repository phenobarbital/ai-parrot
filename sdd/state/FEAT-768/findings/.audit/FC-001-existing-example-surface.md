# FC-001 — The existing example already owns the "guarded hand-off" story; a second example must pick a different surface

**Query**: Q006 · **Type**: read · **Depth**: 0

## Summary
`examples/semantic/agent_semantic_example.py` (362 lines) is a *scripted, no-LLM* demo whose single
narrative is the **FEAT-704 guarded dataset hand-off**: build a temp DuckDB warehouse, write a
one-model `orders.yml` + `orders.policy.yaml` at runtime, wire a real `DataPlanePolicyGuard` with a
local allow-list `ExamplePolicyEvaluator`, bind a `SemanticRequestIdentity`, run ONE
`query_metrics` call, publish via `save_result_as_dataset`, then read back only through a per-owner
`GuardedDatasetFacade` and prove a second session is denied. The `Agent` is *constructed but never
asked* (`build_agent()` is called in `run_demo()` and its return value is discarded, line 335) —
so there is currently **no example of an LLM actually driving the `sl_*` tools**.
Surfaces it does NOT touch: `sl_list_models`, `sl_get_dimensions`, `sl_get_dimension_values`,
`sl_search_data_model`, `sl_list_saved_queries`, `sl_compile_query`, `sl_run_sql`; column **masking**
(`policy.masks`), **saved_queries**, multi-model **relationships/joins**, time grains, the
**OSSIE** import format, the Postgres **audit sink**, and the **MCP-local / HTTP handler** surfaces.
A second example should take one of those, not re-stage the hand-off.
It uses `print`-free logging (`LOGGER = logging.getLogger(__name__)`), restores `os.environ` via a
`connection_env()` context manager, and keeps everything inside `tempfile.TemporaryDirectory`.

## Citations
- `examples/semantic/agent_semantic_example.py:16-25` — the exact import surface the example relies on: `parrot.auth` (`DataPlanePolicyGuard`, `PermissionContext`, `RlsRegistry`, `UserSession`), `parrot.bots.Agent`, `parrot.semantic.context` (`SemanticRequestIdentity`, `bind_semantic_context`, `require_identity`), `parrot.semantic.errors.SemanticResultError`, `parrot.semantic.handoff` (`GovernedDatasetSink`, `ReadAuthorizer`, `handle_owner`), `parrot.semantic.models.SemanticQuery`, `parrot.semantic.results.ResultHandle`, `parrot.semantic.toolkit.SemanticLayerToolkit`, `parrot.tools.dataset_manager.DatasetManager`, `parrot.tools.toolkit.AbstractToolkit`
- `examples/semantic/agent_semantic_example.py:29-32` — `CONNECTION_ENV = "PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE"`, `_ALLOWED_DRIVER/_ALLOWED_TABLE/_ALLOWED_ROLE` — the env-var naming convention `PARROT_SEMANTIC_CONN_<CONNECTION>_DATABASE` derived from `connection: semantic_example` in the policy
- `examples/semantic/agent_semantic_example.py:35-126` — `GuardedDatasetFacade(AbstractToolkit)` — `tool_prefix = "guarded_dataset"`, `exclude_tools = ("publish",)`, `guarded_reads = True`; six async routes all funnelling through `_read()` which calls `require_identity()` + a per-result `ReadAuthorizer`
- `examples/semantic/agent_semantic_example.py:139-184` — `ExamplePolicyEvaluator` + `build_guard(evaluator, rls_registry) -> DataPlanePolicyGuard` — the local PBAC stand-in (`check_access` / `filter_resources` returning `SimpleNamespace(allowed=...)`)
- `examples/semantic/agent_semantic_example.py:187-218` — `_OwnerFacadeFactory.__call__(identity) -> GovernedDatasetSink` and `_FacadeSink` — the `dataset_manager_factory` contract (a toolkit may NOT itself be the sink)
- `examples/semantic/agent_semantic_example.py:221-264` — `build_warehouse(directory)` / `build_models_dir(directory)` — the YAML is written inline by the example, not read from a fixture dir
- `examples/semantic/agent_semantic_example.py:285-325` — `build_toolkits(directory, evaluator=None)`, `build_agent(toolkits)`, `_example_identity(user_id, session_id, program)` — the three entry points the pinning test imports
- `examples/semantic/agent_semantic_example.py:314-317` — `build_agent` constructs `Agent(name="semantic-example", llm="google", tools=[*semantic.get_tools(), *facade.get_tools()])`
- `examples/semantic/agent_semantic_example.py:328-362` — `run_demo(directory)` + `main()` + `if __name__ == "__main__": logging.basicConfig(...); asyncio.run(main())`
- `examples/semantic/README.md:1-16` — the README narrative (production-wiring paragraph at line 15 is the piece most worth preserving/extending)

## Notes
- The example is docstring-complete, fully type-hinted, Google-style — it is held to the same bar as
  library code, not "illustrative snippet" quality. New examples will be judged the same way.
- `build_agent`'s hard-coded `llm="google"` means a *conversational* second example would need real
  credentials; the house pattern for that is an explicit `--smoke` / scripted mode (see FC-005).
