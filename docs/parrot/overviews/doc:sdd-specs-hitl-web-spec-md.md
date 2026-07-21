---
type: Wiki Overview
title: 'Feature Specification: HITL over Stateless Web Request/Response (AgentTalk
  HTTP)'
id: doc:sdd-specs-hitl-web-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The AI-Parrot HITL stack (`parrot/human/`) lets an agent ask a human for
  input
relates_to:
- concept: mod:parrot.auth.oauth2.models
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: HITL over Stateless Web Request/Response (AgentTalk HTTP)

**Feature ID**: FEAT-204
**Date**: 2026-05-29
**Author**: Jesus Lara
**Status**: approved
**Target version**: `ai-parrot-server` 0.24.x · `ai-parrot` 0.25.x

> Input: `sdd/proposals/hitl_web.brainstorm.md` (Recommended Option A) and the
> source design note `sdd/proposals/hitl_web.proposal.md`. The brainstorm's two
> arrival decisions (`wait_strategy` on `HumanTool`; lazy TTL expiry) are treated
> as authoritative. Builds alongside FEAT-146
> (`sdd/specs/web-hitl-and-demo-agent.spec.md`), which shipped the **WebSocket
> long-poll** Web HITL path; this feature adds the **stateless suspend/resume**
> path without removing it.

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The AI-Parrot HITL stack (`parrot/human/`) lets an agent ask a human for input
via `HumanTool` (`ask_human`). Today that tool **blocks**: `HumanTool._execute`
awaits `HumanInteractionManager.request_human_input()`, which registers an
in-memory `asyncio.Future` and waits for a reply resolved by a *live channel*.

Web HITL already exists (FEAT-146) but only in **WebSocket long-poll** mode:
`WebHumanTool` blocks, the question is pushed over the user's WebSocket as
`hitl:question`, and the open HTTP POST is resolved when the human answers via
`POST /api/v1/agents/hitl/respond`. On Fargate workers that recycle, holding an
HTTP connection (and an in-memory Future) for the 2-hour default `timeout` is
not viable, and there is no live channel to push to in a pure-REST deployment.

We want the **request/response cycle itself** to be the transport: the agent
suspends mid-reasoning, its tool-loop state is serialized, the question travels
to the frontend as a `paused` HTTP response, and a later request carrying the
human's answer resumes the agent — injecting the answer as the `tool_result` of
the pending `ask_human` call. No WebSocket, no parked connection, no in-process
timer.

**Who is affected**: end users on the REST/SvelteKit chat surface; backend
engineers wiring agents for stateless deployment; ops running Fargate workers.

### Goals
- Add a `WaitStrategy` enum and a `wait_strategy` field to `HumanTool`
  (default `BLOCK`), **not exposed to the LLM**.
- Provide a `SUSPEND` branch in `HumanTool._execute` that registers the
  interaction and raises `HumanInteractionInterrupt` instead of blocking.
- Add a dedicated REST tool (`SuspendingWebHumanTool`) that wires `SUSPEND`,
  sibling to the existing blocking `WebHumanTool`.
- Make `AgentTalk.post` catch `HumanInteractionInterrupt`, persist the tool-loop
  state, rehydrate the interaction, and return a `paused` envelope (HTTP 200)
  carrying `options` / `form_schema` for structured rendering.
- Add a HITL-tagged **resume** branch in `AgentTalk.post` that validates the
  respondent, applies a three-state TTL/tombstone check, routes the answer
  through `manager.receive_response()`, then calls `agent.resume(...)`.
- Persist tool-loop state as a `SuspendedExecution` blob in Redis under
  `hitl:suspended:{interaction_id}`, TTL-aligned with `hitl:interaction:{id}`.
- Preserve structured interaction types end-to-end.
- Use lazy TTL expiry only — no in-process timeout task in `SUSPEND` mode.

### Non-Goals (explicitly out of scope)
- **Proactive escalation driver** (a qworker sweep/listener acting *at* expiry):
  reserved seam only — must not be foreclosed, but not implemented here.
- **Frontend implementation** (`navigator-frontend-next`): a separate frontend
  spec consumes the `paused` envelope contract (cf.
  `docs/web-hitl-frontend-brainstorm.md`).
