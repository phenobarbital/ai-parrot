# A2UI Agent Functions Runtime — the v1.0 RPC leg (FEAT-469)

`parrot.outputs.a2ui.runtime` implements the **RPC leg** of the A2UI v1.0
protocol: a renderer can now ask an agent to run a function
(`callAgentFunction`), the agent can ask the renderer to run one back
(`callRendererFunction`), and a surface's live `dataModel` can be persisted
and exposed to the agent/tools (`sendDataModel`). [`a2ui-v1.md`](a2ui-v1.md)
(FEAT-470) covers the wire and the **display-only** surfaces this feature
builds on; this page covers what's new here.

## 1. What this adds

FEAT-470 left the wire 100% v1.0-conformant but scoped interactivity to
"models + `Form` composition + deep links" — the renderer could show a
surface and resume a conversation through a deep link, but it could never
call the agent back mid-conversation, and the agent could never call the
renderer back either. FEAT-469 is that follow-up: a pure-protocol
`A2UIRuntime` (`parrot/outputs/a2ui/runtime/`) dispatches renderer→agent
envelopes to **any** non-hidden tool on the agent's `ToolManager`, and lets
the agent queue renderer→agent RPC calls of its own.

## 2. The four flows

Each example below is copied from a passing test
(`tests/outputs/a2ui/runtime/test_dispatch.py`,
`tests/outputs/a2ui/conformance/test_runtime_envelopes.py`).

### `callAgentFunction` → `agentFunctionResponse`

```json
{"version": "v1.0", "callAgentFunction": {
  "surfaceId": "s-1", "functionCallId": "fc-1",
  "callFunction": {"call": "get_weather", "args": {"location": "Caracas"},
                    "catalogId": "https://parrot.dev/catalogs/v1"}}}
```

```json
{"version": "v1.0", "agentFunctionResponse": {"functionCallId": "fc-1", "value": {"ok": 1}}}
```

A denied call maps to `error{code: "FORBIDDEN"}`; an unknown function, a
renderer-only function, or an unresolvable catalog all map to
`error{code: "INVALID_FUNCTION_CALL"}`; an exception inside the tool maps to
`error{code: "INTERNAL"}` — the message is always a safe, generic string,
never a traceback (the real cause goes to the server log via
`self.logger.exception`).

### `action` (+ `sendDataModel`)

```json
{"version": "v1.0", "action": {
  "name": "submit", "surfaceId": "s-1", "sourceComponentId": "btn-1",
  "timestamp": "2026-08-29T10:00:00Z", "context": {},
  "dataModel": {"rows": [1, 2, 3]}}}
```

`dataModel` is only legal on `action` (`callAgentFunction` rejects it —
`additionalProperties: false`). When present, the last `dataModel` per
`surfaceId` is persisted and exposed to the turn (§6). `action.userMessage`,
when present, becomes a **visible** user turn carrying that text verbatim;
absent, it becomes a **system** turn tagged
`{"type": "a2ui_action", "action": <the envelope, dataModel stripped>}` —
the same tag Teams/Telegram/deep-link resume already consume. `dataModel`/
`context` never appear in the turn text either way — only `_a2ui_surface_state`
carries it (§6).

### `callRendererFunction` → `rendererFunctionResponse`

```json
{"version": "v1.0", "callRendererFunction": {
  "functionCallId": "fc-2",
  "callFunction": {"call": "refreshChart", "args": {},
                    "catalogId": "https://parrot.dev/catalogs/v1"}}}
```

Minted by `A2UIRuntime.call_renderer(session_id, surface_id, call, args)`,
which registers the pending call **before** returning
(`secrets.token_urlsafe(16)` ids, matching the deep-link token convention)
and always sets `callFunction.catalogId` — the official schema requires it
here even though the shared `FunctionCall` model does not.

```json
{"version": "v1.0", "rendererFunctionResponse": {"functionCallId": "fc-2", "value": {"done": true}}}
```

An unknown or already-resolved `functionCallId` maps to
`error{code: "NOT_FOUND"}`.

### `error` (generic and validation shapes)

```json
{"version": "v1.0", "error": {"code": "UNALLOWED_PARENT", "surfaceId": "s-1",
  "path": "/components/0", "message": "bad"}}
```

