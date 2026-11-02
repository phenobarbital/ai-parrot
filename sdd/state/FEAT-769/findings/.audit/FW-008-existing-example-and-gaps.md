# FW-008 — The existing example is scripted-only (no LLM turn); `examples/agents/semantic/` does not exist yet

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
