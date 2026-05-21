---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: HITL Multi-Tier Escalation Policy (per-agent) + HumanTool/HandoffTool Unification

**Date**: 2026-05-21
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot has **two parallel Human-in-the-Loop (HITL) paths** that don't share
a model of escalation:

1. `parrot.human.*` — rich, async, multi-channel (CLI / Telegram / Web).
   Provides `HumanTool`, `HumanDecisionNode`, `HumanInteractionManager`,
   consensus modes, timeouts. **Escalation is a single flat hop**: on
   `TimeoutAction.ESCALATE`, the manager re-emits the *same* interaction to
   `escalation_targets` over the *same* channel. There is no concept of tiers,
   no concept of *changing the medium* (ticket / email / live chat link),
   and no policy declared at the agent level.

2. `parrot.core.tools.handoff.HandoffTool` — synchronous, in-band with the
   active chat (Telegram / Slack / Teams). Raises `HumanInteractionInterrupt`,
   the `AutonomousOrchestrator` catches it, suspends the agent, sends the prompt
   to the same user, then resumes. Useful for "missing parameter" prompts but
   has no targets, no consensus, no timeouts, no escalation, and bypasses
   `HumanInteractionManager` entirely.

Real-world HITL escalations are not "ask the same question to a backup person."
They follow business rules driven by **criticality + tier-specific actions**:

- **L0** (the active chat user) — "missing project key?"
- **L1** (on-call human group) — "approve before deletion?"
- **L2** — open a ticket in Zammad / Zendesk
- **L3** — generate a deep-link so the user can chat with a live support agent
- **L4** — email the manager / director

These actions are **heterogeneous** (not the same "send the prompt again") and
must be **per-agent** (an HR agent escalates to HR managers; a Finance agent
escalates to a Finance director). The manager today cannot represent any of this.

### Who is affected

- **Agent authors** — today they cannot declare escalation rules on the agent;
  they bolt them on at runtime via plain `escalation_targets` lists.
- **End users** — when no human is available, the agent either hallucinates,
  fails, or stays blocked. There is no ticket-fallback path.
- **Ops / support** — no audit trail of which tier handled which interaction;
  no way to reroute to a ticketing system when chat-based humans are off-hours.

### Why now

- FEAT-045 (Handoff) is in production; FEAT-187 settled the branch flow; HITL
  channels (CLI, Telegram, Web) are stabilised. The HITL surface is mature
  enough that the next blocker is **policy expressiveness**, not channels.
- The `HumanInteractionInterrupt` exception already exposes `interaction_id`
  and `policy_id` slots (`parrot/core/exceptions.py:11-40`) — i.e., the
  codebase has already started reserving room for a policy-driven bridge.
  Time to land it.

---

## Constraints & Requirements

- **Backwards compatible**: existing `HumanTool`/`HumanDecisionNode`/
  `HandoffTool` agents must keep working with zero code changes. Policies are
  *opt-in*. `escalation_targets` (flat list) keeps working and is interpreted
  as "single AskAlternateHumansAction tier".
- **HandoffTool stays as a deprecated alias** (per Round 2 decision) — its
  callers in `parrot/agents/demo.py:194` and ad-hoc integrations must keep
  working; only a deprecation warning is emitted.
- **Fire-and-forget for async actions** (per Round 2 decision) — when a tier
  opens a ticket or sends an email, the `ask_human` call resolves immediately
  with a confirmation string (e.g., `"[escalated:ticket] TKT-123 opened"`). No
  cross-channel correlation in V1; the ticket / email lives on its own.
- **Per-agent policy granularity** (per Round 1 decision) — the
  `EscalationPolicy` is owned by the Agent class, not by individual tools or
  by a global registry. Tools and toolkits inherit.
- **Policy injection happens in `HumanTool.__init__`** (per Round 1 decision) —
  the agent passes its policy to the tool; the tool serialises a reference
  on each `HumanInteraction`; the manager reads it when escalating. No global
  registry lookup in V1.
- **Triggers in V1**: `TIMEOUT` (already exists), `EXPLICIT_REJECT` (new —
  button + lightweight intent detection), `SEVERITY` (new — declarative param
  on `ask_human`), `BUSINESS_HOURS_OFF` (new — per-tier hours window).
- **Actions in V1**: `AskAlternateHumansAction` (refactor of current behaviour),
  `OpenTicketAction` (Zammad first; Zendesk as second adapter), `LiveChatHandoffAction`
  (deep-link generator), `EmailAction` (SMTP via existing `parrot/handlers/agents/abstract.py:581`
  config keys).
- **Persistence**: must reuse Redis (`REDIS_URL` from `parrot.conf`), same
  `hitl:*` key namespace. No new datastore in V1. Tier transitions are
  logged but do *not* require infinite TTL — once a tier's action resolves
  (ticket opened, email sent), the interaction is closed.
- **No new external dependency unless it pulls its weight** — prefer adapters
  over heavy SDKs. Zammad/Zendesk via `aiohttp` against their REST API;
  email via `aiosmtplib` (already in dep tree for handlers).
