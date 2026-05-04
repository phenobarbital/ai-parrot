# Feature Specification: Web HITL Channel & Demo Agent

**Feature ID**: FEAT-146
**Date**: 2026-05-05
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

`HumanTool` and `HandoffTool` are exercised today only via the Telegram
integration. The web surface (`AgentTalk` HTTP handler at
`/api/v1/agents/chat/{agent_id}` consumed by the `AgentChat.svelte` UI in
`navigator-frontend-next`) has never been used to drive a Human-in-the-Loop
flow. This blocks two things:

1. Web users cannot interact with agents that need mid-flight clarification
   (approvals, single-choice picks, free-text questions).
2. There is no end-to-end web demo for prospective customers / internal QA
   to *see* HITL working in the UI we ship.

The HITL substrate (`HumanInteractionManager`, `HumanChannel`, Redis
persistence, three dispatch modes) already exists and is production-ready
on Telegram. What is missing is:

- A `HumanChannel` implementation that delivers questions over the existing
  WebSocket (`UserSocketManager` at `/ws/userinfo`) and accepts answers
  through a small HTTP endpoint.
- A `HumanTool` variant that auto-resolves the active web session as the
  recipient (mirroring `TelegramHumanTool`).
- A bootstrap path so the manager exists in web-only deployments (today
  it is only created when an integration bot starts —
  `parrot/integrations/manager.py:154`).
- A registered demo agent that calls **both** `ask_human` (HumanTool) and
  `handoff_to_human` (HandoffTool) so the contrast between the two
  mechanisms is visible from the same chat.

### Goals

- Implement `WebHumanChannel` that delivers `HumanInteraction` over the
  existing `UserSocketManager` channel for the user's session.
- Implement `WebHumanTool` that auto-resolves the manager and the recipient
  (the active session id) at invocation time — analogous to
  `TelegramHumanTool`.
- Add `POST /api/v1/agents/hitl/respond` so the frontend can submit answers
  back to the manager.
- Bootstrap a process-wide `HumanInteractionManager` + `WebHumanChannel`
  on app startup when no other integration has done so already.
- Register a demo agent (`agents/demo.py`, registry name `hitl_demo`)
  that uses `WebHumanTool`, `HandoffTool`, and a custom tool whose call
  intentionally raises `HumanInteractionInterrupt` to exercise the
  Handoff resume path.
- Ship a brainstorm document for the frontend changes
  (`docs/web-hitl-frontend-brainstorm.md`) that the user takes to
  `navigator-frontend-next` to drive its own SDD spec.

### Non-Goals (explicitly out of scope)

- Frontend implementation in `navigator-frontend-next`. Only a brainstorm
  document is produced here.
- Suspend/resume mode (`request_human_input_async`). Long-poll only —
  the HTTP POST that started the agent stays open until the human
  responds. Suspend/resume can be added later if web disconnections
  prove problematic.
- Authentication-aware multi-respondent / consensus scenarios. The web
  channel sends to a single recipient — the active web session — and
  uses `ConsensusMode.FIRST_RESPONSE` (the default).
- Reusing the existing follow-up flow (`bot.followup` /
  `turn_id` + `data` POST body). That mechanism is caller-driven; HITL
  is agent-driven and remains a separate code path.

---

## 2. Architectural Design

### Overview

A new `WebHumanChannel` implements `HumanChannel` and uses
`UserSocketManager.notify_channel(channel, payload)` (already at
`parrot/handlers/user.py:756`) to push messages of type
`"hitl:question"` to the channel named after the user's `session_id`
(or an explicit `ws_channel_id` if the request supplied one).

The HTTP request lifecycle is unchanged for the agent: `AgentTalk.post`
still calls `bot.ask(...)` and waits for the response. While the agent's
LLM loop is running, a `HumanTool` invocation calls
`manager.request_human_input(interaction, channel="web")`, which:

1. Persists the interaction in Redis.
2. Creates a `Future` and stores it in `manager._pending_futures`.
3. Calls `WebHumanChannel.send_interaction(...)`, which pushes a JSON
   payload to the user's WebSocket channel.
4. Awaits the future (blocks the agent — and therefore the HTTP POST).

The frontend's `wsService` already receives the message (subscription
to `currentSessionId` happens at `AgentChat.svelte:217`). The user
answers; the frontend POSTs `{interaction_id, value, response_type?}`
to `/api/v1/agents/hitl/respond`. The handler builds a `HumanResponse`
and calls `manager.receive_response(...)`, which resolves the future,
the agent's `_execute` returns the value, and the agent continues. The
original POST eventually returns when the LLM finishes.

`WebHumanTool` resolves its dependencies the same way `TelegramHumanTool`
does:

- `manager` ← `get_default_human_manager()` if none was passed
  (`parrot/human/__init__.py:40`).
- `target_humans[0]` ← the value of a new `current_web_session`
  ContextVar set by `AgentTalk.post()` at request entry. The recipient
  string is the WebSocket channel name to publish to.

### Component Diagram

