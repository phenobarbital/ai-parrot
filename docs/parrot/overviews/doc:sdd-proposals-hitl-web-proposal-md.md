---
type: Wiki Overview
title: FEAT-XXX — HITL over Web Request/Response (AgentTalk HTTP)
id: doc:sdd-proposals-hitl-web-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The AI-Parrot HITL stack (`parrot/human/`) lets an agent ask a human for
---

# FEAT-XXX — HITL over Web Request/Response (AgentTalk HTTP)

> **Status:** Brainstorm (pre-spec). Design-level only.
> Codebase contract (verified imports, exact signatures, line numbers) is
> deferred to `/sdd-spec`. This document fixes the architecture and the two
> arrival decisions, and bounds scope against the escalation work.

---

## 1. Problem

The AI-Parrot HITL stack (`parrot/human/`) lets an agent ask a human for
input via `HumanTool` (`ask_human`). Today that tool **blocks**: it calls
`HumanInteractionManager.request_human_input()`, which registers an in-memory
`asyncio.Future` and awaits the human reply, resolved by a *live channel*
(CLI inline, Telegram webhook, Web WebSocket).

Our production medium is **plain web REST via the AgentTalk HTTP handler** —
stateless by default (only the user session persists). There is no live
channel to push a question to and no process kept alive to await a Future.

The interaction model we want mirrors the existing **follow-up** mechanism
(`turn_id` ↔ `answer_memory`):

1. The agent decides it needs human input mid-reasoning.
2. The pending interaction + the agent's execution state are **serialized**.
3. The question and a correlation id travel to the frontend **as the HTTP
   response body** (status `paused`).
4. The frontend renders the question and, on the next call, sends the human's
   answer back **tagged as a HITL response** carrying that id.
5. The handler loads the serialized state, injects the answer **as the
   `tool_result` of the pending `ask_human` call**, and resumes the tool-loop
   to a final answer.

The transport is the request/response cycle itself — no WebSocket, no Telegram.

---

## 2. What already exists (and where)

The suspend → serialize → resume machinery is implemented in **two of the
three** layers; only the web layer is missing.

- **Client layer (`clients/*.py`):** `resume(session_id, user_input, state)`
  already replays `state["messages"]` into a fresh chat and injects
  `user_input` **as a `tool_result` keyed by `state["tool_call_id"]`** when the
  pause happened inside a tool call (else as a `user` turn), then continues the
  tool-call loop like `ask()`. This is exactly "resume the same reasoning with
  the human answer placed where the model expects it."
- **Orchestrator layer (`autonomous/orchestrator.py`):** `_execute` catches
  `HumanInteractionInterrupt` and returns an `ExecutionResult` with
  `status="paused"`, `metadata.prompt`, and
  `metadata.state = {session_id, messages, tool_call_id, agent_name}`.
  `resume_agent(session_id, user_input, state)` then calls `agent.resume(...)`.
- **`HumanInteractionInterrupt`** carries `prompt` + `interaction_id` +
  `policy_id`, and the **client tool-loop enriches it** with `messages` and
  `tool_call_id` before it bubbles (the orchestrator reads them via `getattr`).
- The tool wired to this path today is **`HandoffTool` (deprecated)** — it
  *raises* the interrupt but exposes only a `prompt` + `policy_id` schema
  (free-text only; no structured interaction types).

**Gap:** the AgentTalk HTTP handler + `BasicAgent.ask()` path neither catches
the interrupt nor exposes a resume entry point, and `HumanTool` blocks instead
of suspending.

---

## 3. Arrival decisions (FIXED)

### Decision A — Add a `wait_strategy` to `HumanTool`; do **not** revive `HandoffTool`

Two orthogonal axes were being conflated:

- **Interaction semantics** — what is asked, the `InteractionType`
  (`approval` / `single_choice` / `form` / …), options, severity, policy.
- **Wait strategy** — block-and-await (live channel, single process) vs
  register-and-suspend (stateless HTTP).