- **Channels MUST opt-in to the explicit-reject button** — `HumanChannel`
  base class adds an optional hook; channels that don't render it (CLI in
  daemon mode) fall back to intent detection only.

---

## Options Explored

### Option A: Per-Agent `EscalationPolicy` + Pluggable `EscalationAction` Strategies

The agent declares an `EscalationPolicy` containing an ordered list of
`EscalationTier`s. Each tier carries a `Trigger` (when to fire), an
`EscalationAction` (what to do — pluggable strategy class), `targets`, an
optional `channel` override, and an optional `business_hours` window. The
`HumanTool` reads the policy from `self.escalation_policy` at construction
time, attaches a *reference* (policy_id) and the resolved chain to the
`HumanInteraction`. The `HumanInteractionManager` is refactored so its
existing `_escalate` becomes a loop that, on trigger fire, looks up the
*next applicable tier* and calls `await action.execute(interaction, tier, ctx)`
instead of always re-emitting the same interaction.

Severity is a new parameter on the `ask_human` tool input
(`severity: Literal["low", "normal", "high", "critical"] = "normal"`).
The manager's tier-advance loop uses severity to pick the *starting tier*
(skip L0/L1 when severity=critical).

`HandoffTool` is kept; its `_execute` is rewritten to build a
`HumanInteraction` with `target_humans=["__current_user__"]`,
`escalation_policy=None`, and dispatch via the same manager. A deprecation
warning is emitted.

**Bridge to `HumanInteractionInterrupt`**: when the orchestrator catches the
interrupt, it already has `interaction_id` and `policy_id` available
(`parrot/core/exceptions.py:22-36`). For escalation-flagged interactions, the
orchestrator does NOT block waiting (fire-and-forget); the tool returns a
confirmation string directly to the LLM.

✅ **Pros:**
- Closest mapping to the user's real-world model ("Tier 1 / Tier 2 / Tier 3
  do different things").
- Single source of truth lives on the Agent — easy to test in isolation, easy
  to compose (an agent factory can attach a shared policy to many agents).
- Reuses the existing `HumanInteractionManager` machinery; only `_escalate`
  changes shape (loop instead of single hop) plus a new `EscalationAction`
  port.
- Zero breakage for existing flat `escalation_targets` callers — interpreted
  as one `AskAlternateHumansAction` tier behind the scenes.
- The `HumanInteractionInterrupt` slots already exist — minimal orchestrator
  surgery to honour `policy_id`.
- Honest about V1 limits (fire-and-forget) — no fake "we'll wait for the
  ticket" path that would require months of cross-channel correlation work.

❌ **Cons:**
- New abstractions (Policy, Tier, Trigger, Action) — more cognitive load for
  agent authors. Mitigation: ship 3-4 prebuilt policies (`SimpleHITLPolicy`,
  `TicketingFallbackPolicy`, `BusinessHoursPolicy`).
- Per-agent injection means *no runtime reconfiguration* — to change a
  policy you must restart. Acceptable for V1; PolicyRegistry can be added
  later (Option B) without breaking the API.
- Adds 4 new action implementations to test (3 if Zendesk is deferred).

