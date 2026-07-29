---
type: Wiki Overview
title: 'Brainstorm: HITL over Stateless Web Request/Response (AgentTalk HTTP)'
id: doc:sdd-proposals-hitl-web-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The AI-Parrot HITL stack (`parrot/human/`) lets an agent ask a human for
  input
relates_to:
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

# Brainstorm: HITL over Stateless Web Request/Response (AgentTalk HTTP)

**Date**: 2026-05-29
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

> Derived from `sdd/proposals/hitl_web.proposal.md` (pre-spec design note).
> The proposal's two arrival decisions (`wait_strategy` on `HumanTool`; lazy
> TTL expiry) are treated as **FIXED** per discovery; the alternatives below
> exist only to document the tradeoffs honestly. This brainstorm adds the
> **verified codebase contract** the proposal deferred, and corrects one
> framing error (see "Important correction" below).

---

## Problem Statement

The AI-Parrot HITL stack (`parrot/human/`) lets an agent ask a human for input
via `HumanTool` (`ask_human`). Today that tool **blocks**: `HumanTool._execute`
awaits `HumanInteractionManager.request_human_input()`, which registers an
in-memory `asyncio.Future` and waits for a reply resolved by a *live channel*.

Our production medium is **plain web REST via the AgentTalk HTTP handler**, on
Fargate workers that recycle. There is no guarantee a single process stays
alive for the 2-hour default `timeout`, and keeping the POST open ties an HTTP
connection to a human's think-time. We want the **request/response cycle itself**
to be the transport:

1. The agent decides mid-reasoning it needs human input.
2. The pending interaction + the agent's tool-loop state are **serialized**.
3. The question + a correlation id travel to the frontend **as the HTTP response
   body** (status `paused`) — no WebSocket push required.
4. The frontend renders the question and, on a later call, sends the human's
   answer back **tagged as a HITL response** carrying that id.
5. The handler loads the serialized state, injects the answer **as the
   `tool_result` of the pending `ask_human` call**, and resumes the tool-loop to
   a final answer.

**Who is affected**: end users on the REST/SvelteKit chat surface; backend
engineers wiring agents for stateless deployment; ops running Fargate workers
that cannot hold long-poll connections.

### Important correction to the source proposal

The proposal says *"only the web layer is missing."* **It is not.** A Web HITL
layer already shipped in **FEAT-146** (`sdd/specs/web-hitl-and-demo-agent.spec.md`),
but in **WebSocket long-poll mode**:

- `WebHumanTool` (subclass of `HumanTool`) **blocks** — its `_execute` resolves
  targets/manager then calls `super()._execute()`, awaiting `request_human_input()`.
- The question is **pushed over the user's WebSocket** as `hitl:question` via
  `WebHumanChannel` / `user_socket_manager`; the open HTTP POST stays parked.
- The human answer returns via `POST /api/v1/agents/hitl/respond`
  (`HITLResponseHandler`) → `manager.receive_response()` resolves the open future.

The FEAT-146 frontend brainstorm states this explicitly
(`docs/web-hitl-frontend-brainstorm.md:154`):
> *"suspend/resume mode (where the agent suspends and a fresh POST can re-enter
> it) is not implemented in FEAT-146. Long-poll only — the original POST stays
> open. If the HTTP connection drops the agent request will also fail."*

So this feature's true gap is the **stateless `SUSPEND` wait-strategy** plus the
AgentTalk catch + resume entry point + serialized tool-loop state — *not* the
web layer wholesale. Much of the FEAT-146 plumbing (response endpoint, channel
abstraction, manager async APIs) is reusable.

Also note: the proposal's `turn_id ↔ answer_memory` analogy is grounded not in
`parrot/human/` (no such symbol exists there) but in the AgentTalk **follow-up**
mechanism — `followup_turn_id` + `bot.followup(...)` + `response.turn_id`
(`handlers/agent.py:1538-1552, 1617`). OQ-1 below reuses that `turn_id` contract.

---

## Constraints & Requirements

