# F001 — Existing example: what it already demonstrates, its exact helper API, and the surfaces it leaves untouched

**Merged from**: FC-001, FW-008

<!-- merged from FC-001 -->
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

---

<!-- merged from FW-008 -->
**Query**: Q001 follow-up · **Type**: wiki_query + source read · **Depth**: 1

## Summary
`examples/semantic/agent_semantic_example.py` (≈370 lines) is the only semantic example. It builds a
temp-dir DuckDB warehouse, writes the `orders.yml` / `orders.policy.yaml` fixtures, wires a real
`DataPlanePolicyGuard` around a hand-written `ExamplePolicyEvaluator`, constructs the toolkit, builds
an `Agent` — and then **never calls the LLM**: `run_demo()` drives `query_metrics` /
`save_result_as_dataset` directly inside `bind_semantic_context`. `build_agent` exists only so the
test can assert the tool names. `examples/agents/` currently has subdirectories `a2ui/`, `aws/`,
`finance/`, `oauth/`, `webbrowser/` and loose scripts — **there is no `semantic/` subdirectory**,
so the requested path is new. `examples/agents/a2ui/README.md` is the precedent for a per-directory
README. The example is contract-tested by `packages/ai-parrot-semantic/tests/test_example_agent.py`,
which loads it by file path via `importlib.util.spec_from_file_location` — new examples would need
their own test or none.

## Citations
- `examples/semantic/agent_semantic_example.py:1-28` — imports; note the *submodule* import paths
  actually used: `from parrot.semantic.context import SemanticRequestIdentity, bind_semantic_context, require_identity`,
  `from parrot.semantic.handoff import GovernedDatasetSink, ReadAuthorizer, handle_owner`,
  `from parrot.semantic.models import SemanticQuery`, `from parrot.semantic.results import ResultHandle`,
  `from parrot.semantic.toolkit import SemanticLayerToolkit`.
- `examples/semantic/agent_semantic_example.py:30-33` —
  `CONNECTION_ENV = "PARROT_SEMANTIC_CONN_SEMANTIC_EXAMPLE_DATABASE"` (matches FW-003's prefix rule
  for `connection: semantic_example`).
- `examples/semantic/agent_semantic_example.py` — verified helper signatures:
  `def build_warehouse(directory: Path) -> Path`;
  `def build_models_dir(directory: Path) -> Path`;
  `@contextmanager def connection_env(directory: Path) -> Iterator[None]`;
  `def build_toolkits(directory: Path, evaluator: ExamplePolicyEvaluator | None = None) -> tuple[SemanticLayerToolkit, GuardedDatasetFacade]`;
  `def build_agent(toolkits: tuple[SemanticLayerToolkit, GuardedDatasetFacade]) -> Agent`;
  `def _example_identity(user_id: str, session_id: str, program: str) -> SemanticRequestIdentity`;
  `async def run_demo(directory: Path) -> None`; `async def main() -> None`.
- `examples/semantic/agent_semantic_example.py` — the toolkit construction actually used:
  `SemanticLayerToolkit(models_dir=models_dir, dialect="duckdb", dataplane_guard=build_guard(...), rls_registry=rls_registry, dataset_manager_factory=factory)`
  — i.e. **no** `allow_raw_sql`, so `sl_run_sql` is absent from that agent.
- `examples/semantic/agent_semantic_example.py` — the agent:
  `Agent(name="semantic-example", llm="google", tools=[*semantic.get_tools(), *facade.get_tools()])`.
- `examples/semantic/agent_semantic_example.py` — identity:
  `PermissionContext(session=UserSession(user_id, "example-tenant", frozenset({"analyst"}), {"programs": [program]}))`
  then `SemanticRequestIdentity(ctx=context, channel="agent", agent_id="semantic-example", session_id=session_id)`.
  Note `UserSession` is constructed **positionally** here (`user_id, tenant_id, roles, metadata`),
  whereas bootstrap.py uses keywords — both work.
- `packages/ai-parrot-semantic/tests/test_example_agent.py:21-23, 60-74` — loads the example by
  absolute path and asserts `sl_query_metrics`, `sl_save_result_as_dataset`,
  `guarded_dataset_query_dataset` are registered and `guarded_dataset_publish` / `dataset_*` are not.
- `examples/semantic/README.md` — the existing README's shape and the "For production, replace
  `ExamplePolicyEvaluator` with the navigator-auth `PolicyEvaluator`" guidance.
- `ls examples/agents` — subdirs `a2ui`, `aws`, `finance`, `oauth`, `webbrowser`; no `semantic`.

## Notes
The clearest gap a new pair of examples can fill: (a) a genuine **LLM-driven** agent turn —
`async with bind_semantic_context(ctx, identity=identity): await agent.ask(question, permission_context=ctx)`
(see FW-002 for why both are required), which no example demonstrates today; and (b) a second,
*different* surface — `parrot mcp-local semantic-layer` (FW-006) or the HTTP handler (FW-007).
I did **not** verify `Agent.__init__`'s full signature — only the call form used by the existing
example (`name=`, `llm=`, `tools=`). Treat any other Agent kwarg as unverified.