📊 **Effort:** Medium (≈ 8–12 tasks: models, manager refactor, 4 actions,
HumanTool injection, HandoffTool aliasing, channel reject-button hook,
docs/tests).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiosmtplib` (≥ 3.0) | `EmailAction` async SMTP send | Already wired indirectly via `parrot/handlers/agents/abstract.py` smtp_host config keys |
| `aiohttp` (existing) | Zammad/Zendesk REST clients | Project policy: no `requests`/`httpx` |
| `python-dateutil` / `pytz` (existing in deps) | Business-hours timezone math | Avoid `zoneinfo`-only solution (Windows quirks) |
| `pydantic` ≥ 2 (existing) | Policy / Tier / Action config models | Use discriminated unions for `EscalationAction` config (`type: "ticket"` vs `type: "email"`) |

🔗 **Existing Code to Reuse:**
- `parrot/human/manager.py` (`_escalate`, lines 634–699) — refactor into a
  loop-based escalator that delegates to `EscalationAction.execute`.
- `parrot/human/models.py` (`HumanInteraction`, `TimeoutAction`, lines 60–90) —
  extend `escalation_targets: List[str]` to `escalation_policy_ref: Optional[str]`
  (policy_id) plus a denormalised `escalation_chain: Optional[List[EscalationTier]]`
  for crash-recovery.
- `parrot/human/tool.py` (`HumanTool.__init__`, lines 126–139) — add
  `escalation_policy: Optional[EscalationPolicy]` constructor kwarg.
- `parrot/core/tools/handoff.py` (lines 22–44) — rewrite `_execute` to delegate
  to `HumanInteractionManager`; emit `DeprecationWarning` once per process.
- `parrot/core/exceptions.py:11–40` — `HumanInteractionInterrupt` already
  carries `policy_id`. No change needed.
- `parrot/human/channels/base.py` (lines 11–70) — add optional
  `render_reject_button: bool = False` class attribute; channels that
  support it set `True` and inject "↑ Escalar" into every interaction.
- `parrot/integrations/manager.py:154–168` (`_ensure_human_manager`) —
  unchanged; manager stays a singleton, only its `_escalate` gets the loop.
- `parrot/handlers/agents/abstract.py:581–584` — reuse the same SMTP config
  keys for `EmailAction`.

---

### Option B: Global `EscalationPolicyRegistry` (manager-driven lookup)

Same `EscalationPolicy` data model as Option A, but policies live in a
process-wide `EscalationPolicyRegistry` (string id → policy). The agent only
sets a `policy_id` (e.g., `"hr_default"`); the `HumanInteractionManager`
calls `registry.get(policy_id)` whenever it needs to escalate. Policies can
be loaded from YAML/JSON, hot-reloaded from a config endpoint, or scoped
per-tenant.

✅ **Pros:**
- Runtime reconfiguration — change a policy without restarting agents.
- Cleaner separation: agents declare *intent* (a policy_id), ops controls
  *behaviour* (registry contents).
- Easier multi-tenant scenarios (one agent class, many tenant-specific
  policies).
- Symmetric with the existing pattern of `set_default_human_manager`
  (`parrot/human/__init__.py:54`) — same "process-wide registry of HITL
  infrastructure" mental model.

❌ **Cons:**
- More moving parts: agent → policy_id → registry → policy → tier → action.
- Registry becomes another global state to test, to seed, to clear between
  tests. The current global `_default_manager` already produced subtle
  test-isolation bugs.
- Doesn't match how AI-Parrot agents are typically built today — they wire
  their tools and policies in `agent_tools()` factory methods; a registry
  feels alien.
- The user explicitly chose "injection in HumanTool" in Round 1.

📊 **Effort:** Medium (similar to A: ≈ 9–13 tasks, +1 for registry +1 for
hot-reload + tests).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Same as A plus | | |
| `pyyaml` (existing) | Load policies from YAML files | Optional — JSON works too |

🔗 **Existing Code to Reuse:**
- Everything from Option A.
- `parrot/human/__init__.py:51-62` (`_default_manager` pattern) — mirror it
  for `_default_policy_registry`.

---

### Option C: Event-Bus driven escalation (FEAT-176 EventEmitter pattern)

Instead of a `Tier` calling an `Action` directly, the manager emits a
domain event (`interaction.timeout`, `interaction.rejected`,
`interaction.severity_set`) on the existing `EventEmitterMixin` bus
(used by `AbstractTool`, `parrot/tools/abstract.py:78`). Independent
subscribers (`TicketingEscalator`, `EmailEscalator`, `LiveChatEscalator`)
listen and act when their predicate matches. The "policy" is really a
collection of registered subscribers with priority ordering.

✅ **Pros:**
- Maximum decoupling — adding a new escalation behaviour means writing one
  subscriber, no manager change.
- Naturally observable — every escalation step becomes an event that can
  be logged, traced, replayed.
- Plays well with future FEAT-192 (graph/community signals) and any
  observability pipeline.

❌ **Cons:**
- Hard to *reason* about ordering / preemption when many subscribers can
  fire. "Did L2 actually fire before L3?" becomes a timing puzzle.
- Per-agent scoping is awkward — subscribers are global by nature; we'd
  need a `policy_filter` on each event or a per-agent EventBus, both of
  which reintroduce the registry problem.
- Less explicit contracts — the agent author can't look at one place and
  see "this is what happens when I get timed out."
- Heavier mental load than the user's stated mental model
  ("Tier 1 abre ticket; Tier 2 manda link; Tier 3 mail").

📊 **Effort:** High (≈ 14–18 tasks: event schema, subscriber registry, 4
escalator subscribers, agent-scoped filtering, ordering guarantees, tests
including race conditions).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.events.EventBus` (existing internal) | Event transport | Confirm capacity for ordered delivery |

🔗 **Existing Code to Reuse:**
- `parrot/tools/abstract.py:78` (`EventEmitterMixin`).
- `parrot/autonomous/orchestrator.py:526-538` (existing event emissions).

---

### Option D (unconventional): LLM-driven policy interpretation

The policy is declared as a *natural-language ruleset* on the agent (or in a
config file): "If the user asks for help with payroll outside business hours,
escalate to Carla via Telegram. If she doesn't reply in 2h, open a ticket.
For anything tagged 'urgent', email the manager immediately." At
escalation-decision time, a small LLM (Haiku, Groq-Llama-3.1-8B) reads the
ruleset + the interaction context + the human's reply (if any) and returns
a structured `(action, targets)` decision.

✅ **Pros:**
- Authoring policies in plain English is dramatically faster than configuring
  structured tiers.
- Adapts to nuance the structured model can't catch ("the user sounds
  furious in their last reply → skip L1, go to L3 manager").
- Lines up well with the user's "intent detection with a lightweight LLM"
  preference from Round 3 — the same LLM could do *both* reject-detection
  and policy interpretation.

❌ **Cons:**
- Adds latency (one LLM round-trip per escalation decision) to a flow that
  is already slow because humans are involved — usually fine, but breaks the
  "deterministic test" expectation for SDD-QA-style validation.