`HandoffTool` is not "the suspend tool"; it is a *poorer* tool that happens to
suspend (free-text only). Reviving it for web would lose structured types —
precisely what renders best in the SvelteKit frontend (buttons / forms) — and
would expose **both** `ask_human` and `handoff_to_human` to the LLM depending
on deployment, making the **agent definition transport-aware**. That breaks the
abstraction: the agent declares `ask_human`, full stop; block vs suspend is a
wiring decision.

Factor a `wait_strategy` into `HumanTool`, **not exposed to the LLM** (same
philosophy `HumanToolInput` already applies to consensus / escalation /
timeout_action):

```python
class WaitStrategy(str, Enum):
    BLOCK = "block"            # current: in-memory Future (live channel / single process)
    SUSPEND = "suspend"        # web stateless: register + raise interrupt
    HOT_THEN_SUSPEND = "hot"   # hybrid documented in the manager (future)

HumanTool(manager=..., wait_strategy=WaitStrategy.SUSPEND)
```

In `SUSPEND`, `HumanTool._execute`:

1. Builds the **rich** `HumanInteraction` exactly as today (options /
   form_schema / severity preserved).
2. Calls `request_human_input_async()` — persists to Redis and, since no
   channel is registered in the web deployment, **skips dispatch on its own**
   (the existing `if channel in self.channels` guard).
3. Raises `HumanInteractionInterrupt(interaction_id=...)`; the client tool-loop
   enriches it with `messages` + `tool_call_id` (existing, reusable — lives in
   the client loop, not in `HandoffTool`).

> **No hot-wait in pure web.** The human reply arrives by definition in a
> *separate* HTTP request, so the `HOT_THEN_SUSPEND` 500 ms poll is noise here.
> Immediate suspend. `HOT_THEN_SUSPEND` stays reserved for live channels.

**Structured types survive the round-trip:** the interrupt carries only the
`interaction_id`; the AgentTalk handler **rehydrates the full
`HumanInteraction` from `hitl:interaction:{id}`** to build the paused
`AgentResponse` with `options` / `form_schema` for the frontend to render.
`HandoffTool` is left dead.

### Decision B — Lazy TTL expiry via Redis + result tombstone; no active timeout task in SUSPEND

No "expired" flag is needed. The Redis TTL on `hitl:interaction:{id}` already
expires the question by absence (`_compute_ttl` = `timeout` + buffer). On the
inbound answer:

- `hitl:result:{id}` present → **already answered** (replay / double-submit
  guard — `receive_response` already persists this, reused as a tombstone).
- `hitl:interaction:{id}` present, no result → **alive** → resume.
- Neither present → **expired or unknown** → fast reply "that question
  expired." (Three states, not two — distinguishes expired vs never-existed vs
  answered.)

> **Do not schedule the `_handle_timeout` asyncio task in SUSPEND mode.** It
> dies when Fargate recycles the worker anyway and only leaves orphaned tasks.
> Rely on TTL + lazy check.

**Lazy covers cancel-on-expire only.** Proactive timeout actions
(`ESCALATE` / `RETRY` / proactive `DEFAULT`) need someone acting *at expiry*,
not *on return* → see §6, out of scope here.

---

## 4. Proposed flow

### 4.1 Suspend (agent asks)

```
POST /agent/ask  {question, session_id, user_id}
  └─ BasicAgent.ask()
       └─ client tool-loop → LLM calls ask_human
            └─ HumanTool._execute (SUSPEND)
                 ├─ build rich HumanInteraction
                 ├─ manager.request_human_input_async()  # persist hitl:interaction:{id}, skip dispatch
                 └─ raise HumanInteractionInterrupt(interaction_id)
       └─ client loop enriches interrupt: + messages + tool_call_id
  └─ ask() lets it bubble (NEW: today only the orchestrator catches it)
  └─ AgentTalk handler catches HumanInteractionInterrupt (NEW)
       ├─ persist SuspendedExecution{messages, tool_call_id, agent_name, session_id, interaction_id}  # §5
       ├─ rehydrate HumanInteraction from hitl:interaction:{id}
       └─ return AgentResponse(status="paused", question=..., interaction_id=..., options/form_schema)
```

### 4.2 Resume (human answers)