`VALIDATION_FAILED`/`UNALLOWED_PARENT`/`UNALLOWED_CHILD` require
`surfaceId`+`path` (no `functionCallId`); every other code requires
**exactly one** of `surfaceId`/`functionCallId`. `FORBIDDEN`/`NOT_FOUND`/
`INTERNAL`/`TIMEOUT` are **parrot extensions** — the official protocol
reserves no fixed code list for generic errors.

> **Vendored-schema quirk, not a defect**: `agent_to_renderer.json` has no
> top-level `error` message at all (`A2UIAgentMessage` has no `error`
> field) — every `error` envelope this runtime emits or accepts validates
> against `renderer_to_agent.json` instead, confirmed structurally and by
> the conformance suite.

## 3. Transports

| Transport | Endpoint | Auth | Notes |
|---|---|---|---|
| HTTP | `POST /api/v1/agents/{agent_id}/a2ui` | Same resolution as AgentTalk (`_resolve_bot`/`_get_user_session`); **401 without an authenticated user** | One envelope or JSONL/list body → `{"messages": [...]}`; a single envelope uses `Content-Type: application/a2ui+json` |
| HTTP (stream) | `GET /api/v1/agents/{agent_id}/a2ui` | Same as above | `text/event-stream` SSE, one event per envelope — **not** AgentTalk's `b'\n\x00'` chunked-AIMessage framing |
| HTTP (capabilities) | `GET /api/v1/agents/{agent_id}/a2ui/capabilities` | None | The same `agent_capabilities()` document published on the Agent Card |
| A2A | `message:send` / `message:stream`, a `Part` with `metadata.mimeType == "application/a2ui+json"` | A2A's own identity extraction (`_extract_identity`); **fails closed** (`FAILED` task, no dispatch) without a verifiable identity — the same posture as the HTTP transport's 401 | Dispatched synchronously — never spawned as a background task even with `returnImmediately` |
| Deep link | `POST /api/v1/a2ui/resume/web?token=...` | Single-use token | `GET` renders a confirm page (no state change — safe for link prescanners); only `POST` consumes |

`callRendererFunction` is delivered **both ways** on the A2A/HTTP-stream
paths: as an SSE event as soon as it is minted, **and** attached to the
NEXT `message/send`/HTTP POST response for that session (drained from the
same `PendingCallRegistry` a `_delivered` marker tracks — never both for
the same `functionCallId`). Deep-link resume routes through the exact same
`A2UIRuntime.dispatch(..., transport="deeplink")` call as the other two
transports, so a resume that carries `dataModel` persists surface state
identically.

## 4. Security posture

This is the section that matters most before you deploy this feature.

- **Every non-hidden `ToolManager` tool is renderer-invocable.** There is no
  per-tool opt-in and no per-surface allowlist (both were explicitly
  rejected during design) — the model is opt-**out** (§5).
- **The only barrier is the session user's `PermissionContext`.** Every
  transport builds one via `parrot.auth.permission.build_principal_context`
  and passes it to `ToolManager.execute_tool(permission_context=...)` on
  every single dispatch.
- `build_principal_context` defaults `roles` to an **empty `frozenset()`**.
  Role-gated PBAC policies **deny by default** until real role claims are
  threaded through your deployment's identity mapping — this is the safe
  direction for a newly renderer-invocable surface, but it means a
  role-gated tool will simply refuse until you wire real roles in.
- **Known limitation, not fixed by this feature**: `ToolManager.execute_tool()`
  bypasses `permission_context` entirely for the `ToolDefinition`
  (`@tool`-decorated function) path — it calls the plain function directly
  with no permission check at all. `ToolManagerExecutor.call()` detects
  this (`isinstance(tool, ToolDefinition)`) and logs a `WARNING` naming the
  gap on every such call; it does not — and structurally cannot, from this
  feature's own file scope — enforce anything on that path. If you need a
  `@tool` function gated the same way an `AbstractTool` subclass is, either
  convert it to an `AbstractTool` subclass or file a fast-follow against
  `ToolManager` itself.
- **Every invocation is audited.** `ToolManagerExecutor.call()` logs one
  `INFO` line per call: `a2ui_audit agent_id=... user_id=... call=... status=...`.
- **Hide a destructive tool** with `a2ui_hidden = True` (§5) rather than
  reverting the whole catalog to an opt-in model.

## 5. Marking a tool