- Non-deterministic / harder to audit — "why did the bot choose Tier 3
  instead of Tier 2?" becomes an LLM-explanation problem.
- Adds a runtime LLM dependency to a code path that today has none. If the
  LLM provider is down, no escalation happens.
- Hard to express precise SLAs ("must escalate within 30s of timeout") when
  the deciding component is itself an LLM call.
- Requires a fallback to structured rules anyway for unit tests and CI.

📊 **Effort:** High (≈ 12–16 tasks: prompt engineering, LLM choice + retry,
fallback to structured rules, deterministic test seam, audit log of LLM
decisions, schema for output validation).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.clients.groq` (existing) | Fast LLM for policy interpretation | Already vetted |
| `pydantic` | Structured output validation | Same as A |

🔗 **Existing Code to Reuse:**
- `parrot/clients/groq.py` (Groq client).
- The structured `EscalationPolicy` from Option A as the *fallback* path.

---

## Recommendation

**Option A** is recommended.

Reasoning:

1. **It matches the user's stated mental model and explicit Round-1 choices**
   (per-agent scope, injection in `HumanTool`). Going against those would
   produce a brainstorm that the spec phase would just revert.
2. **It minimises orchestrator surgery.** The `HumanInteractionInterrupt`
   slots (`interaction_id`, `policy_id`) already exist; the orchestrator
   catches the interrupt; the only behavioural change is "for
   escalation-flagged interactions, do not re-enter the suspend/resume loop —
   resolve with the confirmation string." The rest of the work happens
   inside `HumanInteractionManager`, which is the right place for it.
3. **It reuses every existing piece**: Redis, channels, `_escalate`,
   `HumanResponse` model, `register_response_handler`. The new abstractions
   (`EscalationTier`, `EscalationAction`) plug *into* the existing manager;
   they don't replace it.
4. **It's honest about V1 limits.** Fire-and-forget for async actions means
   no cross-channel correlation work in this iteration — that becomes a
   future spec ("ticket reply → resume agent") with its own brainstorm.
5. **It leaves the door open to Option B and Option D as v2.** A future
   `PolicyRegistry` (B) can be added without changing the on-the-wire
   contract — `HumanTool` would just look up `self.escalation_policy or
   registry.get(self.policy_id)`. An LLM-driven layer (D) can be a *pre*
   stage that picks the starting tier given a structured policy.

What we're trading off vs. the alternatives:

- vs. B: we give up runtime reconfiguration. Acceptable — restart-to-reconfig
  is the AI-Parrot norm today; a registry can be retrofitted later without
  breakage.
- vs. C: we give up the elegance of event-driven decoupling. Acceptable —
  the policy lives in a place agent authors expect to find it (on the
  agent), and the manager loop is easy to step-debug.
- vs. D: we give up natural-language policy authoring. Acceptable for V1 —
  structured tiers are easier to test, audit, and reason about. D can be
  added on top as an optional "tier-picker LLM."

---

## Feature Description

### User-Facing Behavior

**For agent authors:**

```python
# Declarative policy attached to an HR agent
hr_policy = EscalationPolicy(
    id="hr_default",
    tiers=[
        EscalationTier(
            level=1,
            label="HR on-call",
            trigger=TimeoutTrigger(seconds=900),  # 15 min
            action=AskAlternateHumansAction(targets=["telegram:@hr-oncall"]),
            channel="telegram",
        ),
        EscalationTier(
            level=2,
            label="Ticket fallback",
            trigger=TimeoutTrigger(seconds=7200),  # 2 hours since L1
            action=OpenTicketAction(
                platform="zammad", queue="HR-L2",
                title_template="HITL escalation: {interaction.question}",
            ),
            business_hours=BusinessHours(  # tier-level (Round 2 decision)
                tz="Europe/Madrid", days="mon-fri", hours="09:00-18:00",
            ),
        ),
        EscalationTier(
            level=3,
            label="Manager",
            trigger=SeverityTrigger(min_severity="high"),
            action=EmailAction(
                to=["hr-manager@example.com"],
                subject_template="[L3 escalation] {interaction.question}",
            ),
        ),
    ],
)

HRAgent(
    name="hr_bot",
    tools=[
        HumanTool(escalation_policy=hr_policy, default_channel="telegram"),
        # ... other tools
    ],
)
```

**For the LLM (tool description excerpt):**

```text
ask_human(question, ..., severity="normal")
    severity: one of 'low' | 'normal' | 'high' | 'critical'.
        Default 'normal'. Use 'high' or 'critical' for irreversible,
        compliance-sensitive, or time-pressured situations — the agent's
        escalation policy may skip lower tiers based on this value.
```

**For the end human (on Telegram):**

```
🤖 Bot: Need to delete account #1234. Confirm?
       [ ✅ Approve ]  [ ❌ Reject ]  [ ↑ Escalar ]   ← NEW reject/escalate button
