# TASK-2573: HTTP endpoint — `A2UIHandler` (POST, SSE stream, capabilities)

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2571
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 6** and goal **G6**: a dedicated HTTP transport for
renderer→agent envelopes outside A2A, at
`/api/v1/agents/{agent_id}/a2ui`. The §8 clarification explicitly **rejected**
routing A2UI envelopes through the AgentTalk POST — this is its own endpoint
with its own content type, sharing only AgentTalk's authentication and session
resolution.

Three routes:
- **POST** — a single R→A envelope (or JSONL list) → `{"messages": [...A→R...]}`
- **GET** (SSE) — delivers queued `callRendererFunction` envelopes for the session
- **GET `/capabilities`** — the `agent_capabilities()` document, so a non-A2A
  renderer can discover `supportedCatalogIds` without fetching an Agent Card
  (spec §8 resolved OQ)

Runs in **parallel with TASK-2572** (A2A transport): different packages, same
upstream dependency.

---

## Scope

- Implement `A2UIHandler(BaseView)` with `post`, `get` (SSE stream), and the
  capabilities route.
- Reuse AgentTalk's agent/user/session resolution; **401 when unauthenticated**.
- Build the `PermissionContext` via `build_principal_context` (spec §8 resolved OQ).
- Register all routes in `manager.py`.
- Inject `DispatchResult.user_turn` into the bot and append the bot's response
  (including its `a2ui_envelope`) to `messages`.
- Unit tests with the aiohttp test client.

**NOT in scope**: A2A (TASK-2572), deep links (TASK-2574), the bot-side
`_a2ui_surface_state` kwarg (TASK-2575), E2E (TASK-2576).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/a2ui.py` | CREATE | `A2UIHandler` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Register the three routes |
| `packages/ai-parrot-server/tests/handlers/test_a2ui_handler.py` | CREATE | Handler tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29). **The spec's §6 line numbers for
> `handlers/agent.py` are STALE** — use these.

### Verified Imports
```python
from parrot.handlers.agent import AgentTalk              # handlers/agent.py:110  (spec said 104 — wrong)
from parrot.a2a.models import A2UI_MEDIA_TYPE            # a2a/models.py:336 == "application/a2ui+json"
from parrot.auth.permission import build_principal_context   # auth/permission.py:166
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime  # TASK-2569
from parrot.outputs.a2ui.runtime.models import A2UICallContext, A2UIErrorCode, error_envelope  # TASK-2568
from parrot.outputs.a2ui.runtime.adapters import (       # TASK-2570
    ConversationMemorySurfaceStore, ToolManagerExecutor,
)
from parrot.outputs.a2ui.catalog.export import agent_capabilities   # TASK-2571
from parrot.outputs.a2ui.serialization import deserialize, iter_jsonl  # serialization.py:155, :215
from aiohttp import web
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py   (CORRECTED line numbers)
class AgentTalk(BaseView):                                                 # 110
    async def _get_user_session(self, data: dict) -> tuple[str|None, str|None]:   # 867
        """Priority — session_id: body 'session_id' -> new uuid4().hex (NEVER the
        browser session: it mixes histories). user_id: body 'user_id' ->
        self.request.get('user_id') -> request_session.get('user_id')."""
    async def _get_agent(self, data) -> Union[AbstractBot, web.Response]:  # 898
    async def _resolve_bot(self, data) -> Tuple[Optional[AbstractBot], bool]:  # 920
        """1) BotManager.get_user_bot(request, name)  2) BotManager.get_bot(name)"""
    async def post(self)                                                   # 1441
    async def put(self)                                                    # 2075
    async def get(self)                                                    # 2157
    # stream final dict sets envelope['a2ui_envelope'] = ai_message.a2ui_envelope
    # non-stream A2UI reply: {"input","output","output_mode":"a2ui","a2ui_envelope"}

# packages/ai-parrot/src/parrot/auth/permission.py
@dataclass(frozen=True)
class UserSession:                    # 21
    user_id: str; tenant_id: str; roles: frozenset[str]; metadata: dict

class PermissionContext:              # 81
    session: UserSession; request_id; channel; trace_context; extra

def build_principal_context(principal: str, channel: str | None = None,
                            tenant_id: str | None = None,
                            roles: frozenset[str] | None = None) -> PermissionContext:  # 166
    """returns at :199 — tenant_id defaults to `principal`; roles defaults to
    frozenset() ⇒ role-gated PBAC policies DENY by default."""