- **Reviving `HandoffTool`** — rejected in brainstorm Option B (free-text only;
  would make the agent definition transport-aware). See
  `proposals/hitl_web.brainstorm.md` Option B.
- **Removing or replacing the FEAT-146 WebSocket long-poll path** — rejected in
  brainstorm Option C; both paths coexist.
- **Pure-web hot-wait** (`HOT_THEN_SUSPEND`) — reserved for live channels only.

---

## 2. Architectural Design

### Overview

A new `WaitStrategy` enum (`BLOCK` | `SUSPEND` | `HOT_THEN_SUSPEND`) is added to
`parrot/human/models.py`, and `HumanTool` gains a `wait_strategy` field
(default `BLOCK`, never added to `HumanToolInput`/the LLM schema).

In `SUSPEND`, `HumanTool._execute` builds the **rich** `HumanInteraction`
exactly as today, calls `manager.request_human_input_async()` (persists
`hitl:interaction:{id}`, skips dispatch because no channel is registered in
pure-web), and raises `HumanInteractionInterrupt(interaction_id=...)`. The client
tool-loop enriches the interrupt with `messages` + `tool_call_id` (existing
behaviour). `BasicAgent.ask()` lets it bubble (verified: it does not catch it).

A dedicated `SuspendingWebHumanTool` (sibling to the blocking `WebHumanTool`)
wires `wait_strategy=SUSPEND` and resolves the manager lazily, mirroring
`WebHumanTool`'s lazy-resolution pattern.

`AgentTalk.post` gains two new branches, both modelled on the existing
`AuthorizationRequired → AuthRequiredEnvelope` (HTTP 200) precedent:

1. **Suspend catch**: catches `HumanInteractionInterrupt`, persists a
   `SuspendedExecution{messages, tool_call_id, agent_name, session_id, user_id,
   interaction_id}` to `hitl:suspended:{id}`, rehydrates the full
   `HumanInteraction` from `hitl:interaction:{id}`, and returns a `PausedEnvelope`
   carrying the question, a `turn_id` wrapping `interaction_id` (OQ-1),
   `interaction_type`, `options`, `form_schema`, `deadline`.
2. **Resume detect**: when the request body carries a HITL-response tag
   (e.g. `hitl_response: {turn_id, value, response_type?}`), derive `respondent`
   from the authenticated session, run `is_valid_respondent`, apply the
   three-state TTL/tombstone check, call `manager.receive_response(...)`, load
   the `SuspendedExecution`, and call `agent.resume(session_id, value, state)` to
   continue the tool-loop to a `success` response.