```
[Browser]
   │  ws subscribe(session_id)        ┌─────────────────┐
   │ ◀──────────────────────────────  │ UserSocketMgr   │
   │                                  │  notify_channel │
   │  hitl:question {interaction_id}  └─────▲───────────┘
   │ ◀──────────────────────────────        │ send msg
   │                                  ┌─────┴───────────┐
   │  POST /agents/hitl/respond ────► │ WebHumanChannel │
   │       {interaction_id, value}    └─────▲───────────┘
   │                                        │ register/dispatch
   │                                  ┌─────┴───────────┐
   │  POST /agents/chat/hitl_demo ──► │ AgentTalk       │
   │       (long-poll, blocks)        │  - sets ContextV│
   │                                  └─────┬───────────┘
   │                                        │ bot.ask(...)
   │                                  ┌─────▼───────────┐
   │                                  │ BasicAgent      │
   │                                  │   tools:        │
   │                                  │     ask_human ──┼──► WebHumanTool
   │                                  │     handoff ────┼──► HandoffTool
   │                                  │     book_flight ┼──► HumanInteractionInterrupt
   │                                  └─────────────────┘
                                            │
                                      ┌─────▼───────────┐
                                      │ HumanInteract.. │
                                      │    Manager      │  ◄── Redis (state)
                                      └─────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `HumanChannel` (`parrot/human/channels/base.py:11`) | extends | New `WebHumanChannel` implements all 4 abstract methods. |
| `HumanTool` (`parrot/human/tool.py:98`) | extends | New `WebHumanTool` overrides `_execute` to resolve manager + target lazily, then delegates to `super()._execute`. |
| `HumanInteractionManager` (`parrot/human/manager.py:34`) | uses | Bootstrap creates an instance and registers `WebHumanChannel` under name `"web"`. Calls `set_default_human_manager(...)`. |
| `UserSocketManager` (`parrot/handlers/user.py:27`) | uses | `WebHumanChannel` calls `notify_channel(session_id, payload)` to deliver questions. Already attached at `app['user_socket_manager']` (`app.py:208`). |
| `AgentTalk` (`parrot/handlers/agent.py:50`) | modifies | `post()` sets `current_web_session` ContextVar at entry, resets in `finally`. Existing `ws_channel_id`/`session_id` extraction at lines 1297, 1381 is reused. |
| `BotManager.setup` (`parrot/manager/manager.py:964`) | adds | New route for the HITL response endpoint registered next to `/api/v1/agents/chat/...`. |
| `app.py:setup_app` (`/home/jesuslara/proyectos/navigator/ai-parrot/app.py:202`) | adds | One call to `setup_web_hitl(app)` after `app['user_socket_manager']` is set. |
| `register_agent` (`parrot/registry/__init__.py:12`) | uses | Demo agent uses `@register_agent(name="hitl_demo", at_startup=True)`. |
| `HandoffTool` (`parrot/core/tools/handoff.py:18`) | uses | Demo agent registers it directly. The custom `book_flight` tool also raises `HumanInteractionInterrupt` from `parrot/core/exceptions.py:11` for the handoff demo. |

### Data Models

The wire format from server → browser (WebSocket payload) and from
browser → server (HTTP POST body) are the only new contracts. Internal
domain models (`HumanInteraction`, `HumanResponse`,
`InteractionResult`) are reused unchanged.

```python
# WebSocket payload — emitted by WebHumanChannel.send_interaction
{
    "type": "hitl:question",
    "interaction_id": "uuid-string",
    "interaction_type": "approval" | "single_choice" | "multi_choice"
                        | "form" | "free_text",
    "question": "string",
    "context": "optional string",
    "options": [
        {"key": "stable_id", "label": "What user sees", "description": "?"}
    ],
    "form_schema": {...} | None,
    "default_response": Any | None,
    "timeout": 7200.0,
    "source_agent": "hitl_demo",
    "deadline": "2026-05-05T12:34:56Z",
}

# WebSocket payload — emitted on cancellation by WebHumanChannel.cancel_interaction
{
    "type": "hitl:cancel",
    "interaction_id": "uuid-string",
    "reason": "string"
}

# HTTP request body — POST /api/v1/agents/hitl/respond
{
    "interaction_id": "uuid-string",
    "value": Any,                          # type matches interaction_type
    "response_type": "single_choice"       # optional; defaults to the
                                           # interaction's declared type
}

# HTTP response body — 200 OK on success
{
    "ok": true,
    "interaction_id": "uuid-string"
}

# Error responses
# 400 — malformed body or missing fields
# 404 — interaction_id not found (already resolved or expired)
```

### New Public Interfaces

```python
# parrot/human/channels/web.py
class WebHumanChannel(HumanChannel):
    channel_type: str = "web"

    def __init__(
        self,
        socket_manager: "UserSocketManager",
    ) -> None: ...

    async def send_interaction(
        self, interaction: HumanInteraction, recipient: str,
    ) -> bool: ...

    async def register_response_handler(
        self,
        callback: Callable[[HumanResponse], Awaitable[None]],
    ) -> None: ...

    async def send_notification(
        self, recipient: str, message: str,
    ) -> None: ...

    async def cancel_interaction(
        self, interaction_id: str, recipient: str,
    ) -> None: ...

    # The HTTP endpoint reaches the manager directly (manager.receive_response),
    # so register_response_handler stores the callback but the channel does
    # not invoke it itself.