# packages/ai-parrot-server/src/parrot/manager/manager.py
router.add_view("/api/v1/agents/chat/{agent_id}", AgentTalk)                 # 1933
router.add_view("/api/v1/agents/chat/{agent_id}/{method_name}", AgentTalk)   # 1934
router.add_view("/api/v1/agents/knowledge/{agent_id}/{action}", ...)         # 1939
```

### The `PermissionContext` finding (spec §8 resolved OQ — read this)
`grep -rn "PermissionContext(" packages/*/src` proves **AgentTalk never builds
one**. The only construction sites are `auth/permission.py:199` (inside
`build_principal_context`), `cli/identity.py:105`,
`knowledge/ontology/tool_dispatcher.py:214`, and three integration wrappers
(msagentsdk `agent.py:375`, `resume.py:298`, telegram `wrapper.py:1271`). So the
AgentTalk HTTP path effectively runs with `permission_context=None`.

There is nothing to "reuse" — you must **construct** it. Use
`build_principal_context(principal=user_id, channel="a2ui")` and model the call
on `tool_dispatcher.py:195-214`. Be aware of the security consequence, and state
it in the module docstring: `roles` defaults to `frozenset()`, so role-gated
PBAC policies **deny by default**. That is the safe direction for a
renderer-invocable surface, but it means a tool gated on roles will refuse until
real role claims are threaded through.

### Does NOT Exist
- ~~`parrot.handlers.a2ui` / `A2UIHandler`~~ — this task creates it.
- ~~the route `/api/v1/agents/{agent_id}/a2ui`~~ — AgentTalk lives at `/api/v1/agents/chat/{agent_id}`; there is no conflict, but register carefully so `{agent_id}` does not shadow the literal `chat` segment.
- ~~`AgentTalk._get_permission_context()`~~ — no such method.
- ~~a shared SSE helper~~ — AgentTalk streams with a `b'\n\x00'` separator, which is its **own** chunked-AIMessage format. Spec §7 is explicit: **do not reuse it**. Use standard `text/event-stream` SSE framing.

---

## Implementation Notes

### Transport must stay thin
Spec §7: "Transporte fino (como `DeepLinkResumeHandler`): auth → contexto →
`dispatch` → respuesta; ninguna lógica de protocolo en handlers." Every
protocol decision belongs to `A2UIRuntime`. The handler only authenticates,
builds `A2UICallContext`, calls `dispatch`, and serializes the result.

### POST
1. Resolve agent (`_resolve_bot` pattern) → 404 when unknown.
2. Resolve user/session (`_get_user_session` pattern). **No authenticated user ⇒ 401**
   (spec §7 makes this the first line of defence, since all tools are exposed).
3. Body is one envelope, or JSONL / a JSON list → use `iter_jsonl`
   (`serialization.py:215`) rather than splitting lines by hand.
4. `dispatch()` each envelope, in order.
5. If any `DispatchResult.user_turn` is set, inject it as a bot turn by the same
   path AgentTalk POST uses, and append the bot's reply — including its
   `a2ui_envelope` when present — to `messages`.
6. Respond `{"messages": [...]}`. Content type: `application/a2ui+json`
   (`A2UI_MEDIA_TYPE`) for a **single** envelope; plain `application/json` for a list.
7. A malformed envelope ⇒ **400 whose body is itself an `error` envelope**
   (built with `error_envelope`, never hand-rolled JSON).

### GET — SSE stream
`text/event-stream`, one event per A→R envelope, draining queued
`callRendererFunction`s for the session from the `PendingCallRegistry`. Send
periodic comment heartbeats (`: keepalive\n\n`) so proxies do not drop an idle
stream, and handle client disconnect without leaving the pending entry consumed
but undelivered — re-queue on write failure.

### GET `/capabilities`
Return `agent_capabilities([...])` as JSON — the same document TASK-2572 puts in
the Agent Card. Derive both from `agent_capabilities()` so they can never drift.

### Route registration
```python
router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
router.add_view("/api/v1/agents/{agent_id}/a2ui/capabilities", A2UIHandler)
```
Register **next to** the AgentTalk views (manager.py:1933-1934) and verify the
literal-vs-pattern ordering: aiohttp matches in registration order, so confirm
`/api/v1/agents/chat/{agent_id}` still resolves to AgentTalk after adding a
`{agent_id}` pattern at the same depth. Add a test that asserts it.

### Key Constraints
- aiohttp only — **never** `requests`/`httpx`.
- async throughout; Pydantic v2; Google-style docstrings; `self.logger`.
- Do not reuse the AgentTalk `b'\n\x00'` separator.
- No protocol logic in the handler.

### References in Codebase
- `handlers/deeplink.py:66-110` — `DeepLinkResumeHandler`, the thin-transport model to imitate.
- `handlers/agent.py:867` `_get_user_session`, `:920` `_resolve_bot` — the resolution patterns to reuse.
- `knowledge/ontology/tool_dispatcher.py:195-214` — building a `PermissionContext`.
- `packages/ai-parrot-server/tests/test_deeplink_resume_web.py` — aiohttp handler test precedent.

---

## Acceptance Criteria

- [ ] `POST /api/v1/agents/{agent_id}/a2ui` with a valid `callAgentFunction` returns 200 `{"messages": [agentFunctionResponse]}`.
- [ ] An invalid envelope returns **400 with an `error` envelope as the body**.
- [ ] An unauthenticated request returns **401** (same behaviour as AgentTalk).
- [ ] An `action` envelope injects a bot turn and `messages` includes the bot's `a2ui_envelope` when it produced one.
- [ ] `GET` (SSE) delivers a registered `callRendererFunction` as a `text/event-stream` event and does not use the `b'\n\x00'` separator.
- [ ] `GET .../a2ui/capabilities` returns the same document the Agent Card publishes, valid against `agent_capabilities.json`.
- [ ] `permission_context` is built with `build_principal_context` and reaches `execute_tool` on every dispatch.
- [ ] Adding the routes does not break `/api/v1/agents/chat/{agent_id}` resolution (asserted by test).
- [ ] Single-envelope responses use `application/a2ui+json`; list responses use `application/json`.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_a2ui_handler.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/a2ui.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_a2ui_handler.py
import pytest


CALL_ENV = {"version": "v1.0", "callAgentFunction": {
    "surfaceId": "s-1", "functionCallId": "fc-1",
    "callFunction": {"call": "get_weather", "args": {"location": "Caracas"}}}}


class TestPost:
    async def test_call_agent_function(self, client):
        r = await client.post("/api/v1/agents/demo/a2ui", json=CALL_ENV)
        assert r.status == 200
        body = await r.json()
        assert body["messages"][0]["agentFunctionResponse"]["functionCallId"] == "fc-1"

    async def test_invalid_envelope_returns_error_envelope(self, client):
        r = await client.post("/api/v1/agents/demo/a2ui", json={"version": "v1.0"})
        assert r.status == 400
        assert (await r.json())["error"]["code"] == "INVALID_FUNCTION_CALL"

    async def test_requires_auth(self, anon_client):
        assert (await anon_client.post("/api/v1/agents/demo/a2ui", json=CALL_ENV)).status == 401

    async def test_action_injects_turn(self, client): ...

    async def test_single_envelope_content_type(self, client):
        r = await client.post("/api/v1/agents/demo/a2ui", json=CALL_ENV)
        assert r.headers["Content-Type"].startswith("application/a2ui+json")


class TestStream:
    async def test_delivers_pending_call_renderer_function(self, client): ...
    async def test_does_not_use_agenttalk_separator(self, client): ...


class TestCapabilities:
    async def test_matches_agent_card_document(self, client, v1_schemas): ...


class TestRouting:
    async def test_agenttalk_route_still_resolves(self, client):
        """{agent_id}/a2ui must not shadow chat/{agent_id}."""
        ...


class TestPermissionContext:
    async def test_permission_context_reaches_execute_tool(self, client, spy_tool_manager): ...
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 6, §7 ("Transporte fino", "Streaming"), §8 resolved OQs on the endpoint and the capabilities route.
2. **Check dependencies** — TASK-2571 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — the spec's `handlers/agent.py` line numbers
   are stale; re-confirm `_get_user_session` at **867** and `AgentTalk` at **110**
   before reusing them, and re-confirm `build_principal_context` at
   `auth/permission.py:166`.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** per scope, keeping all protocol logic in `A2UIRuntime`.
6. **Verify** every acceptance criterion, including the route-shadowing test.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