```

- If the human taps **↑ Escalar**, the manager treats it as `EXPLICIT_REJECT`
  and advances to the next tier.
- If the human types something like *"no puedo, pasame con un humano"*, a
  lightweight LLM intent classifier converts that to the same
  `EXPLICIT_REJECT` (Round 3 decision: button + LLM intent detection).

**For the agent caller (return value):**

- Tier reached a human → returns the human's answer (today's behaviour).
- Tier opened a ticket → returns `"[escalated:ticket:zammad] Ticket TKT-123 opened. A human will follow up there."`
- Tier sent an email → returns `"[escalated:email] Notified hr-manager@example.com. A human will follow up."`
- Tier generated a chat link → returns `"[escalated:live_chat] Tap the link in the chat to connect with a live agent."`

### Internal Behavior

```
┌─────────────────────────────────────────────────────────────────────┐
│  Agent → HumanTool.execute(question, severity="high")               │
│      builds HumanInteraction with escalation_chain from policy      │
│      → HumanInteractionManager.request_human_input(interaction)     │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │
                                       ▼
            ┌─────────────────────────────────────────────────┐
            │ select_starting_tier(policy, severity)          │
            │   severity=high → start at L2 (skip L0/L1)      │
            │   check tier.business_hours; if OFF → next tier │
            └──────────────────────────────┬──────────────────┘
                                           │
                       ┌───────────────────┴────────────────────┐
                       ▼                                        ▼
              ┌────────────────────┐                ┌────────────────────┐
              │ tier.action is     │                │ tier.action is     │
              │ AskAlternateHumans │                │ OpenTicket / Email │
              │ (synchronous)      │                │ / LiveChat (async) │
              └─────────┬──────────┘                └─────────┬──────────┘
                        │                                     │
              Dispatch via channel,                  Call action.execute()
              start timeout task,                    → returns confirmation
              wait for human OR                      → set result, persist,
              trigger fire.                          → resolve future immediately
                        │
              On TIMEOUT or EXPLICIT_REJECT:
              advance_to_next_tier(current, policy)
                        │
                        ▼
              Loop until tier resolves OR
              chain exhausted (→ CANCEL/TIMEOUT).
```

Key responsibilities:

- **`EscalationPolicy.resolve_chain(severity, now)`** — returns the ordered
  list of *applicable* tiers (skipping severity-floored and off-hours ones).
  Pure function, easy to unit-test.
- **`EscalationAction.execute(interaction, tier, ctx) -> EscalationOutcome`**
  — abstract. Outcomes: `RESOLVED(human_value)`, `ASYNC_HANDLED(message)`,
  `FAILED(reason)`. `FAILED` advances to the next tier; `ASYNC_HANDLED` closes
  the interaction with the confirmation message.
- **Manager loop** — `_escalate` becomes `_advance_chain`. It picks the next
  tier whose trigger matches the cause-of-advance (TIMEOUT, REJECT, SEVERITY)
  and calls its action.
- **`HumanChannel.render_reject_button`** — optional opt-in attribute.
  Telegram/Web set `True`; CLI sets `False`. When `True`, the channel
  appends a standard "↑ Escalar" button/option to every rendered interaction.
- **`RejectIntentDetector`** — small classifier called by the manager when
  a free-text response is received: if intent == "escalate", treat the
  response as `EXPLICIT_REJECT` instead of an answer. Implementation can
  start with a regex of canned phrases and graduate to a Groq Haiku call.

### Edge Cases & Error Handling

- **Tier chain exhausted** — no more tiers to advance to → resolve with the
  current `TimeoutAction` (`CANCEL` or `DEFAULT`). Returns a clear message.
- **`OpenTicketAction` HTTP failure** — outcome=`FAILED`, manager advances to
  next tier. If next tier is also a ticket action against the same platform,
  it will likely fail too → terminal `TIMEOUT` with an audit log.
- **`EmailAction` SMTP refused** — same as above (`FAILED` → next tier).
- **Concurrent reject + timeout** — first-cause-wins: whichever
  `_advance_chain` call grabs the asyncio lock first proceeds; the other
  is a no-op.
- **Severity downgrade across tiers** — `SeverityTrigger` only *raises* the
  floor; once you've advanced to L3 you don't go back to L1 if severity
  drops. (Severity is set once at `ask_human` time.)
- **Business-hours boundary** — evaluated at *tier-start time*. If a tier
  starts at 17:55 and the timeout is 1h, the timeout fires at 18:55 even
  if business hours end at 18:00. Advancement to the *next* tier
  re-evaluates business hours. Documented behaviour.
- **`HandoffTool` deprecation** — calling `HandoffTool()` emits
  `DeprecationWarning` once per process; its `_execute` raises a
  `HumanInteractionInterrupt(prompt=..., policy_id=None)` exactly like
  today. No escalation behaviour for V1.
- **Channel without reject button** — the agent's policy still works; just
  no UI affordance for `EXPLICIT_REJECT`. Intent detection still applies.
- **Policy with zero tiers** — illegal; raises on `EscalationPolicy.__init__`.
- **Policy `id` collisions** — managed by the agent author; if two agents
  share an `id`, the only effect is muddled logs. No global registry in V1.

---

## Capabilities

### New Capabilities

- `hitl-escalation-policy`: declarative per-agent policy with ordered tiers,
  pluggable actions, and severity / hours / explicit-reject triggers.
- `hitl-escalation-action-ask-alternate`: refactor of today's `_escalate` as
  a first-class action.
- `hitl-escalation-action-ticket`: Zammad adapter (Zendesk deferred or added
  as a sibling task if effort budget allows).
- `hitl-escalation-action-live-chat`: deep-link generator (depends on which
  live-chat vendor is chosen — open question below).
- `hitl-escalation-action-email`: aiosmtplib-backed async email sender,
  reusing existing SMTP config keys.
- `hitl-channel-reject-button`: opt-in `render_reject_button` hook on
  `HumanChannel`, implemented for Telegram and Web first.
- `hitl-reject-intent-detector`: lightweight (regex + optional Groq Haiku)
  classifier for `EXPLICIT_REJECT` from free-text responses.
- `handoff-tool-deprecation-alias`: keep `HandoffTool` working as a
  thin wrapper around `HumanInteractionManager` with a deprecation warning.

### Modified Capabilities

- `human-tool` (existing in `web-hitl-and-demo-agent.spec.md` family) —
  adds optional `escalation_policy` constructor kwarg and `severity` field
  on `HumanToolInput`.
- `human-interaction-manager` — `_escalate` becomes `_advance_chain`;
  adds `_run_action`, `_select_starting_tier`.
- `human-interaction-model` — adds `escalation_chain: Optional[List[EscalationTier]]`
  and `severity: Optional[Literal[...]]` fields, keeps `escalation_targets`
  as legacy alias auto-converted to a single `AskAlternateHumansAction` tier.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/human/manager.py` | modifies | `_escalate` → `_advance_chain` loop + action runner |