Both attributes are optional class attributes on `AbstractTool`, default
`False`, no `__init__` signature change:

```python
from parrot.tools.abstract import AbstractTool

class DropTableTool(AbstractTool):
    name = "drop_table"
    # Exclude from the A2UI catalog entirely — callAgentFunction and
    # export_functions() both skip it. Everything ELSE stays exposed.
    a2ui_hidden = True

class ShareLocationTool(AbstractTool):
    name = "share_location"
    # Declarative only — the RENDERER enforces this (a live user gesture),
    # never the agent. Also forces `allowedCallers: "rendererOnly"` in the
    # exported catalog document (the vendored schema's own conditional
    # rule): a gesture-gated function has no "user activation" context
    # when the agent would invoke it itself.
    a2ui_requires_user_activation = True
```

## 6. Surface state in the turn (`_a2ui_surface_state`)

A turn that came from `A2UIRuntime.dispatch` (any transport) carries its
`SurfaceState` (if `sendDataModel`/`dataModel` was present) into the bot
call as `AbstractBot.ask(..., a2ui_surface_state=result.surface_state)`.
Inside that call's tool loop, any tool receives it via the reserved
`_a2ui_surface_state` kwarg — `AbstractTool.execute()` pops it (never
forwarded to the LLM, never appears in a generated tool schema) and applies
it to a `ContextVar` for the duration of the call; `_execute()` reads it via
`current_a2ui_surface_state()`:

```python
from parrot.tools.abstract import AbstractTool, current_a2ui_surface_state

class ChartRefreshTool(AbstractTool):
    name = "refresh_chart"

    async def _execute(self, **kwargs):
        state = current_a2ui_surface_state()
        if state is not None:
            current_rows = state.data_model.get("rows", [])
            ...
```

**Implementation note**: this uses a `ContextVar` set by `ask()`, not a
`ToolManager.execute_tool()` keyword argument — that hop would require
changes to `tools/manager.py` and every LLM client (out of this feature's
scope), whereas a `ContextVar` set in `bots/base.py` and read in
`tools/abstract.py` gets the same tool-visible, LLM-invisible result from
only those two files. Unlike the neighboring `_permission_context`/
`self._current_pctx` convention (an unguarded instance attribute, safe only
because that state is never awaited concurrently on the same instance in
practice), `_a2ui_surface_state` is read exclusively via the ContextVar —
never stashed on `self` — because FEAT-469 specifically increases
concurrent multi-session invocation of a shared tool instance.

## 7. Operational limits

- **Pending renderer calls expire after 900 s** (`FunctionCallRecord.ttl_seconds`),
  swept lazily on every registry access — there is no background reaper.
- **`sendDataModel` payloads are capped at 1 MiB** by default
  (`A2UI_MAX_DATA_MODEL_BYTES`, environment-overridable). An oversized
  payload maps to `error{code: "INTERNAL"}` and leaves the surface's
  previous state untouched.
- **Surface state has no TTL of its own** — it lives in
  `ConversationHistory.metadata["a2ui_surfaces"]` and inherits the
  session's own lifecycle. Only pending renderer calls are TTL-bound.
- **Concurrency caveat**: `RedisConversation` exposes no atomic
  compare-and-set/pipeline primitive for a partial metadata update, so
  `ConversationMemorySurfaceStore` serializes read-modify-write with a
  per-`session_id` `asyncio.Lock`. This is a **process-local** mitigation —
  it does not protect a multi-worker deployment where two processes race
  the same session concurrently.
- **Measured dispatch overhead**: `A2UIRuntime.dispatch()` on a
  `callAgentFunction` adds roughly 0.02–0.03 ms over a no-op
  `execute_tool` call (median over 50 runs) — comfortably inside the 5 ms
  budget.

## See also

- [`a2ui-v1.md`](a2ui-v1.md) — the wire protocol and display-only surfaces
  this feature builds on.
- [`docs/migration/feat-273-a2ui-deprecations.md`](../migration/feat-273-a2ui-deprecations.md)
  — the FEAT-469 section covers what changed for existing callers.
- `sdd/specs/a2ui-agent-functions.spec.md` (FEAT-469) — the full design spec
  this page summarizes.
- `packages/ai-parrot/tests/outputs/a2ui/conformance/test_runtime_envelopes.py`
  — the conformance suite validating every RPC-leg envelope against the
  vendored wire schemas.