# parrot/handlers/web_hitl.py
def get_current_web_session() -> Optional[str]: ...
def set_current_web_session(session: Optional[str]) -> "Token": ...
def reset_current_web_session(token: "Token") -> None: ...

class WebHumanTool(HumanTool):
    """HumanTool that auto-resolves the manager + target from the
    current AgentTalk request's session/ws_channel_id."""

    def __init__(
        self,
        *,
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...

    async def _execute(self, **kwargs: Any) -> Any: ...

class HITLResponseHandler(BaseView):
    """POST /api/v1/agents/hitl/respond — submit a HumanResponse."""
    async def post(self) -> web.Response: ...

def setup_web_hitl(app: web.Application) -> None:
    """Bootstrap the process-wide HumanInteractionManager and register
    the WebHumanChannel under name 'web'. No-op if already configured."""

# agents/demo.py — registered as `hitl_demo`
@register_agent(name="hitl_demo", at_startup=True)
class HITLDemoAgent(BasicAgent):
    agent_id: str = "hitl_demo"
    ...
```

---

## 3. Module Breakdown

### Module 1: `WebHumanChannel`
- **Path**: `packages/ai-parrot/src/parrot/human/channels/web.py`
- **Responsibility**: Translate `HumanInteraction` → JSON payload and
  publish via `UserSocketManager.notify_channel(recipient, payload)`.
  Implements `cancel_interaction` (emits `hitl:cancel`) and
  `send_notification` (emits `hitl:notification`).
  Stores the response callback registered by `manager.startup()`, but
  does **not** invoke it on its own — the HTTP endpoint reaches the
  manager directly. Keeping the registration is a contract requirement
  of `HumanChannel`.
- **Depends on**: `parrot/human/channels/base.py`, `parrot/human/models.py`,
  `parrot/handlers/user.py:UserSocketManager`.

### Module 2: `WebHumanTool` + ContextVar
- **Path**: `packages/ai-parrot/src/parrot/handlers/web_hitl.py`
- **Responsibility**:
  - Define `current_web_session: ContextVar[Optional[str]]` and three
    helpers (`set_current_web_session`, `get_current_web_session`,
    `reset_current_web_session`).
  - `WebHumanTool` subclasses `HumanTool`. In `_execute`, lazily
    resolves `self.manager` from `get_default_human_manager()` and
    fills `target_humans` from the ContextVar when neither the call
    nor the tool default supplied one.
  - Default channel is `"web"`.
- **Depends on**: Module 1, `parrot/human/__init__.py`,
  `parrot/human/tool.py`.

### Module 3: HITL Response Handler
- **Path**: `packages/ai-parrot/src/parrot/handlers/web_hitl.py`
  (same file as Module 2).
- **Responsibility**: `HITLResponseHandler(BaseView)` exposing
  `POST /api/v1/agents/hitl/respond`. Validates the JSON body,
  builds a `HumanResponse`, looks up the manager via
  `get_default_human_manager()`, calls `manager.receive_response`,
  returns 200/400/404 as appropriate.
  Decorated with `@is_authenticated()` so unauthenticated callers
  cannot resolve someone else's interaction.
  Respondent identity is taken from the authenticated session
  (`request.session.get('user_id')`), not from the request body.
- **Depends on**: Module 2, `parrot/human/manager.py`,
  `parrot/human/models.py`.

### Module 4: Bootstrap
- **Path**: `packages/ai-parrot/src/parrot/handlers/web_hitl.py`
  (same file as Module 2/3).
- **Responsibility**: `setup_web_hitl(app)` —
  1. If `get_default_human_manager()` already returns a manager, skip
     creating a new one but still register a `WebHumanChannel` under
     name `"web"` if no channel with that name is registered.
  2. Otherwise create `HumanInteractionManager(redis_url=REDIS_URL)`,
     register `WebHumanChannel(socket_manager=app['user_socket_manager'])`
     under `"web"`, call `set_default_human_manager`, and append an
     `app.on_startup` hook that calls `manager.startup()` so response /
     cancel handlers are wired.
  3. Append the HITL POST route.
- **Depends on**: Modules 1, 2, 3, `parrot/conf.py:REDIS_URL`,
  `app['user_socket_manager']`.

### Module 5: AgentTalk wiring
- **Path**: `packages/ai-parrot/src/parrot/handlers/agent.py` (edits inside
  `AgentTalk.post`).
- **Responsibility**: After extracting `session_id`/`ws_channel_id`
  (existing code paths at lines 1297, 1381), set the ContextVar:
  ```python
  hitl_token = set_current_web_session(ws_channel_id or session_id)
  try:
      ...
  finally:
      reset_current_web_session(hitl_token)
  ```
  No other behavioral change.
- **Depends on**: Module 2.

### Module 6: Route registration in BotManager
- **Path**: `packages/ai-parrot/src/parrot/manager/manager.py` (small edit
  inside `BotManager.setup` at line 964).
- **Responsibility**: Register `/api/v1/agents/hitl/respond` next to the
  existing `/api/v1/agents/chat/{agent_id}` route (line 998). Also call
  `setup_web_hitl(app)` here if `app['user_socket_manager']` is present.
  Keeping the bootstrap inside `BotManager.setup` means consumers like
  `app.py` do not need a second wiring call, and the order
  (`UserSocketManager` already in `app.py:202`, then
  `BotManager.setup(app)` later) is preserved. If
  `app['user_socket_manager']` is absent the bootstrap is skipped with a
  WARNING log — the HITL endpoint is still registered but will return
  503 until the socket manager exists.
- **Depends on**: Module 4.

### Module 7: Demo Agent
- **Path**: `agents/demo.py`
- **Responsibility**: A `BasicAgent` subclass registered as `hitl_demo`
  ("Travel Concierge"). System prompt instructs the agent to:
  1. Use `ask_human` (single_choice) to pick a destination from a
     short list.
  2. Use `ask_human` (free_text) to ask for the travel date.
  3. Call `book_flight(destination, date)`. The custom tool intentionally
     raises `HumanInteractionInterrupt` if `date` looks malformed
     (regex check) — to demo the Handoff path. Otherwise it returns a
     fake confirmation string.
  4. If `book_flight` returns a confirmation, summarize the trip.

  Tools registered:
  - `WebHumanTool(source_agent="hitl_demo")`
  - `HandoffTool()`
  - `BookFlightTool()` (defined in the same file).

  Uses `use_llm="google"` (default) but does not require any external
  service besides the LLM and Redis.
- **Depends on**: Modules 2, 6 (the agent runs only inside the web
  handler), `parrot/core/tools/handoff.py`,
  `parrot/core/exceptions.py:HumanInteractionInterrupt`.

### Module 8: Tests
- **Path**: `packages/ai-parrot/tests/handlers/test_web_hitl.py` and
  `packages/ai-parrot/tests/human/test_web_channel.py`.
- **Responsibility**:
  - Unit: `WebHumanChannel.send_interaction` calls
    `notify_channel(recipient, payload)` with the right shape per
    `interaction_type`.
  - Unit: `WebHumanChannel.cancel_interaction` emits `hitl:cancel`.
  - Unit: `HITLResponseHandler` returns 400 on malformed body, 404 on
    unknown id, 200 on valid; calls `manager.receive_response` exactly
    once.
  - Unit: `WebHumanTool._execute` resolves manager and target from the
    ContextVar; returns a clear error string when the ContextVar is
    empty and no `default_targets`.
  - Integration: end-to-end with an in-memory `HumanInteractionManager`
    and a fake `UserSocketManager`. Drive an agent that calls
    `ask_human`; assert the channel received the question; simulate
    the POST response; assert the agent's coroutine resumed with the
    answer.
- **Depends on**: All previous modules.

### Module 9: Frontend brainstorm
- **Path**: `docs/web-hitl-frontend-brainstorm.md`
- **Responsibility**: A self-contained brainstorm document the user
  copies into `navigator-frontend-next` to drive its own `/sdd-spec`.
  Contents:
  - Wire-format contract for `hitl:question`, `hitl:cancel`,
    `/agents/hitl/respond`.
  - Mapping `interaction_type → UI component` (approval / single_choice
    / multi_choice / form / free_text).
  - Edge cases: WS disconnect mid-question, timeout, cancel,
    page reload, multiple concurrent interactions, what to render for
    `HandoffTool` vs `HumanTool`.
  - Recommended file layout in `navigator-frontend-next` and a
    minimal sketch of `HitlPrompt.svelte`.
  - Open questions for the frontend author (modal vs inline bubble,
    theming, accessibility, telemetry).
- **Depends on**: nothing in this repo; ships as a deliverable.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_web_channel_send_approval` | 1 | `send_interaction` with `APPROVAL` produces a payload with `interaction_type="approval"` and no `options`. |
| `test_web_channel_send_single_choice` | 1 | Payload contains `options=[{key,label,description}]` exactly as provided. |
| `test_web_channel_send_form` | 1 | Payload contains `form_schema` verbatim. |
| `test_web_channel_returns_false_when_channel_missing` | 1 | If `notify_channel` returns `False` (no subscriber), `send_interaction` returns `False`. |
| `test_web_channel_cancel` | 1 | `cancel_interaction` emits `{"type":"hitl:cancel", interaction_id, reason}`. |
| `test_context_var_isolation` | 2 | Setting `current_web_session` in one task does not leak to another (`asyncio.gather` of two tasks, each sets and reads its own value). |
| `test_web_human_tool_resolves_manager_lazily` | 2 | Construct tool with `manager=None`; call `_execute`; assert `get_default_human_manager` was queried. |
| `test_web_human_tool_target_from_contextvar` | 2 | Set ContextVar to `"sess-123"`; call tool; assert the dispatched interaction's `target_humans == ["sess-123"]`. |
| `test_web_human_tool_explicit_targets_win` | 2 | When the LLM passes `target_humans=["override"]`, ContextVar is ignored. |
| `test_hitl_endpoint_400_on_missing_field` | 3 | POST with `{"value": ...}` and no `interaction_id` returns 400. |
| `test_hitl_endpoint_404_on_unknown_id` | 3 | POST with valid shape but unknown id returns 404. |
| `test_hitl_endpoint_200_calls_receive_response` | 3 | POST with valid id returns 200 and calls `manager.receive_response` once. |
| `test_hitl_endpoint_requires_auth` | 3 | Unauthenticated POST returns 401/403 (whatever `@is_authenticated` produces). |
| `test_setup_web_hitl_idempotent` | 4 | Calling `setup_web_hitl(app)` twice does not create two managers nor two channels. |
| `test_setup_web_hitl_skips_when_no_socket_manager` | 4 | Without `app['user_socket_manager']`, the function logs a warning and does not raise. |
| `test_demo_agent_registers` | 7 | `parrot.registry.agent_registry` lists `hitl_demo` after import. |
| `test_book_flight_raises_on_bad_date` | 7 | `BookFlightTool._aexecute(date="next year")` raises `HumanInteractionInterrupt`. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_human_tool_over_web` | With a real `HumanInteractionManager` and a fake `UserSocketManager`, drive a stub agent that calls `WebHumanTool` once. Assert the channel emitted the right payload, simulate `POST /agents/hitl/respond`, assert the tool returned the submitted value. |
| `test_e2e_handoff_tool_over_web` | Drive `BookFlightTool` with a malformed date; assert `HumanInteractionInterrupt` propagates out of `agent.invoke()` and the LLM client's resume hook can be re-entered with the user's reply. |
| `test_e2e_demo_agent_full_flight` | Smoke test: run the registered `hitl_demo` agent against a mocked Google client (canned tool calls) end-to-end, including one HumanTool round-trip. |

### Test Data / Fixtures

```python
@pytest.fixture
def fake_user_socket_manager():
    """Records every notify_channel call and exposes them for assertions."""

@pytest.fixture
def in_memory_manager():
    """HumanInteractionManager wired to a fakeredis instance."""

@pytest.fixture
async def web_hitl_app(aiohttp_client, fake_user_socket_manager, in_memory_manager):
    """aiohttp app with WebHumanChannel + HITLResponseHandler mounted, the
    default_human_manager set to in_memory_manager, and an authenticated
    test user pre-installed."""
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `WebHumanChannel` exists at `parrot/human/channels/web.py` and
      implements all four abstract methods of `HumanChannel`.
- [ ] `WebHumanChannel.send_interaction` produces the JSON payload
      documented in §2 Data Models, with one entry per interaction
      type, and pushes it via `UserSocketManager.notify_channel`.
- [ ] `WebHumanTool`, the `current_web_session` ContextVar (and its
      three helpers), `HITLResponseHandler`, and `setup_web_hitl` all
      live in `parrot/handlers/web_hitl.py`.
- [ ] `WebHumanTool` resolves the manager via
      `get_default_human_manager()` when none is supplied, and resolves
      `target_humans` from the ContextVar when neither the call nor the
      tool default did.
- [ ] `POST /api/v1/agents/hitl/respond` returns 200 on a valid body,
      400 on missing/invalid fields, 404 on unknown `interaction_id`,
      and 401/403 when unauthenticated. The respondent identity is
      taken from the authenticated session, never from the request body.
- [ ] `setup_web_hitl(app)` is idempotent (safe to call twice) and is
      invoked from `BotManager.setup` after the routes are registered.
- [ ] `AgentTalk.post` sets `current_web_session` to
      `ws_channel_id or session_id` at request entry and resets it in
      `finally`. ContextVar isolation under concurrent requests is
      covered by `test_context_var_isolation`.
- [ ] `agents/demo.py` registers an agent named `hitl_demo` exposing
      `WebHumanTool`, `HandoffTool`, and a `BookFlightTool` that raises
      `HumanInteractionInterrupt` on malformed input.
- [ ] All unit tests in `test_web_hitl.py` and `test_web_channel.py`
      pass: `pytest packages/ai-parrot/tests/handlers/test_web_hitl.py
      packages/ai-parrot/tests/human/test_web_channel.py -v`.
- [ ] Integration tests pass: `pytest -k "e2e_human_tool_over_web or
      e2e_handoff_tool_over_web or e2e_demo_agent" -v`.
- [ ] `docs/web-hitl-frontend-brainstorm.md` exists, contains the
      wire-format contract, the `interaction_type → UI` mapping, and
      the open questions list described in Module 9.
- [ ] No regression in the existing Telegram HITL path
      (`pytest packages/ai-parrot/tests/integrations/telegram -v` still
      passes) — the bootstrap must not register a web channel under a
      name that would collide with Telegram's per-bot channel name.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references below were
> verified by reading the source on 2026-05-05.

### Verified Imports

```python
# Human-in-the-Loop substrate
from parrot.human import (                                                  # parrot/human/__init__.py:9-43
    HumanTool,
    HumanInteractionManager,
    set_default_human_manager,
    get_default_human_manager,
)
from parrot.human.models import (                                           # parrot/human/models.py:11-120
    HumanInteraction,
    HumanResponse,
    InteractionType,
    InteractionStatus,
    InteractionResult,
    ChoiceOption,
    TimeoutAction,
    ConsensusMode,
)
from parrot.human.channels.base import HumanChannel                          # parrot/human/channels/base.py:11

# Tools / agents
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema       # parrot/tools/abstract.py:23,71
from parrot.core.tools.handoff import HandoffTool                            # parrot/core/tools/handoff.py:18
from parrot.core.exceptions import HumanInteractionInterrupt                 # parrot/core/exceptions.py:11
from parrot.bots import Agent                                                # parrot/bots/__init__.py (re-export of BasicAgent subclass)
from parrot.bots.agent import BasicAgent                                     # parrot/bots/agent.py:36
from parrot.registry import register_agent                                    # parrot/registry/__init__.py:12

# Web infra
from parrot.handlers.user import UserSocketManager                            # parrot/handlers/user.py:27
from parrot.handlers.agent import AgentTalk                                   # parrot/handlers/agent.py:50
from parrot.conf import REDIS_URL                                             # parrot/conf.py:271

# Reference patterns to mimic — DO NOT subclass these from web code
from parrot.integrations.telegram.context import (                            # parrot/integrations/telegram/context.py:30
    get_current_telegram_chat_id,
)
from parrot.integrations.telegram.human_tool import TelegramHumanTool         # parrot/integrations/telegram/human_tool.py:20
```

### Existing Class Signatures

```python
# parrot/human/channels/base.py
class HumanChannel(ABC):                                                     # line 11
    channel_type: str = "base"                                               # line 19

    @abstractmethod
    async def send_interaction(
        self, interaction: "HumanInteraction", recipient: str,               # line 22
    ) -> bool: ...

    @abstractmethod
    async def register_response_handler(                                     # line 33
        self, callback: Callable[["HumanResponse"], Awaitable[None]],
    ) -> None: ...

    @abstractmethod
    async def send_notification(                                             # line 41
        self, recipient: str, message: str,
    ) -> None: ...

    @abstractmethod
    async def cancel_interaction(                                            # line 50
        self, interaction_id: str, recipient: str,
    ) -> None: ...

    async def register_cancel_handler(                                       # line 59 (default no-op)
        self, callback: Callable[[str], Awaitable[bool]],
    ) -> None: return None

# parrot/human/manager.py
class HumanInteractionManager:                                               # line 34
    def __init__(
        self,
        channels: Optional[Dict[str, HumanChannel]] = None,                  # line 56
        redis_url: Optional[str] = None,
    ) -> None: ...

    def register_channel(self, name: str, channel: HumanChannel) -> None:    # line 144
    async def startup(self) -> None: ...                                     # line 148
    async def request_human_input(                                           # line 161
        self, interaction: HumanInteraction, channel: str = "telegram",
    ) -> InteractionResult: ...
    async def receive_response(self, response: HumanResponse) -> None: ...   # line 337
    async def cancel_pending(                                                # line 416
        self, interaction_id: str, reason: str = "user_cancelled",
    ) -> bool: ...
    async def get_result(                                                    # line 323
        self, interaction_id: str
    ) -> Optional[InteractionResult]: ...

# parrot/human/tool.py
class HumanTool(AbstractTool):                                               # line 98
    name: str = "ask_human"                                                  # line 112
    args_schema: Type[BaseModel] = HumanToolInput                            # line 124

    def __init__(                                                            # line 126
        self,
        manager: Any = None,
        *,
        default_channel: str = "telegram",
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...

    async def _execute(self, **kwargs: Any) -> Any: ...                      # line 141

# parrot/handlers/user.py
class UserSocketManager(WebSocketManager):                                   # line 27
    async def notify_channel(                                                # line 756
        self, channel_name: str, message: Dict[str, Any],
    ) -> bool: ...
    async def broadcast_to_channel(                                          # line 357
        self, channel: str, message: Dict[str, Any],
        exclude_ws: Optional[web.WebSocketResponse] = None,
    ) -> None: ...
    channel_subscriptions: Dict[str, List[web.WebSocketResponse]]            # line 97

# parrot/handlers/agent.py
class AgentTalk(BaseView):                                                   # line 50
    async def post(self): ...                                                # line 1237
    # Where ws_channel_id and session_id are extracted:
    #   user_id, user_session = await self._get_user_session(data)           # line 1297
    #   session_id = user_session                                            # line 1303
    #   ws_channel_id = data.pop('ws_channel_id', None)                      # line 1381
    # Where the existing post-response WS notify happens:
    #   if ws_channel_id: await self._notify_ws_channel(...)                 # line 1557

# parrot/manager/manager.py
class BotManager:                                                            # importable as parrot.manager.BotManager
    def setup(self, app: web.Application) -> web.Application: ...            # line 964
    # Existing AgentTalk routes:
    #   '/api/v1/agents/chat/{agent_id}'           → AgentTalk                # line 998
    #   '/api/v1/agents/chat/{agent_id}/{method_name}' → AgentTalk            # line 1002

# parrot/core/tools/handoff.py
class HandoffTool(AbstractTool):                                             # line 18
    name: str = "handoff_to_human"                                           # line 27
    args_schema: Type[BaseModel] = HandoffToolSchema                         # line 33

    def _execute(self, prompt: str, **kwargs: Any) -> Any:                   # line 36
        raise HumanInteractionInterrupt(prompt=prompt)
    async def _aexecute(self, prompt: str, **kwargs: Any) -> Any:            # line 40
        raise HumanInteractionInterrupt(prompt=prompt)

# parrot/integrations/telegram/human_tool.py — REFERENCE PATTERN
class TelegramHumanTool(HumanTool):                                          # line 20
    def __init__(
        self, *, default_channel: Optional[str] = None,
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...                                                           # line 33
    async def _execute(self, **kwargs: Any) -> Any:                          # line 51
        # Lazy-resolve manager from get_default_human_manager()
        # Auto-fill target_humans from ContextVar
        return await super()._execute(**kwargs)

# parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):                                # line 36
    agent_id: Optional[str] = None                                           # line 53

    def __init__(                                                            # line 79
        self,
        name: str = 'Agent',
        agent_id: str = 'agent',
        use_llm: str = 'google',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        use_tools: bool = True,
        instructions: Optional[str] = None,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        **kwargs,
    ): ...
    def agent_tools(self) -> List[AbstractTool]: return []                   # line 253

# parrot/registry/registry.py — register_agent decorator
# Bound to AgentRegistry.register_bot_decorator at parrot/registry/__init__.py:12
def register_bot_decorator(                                                  # line 1031
    self,
    name: str,
    *,
    at_startup: bool = False,
    startup_config: dict | None = None,
    ...,
): ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `WebHumanChannel.send_interaction` | `UserSocketManager.notify_channel` | direct method call | `parrot/handlers/user.py:756` |
| `setup_web_hitl` | `app['user_socket_manager']` | `app[...]` lookup | set at `app.py:208`, read at `parrot/handlers/agent.py:859` |
| `setup_web_hitl` | `set_default_human_manager` | direct call | `parrot/human/__init__.py:34` |
| `HITLResponseHandler.post` | `HumanInteractionManager.receive_response` | direct call | `parrot/human/manager.py:337` |
| `HITLResponseHandler.post` | `get_default_human_manager` | direct call | `parrot/human/__init__.py:40` |
| `WebHumanTool._execute` | `super()._execute` (`HumanTool`) | `super()` chain | `parrot/human/tool.py:141` |
| `WebHumanTool._execute` | `get_current_web_session` | ContextVar read | new code (Module 2) |
| `AgentTalk.post` | `set_current_web_session` / `reset_current_web_session` | ContextVar set/reset | edits in `parrot/handlers/agent.py` (Module 5) |
| `BotManager.setup` | adds `/api/v1/agents/hitl/respond` route | `router.add_view(...)` | edits in `parrot/manager/manager.py:964` (Module 6) |
| `agents/demo.py:HITLDemoAgent` | `register_agent` | decorator | `parrot/registry/__init__.py:12` |
| `agents/demo.py:BookFlightTool._aexecute` | `HumanInteractionInterrupt` | `raise` | `parrot/core/exceptions.py:11` |

### Does NOT Exist (Anti-Hallucination)

- ~~`WebHumanChannel`~~ — to be created in this feature.
- ~~`WebHumanTool`~~ — to be created in this feature.
- ~~`POST /api/v1/agents/hitl/respond` endpoint~~ — to be created.
- ~~`current_web_session` ContextVar~~ — to be created.
- ~~`AgentTalk.on_startup`~~ — `AgentTalk` is a `BaseView` per request,
  it has no class-level startup hook. App startup hooks must be appended
  via `app.on_startup.append(...)` (see `BotManager.setup` at
  `parrot/manager/manager.py:969` for the existing pattern).
- ~~`HumanInteractionManager.notify_channel`~~ — `notify_channel` is on
  `UserSocketManager`, not on the HITL manager.
- ~~`UserSocketManager.send_interaction`~~ — does not exist; only
  `notify_channel`, `broadcast_to_channel`, `broadcast_to_all`, and
  `send_direct_message` exist.
- ~~`HumanTool.target_humans`~~ — there is no class attribute named
  `target_humans` on `HumanTool`. The list lives on `default_targets`
  (init kwarg, line 138) and on the per-call `kwargs["target_humans"]`
  inside `_execute` (line 156).
- ~~`agent.followup` for HITL~~ — `bot.followup` exists
  (`parrot/bots/agent.py:1169`) but is for caller-supplied data
  (`turn_id` + `data`); it is **not** the agent-driven HITL path and
  is explicitly out of scope (see §1 Non-Goals).
- ~~`HumanChannel.invoke_response_callback`~~ — does not exist;
  channels resolve interactions by calling
  `manager.receive_response(...)` directly, which the channel either
  invokes itself (Telegram) or via an external entry point (web POST).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `TelegramHumanTool` (`parrot/integrations/telegram/human_tool.py`)
  for the manager/target lazy-resolution pattern in `WebHumanTool`.
- Mirror `parrot/integrations/manager.py:_ensure_human_manager` (line 154)
  for the bootstrap pattern, but adapt it to live in
  `parrot/handlers/web_hitl.py:setup_web_hitl`.
- Channel names registered on the manager must be unique. Telegram
  registers per-bot under the bot's name; web always uses `"web"`.
- ContextVar pattern: `parrot/integrations/telegram/context.py:30` is
  the canonical reference. Use the same `Token`-based reset.
- New `BaseView` handlers go through aiohttp's `request.app[...]` for
  shared services; never create global singletons in module scope.
- Logging: every new class instantiates `self.logger =
  logging.getLogger(__name__)` per CLAUDE.md.
- Pydantic models for request body validation in
  `HITLResponseHandler.post` (build a `HITLResponseBody(BaseModel)`).
- Async-first: every method that touches I/O is `async`.
- Google-style docstrings on every class and public method.

### Known Risks / Gotchas

- **Long-poll timeout**: `HumanInteraction.timeout` defaults to 7200 s.
  aiohttp clients (and any reverse proxy) must allow a `POST` to hang
  that long. Mitigation: documented in the brainstorm; the demo agent
  passes a smaller `timeout` (e.g. 300 s) to keep iteration fast.
- **WebSocket disconnect**: if the user reloads while waiting, the
  `wsService` re-subscribes to the same `session_id` on reconnect, so
  a *future* `notify_channel` reaches them — but the original
  `hitl:question` message is gone. Mitigation: the frontend brainstorm
  must call out a strategy (e.g. `GET /agents/hitl/pending?session_id=`
  to recover; out of scope for this backend spec but flagged).
- **ContextVar leakage across tasks**: `asyncio.create_task` copies the
  current context. `AgentTalk.post` runs inside the request's context,
  so child tasks spawned by the LLM client inherit the right session.
  Tested explicitly by `test_context_var_isolation`.
- **Channel name collision**: if Telegram is also running, it registers
  channels under each bot's name (e.g. `"my_telegram_bot"`); the web
  channel registers as `"web"`. They cannot collide unless someone
  names a Telegram bot `web`. The bootstrap logs a WARNING and skips
  re-registration if a `"web"` channel already exists.
- **PBAC for the HITL endpoint**: an attacker who guesses an
  `interaction_id` could otherwise resolve someone else's interaction.
  Mitigation: `@is_authenticated` plus persisting the requesting
  `user_id` on the `HumanInteraction.metadata` is the long-term fix;
  for v1, we accept the risk because `interaction_id` is a UUID4 and
  the endpoint requires a valid session — this is logged as a known
  risk and documented in the open questions.
- **HandoffTool over web**: when `HumanInteractionInterrupt` propagates
  out of the LLM client, the existing client behavior catches it and
  returns the prompt as the assistant message. The frontend will see
  it as a normal assistant turn — there is no special "handoff"
  rendering. This is acceptable for the demo; richer UX is left to the
  frontend brainstorm.
- **`use_llm="google"` requirement**: Google's `agentic` loop
  (`parrot/clients/google/client.py`) handles `HumanInteractionInterrupt`
  resume. The demo agent uses Google by default — switching providers
  requires verifying that provider's resume hook supports HITL.
- **Test isolation**: the global `_default_manager` in
  `parrot/human/__init__.py:31` is process-wide. Tests that swap it
  must restore the previous value in a fixture teardown.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `redis` (`redis.asyncio`) | already pinned | Reused via `parrot.conf:REDIS_URL` for HumanInteractionManager state. |
| `pydantic` | already pinned | Request body validation in `HITLResponseHandler`. |
| `fakeredis` | already in dev deps | Used by the integration test fixture. |
| `pytest-aiohttp` | already in dev deps | `aiohttp_client` fixture for endpoint tests. |

No new runtime dependencies.

---

## Worktree Strategy

**Default isolation**: per-spec.

All tasks share the same Python files (notably `parrot/handlers/web_hitl.py`)
and depend on each other in a clear sequence: channel → tool → endpoint →
bootstrap → wiring → demo agent → tests → docs. Parallelization across
tasks would force complex merges inside the same module file. One worktree
runs all tasks sequentially via `sdd-worker`.

Cross-feature dependencies: none. The Telegram HITL stack must keep working
unchanged — verified by re-running the existing
`tests/integrations/telegram` suite at the end.

Suggested branch name: `feat-146-web-hitl-and-demo-agent`.
Suggested worktree path: `.claude/worktrees/feat-146-web-hitl-and-demo-agent`.

---

## 8. Open Questions

- [ ] Should `HumanInteraction.metadata` be extended to carry the
      requesting `user_id` so the HITL endpoint can reject responses
      from a different authenticated user? (Defer — UUID4 + auth is
      acceptable for v1; revisit if we open the endpoint to multi-user
      scenarios.) — *Owner: Jesus Lara*
- [ ] How should the frontend recover from a WS disconnect that drops
      a `hitl:question` message? Options: (a) ephemeral — let it
      timeout; (b) backend exposes `GET /agents/hitl/pending?session_id=`
      to refetch active interactions; (c) push the message via Redis
      pub/sub on reconnect. To be discussed in the frontend brainstorm.
      — *Owner: Jesus Lara*
- [ ] Should the demo agent also exercise the `multi_choice` and
      `form` interaction types, or is `single_choice` + `free_text`
      enough to validate the channel? Defer to implementation — start
      with the two most common, add the others if time allows.
      — *Owner: sdd-worker*
- [ ] Reverse-proxy / aiohttp client read timeout for long-polled HITL
      POSTs. Verify our default deployment (nginx? aiohttp-only?) does
      not cap connections at < 7200 s. — *Owner: Jesus Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-05 | Jesus Lara | Initial draft |