- **Stateless transport**: the human reply arrives in a *separate* HTTP request;
  no process may be assumed alive between suspend and resume. No hot-wait poll in
  pure web (the `HOT_THEN_SUSPEND` 500 ms poll is noise here — reserved for live
  channels).
- **Agent definition must stay transport-agnostic**: the agent declares
  `ask_human`, full stop. Block-vs-suspend is a *wiring* decision, never exposed
  to the LLM.
- **Structured interaction types must survive the round-trip**: `approval` /
  `single_choice` / `multi_choice` / `form` / `free_text` render as buttons/forms
  in the SvelteKit frontend — must not be flattened to free-text.
- **Lazy expiry only**: rely on Redis TTL + a lazy three-state check on return
  (answered / alive / expired-or-unknown). Do **not** schedule an in-process
  `_handle_timeout` task in `SUSPEND` mode.
- **Forward-compatible with a future proactive escalation driver** (out of scope
  to *implement*; in scope to *not foreclose*): do not delete
  `hitl:interaction:{id}` early; keep `policy_id` / `severity` on the persisted
  interaction; align the suspended-state TTL so a sweeper can observe pending
  interactions.
- **Idempotent resume**: `receive_response` dedupes by respondent, but `resume()`
  is not idempotent — need a tombstone-before-resume ordering / lease.
- **Auth**: derive `respondent` from the authenticated session, never the body;
  reject cross-session answer injection (the FEAT-146 handler already does this).
- **Async-first, `aiohttp`, `redis.asyncio`** — no blocking I/O, no `requests`.

---

## Options Explored

### Option A: `SUSPEND` wait-strategy on `HumanTool` + AgentTalk catch + `SuspendedExecutionStore` (RECOMMENDED)

Factor a `WaitStrategy` enum into `HumanTool` (**not** exposed to the LLM, same
philosophy `HumanToolInput` already applies to consensus/escalation/timeout):

```python
class WaitStrategy(str, Enum):
    BLOCK = "block"            # current: in-memory Future (live channel / single process)
    SUSPEND = "suspend"        # web stateless: register + raise interrupt
    HOT_THEN_SUSPEND = "hot"   # hybrid reserved for live channels (future)
```

Flow:

- **Suspend**: in `SUSPEND`, `HumanTool._execute` builds the rich
  `HumanInteraction` exactly as today, calls `request_human_input_async()`
  (persists `hitl:interaction:{id}`, skips dispatch because no channel is
  registered in pure-web), then raises `HumanInteractionInterrupt(interaction_id)`.
  The client tool-loop enriches the interrupt with `messages` + `tool_call_id`
  (existing behaviour, verified in `claude.py:551-557`). `BasicAgent.ask()` lets
  it bubble (verified: `ask()` does not catch it). **NEW**: `AgentTalk.post`
  catches it — exactly mirroring its existing `AuthorizationRequired →
  AuthRequiredEnvelope` 200-status pattern — persists a `SuspendedExecution`
  blob to `hitl:suspended:{id}`, rehydrates the full `HumanInteraction` from
  `hitl:interaction:{id}`, and returns a `paused` envelope with
  `options`/`form_schema` for rendering.
- **Resume**: a later POST tagged as a HITL response → `AgentTalk.post` detects
  the tag, runs the auth + three-state tombstone/TTL check, calls
  `manager.receive_response(...)` (keeps the HITL ledger coherent), loads the
  `SuspendedExecution`, and calls `agent.resume(session_id, value, state)` which
  injects the answer as `tool_result(tool_call_id)` and continues the tool-loop
  to a final `success` response.

✅ **Pros:**
- Agent stays transport-agnostic; `block` vs `suspend` is pure wiring.
- Reuses the **entire** verified suspend→serialize→resume machinery already
  present in the client (`resume()`) and orchestrator layers — only the AgentTalk
  HTTP path is new.
- Structured types survive: interrupt carries only `interaction_id`; the handler
  rehydrates the rich interaction.
- Lazy TTL expiry → no orphaned asyncio tasks on Fargate recycle.
- Forward-compatible with the escalation sweeper (keys persist under TTL).