| `parrot/human/models.py` | extends | New `EscalationPolicy`, `EscalationTier`, `EscalationAction*` config models, `Severity` enum |
| `parrot/human/tool.py` | extends | Optional `escalation_policy` kwarg + `severity` input field |
| `parrot/human/node.py` | extends | Optional `escalation_policy` kwarg mirroring `HumanTool` |
| `parrot/human/channels/base.py` | extends | Add `render_reject_button` opt-in attribute + standard reject `ChoiceOption` constant |
| `parrot/human/channels/telegram.py` | extends | Render the "↑ Escalar" inline button |
| `parrot/human/channels/web.py` | extends | Render the same affordance in the web UI |
| `parrot/human/channels/cli.py` | none | Leaves `render_reject_button=False`; intent detection only |
| `parrot/core/tools/handoff.py` | refactors | Becomes deprecated alias delegating to manager |
| `parrot/core/exceptions.py` | none | `interaction_id` + `policy_id` already there |
| `parrot/autonomous/orchestrator.py` | minor | Honour `policy_id` if set: don't re-enter suspend/resume on async-handled escalations |
| `parrot/integrations/manager.py` | none in V1 | Manager wiring unchanged |
| New: `parrot/human/escalation/actions/{ask_alternate,ticket,email,live_chat}.py` | adds | Pluggable strategies |
| New: `parrot/human/escalation/triggers.py` | adds | `TimeoutTrigger`, `RejectTrigger`, `SeverityTrigger`, `BusinessHoursTrigger` |
| New: `parrot/human/escalation/intent.py` | adds | `RejectIntentDetector` (regex + optional Groq) |
| New: `parrot/clients/zammad.py` (or `parrot/tools/zammad.py`) | adds | Async REST client for `OpenTicketAction(platform="zammad")` |
| `parrot/handlers/web_hitl.py` | minor | If the reject button affects callbacks, route it to `manager.advance_chain(interaction_id, cause=REJECT)` |
| Tests in `tests/human/`, `tests/core/tools/test_handoff_tool.py` | extends | New tier-advancement tests, deprecation-warning test |

No breaking changes. `escalation_targets` continues to work via auto-conversion.

---

## Code Context

### User-Provided Code

The user did not paste code in this session — references below are all from
the verified codebase.

### Verified Codebase References

#### Classes & Signatures

