# F013 — The governance binding gap: an LLM-driven example needs BOTH bind_semantic_context AND ask(permission_context=)

**Merged from**: FW-002

<!-- merged from FW-002 -->
**Query**: Q004 · **Type**: symbol + source read · **Depth**: 1

## Summary
`bind_semantic_context` is an `@asynccontextmanager` that deep-copies the `PermissionContext` and
sets three ContextVars (the satellite `_semantic_pctx_var`, core `parrot.auth.context._pctx_var`,
and `_identity_var`), restoring all three in `finally`. The toolkit's `_pre_execute` hook is
fail-closed: it compares the `_permission_context` kwarg injected by `ToolkitTool._execute` against
`current_pctx()` and raises `SemanticAccessError("context_required", ...)` when either is `None` or
they differ. That means **an LLM-driven example must do two things**: wrap the turn in
`async with bind_semantic_context(ctx, identity=identity)` *and* pass `permission_context=ctx` to
`Agent.ask(...)`, because the kwarg reaches the tool only via
`AbstractBot.ask(permission_context=...)` → `client._permission_context` →
`ToolManager.execute_tool(permission_context=...)` → `exec_kwargs["_permission_context"]`.
Direct `await toolkit.query_metrics(query)` calls (the scripted style of the existing example)
bypass `_pre_execute` entirely and only need the `bind_semantic_context` scope.

## Citations
- `packages/ai-parrot-semantic/src/parrot/semantic/context.py:86-88` — exact signature:
  `async def bind_semantic_context(ctx: PermissionContext, *, identity: SemanticRequestIdentity | None = None) -> AsyncIterator[None]`,
  decorated `@asynccontextmanager`. Raises `SemanticAccessError("context_required")` if `ctx` is not
  a `PermissionContext`, and `SemanticAccessError("identity_mismatch")` if
  `_trusted_scope(identity.ctx) != _trusted_scope(ctx)`.
- `packages/ai-parrot-semantic/src/parrot/semantic/context.py:18-36` — `class SemanticRequestIdentity(BaseModel, frozen=True)`
  with `model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")` and fields
  `ctx: PermissionContext`, `channel: Literal["http", "agent", "mcp-local"]`,
  `agent_id: str = Field(min_length=1)`, `session_id: str = Field(min_length=1)`.
  A `model_validator(mode="after")` deep-copies `ctx` and rejects blank ids.
- `packages/ai-parrot-semantic/src/parrot/semantic/context.py:44-75` — `current_pctx()`,
  `current_identity()`, `require_identity()` (raises `SemanticResultError("identity_required")`).
- `packages/ai-parrot-semantic/src/parrot/semantic/context.py:79-82` — `_trusted_scope(ctx)` compares
  `(ctx.user_id, ctx.tenant_id, frozenset(ctx.roles), ctx.session.metadata, ctx.extra)`.
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:110-116` —
  `async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None`; raises
  `SemanticAccessError("context_required", "A matching trusted semantic context is required")`.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:170-179` — `ToolkitTool._execute` always sets
  `hook_kwargs["_permission_context"] = getattr(self, "_current_pctx", None)` before `_pre_execute`.
- `packages/ai-parrot/src/parrot/tools/manager.py:2172-2174` —
  `exec_kwargs = dict(parameters)` then `exec_kwargs["_permission_context"] = permission_context`
  only `if permission_context is not None`.
- `packages/ai-parrot/src/parrot/bots/base.py:1069, 1083` — `async def ask(` accepts
  `permission_context: Optional[Any] = None`; `base.py:1439-1440` and `2095-2096` assign
  `client._permission_context = permission_context`.
- `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py:118-121` — `_post_execute` returns
  `result.model_dump(mode="json")` for Pydantic results, so **tool** callers see dicts while direct
  method callers see `SemanticQueryResult`.

## Notes
`parrot/bots/agent.py` has **no** `permission_context` reference; the plumbing lives entirely in
`bots/base.py`. A `UserSession`-derived `PermissionContext` built with `channel="agent"` is what an
example agent should use (`channel` is a `SemanticRequestIdentity` field, see FW-008 for the exact
construction used today).
