# FW-007 — Third surface: `SemanticLayerHandler` at `/api/v1/agents/semantic/{agent_id}[/{tail}]`

**Query**: Q012 · **Type**: wiki_query + source read · **Depth**: 2

## Summary
`ai-parrot-server` exposes the semantic layer over aiohttp through `SemanticLayerHandler`
(a navigator `BaseView` decorated `@is_authenticated()` / `@user_session()`). Routes are registered
only when `importlib.util.find_spec("parrot.semantic")` succeeds. `GET` returns `list_models()`;
`POST` dispatches on the `{tail}` match-info: `compile`, `query`, and
`results/{result_id}/dataset`. The handler builds `PermissionContext` and
`SemanticRequestIdentity` from the **server-side navigator session only** (channel `"http"`), and
strips `agent_id`, `session_id`, `identity`, `context`, `_permission_context`, `pctx` from the
client payload before validating it as a `SemanticQuery`. It resolves the toolkit from the bot's
`tool_manager.find_registered_toolkit(SemanticLayerToolkit)` and **refuses**
`LocalSemanticLayerToolkit` with `SemanticAccessError("local_toolkit_rejected")`. So an agent that
wants the HTTP surface must register an ordinary `SemanticLayerToolkit` on its `tool_manager`.

## Citations
- `packages/ai-parrot-server/src/parrot/manager/manager.py:2585-2589` —
  `if importlib.util.find_spec("parrot.semantic") is not None:` →
  `router.add_view("/api/v1/agents/semantic/{agent_id}", SemanticLayerHandler)` and
  `router.add_view("/api/v1/agents/semantic/{agent_id}/{tail:.*}", SemanticLayerHandler)`.
- `packages/ai-parrot-server/src/parrot/handlers/semantic.py:15-18` —
  `@is_authenticated()` `@user_session()` `class SemanticLayerHandler(BaseView)`.
- `packages/ai-parrot-server/src/parrot/handlers/semantic.py:68-99` —
  `async def _dispatch(self, toolkit, context: PermissionContext, identity, body: dict[str, Any]) -> dict`;
  the stripped field list; `tail == "compile"` → `compile_query`; `tail == "query"` →
  `query_metrics(...).model_dump(mode="json")`; `results/<id>/dataset` →
  `save_result_as_dataset(result_id, name, description)`.
- `packages/ai-parrot-server/src/parrot/handlers/semantic.py:100-119` — `_toolkit(agent_id)`:
  needs `request.app["bot_manager"]`, `manager.get_bot(agent_id, request=...)`, the bot must have
  `tool_manager`, and `find_registered_toolkit(LocalSemanticLayerToolkit)` must be `None`.
- `packages/ai-parrot-server/src/parrot/handlers/semantic.py:121-152` — `_pctx()` builds
  `PermissionContext(session=UserSession(str(user_id), str(tenant_id), frozenset(roles), dict(metadata)), channel="http")`.
- `packages/ai-parrot-server/src/parrot/handlers/semantic.py:154-166` — `_identity()` builds
  `SemanticRequestIdentity(ctx=context, channel="http", agent_id=agent_id, session_id=session_id)`.
- wiki result `file:sdd/tasks/completed/TASK-4480-semantic-http-handler.md` — the originating task
  (M11a, "Authenticated HTTP routes and guarded hand-off wiring").

## Notes
A second example that demonstrates the server surface would be a *bot definition* registered with
`BotManager` plus curl/aiohttp client calls — not a standalone script — because identity comes from
the navigator session. [cross-lane: type=code_read, intent=confirm how examples register a bot with
`BotManager` (`examples/agents/webapp_api.py` looks like the closest precedent)]
