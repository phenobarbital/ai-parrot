---
type: Wiki Overview
title: 'Feature Specification: Web HITL Channel & Demo Agent'
id: doc:sdd-specs-web-hitl-and-demo-agent-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: integration. The web surface (`AgentTalk` HTTP handler at
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.core.tools.handoff
  rel: mentions
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.handlers.user
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.integrations.telegram.context
  rel: mentions
- concept: mod:parrot.integrations.telegram.human_tool
  rel: mentions
- concept: mod:parrot.manager
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

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

…(truncated)…
