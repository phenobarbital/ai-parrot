# FW-006 — Second surface: `LocalSemanticLayerToolkit` + `parrot mcp-local semantic-layer` (keyword-only ctor)

**Query**: Q003/Q012 · **Type**: wiki_query + source read · **Depth**: 1

## Summary
`parrot.semantic.bootstrap.LocalSemanticLayerToolkit` is the stdio/MCP subclass. Unlike the parent
it has an explicit **keyword-only** signature and *requires* `static_subject`, `agent_id` and a
dotted `guard_factory` string. It builds the `PermissionContext` and `SemanticRequestIdentity` itself
(`channel="mcp-local"`, a fresh `uuid4()` session id) and overrides `_create_tool_from_method` so that
every generated tool binds that identity around the call — tool callers cannot supply or override
credentials. Startup fails closed on a malformed subject, a blank `agent_id`, a missing/invalid
`guard_factory`, or missing navigator-auth evaluator modules. It is wired via
`parrot.cli.__init__`'s `"mcp-local": "parrot.mcp.local_cli"` entry plus a
`.parrot/mcp-toolkits.yaml` block, and the HTTP handler explicitly **refuses** it (FW-007).

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:60-73` —
  `class LocalSemanticLayerToolkit(SemanticLayerToolkit)` with `local_only = True` and
  `def __init__(self, *, static_subject: StaticSubject | dict[str, Any], agent_id: str, guard_factory: str, guard_factory_kwargs: dict[str, Any] | None = None, **kwargs: Any) -> None`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:22-29` —
  `class StaticSubject(BaseModel)`: `user_id: str = Field(min_length=1)`,
  `tenant_id: str = Field(min_length=1)`, `roles: list[str]`,
  `metadata: dict[str, Any] = Field(default_factory=dict)`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:100-113` — builds
  `PermissionContext(session=UserSession(user_id=..., tenant_id=..., roles=frozenset(...), metadata=dict(...)), channel="mcp-local")`
  and `SemanticRequestIdentity(ctx=..., channel="mcp-local", agent_id=agent_id, session_id=str(uuid4()))`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:128-156` —
  `_build_guard(factory_path, rls_registry, factory_kwargs)`; the host factory is called as
  `factory(rls_registry=rls_registry, **factory_kwargs)` and must return a
  `DataPlanePolicyGuard` with a non-`None` `_evaluator`.
- `packages/ai-parrot-semantic/src/parrot/semantic/bootstrap.py:16-20, 117-126` —
  `_EVALUATOR_MODULES = ("navigator_auth.abac.policies.environment", "navigator_auth.abac.policies.evaluator")`;
  missing → `SemanticPolicyError("pbac_unavailable")`.
- `packages/ai-parrot/src/parrot/cli/__init__.py:116` — `"mcp-local": "parrot.mcp.local_cli"`.
  The module exists at `packages/ai-parrot/src/parrot/mcp/local_cli.py`.
- wiki page `file:docs/tools/semantic-layer.md` — the exact `.parrot/mcp-toolkits.yaml` block
  (`class: parrot.semantic.bootstrap.LocalSemanticLayerToolkit`, kwargs `models_dir`, `dialect`,
  `agent_id`, `static_subject`, `guard_factory`, `guard_factory_kwargs`) and the matching
  `.mcp.json` entry `{"command": "parrot", "args": ["mcp-local", "semantic-layer"]}`.
- wiki stub `sym:packages/ai-parrot-semantic/tests/test_mcp_local.py#test_documented_yaml_and_json_parse`
  (score=0.99) — the docs blocks are contract-tested, so an example must not diverge from them.

## Notes
`packages/ai-parrot-semantic/tests/test_mcp_local.py` asserts the *documented* fenced blocks parse
and start the real factory. If a new example ships its own YAML it should not be mistaken for the
documented one.