```python
# From parrot/human/models.py:60-90
class HumanInteraction(BaseModel):
    interaction_id: str = Field(default_factory=lambda: str(uuid4()))  # line 64
    question: str                                                       # line 67
    context: Optional[str] = None                                       # line 68
    interaction_type: InteractionType = InteractionType.FREE_TEXT       # line 69
    options: Optional[List[ChoiceOption]] = None                        # line 70
    form_schema: Optional[Dict[str, Any]] = None                        # line 71
    default_response: Optional[Any] = None                              # line 72
    target_humans: List[str] = Field(default_factory=list)              # line 75
    consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE        # line 76
    timeout: float = 7200.0                                             # line 79
    timeout_action: TimeoutAction = TimeoutAction.CANCEL                # line 80
    escalation_targets: Optional[List[str]] = None                      # line 81
    source_agent: Optional[str] = None                                  # line 84
    source_flow: Optional[str] = None                                   # line 85
    source_node: Optional[str] = None                                   # line 86
    status: InteractionStatus = InteractionStatus.PENDING               # line 89

# From parrot/human/models.py:22-32
class InteractionStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    PARTIAL = "partial"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ESCALATED = "escalated"           # line 30 — already reserved
    CANCELLED = "cancelled"

# From parrot/human/models.py:34-41
class TimeoutAction(str, Enum):
    CANCEL = "cancel"
    DEFAULT = "default"
    ESCALATE = "escalate"             # line 39 — already drives current single-hop escalation
    RETRY = "retry"

# From parrot/human/manager.py:34-67
class HumanInteractionManager:
    def __init__(
        self,
        channels: Optional[Dict[str, HumanChannel]] = None,  # line 58
        redis_url: Optional[str] = None,                     # line 59
    ) -> None: ...

# From parrot/human/manager.py:634-699
async def _escalate(
    self, interaction: HumanInteraction, channel: str
) -> None:
    """Escalate to alternate humans when the primary target times out."""
    # Current behaviour: re-emits the SAME interaction to escalation_targets
    # over the SAME channel with TimeoutAction.CANCEL to avoid loops.

# From parrot/human/tool.py:98-139
class HumanTool(AbstractTool):
    name: str = "ask_human"                                           # line 112
    args_schema: Type[BaseModel] = HumanToolInput                     # line 124
    def __init__(
        self,
        manager: Any = None,                                          # line 128
        *,
        default_channel: str = "telegram",                            # line 130
        default_targets: Optional[List[str]] = None,                  # line 131
        source_agent: Optional[str] = None,                           # line 132
        **kwargs: Any,
    ) -> None: ...

# From parrot/human/channels/base.py:11-57
class HumanChannel(ABC):
    channel_type: str = "base"                                         # line 19
    @abstractmethod
    async def send_interaction(
        self, interaction: HumanInteraction, recipient: str,
    ) -> bool: ...                                                     # line 22-31
    @abstractmethod
    async def register_response_handler(
        self, callback: Callable[[HumanResponse], Awaitable[None]],
    ) -> None: ...                                                     # line 33-39
    async def register_cancel_handler(
        self, callback: Callable[[str], Awaitable[bool]],
    ) -> None: return None                                             # line 59-70 (default no-op)

# From parrot/core/exceptions.py:11-40 — ALREADY has policy_id slot!
class HumanInteractionInterrupt(ParrotError):
    def __init__(
        self,
        prompt: str,
        interaction_id: Optional[str] = None,                          # line 22
        policy_id: Optional[str] = None,                               # line 23 — reserved for THIS feature
        *args, **kwargs
    ): ...

# From parrot/core/tools/handoff.py:18-44
class HandoffTool(AbstractTool):
    name: str = "handoff_to_human"                                     # line 31
    args_schema: Type[BaseModel] = HandoffToolSchema                   # line 33
    def _execute(self, prompt: str, **kwargs: Any) -> Any:
        raise HumanInteractionInterrupt(prompt=prompt)                 # line 38-39
```

#### Verified Imports

```python
# All confirmed working:
from parrot.human import (
    HumanInteractionManager, HumanInteraction, HumanResponse,
    HumanChannel, InteractionType, InteractionStatus, TimeoutAction,
    ConsensusMode, ChoiceOption, HumanTool, HumanDecisionNode,
    set_default_human_manager, get_default_human_manager,
)                                          # parrot/human/__init__.py:10-87
from parrot.core.tools.handoff import HandoffTool, HandoffToolSchema
from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema  # tools/abstract.py:78
```

#### Key Attributes & Constants

- `HumanInteraction.escalation_targets` → `Optional[List[str]]` (parrot/human/models.py:81)
- `HumanInteraction.timeout_action` → `TimeoutAction` (parrot/human/models.py:80)
- `InteractionStatus.ESCALATED` already exists (parrot/human/models.py:30)
- `HumanInteractionInterrupt.policy_id` already exists (parrot/core/exceptions.py:23)
- `HumanChannel.channel_type` class attr conventions: `"cli"`, `"telegram"`, `"web"`
- Redis URL: `parrot.conf.REDIS_URL` consumed in `HumanInteractionManager._get_redis`
  (parrot/human/manager.py:80) and `parrot/integrations/manager.py:160`
- SMTP config keys already used elsewhere: `smtp_host`, `smtp_port`,
  `smtp_host_user`, `smtp_host_password` (parrot/handlers/agents/abstract.py:581-584)