❌ **Cons:**
- Introduces a new persisted artifact (`SuspendedExecution`) and its TTL
  lifecycle to keep coherent with `hitl:interaction:{id}`.
- `resume()` idempotency must be solved (tombstone/lease) — see OQ-4.
- Multi-turn HITL (two `ask_human` in one task) needs `messages` accumulation to
  be verified per client (OQ-6).
- Two `HumanTool` subclasses/paths now coexist (blocking `WebHumanTool` for
  WebSocket, `SUSPEND` for REST) — wiring clarity needed.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis` (`redis.asyncio`) | Persist `hitl:suspended:{id}` blob + TTL | already the manager's backing store; `aioredis.from_url(...)` |
| `pydantic` v2 | `SuspendedExecution` model + `paused` envelope | matches existing `AuthRequiredEnvelope` style |
| `aiohttp` | AgentTalk handler catch + `web.json_response(..., status=200)` | existing handler stack |
| (none new) | — | no new third-party dependency required |

🔗 **Existing Code to Reuse:**
- `parrot/human/tool.py` — `HumanTool._execute` (247-351); add `wait_strategy`.
- `parrot/human/manager.py` — `request_human_input_async()` (471-509),
  `receive_response()` (580+), `is_valid_respondent()` (222-246),
  `get_result()`, `has_pending()`, `_compute_ttl()` (141-160).
- `parrot/clients/*.py` — `resume(session_id, user_input, state)` already injects
  `tool_result` keyed by `state["tool_call_id"]` (claude.py:479-578).
- `parrot/core/exceptions.py` — `HumanInteractionInterrupt` (carries `prompt`,
  `interaction_id`, `policy_id`, `state`, `tool_call_id`, `agent_name`, `messages`).
- `handlers/agent.py` — `AgentTalk.post` (1245); `AuthorizationRequired →
  AuthRequiredEnvelope` 200-status precedent (1569-1580); `followup_turn_id` /
  `bot.followup` contract (1538-1552); ContextVar set/reset (1405, 1610).
- `handlers/web_hitl.py` — `HITLResponseHandler` (251-424) auth + respondent +
  three-state check + escalate-via-`advance_chain` precedent; `HITLResponseBody`.

---

### Option B: Revive `HandoffTool` for the web path (REJECTED)

Wire the deprecated `HandoffTool` (which already *raises* the interrupt after a
500 ms poll) as the web suspend tool, and expose `handoff_to_human` to the LLM
in web deployments instead of `ask_human`.

✅ **Pros:**
- `HandoffTool` already raises `HumanInteractionInterrupt` — least new code in the
  tool itself.

❌ **Cons:**
- **Free-text only** (`HandoffToolSchema = {prompt, policy_id}`) — loses
  `options`/`form_schema`, precisely what renders best in SvelteKit.
- Makes the **agent definition transport-aware** (LLM sees a different tool name
  per deployment) — breaks the core abstraction.
- It is deprecated and slated for removal; building on it is debt.
- Conflates two orthogonal axes (interaction semantics vs wait strategy).

📊 **Effort:** Low (but wrong)

📦 **Libraries / Tools:** (none new)

🔗 **Existing Code to Reuse:**
- `parrot/core/tools/handoff.py` — `HandoffTool` (deprecated, 500 ms poll then
  raises interrupt). Documented here only to record why it stays dead.

---

### Option C: Extend the FEAT-146 WebSocket long-poll model (REJECTED — re-creates the problem)

Keep `WebHumanTool` blocking and lean harder on the WebSocket channel; add
reconnect/replay so the open POST survives longer.

✅ **Pros:**
- Already shipped and working for single-process / sticky-session deployments.
- Real-time push UX (no polling on the frontend).

❌ **Cons:**
- **Keeps the HTTP POST open** for up to 2h — the exact constraint we must break
  on Fargate workers that recycle (`WebHumanTool._execute` docstring even warns
  about this, web_hitl.py:150-154).
- Requires a live WebSocket + `user_socket_manager`; degrades to a warning when
  absent (`setup_web_hitl` 464-469).
- Connection drop = lost question + failed agent request (per FEAT-146 brainstorm).
- Does not satisfy the stateless requirement.

📊 **Effort:** Medium (and does not meet the constraint)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` WebSocket | push `hitl:question` | existing `WebHumanChannel` |

🔗 **Existing Code to Reuse:**
- `parrot/human/channels/web.py` (`WebHumanChannel`), `handlers/web_hitl.py`
  (`setup_web_hitl`, `WebHumanTool`).

---

### Option D (unconventional): Durable workflow engine owns suspend/resume (REJECTED for now — over-engineered)

Delegate suspend/resume to an external durable executor (Temporal, or the
in-house `qworker` durable task queue). The agent run becomes a durable workflow;
a human signal resumes it; state lives in the engine, not a Redis blob.

✅ **Pros:**
- Battle-tested durability, retries, visibility, and timers (the proactive
  escalation timer comes "for free").
- A single mechanism covers both suspend/resume **and** the future escalation
  sweeper.

❌ **Cons:**
- Heavy new infra + operational surface for what is a Redis-blob-sized problem.
- The client `resume()` + manager already give us 80% of the machinery; a
  workflow engine would mostly duplicate it.
- Couples agent execution to an external runtime — large blast radius, slow to
  ship.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `temporalio` | durable workflow + signals + timers | new infra; or reuse internal `qworker` |

🔗 **Existing Code to Reuse:**
- Internal `qworker` scheduled-sweep pattern (referenced in proposal §6 as the
  future escalation driver host) — relevant if/when escalation is built.

---

## Recommendation

**Option A** is recommended. It is the only option that (a) satisfies the
stateless-transport constraint, (b) keeps the agent definition transport-agnostic,
(c) preserves structured interaction types end-to-end, and (d) reuses the
already-verified `resume()` + manager machinery so the genuinely-new surface is
narrow: a `WaitStrategy` enum + `SUSPEND` branch in `HumanTool._execute`, a
`SuspendedExecutionStore`, and a catch+resume path in `AgentTalk.post` modelled
on the existing `AuthRequiredEnvelope` precedent.

What we trade off: we accept a new persisted artifact (`SuspendedExecution`) and
the idempotency work that comes with a non-idempotent `resume()`. That is a
bounded, local cost — far cheaper than Option D's infra, and it does not carry
Option B's abstraction break or Option C's open-connection liability. Option A
also leaves the escalation seam open by design (TTL-owned expiry, persisted
`policy_id`/`severity`), so the separate proactive-escalation feature can layer
on top without rework.

---

## Feature Description

### User-Facing Behavior
A user chats with an agent over plain REST. When the agent needs human input, the
reply is a **`paused`** envelope (HTTP 200) carrying the question, a correlation
id, and — for structured types — `options` or `form_schema`. The SvelteKit
frontend renders buttons / a choice list / a form. The user answers; the frontend
POSTs that answer tagged as a HITL response with the correlation id. The agent
resumes from exactly where it paused and returns a normal `success` reply. If the
user waits too long, the next answer attempt returns a fast "that question
expired" message rather than hanging.

### Internal Behavior
- **Suspend**: LLM calls `ask_human` → `HumanTool._execute` (SUSPEND) builds the
  rich `HumanInteraction`, persists it via `request_human_input_async()` (no
  dispatch in pure-web), raises `HumanInteractionInterrupt(interaction_id)`. The
  client tool-loop enriches the interrupt with `messages` + `tool_call_id`;
  `ask()` lets it bubble; `AgentTalk.post` catches it, persists
  `SuspendedExecution{messages, tool_call_id, agent_name, session_id, user_id,
  interaction_id}` to `hitl:suspended:{id}` (TTL aligned with
  `hitl:interaction:{id}`), rehydrates the interaction, and returns the `paused`
  envelope (correlation id surfaced as a `turn_id` wrapping `interaction_id` —
  OQ-1).
- **Resume**: a HITL-tagged POST → `AgentTalk.post` derives `respondent` from the
  session, runs `is_valid_respondent`, then the three-state check
  (`hitl:result:{id}` present → already answered; `hitl:interaction:{id}` present,
  no result → alive → resume; neither → expired/unknown → fast reply). On "alive",
  call `manager.receive_response(HumanResponse(...))` (keeps ledger/consensus/audit
  coherent), load `SuspendedExecution`, call
  `agent.resume(session_id, value, state)` → tool-loop continues to `success`.

### Edge Cases & Error Handling
- **Expired question**: TTL lapsed → neither key present → fast "expired" reply.
- **Double-submit / replay**: `hitl:result:{id}` acts as a tombstone → "already
  answered". Resume itself must be guarded against concurrent re-entry (OQ-4:
  lease/lock on `interaction_id`, tombstone-before-resume).
- **Cross-session injection**: `respondent` from authenticated session only;
  `is_valid_respondent` fails closed when the interaction cannot be loaded.
- **Multi-turn HITL**: a second `ask_human` in the same task suspends again;
  `messages` accumulation in `resume()` must round-trip cleanly (OQ-6).
- **Worker recycle mid-think**: no in-process timer to lose; TTL owns expiry.
- **Manager not configured**: 503 (existing `HITLResponseHandler` behaviour).

---

## Capabilities

### New Capabilities
- `hitl-suspend-wait-strategy`: `WaitStrategy` enum + `SUSPEND` branch in
  `HumanTool._execute` (register-and-suspend; not exposed to the LLM).
- `hitl-web-suspend-resume`: `AgentTalk.post` catches `HumanInteractionInterrupt`,
  returns a `paused` envelope, and exposes the HITL-tagged resume path.
- `suspended-execution-store`: `SuspendedExecution` model + `hitl:suspended:{id}`
  Redis persistence with TTL aligned to `hitl:interaction:{id}`.

### Modified Capabilities
- `web-hitl-and-demo-agent` (FEAT-146): adds the stateless suspend mode alongside
  the existing WebSocket long-poll mode; clarifies wiring of blocking vs suspend.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/human/tool.py` (`HumanTool`) | modifies | add `wait_strategy` field + `SUSPEND` branch in `_execute` |
| `parrot/human/models.py` | extends | add `WaitStrategy` enum; no change to `HumanInteraction` shape |
| `parrot/human/manager.py` | depends on | reuse `request_human_input_async`, `receive_response`, `is_valid_respondent`, `get_result`, `_compute_ttl`; do NOT schedule `_handle_timeout` in SUSPEND |
| `handlers/agent.py` (`AgentTalk.post`) | modifies | NEW catch of `HumanInteractionInterrupt` → `paused` envelope; NEW HITL-tagged resume branch |
| `handlers/web_hitl.py` | extends | reuse `HITLResponseHandler` auth/respondent/3-state logic; possibly host the new `SuspendedExecutionStore` + envelope models |
| `parrot/clients/*.py` (`resume`) | depends on | no change expected; verify `messages` accumulation for multi-turn (OQ-6) |
| `autonomous/orchestrator.py` | reference | already implements the same suspend/resume contract; keep shapes aligned |
| `SuspendedExecution` (new model) | new | Redis blob keyed by `interaction_id`, TTL-aligned |
| Frontend (`navigator-frontend-next`) | depends on | new `paused` envelope contract (separate frontend spec; see FEAT-146 brainstorm precedent) |

---

## Code Context

### User-Provided Code
Source: `sdd/proposals/hitl_web.proposal.md` (design note, verbatim intent).

```python
# Proposed (does NOT yet exist) — from the proposal §3 Decision A
class WaitStrategy(str, Enum):
    BLOCK = "block"            # current: in-memory Future (live channel / single process)
    SUSPEND = "suspend"        # web stateless: register + raise interrupt
    HOT_THEN_SUSPEND = "hot"   # hybrid documented in the manager (future)

HumanTool(manager=..., wait_strategy=WaitStrategy.SUSPEND)

# Proposed (does NOT yet exist) — from the proposal §5
class SuspendedExecution(BaseModel):
    interaction_id: str
    session_id: str
    user_id: str
    agent_name: str
    tool_call_id: str
    messages: list[dict]          # provider-shaped message history
    created_at: datetime
```

### Verified Codebase References

> Path note: HITL core (`human/`, `clients/`, `core/exceptions.py`,
> `bots/agent.py`) lives in **`packages/ai-parrot/src/parrot/`**. The web layer
> (`handlers/agent.py`, `handlers/web_hitl.py`, `autonomous/orchestrator.py`)
> lives in **`packages/ai-parrot-server/src/parrot/`**. (The FEAT-146 frontend
> brainstorm's appendix paths are stale — files moved to `ai-parrot-server`.)

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/human/tool.py
class HumanToolInput(AbstractToolArgsSchema):  # lines 31-141
    question: str                              # min_length=1
    interaction_type: str = "free_text"
    options: Optional[List[Union[str, Dict[str, Any]]]] = None
    context: Optional[str] = None              # max_length=280
    timeout: float = 7200.0                    # gt=0, le=7*24*3600
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None
    target_humans: Optional[List[str]] = None
    policy_id: Optional[str] = None
    severity: Literal["low","normal","high","critical"] = "normal"

class HumanTool(...):                          # lines 143-394
    name = "ask_human"
    args_schema = HumanToolInput
    async def _execute(self, **kwargs) -> Any: ...   # 247-351; awaits request_human_input() at 335 (BLOCKS)

# packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:
    def _compute_ttl(self, interaction) -> int: ...                          # 141-160 (timeout + 60, multi-tier aware)
    async def is_valid_respondent(self, interaction_id, respondent) -> bool: # 222-246 (fails closed)
    async def request_human_input(self, interaction, channel="telegram") -> InteractionResult: ...   # 269-346 BLOCKS
    async def request_human_input_async(self, interaction, channel="telegram") -> str: ...           # 471-509 returns interaction_id
    async def advance_chain(self, interaction_id, cause="timeout") -> None: ...                       # 521-574
    async def receive_response(self, response: HumanResponse) -> None: ...                            # 580+
    async def _handle_timeout(self, interaction, channel) -> None: ...                                # 859-905
    # _handle_timeout docstring: "Works for both long-polling and suspend/resume modes —
    #   action helpers fall back to _trigger_rehydration when no future is registered."
    # also: has_pending(interaction_id), get_result(interaction_id)

# packages/ai-parrot/src/parrot/core/exceptions.py
class HumanInteractionInterrupt(ParrotError):
    def __init__(self, prompt, interaction_id=None, policy_id=None, *a, **k): ...
    # attrs: prompt, interaction_id, policy_id, state, tool_call_id, agent_name, messages

# packages/ai-parrot/src/parrot/clients/claude.py
async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage:  # 479-578
    messages = state["messages"]; tool_call_id = state["tool_call_id"]
    messages.append({"role":"user","content":[{"type":"tool_result",
        "tool_use_id": tool_call_id, "content": user_input}]})   # 502-509
    # on nested interrupt: enriches e.session_id/e.messages/e.tool_call_id/e.agent_name (551-557)

# packages/ai-parrot-server/src/parrot/handlers/web_hitl.py
class WebHumanTool(HumanTool):                       # 100-197 — BLOCKS via super()._execute()
class HITLResponseBody(BaseModel):                   # 205-227 — {interaction_id, value, response_type?}
class HITLResponseHandler(BaseView):                 # 251-424 — POST /api/v1/agents/hitl/respond
    # respondent from request.session["user_id"] (313); 3-state check has_pending/get_result (331-342);
    # is_valid_respondent gate (345); ESCALATE_OPTION_KEY -> advance_chain (360-383); receive_response (402)
current_web_session: ContextVar[Optional[str]]       # 53
async def setup_web_hitl(app) -> None:               # 432-496

# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(...):
    async def post(self):                            # 1245
        _hitl_token = set_current_web_session(ws_channel_id or session_id)   # 1405
        ...
        response = await bot.ask(question=query, ...)                        # 1555

…(truncated)…