### Component Diagram
```
POST /api/v1/agents/chat/{agent_id}            (SUSPEND)
  └─ AgentTalk.post
       └─ bot.ask() → client tool-loop → LLM calls ask_human
            └─ SuspendingWebHumanTool._execute (wait_strategy=SUSPEND)
                 ├─ build rich HumanInteraction
                 ├─ manager.request_human_input_async()   # persist hitl:interaction:{id}, skip dispatch
                 └─ raise HumanInteractionInterrupt(interaction_id)
            └─ client loop enriches: + messages + tool_call_id
       └─ ask() lets it bubble
       └─ AgentTalk.post catches HumanInteractionInterrupt        [NEW]
            ├─ SuspendedExecutionStore.save(hitl:suspended:{id})  [NEW]
            ├─ rehydrate HumanInteraction from hitl:interaction:{id}
            └─ return PausedEnvelope(status="paused", turn_id, question, options/form_schema)  [NEW]

POST /api/v1/agents/chat/{agent_id}  {hitl_response:{turn_id,value}}   (RESUME)
  └─ AgentTalk.post detects hitl_response tag                   [NEW]
       ├─ respondent = session["user_id"]
       ├─ manager.is_valid_respondent(interaction_id, respondent)
       ├─ 3-state check: result? → "already answered";
       │                 interaction? → alive; neither → "expired"
       ├─ manager.receive_response(HumanResponse(...))
       ├─ SuspendedExecutionStore.load(hitl:suspended:{id})     [NEW]
       └─ agent.resume(session_id, value, state)  → tool_result(tool_call_id)
            └─ client continues tool-loop → AgentResponse(status="success")
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `HumanTool` (`parrot/human/tool.py`) | extends | add `wait_strategy` field + `SUSPEND` branch in `_execute` |
| `WaitStrategy` (`parrot/human/models.py`) | adds | new enum, not in `HumanToolInput` |
| `HumanInteractionManager` (`parrot/human/manager.py`) | uses | reuse `request_human_input_async`, `receive_response`, `is_valid_respondent`, `get_result`, `has_pending`, `_compute_ttl`; do NOT schedule `_handle_timeout` in SUSPEND |
| `HumanInteractionInterrupt` (`parrot/core/exceptions.py`) | uses | carries `interaction_id`; enriched with `messages`/`tool_call_id` by client |
| `AbstractClient.resume` (`parrot/clients/*.py`) | uses | injects answer as `tool_result(tool_call_id)`; no change expected |
| `AgentTalk.post` (`ai-parrot-server .../handlers/agent.py`) | modifies | NEW interrupt catch + paused envelope; NEW hitl_response resume branch |
| `WebHumanTool` / `web_hitl.py` (ai-parrot-server) | extends | add sibling `SuspendingWebHumanTool`; reuse lazy-resolution + `current_web_session` |
| `HITLResponseHandler` (`web_hitl.py`) | reference | reuse its auth/respondent/3-state logic shape; resume itself lives in AgentTalk |
| `AuthRequiredEnvelope` (`parrot/auth/oauth2/models.py`) | reference | model `PausedEnvelope` on this (HTTP 200 structured reply) |
| `BotManager.setup` (`ai-parrot-server .../manager/manager.py`) | reference | existing `setup_web_hitl` bootstrap; no new route required (resume reuses chat route) |

### Data Models
```python
# parrot/human/models.py  (NEW enum)
class WaitStrategy(str, Enum):
    BLOCK = "block"            # current: in-memory Future (live channel / single process)
    SUSPEND = "suspend"        # web stateless: register + raise interrupt
    HOT_THEN_SUSPEND = "hot"   # reserved for live channels (future)

# New SuspendedExecution model (location: ai-parrot-server, near web_hitl.py)
class SuspendedExecution(BaseModel):
    interaction_id: str
    session_id: str
    user_id: str
    agent_name: str
    tool_call_id: str
    messages: list[dict]          # provider-shaped message history (see OQ-7)
    created_at: datetime

# New PausedEnvelope model (modelled on AuthRequiredEnvelope)
class PausedEnvelope(BaseModel):
    status: str = "paused"
    turn_id: str                  # wraps interaction_id (OQ-1)
    interaction_id: str
    interaction_type: str
    question: str
    context: Optional[str] = None
    options: Optional[list[dict]] = None
    form_schema: Optional[dict] = None
    default_response: Any = None
    deadline: Optional[str] = None    # ISO-8601 absolute expiry
    source_agent: Optional[str] = None
```

### New Public Interfaces
```python
# parrot/human/tool.py
class HumanTool(...):
    wait_strategy: WaitStrategy = WaitStrategy.BLOCK   # NOT in HumanToolInput
    async def _execute(self, **kwargs) -> Any:
        # if wait_strategy == SUSPEND: build interaction,
        #   request_human_input_async(), raise HumanInteractionInterrupt(interaction_id)
        # else: existing blocking behaviour

# ai-parrot-server: handlers/web_hitl.py
class SuspendingWebHumanTool(WebHumanTool):
    """WebHumanTool variant wired with wait_strategy=SUSPEND for stateless REST."""

# ai-parrot-server: SuspendedExecutionStore (Redis)
class SuspendedExecutionStore:
    async def save(self, record: SuspendedExecution, ttl: int) -> None
    async def load(self, interaction_id: str) -> Optional[SuspendedExecution]
    async def delete(self, interaction_id: str) -> None    # NOTE: do NOT delete hitl:interaction early
```

---

## 3. Module Breakdown

> One module per capability as a starting point for task decomposition.

### Module 1: WaitStrategy enum + HumanTool.wait_strategy
- **Path**: `packages/ai-parrot/src/parrot/human/models.py`,
  `packages/ai-parrot/src/parrot/human/tool.py`
- **Responsibility**: Add `WaitStrategy` enum. Add `wait_strategy` field to
  `HumanTool` (default `BLOCK`, excluded from `HumanToolInput`/LLM schema). Add
  the `SUSPEND` branch to `_execute`: build the rich `HumanInteraction`, call
  `manager.request_human_input_async()`, raise
  `HumanInteractionInterrupt(interaction_id=...)`. Do NOT schedule any timeout
  task in SUSPEND.
- **Depends on**: existing `HumanInteractionManager.request_human_input_async`.

### Module 2: SuspendedExecution model + SuspendedExecutionStore
- **Path**: ai-parrot-server, alongside `handlers/web_hitl.py` (e.g.
  `handlers/web_hitl.py` or a new `human/suspended_store.py`)
- **Responsibility**: `SuspendedExecution` Pydantic model; Redis store keyed by
  `hitl:suspended:{interaction_id}` with TTL aligned to `hitl:interaction:{id}`
  (reuse `manager._compute_ttl`). `messages` are provider-shaped (OQ-7).
- **Depends on**: `redis.asyncio` (manager's backing store); Module 1 not
  required.

### Module 3: SuspendingWebHumanTool
- **Path**: ai-parrot-server `handlers/web_hitl.py`
- **Responsibility**: `WebHumanTool` subclass that sets `wait_strategy=SUSPEND`;
  reuses lazy manager + `current_web_session` target resolution.
- **Depends on**: Module 1.

### Module 4: AgentTalk suspend catch → PausedEnvelope
- **Path**: ai-parrot-server `handlers/agent.py` (inside `AgentTalk.post`)
- **Responsibility**: Add `except HumanInteractionInterrupt` after the existing
  `except AuthorizationRequired`. Persist `SuspendedExecution`, rehydrate
  `HumanInteraction` from `hitl:interaction:{id}`, build `PausedEnvelope`
  (`turn_id` wraps `interaction_id`), return `web.json_response(..., status=200)`.
  Add `PausedEnvelope` model.
- **Depends on**: Module 2, Module 3.

### Module 5: AgentTalk resume branch
- **Path**: ai-parrot-server `handlers/agent.py` (inside `AgentTalk.post`)
- **Responsibility**: Detect the `hitl_response` tag in the request body; derive
  `respondent` from the authenticated session; `is_valid_respondent`; three-state
  TTL/tombstone check (result → "already answered"; interaction → alive; neither
  → "expired"); `manager.receive_response(...)`; load `SuspendedExecution`; call
  `agent.resume(session_id, value, state)`; return the final `success` response.
- **Depends on**: Module 2.

### Module 6: Tests
- **Path**: `packages/ai-parrot-server/tests/` (+ `packages/ai-parrot/tests/`
  for the tool-level unit tests)
- **Responsibility**: unit + integration tests per §4.
- **Depends on**: Modules 1–5.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_wait_strategy_enum_values` | 1 | `WaitStrategy.BLOCK/SUSPEND/HOT_THEN_SUSPEND` values are stable strings |
| `test_wait_strategy_not_in_llm_schema` | 1 | `wait_strategy` is absent from `HumanToolInput` / the tool's args schema |
| `test_execute_suspend_raises_interrupt` | 1 | SUSPEND `_execute` calls `request_human_input_async` and raises `HumanInteractionInterrupt` with `interaction_id`; never awaits `request_human_input` |
| `test_execute_block_unchanged` | 1 | BLOCK path still awaits `request_human_input` (no regression) |
| `test_suspend_does_not_schedule_timeout` | 1 | no `_handle_timeout` task is created in SUSPEND |
| `test_suspended_store_roundtrip` | 2 | `save`→`load` returns an equal `SuspendedExecution`; TTL is set; `load` of missing id returns `None` |
| `test_suspended_store_ttl_aligned` | 2 | TTL equals `_compute_ttl(interaction)` for the interaction |
| `test_paused_envelope_shape` | 4 | `PausedEnvelope` carries `turn_id`, `interaction_type`, `options`/`form_schema` for a structured interaction |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_suspend_returns_paused` | Drive a stub agent whose LLM calls `ask_human` (SUSPEND); assert `AgentTalk.post` returns HTTP 200 `paused` with the rehydrated `options`/`form_schema` and a `turn_id`, and that `hitl:suspended:{id}` + `hitl:interaction:{id}` exist |
| `test_e2e_resume_to_success` | POST a `hitl_response` for the prior `turn_id`; assert `receive_response` persisted `hitl:result`, the agent resumed, and the final reply is `status="success"` |
| `test_resume_expired` | With neither `hitl:interaction` nor `hitl:result` present, resume returns the fast "expired" reply |
| `test_resume_already_answered` | With `hitl:result` present (tombstone), resume returns "already answered" and does NOT re-run the tool-loop |
| `test_resume_cross_session_rejected` | A respondent not in `target_humans` is rejected (`is_valid_respondent` fails closed) |
| `test_structured_types_survive` | `single_choice`/`form` options/schema arrive intact in the `paused` envelope after rehydration |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_manager():
    # HumanInteractionManager wired to a fake/inmemory Redis (fakeredis.aioredis)
    ...

@pytest.fixture
def suspend_tool(fake_manager):
    return SuspendingWebHumanTool()   # wait_strategy == SUSPEND
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `WaitStrategy` enum exists in `parrot/human/models.py`; `HumanTool` has a
      `wait_strategy` field defaulting to `BLOCK`, **absent from the LLM schema**.
- [ ] In `SUSPEND`, `HumanTool._execute` builds the rich `HumanInteraction`,
      calls `request_human_input_async()`, and raises
      `HumanInteractionInterrupt(interaction_id=...)`; it does **not** await
      `request_human_input()` and does **not** schedule `_handle_timeout`.
- [ ] `SuspendingWebHumanTool` wires `SUSPEND` and resolves manager/target
      lazily, alongside the unchanged blocking `WebHumanTool`.
- [ ] `AgentTalk.post` catches `HumanInteractionInterrupt`, persists a
      `SuspendedExecution` to `hitl:suspended:{id}` (TTL aligned with
      `hitl:interaction:{id}`), rehydrates the `HumanInteraction`, and returns an
      HTTP 200 `paused` envelope carrying `turn_id`, `interaction_type`,
      `options`/`form_schema`.
- [ ] The `turn_id` on the wire wraps `interaction_id` (one correlation contract
      shared with the existing follow-up mechanism). *(OQ-1)*
- [ ] A `hitl_response`-tagged request resumes: respondent derived from the
      authenticated session, `is_valid_respondent` gate, three-state TTL/tombstone
      check, `receive_response()` **then** `agent.resume()` → final `success`. *(OQ-3)*
- [ ] Expired (neither key) → fast "expired" reply; already-answered
      (`hitl:result` tombstone) → "already answered" without re-running the loop.
- [ ] Cross-session answer injection is rejected (`is_valid_respondent` fails
      closed).
- [ ] Escalation seam preserved: `hitl:interaction:{id}` is **not** deleted
      early; `policy_id`/`severity` remain on the persisted interaction; the
      `hitl:suspended:` TTL lets a future sweeper observe pending interactions.
- [ ] The FEAT-146 WebSocket long-poll path is unchanged (no regression).
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests -k human -v`).
- [ ] All integration tests pass (`pytest packages/ai-parrot-server/tests -k hitl -v`).
- [ ] No breaking changes to the existing `ask_human` tool schema or
      `/api/v1/agents/chat/{agent_id}` request contract (new `hitl_response` field
      is additive).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Re-verified 2026-05-29 against
> working tree on `dev`. Path split: HITL core in
> `packages/ai-parrot/src/parrot/`; web layer in
> `packages/ai-parrot-server/src/parrot/`.

### Verified Imports
```python
from parrot.human import (HumanInteractionManager, HumanTool,
    get_default_human_manager, set_default_human_manager)        # human/__init__.py
from parrot.human.models import (HumanResponse, HumanInteraction,
    InteractionType)                                             # human/models.py
from parrot.human.channels.base import ESCALATE_OPTION_KEY       # human/channels/base.py
from parrot.core.exceptions import HumanInteractionInterrupt     # core/exceptions.py:12
from parrot.auth.oauth2.models import AuthRequiredEnvelope       # imported at handlers/agent.py:46
from parrot.handlers.web_hitl import (WebHumanTool,
    HITLResponseHandler, set_current_web_session,
    reset_current_web_session, get_current_web_session)          # ai-parrot-server handlers/web_hitl.py
# NOTE: WaitStrategy and SuspendingWebHumanTool do NOT exist yet — see "Does NOT Exist".
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/human/tool.py
class HumanToolInput(AbstractToolArgsSchema):                    # lines 31-141
    question: str; interaction_type: str = "free_text"
    options: Optional[List[Union[str, Dict[str, Any]]]] = None
    context: Optional[str] = None; timeout: float = 7200.0
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None
    target_humans: Optional[List[str]] = None
    policy_id: Optional[str] = None
    severity: Literal["low","normal","high","critical"] = "normal"
class HumanTool(...):                                            # 143-394
    name = "ask_human"; args_schema = HumanToolInput
    async def _execute(self, **kwargs) -> Any: ...              # 247-351
    #   awaits self.manager.request_human_input(...) at line 335  (BLOCKS)

# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:
    def _compute_ttl(self, interaction: HumanInteraction) -> int: ...                 # 141
    async def is_valid_respondent(self, interaction_id, respondent) -> bool: ...      # 222  (fails closed)
    async def request_human_input(self, interaction, channel="telegram") -> InteractionResult: ...  # 269  BLOCKS
    async def request_human_input_async(self, interaction, channel="telegram") -> str: ...          # 471  returns interaction_id
    async def get_result(self, ...): ...                                              # 511
    async def advance_chain(self, interaction_id, cause="timeout") -> None: ...       # 521
    async def receive_response(self, response: HumanResponse) -> None: ...            # 580
    def has_pending(self, interaction_id: str) -> bool: ...                           # 1283
    # Redis keys: hitl:interaction:{id} (165), hitl:responses:{id} (188),
    #             hitl:result:{id} (215), hitl:callback:{id} (498)

# packages/ai-parrot/src/parrot/core/exceptions.py
class HumanInteractionInterrupt(ParrotError):                    # 12
    def __init__(self, prompt, interaction_id=None, policy_id=None, *a, **k): ...
    self.prompt; self.interaction_id; self.policy_id              # 35-37
    self.state = None; self.tool_call_id = None                   # 38-39
    self.agent_name = None; self.messages = None                  # 40-41

# packages/ai-parrot/src/parrot/clients/claude.py  (representative; all clients implement resume)
async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage:  # 479
    messages = state["messages"]; tool_call_id = state["tool_call_id"]
    messages.append({"role":"user","content":[{"type":"tool_result",
        "tool_use_id": tool_call_id, "content": user_input}]})    # 502-509
# resume also defined at: clients/base.py:1564 (abstract), gpt.py:1129, groq, grok, hf, gemma4, claude_agent

# packages/ai-parrot-server/src/parrot/handlers/web_hitl.py
current_web_session: ContextVar[Optional[str]]                   # 53
class WebHumanTool(HumanTool):                                   # 100-197  (BLOCKS via super()._execute())
    async def _execute(self, **kwargs) -> Any: ...               # 137-197  (lazy manager + target resolution)
class HITLResponseBody(BaseModel): interaction_id; value; response_type=None   # 205-227
class HITLResponseHandler(BaseView):                             # 251-424  POST /api/v1/agents/hitl/respond
    #   respondent = request.session.get("user_id","unknown")  (313)
    #   3-state check has_pending/get_result (331-342); is_valid_respondent gate (345)
    #   ESCALATE_OPTION_KEY -> advance_chain (360-383); receive_response (402)
async def setup_web_hitl(app) -> None: ...                       # 432

# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(...):
    async def post(self):                                        # 1245
        followup_turn_id = data.pop('turn_id', None)             # 1377  (turn_id read from request body)
        _hitl_token = set_current_web_session(ws_channel_id or session_id)   # 1405

…(truncated)…