- `set_default_human_manager(manager)` is the global wiring used by
  `parrot.integrations.manager.IntegrationBotManager._ensure_human_manager`
  (parrot/integrations/manager.py:154-168) and `parrot/handlers/web_hitl.py:417-464`.

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.human.EscalationPolicy`~~ — not in codebase. To be created.
- ~~`parrot.human.EscalationTier`~~ — not in codebase. To be created.
- ~~`parrot.human.escalation`~~ — submodule does not exist; to be created.
- ~~`parrot.tools.zammad`~~ / ~~`parrot.clients.zammad`~~ — no Zammad adapter
  in the codebase today. To be created.
- ~~`parrot.tools.zendesk`~~ / ~~`parrot.clients.zendesk`~~ — no Zendesk
  adapter today.
- ~~`HumanInteraction.severity`~~ — not a real field today.
- ~~`HumanInteraction.escalation_policy`~~ / ~~`escalation_chain`~~ — not real
  fields today.
- ~~`HumanTool.escalation_policy`~~ — not a real ctor kwarg today.
- ~~`HumanChannel.render_reject_button`~~ — not a real attribute today.
- ~~`PolicyRegistry`~~ — not in codebase (Option B reserves this name).
- ~~`InteractionStatus.REJECTED`~~ — does not exist; `EXPLICIT_REJECT` is a
  *trigger*, not a status. The interaction's resulting status after a reject-
  driven advance is still `ESCALATED` (or `COMPLETED` once the next tier
  resolves).
- ~~`parrot.events.EventBus` ordered delivery guarantees~~ — Option C would
  require verifying these; not done in this brainstorm because A is the
  recommended path.

---

## Parallelism Assessment

- **Internal parallelism**: **Medium-high**. After the foundation lands
  (models + manager loop refactor), the four `EscalationAction`
  implementations (`AskAlternateHumans`, `OpenTicketAction`, `EmailAction`,
  `LiveChatHandoffAction`) are largely independent and can be done in parallel
  sub-tasks. The two channel-reject-button implementations (Telegram, Web) are
  also independent of each other. The reject-intent detector is independent
  of actions and channels.
- **Cross-feature independence**: **High.** The only shared surface with
  in-flight work is:
    - `parrot/core/tools/handoff.py` — the existing FEAT-045
      (`handoff-tool-for-integrations-agents.spec.md`) is in production and we
      are *extending* it (alias). Coordinate so we don't land conflicting
      changes mid-flight.
    - `parrot/human/manager.py` — no other in-flight spec touches the manager
      (verified via `ls sdd/specs/ | grep -i human`).
    - `parrot/autonomous/orchestrator.py` — touched only for the policy_id
      branch; small, contained change.
- **Recommended isolation**: **per-spec** (single worktree for all tasks).
- **Rationale**: the foundation (models + manager loop) must land *first*
  before any action can be tested, so all subsequent tasks have a hard
  dependency on the foundation. Splitting into per-task worktrees would
  produce a flurry of rebases against the foundation branch with little
  upside — the savings from parallel implementation are smaller than the
  coordination cost. Keep everything in one worktree, commit task-by-task,
  open one PR against `dev`.

---

## Open Questions

- [x] Granularity of `EscalationPolicy` (per-agent vs per-toolkit vs per-interaction) — *Owner: Jesus Lara*: per-agent (Round 1).
- [x] Wiring model (`HumanTool` injection vs registry vs hybrid) — *Owner: Jesus Lara*: injection in `HumanTool` (Round 1).
- [x] V1 action set — *Owner: Jesus Lara*: AskAlternateHumans + OpenTicket (Zammad first) + LiveChatHandoff + Email (Round 1).
- [x] V1 trigger set — *Owner: Jesus Lara*: TIMEOUT + EXPLICIT_REJECT + SEVERITY + BUSINESS_HOURS_OFF (Round 1).
- [x] Async-action resolution semantics — *Owner: Jesus Lara*: fire-and-forget, agent gets a confirmation string immediately (Round 2).
- [x] Cross-channel correlation (ticket reply → resume agent) — *Owner: Jesus Lara*: out of scope for V1; future spec (Round 2).
- [x] `HandoffTool` fate — *Owner: Jesus Lara*: keep as deprecated alias delegating to `HumanInteractionManager` (Round 2).
- [x] Business-hours model — *Owner: Jesus Lara*: per-tier `business_hours` declaration (Round 2).
- [x] Severity API — *Owner: Jesus Lara*: `severity` parameter on `ask_human` input; policy maps severity → starting tier (Round 3).
- [x] `EXPLICIT_REJECT` UX — *Owner: Jesus Lara*: standardised "↑ Escalar" button on channels that support it **plus** lightweight LLM intent detection on free-text responses (Round 3, user combined two options).
- [ ] Which live-chat platform powers `LiveChatHandoffAction` V1? (Intercom? Chatwoot? a generic webhook?) — *Owner: Jesus Lara*: a generic webhook for now.
- [ ] Should `OpenTicketAction` also support Zendesk in V1, or punt to V2 to keep scope bounded? — *Owner: Jesus Lara*: punt to V2.
- [ ] Where do tier-transition audit logs land? Reusing `hitl:*` Redis keys is fine for runtime, but ops likely needs a longer-lived store (DB? log shipper?) — *Owner: Jesus Lara + Ops*: only redis for now.
- [ ] Reject-intent detector V1: hand-tuned regex of canned phrases, or straight to a Groq Haiku call? Hybrid (regex first, LLM fallback) is implied by Round 3 — confirm. — *Owner: Jesus Lara*: confirmed, regex first + LLM confirmation on doubt. (not callback)
- [ ] Should `HumanDecisionNode` (flow-level) get the same `escalation_policy` kwarg as `HumanTool` in V1, or defer to V2? — *Owner: Jesus Lara*: accept in v1.
- [ ] Telemetry / observability hook — emit structured events on every tier advance? (would dovetail nicely with FEAT-176 EventEmitterMixin.) — *Owner: Jesus Lara*: yes, emit structured events.