```
POST /agent/ask  {hitl_response: {interaction_id, value}, session_id, user_id}
  └─ AgentTalk handler detects HITL-response tag (NEW)
       ├─ manager.is_valid_respondent(interaction_id, session-derived respondent)
       ├─ tombstone/TTL check (Decision B): result? → "already answered";
       │                                     missing? → "expired"
       ├─ manager.receive_response(HumanResponse(interaction_id, respondent, value))
       │     # persists hitl:result, keeps audit / consensus / policy bookkeeping coherent
       ├─ load SuspendedExecution{...}
       └─ agent.resume(session_id, user_input=value, state)   # inject as tool_result(tool_call_id)
            └─ client continues tool-loop → final AgentResponse(status="success")
```

> **Route through `receive_response` AND `resume`.** Minimal path is
> persist-state + resume, but going through `receive_response` first keeps the
> HITL ledger (`hitl:result`, consensus, future policy) consistent, then we
> resume. (Open question OQ-3 on whether single-user web ever needs consensus.)

---

## 5. New component — `SuspendedExecutionStore`

`answer_memory[turn_id]` stores `{question, answer}` — enough to rebuild a
follow-up *prompt*. HITL resume needs the *tool-loop* state.

```python
# Redis blob keyed by interaction_id (TTL aligned with hitl:interaction TTL)
class SuspendedExecution(BaseModel):
    interaction_id: str
    session_id: str
    user_id: str
    agent_name: str
    tool_call_id: str
    messages: list[dict]          # provider-shaped message history
    created_at: datetime
```

- Key: `hitl:suspended:{interaction_id}` (or fold into `hitl:callback:` — OQ-2).
- TTL: same window as `hitl:interaction:{id}` so expiry stays coherent and
  lazy (Decision B).
- `messages` are provider-shaped (OpenAI-style dicts) to match what `resume()`
  already replays — confirm shape per client in `/sdd-spec`.

---

## 6. Out of scope — reserved seam for escalation (separate brainstorm)

Proactive escalation (`EscalationPolicy` / `EscalationTier`, `advance_chain`,
`select_starting_tier`, business hours, `EscalationActionType`
INTERACT/NOTIFY/TICKET, events `hitl.tier.*`) **already exists in the manager**
but is driven by an in-process timeout task. In a stateless deployment nobody
is alive at expiry, so a separate **proactive escalation driver** (qworker
scheduled sweep or listener) is required. That is its own feature.

**This feature must not foreclose it:**

- `SuspendedExecutionStore` TTL and `timeout_action` handling at resume time
  must be forward-compatible with a future sweeper reading the same keys.
- Do not delete `hitl:interaction:{id}` early; let TTL own expiry so a sweeper
  can observe pending interactions.
- Keep `policy_id` / `severity` on the persisted `HumanInteraction` even though
  SUSPEND ignores proactive actions for now.

---

## 7. Open questions for `/sdd-spec`

- **OQ-1:** Correlation id contract — does the frontend receive the raw
  `interaction_id`, or a `turn_id` wrapping it, so follow-up and HITL-response
  share one correlation contract?
- **OQ-2:** `SuspendedExecution` storage — new `hitl:suspended:` key vs
  extending `hitl:callback:`. Size/serialization of `messages` per provider.
- **OQ-3:** Always route through `receive_response`, or skip it for the
  single-user web case and resume directly? (Audit/consensus vs simplicity.)
- **OQ-4:** Idempotency/replay — `receive_response` dedupes by `respondent`,
  but `resume()` is not idempotent. Lock/lease on `interaction_id` during
  resume? Tombstone-before-resume ordering.
- **OQ-5:** Does `BasicAgent.ask()` (and every client tool-loop) currently let
  `HumanInteractionInterrupt` bubble, or is it swallowed anywhere outside the
  orchestrator? (Read AgentTalk handler + `ask()` before spec.)
- **OQ-6:** Multi-turn HITL — an agent that asks twice in one logical task
  (chained suspends). Does `messages` accumulation in `resume()` handle a second
  `ask_human` cleanly?
- **OQ-7:** Auth — deriving `respondent` from the authenticated session for
  `is_valid_respondent`, and rejecting cross-session answer injection.
