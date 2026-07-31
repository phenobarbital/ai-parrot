---
type: Wiki Overview
title: 'Brainstorm: HITL Multi-Tier Escalation Policy (per-agent) + HumanTool/HandoffTool
  Unification'
id: doc:sdd-proposals-hitl-escalation-tier-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot has **two parallel Human-in-the-Loop (HITL) paths** that don't
  share
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.groq
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.core.tools.handoff
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.integrations.manager
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

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

…(truncated)…
