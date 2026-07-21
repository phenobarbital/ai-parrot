---
type: Wiki Overview
title: 'Feature Specification: HITL Multi-Tier Escalation Policy (per-policy_id registry
  + gap completion)'
id: doc:sdd-specs-hitl-escalation-tier-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot historically had two parallel HITL paths — `parrot.human.*`
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.groq
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.core.tools.handoff
  rel: mentions
- concept: mod:parrot.handlers.agents.abstract
  rel: mentions
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.actions.base
  rel: mentions
- concept: mod:parrot.human.actions.notify
  rel: mentions
- concept: mod:parrot.human.actions.ticket
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
- concept: mod:parrot.human.channels.cli
  rel: mentions
- concept: mod:parrot.human.channels.telegram
  rel: mentions
- concept: mod:parrot.human.channels.web
  rel: mentions
- concept: mod:parrot.human.manager
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.human.node
  rel: mentions
- concept: mod:parrot.human.tool
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: HITL Multi-Tier Escalation Policy (per-policy_id registry + gap completion)

**Feature ID**: FEAT-194
**Date**: 2026-05-21
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.7.0

> Brainstorm source: `sdd/proposals/hitl-escalation-tier.brainstorm.md`
> (Option A was recommended; the implementation that shipped in commit
> `afe70e82` took a simpler **Option-B-leaning** path — registry-based
> policy lookup + enum action type + opaque `action_metadata`. This spec
> is the v0.2 reconciliation: it ratifies the shipped baseline and
> formalises the remaining gaps as the V1 completion work.)

> Companion document: `documentation/hitl_tiered_escalation_example.md`
> shows the public usage shape of the shipped baseline.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot historically had two parallel HITL paths — `parrot.human.*`
(rich, async, multi-channel, **single-hop escalation**) and
`parrot.core.tools.handoff.HandoffTool` (synchronous in-chat handoff,
**no escalation at all**). Real-world HITL escalations need
**criticality + tier-specific actions** (L1 on-call → L2 ticket →
L3 manager email), declared per agent/policy. Commit `afe70e82` shipped
a tiered-escalation baseline that addresses the structural gap, but
several functional gaps remain before the feature is production-grade.

### Goals

**V1 baseline (already shipped in `afe70e82`):**
- `EscalationPolicy` / `EscalationTier` / `EscalationActionType` data
  model with contiguous-level validator.
- `HumanInteractionManager._policies` registry keyed by `policy_id`;
  `manager._escalate_to_next_tier` advances on `TimeoutAction.ESCALATE`.
- Fire-and-forget semantics for non-`INTERACT` action types
  (`NOTIFY` / `TICKET`): the agent is resumed immediately with the
  action's `action_metadata["message"]` string.
- `HumanInteraction.policy_id` / `HumanInteraction.policy` /
  `HumanInteraction.current_tier_level` runtime fields.
- `HumanTool` and `HandoffTool` accept a `policy_id` argument from the
  LLM and forward it to the manager.
- `HumanInteractionInterrupt.policy_id` slot consumed by `HandoffTool`.
- Backwards-compat with legacy `escalation_targets` (single-hop) via
  fallback path in `_handle_timeout`.

**V1 completion (this spec's delta):**
- Replace the two simulated stubs (`NotifyAction`, `TicketAction`) with
  real implementations:
  - `EmailAction` — `aiosmtplib` over existing SMTP config keys
    (`smtp_host`, `smtp_port`, `smtp_host_user`, `smtp_host_password`).
  - `ZammadTicketAction` — `aiohttp` REST client against Zammad.
  - `WebhookLiveChatAction` — generic POST to a configurable webhook,
    returns a `deep_link` string.
- Keep `EscalationActionType` as the public enum, but treat
  `NOTIFY`/`TICKET` as **dispatchers** keyed on `action_metadata["kind"]`
  (`"email"` / `"webhook"` / `"zammad"`) so multiple concrete actions
  share a single enum value without growing the enum.
- Add the missing triggers as first-class causes the manager honours:
  - `EXPLICIT_REJECT` — a standardised `__escalate__` `ChoiceOption` is
    rendered by opt-in channels (Telegram, Web); when the manager
    receives a response with `value="__escalate__"`, it advances
    immediately instead of accumulating.
  - `SEVERITY` — new `Severity` enum + `HumanInteraction.severity` field
    + optional per-tier `min_severity` mapping in `EscalationTier`.
    `_select_starting_tier(policy, severity)` picks the starting tier.
  - `BUSINESS_HOURS_OFF` — new optional `EscalationTier.business_hours`
    (tz + days + hours window). Off-hours tiers are skipped at
    tier-entry time.
- Add `RejectIntentDetector` (regex first, optional Groq Haiku
  confirmation inline with short timeout) so free-text replies can
  also trigger `EXPLICIT_REJECT`. Inline `await`, not callback.
- Add reject-button rendering to `TelegramHumanChannel` and
  `WebHumanChannel` via opt-in `HumanChannel.render_reject_button = True`
  class attr; CLI keeps default `False`.
- Add `HumanDecisionNode.escalation_policy_id` so flow nodes can
  participate.
- Unify the `HandoffTool` dual-path: when the manager registration
  succeeds, the orchestrator MUST NOT also suspend on the
  `HumanInteractionInterrupt` — the tool returns the manager's result
  string directly. Keep `HumanInteractionInterrupt` as the legacy
  no-manager fallback only. Emit a `DeprecationWarning` once per process
  encouraging migration to `HumanTool` with `policy_id`.
- Emit structured tier-transition events on the existing
  `EventEmitterMixin` bus (FEAT-176):
  `hitl.tier.entered`, `hitl.tier.advanced`,
  `hitl.tier.action_executed`, `hitl.tier.action_failed`,
  `hitl.chain.exhausted`.
- Fix the latent action-failure bug in `_escalate_to_next_tier`
  (manager.py:733–740): when `action.execute()` raises, treat as
  `FAILED → advance to next tier`, not "continue silently with empty
  metadata."

### Non-Goals (explicitly out of scope for V1)

- **Cross-channel correlation** (ticket reply → resume original agent).
  Fire-and-forget for non-`INTERACT` tiers stays. Future spec.
- **Zendesk** adapter. Zammad-only in V1 (resolved in brainstorm).
- **External audit-log persistence**. Redis namespace only;
  log-shipper / DB sink deferred (resolved in brainstorm).
- **Hot-reload of policy registry**. Registry is mutated by
  `manager._policies[...] = policy` at startup; no admin endpoint.
- **Removing `HandoffTool`**. Deprecation only — callers in
  `parrot/agents/demo.py:194` and downstream code continue to work.
- **Refactoring the action model into discriminated classes** (the
  brainstorm's Option-A shape). The shipped enum + `action_metadata`
  shape is ratified; concrete action kinds are dispatched by
  `action_metadata["kind"]` within the existing enum values.

---

## 2. Architectural Design

### Overview

Commit `afe70e82` shipped the *control plane*: data model, registry,
tier loop, fire-and-forget for non-`INTERACT` tiers. This spec ships
the *operational completion*: real action backends, the three missing
triggers, reject UX, telemetry, and the `HandoffTool` dedup.

The architectural shape is preserved:

- Policies are owned by `HumanInteractionManager._policies: Dict[str, EscalationPolicy]`.
- `HumanTool` / `HandoffTool` expose `policy_id` to the LLM (already shipped).
- `HumanDecisionNode` gets a constructor `escalation_policy_id` kwarg
  to mirror the same contract from flow code.
- Inside `_escalate_to_next_tier`, the manager picks the next tier from
  `interaction.policy.tiers`, applies severity floor + business-hours
  skip, runs the action through a dispatcher keyed on
  `(action_type, action_metadata["kind"])`, and resolves
  fire-and-forget for non-`INTERACT` kinds.

### Component Diagram

```
                                ┌─────────────────────────┐
                                │  Agent author           │
                                │  manager._policies[id]= │
                                │     EscalationPolicy(…) │
                                └────────────┬────────────┘
                                             │ at startup
                                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Agent → ask_human(question, severity="high", policy_id="hr")       │
│        │                                                            │
│        ▼                                                            │
│  HumanTool builds HumanInteraction(policy_id, severity, …)          │
│        │                                                            │
│        ▼                                                            │
│  HumanInteractionManager.request_human_input(interaction)           │
│        │ load policy from _policies[policy_id]                      │
│        │ attach interaction.policy = <snapshot>                     │
│        │ start_tier = _select_starting_tier(policy, severity)       │
│        │ advance to start_tier (skip lower / off-hours)             │
└────────────────────────────────────┬────────────────────────────────┘
                                     │
            ┌────────────────────────┴────────────────────────┐
            │  _escalate_to_next_tier loop                    │
            │  cause ∈ {TIMEOUT, EXPLICIT_REJECT,             │
            │           BUSINESS_HOURS_OFF, ACTION_FAILED}    │
            │  pick next applicable tier                      │
            │  emit hitl.tier.entered                         │
            │  run action via dispatcher                      │
            │  emit hitl.tier.action_executed | _failed       │
            └────────┬──────────────────────────┬─────────────┘
                     │                          │
        INTERACT tier                  NOTIFY / TICKET tier
        (re-dispatch, wait)            (run action, resolve)
                     │                          │
        on TIMEOUT or REJECT          ASYNC_HANDLED:
        → advance_to_next             attach action_metadata["message"]
                                      resolve future immediately

         ─── reject paths ──────────────────────────────────────────
         channel renders "↑ Escalar" ChoiceOption(key="__escalate__")
            user taps → response.value="__escalate__" → manager
            intercepts in receive_response → advance_chain(cause=REJECT)
         channel delivers free-text response
            → RejectIntentDetector.is_escalation_intent(text)
              regex pass → True → advance(cause=REJECT)
              regex ambiguous + Groq Haiku available
                → inline await (≤1.5s) → if True → advance(cause=REJECT)
              else → treat as normal response
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.human.manager.HumanInteractionManager` | extends | Add `_select_starting_tier`, public `advance_chain`, dispatcher for action kinds, severity + hours skipping in `_escalate_to_next_tier`; fix action-failure bug |
| `parrot.human.models.EscalationTier` | extends | Add optional `business_hours: Optional[BusinessHours]`, optional `min_severity: Optional[Severity]` |
| `parrot.human.models.HumanInteraction` | extends | Add `severity: Optional[Severity]` |
| `parrot.human.tool.HumanToolInput` | extends | Add `severity` field with constrained `Literal` values |
| `parrot.human.node.HumanDecisionNode` | extends | New ctor kwarg `escalation_policy_id`, passed through to interaction build |
| `parrot.human.channels.base.HumanChannel` | extends | Add class attr `render_reject_button: bool = False`; export `ESCALATE_OPTION_KEY = "__escalate__"` constant |
| `parrot.human.channels.telegram.TelegramHumanChannel` | extends | `render_reject_button = True`; inject reject button in inline keyboard |
| `parrot.human.channels.web.WebHumanChannel` | extends | `render_reject_button = True`; render equivalent UI affordance |
| `parrot.human.channels.cli.CLIHumanChannel` | none | Leaves `render_reject_button = False`; reject reachable via intent detector only |
| `parrot.human.actions.notify.NotifyAction` | rewrites | Replace stub with real dispatch: `kind=email` → `EmailBackend`; `kind=webhook` → `WebhookBackend` |
| `parrot.human.actions.ticket.TicketAction` | rewrites | Replace stub with real dispatch: `kind=zammad` → `ZammadBackend` |
| `parrot.core.tools.handoff.HandoffTool` | extends | When manager-registered path succeeds, return manager result string instead of also raising; emit `DeprecationWarning` once per process |
| `parrot.autonomous.orchestrator.AutonomousOrchestrator` | minor | When `HumanInteractionInterrupt.policy_id` is set AND `interaction_id` is set AND a result for it exists in Redis, propagate the result string instead of suspending |
| `parrot.tools.abstract.EventEmitterMixin` (FEAT-176) | uses | Manager emits `hitl.tier.*` and `hitl.chain.*` events |
| `parrot.handlers.web_hitl` | extends | Route `value="__escalate__"` to `manager.advance_chain(interaction_id, cause="reject")` |
| `parrot.handlers.agents.abstract` SMTP config | reuses | `EmailBackend` reads existing `smtp_host`/`smtp_port`/`smtp_host_user`/`smtp_host_password` |

### Data Models (delta over shipped baseline)

```python
# parrot/human/models.py — EXTEND existing classes (do NOT rename)

class Severity(str, Enum):                                          # NEW
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class BusinessHours(BaseModel):                                     # NEW
    tz: str                          # IANA, e.g. "Europe/Madrid"
    days: str                        # "mon-fri" | "mon,wed,fri" | "mon-sun"
    hours: str                       # "09:00-18:00"


class EscalationTier(BaseModel):
    # existing fields preserved (level, name, channel_type, target_humans,
    # timeout, action_type, action_metadata)
    min_severity: Optional[Severity] = None                          # NEW
    business_hours: Optional[BusinessHours] = None                   # NEW


class HumanInteraction(BaseModel):
    # existing fields preserved
    severity: Severity = Severity.NORMAL                             # NEW
```

`EscalationActionType` and `EscalationPolicy` stay byte-identical to
what is committed. The `action_metadata` payload schema is formalised
per kind:

```python
# Documented action_metadata schemas (validated at action-dispatch time)
NotifyAction.kind == "email":     {"kind": "email", "to": List[str], "subject_template": str}
NotifyAction.kind == "webhook":   {"kind": "webhook", "url": str}
TicketAction.kind  == "zammad":   {"kind": "zammad", "queue": str, "title_template": str}
```

### New / Extended Public Interfaces

```python
# parrot/human/manager.py — NEW PUBLIC METHOD
class HumanInteractionManager:
    async def advance_chain(
        self,
        interaction_id: str,
        cause: Literal[
            "timeout", "reject", "business_hours_off", "action_failed"
        ],
    ) -> None:
        """Public entry point for channels (reject button) and tests."""


# parrot/human/node.py — EXTENDED ctor
class HumanDecisionNode:
    def __init__(
        self,
        name: str,
        manager: Any,
        interaction_config: Optional["HumanInteraction"] = None,
        *,
        channel: str = "telegram",
        target_humans: Optional[List[str]] = None,
        consensus_mode: "ConsensusMode" = ConsensusMode.FIRST_RESPONSE,
        source_agent: Optional[str] = None,
        source_flow: Optional[str] = None,
        escalation_policy_id: Optional[str] = None,                   # NEW
        severity: Severity = Severity.NORMAL,                         # NEW
    ) -> None: ...


# parrot/human/actions/backends/ (NEW submodule)
class ActionBackend(ABC):
    @abstractmethod
    async def execute(
        self,
        interaction: HumanInteraction,
        tier: EscalationTier,
    ) -> Dict[str, Any]:
        """Concrete backend (Email/Zammad/Webhook) returns metadata dict
        with at minimum {'message': '<string to send to LLM>'}."""


# parrot/human/escalation_intent.py (NEW)
class RejectIntentDetector:
    def __init__(
        self,
        regex_phrases: Optional[List[str]] = None,
        llm_client: Optional["AbstractClient"] = None,
        llm_timeout_seconds: float = 1.5,
    ) -> None: ...
    async def is_escalation_intent(self, text: str) -> bool: ...
```

---

## 3. Module Breakdown

> Modules below are split into **(B) baseline already shipped** and
> **(C) completion work** for this spec. (B) modules are listed for
> context and reference; tasks should be created only for (C).

### (B) Baseline — already shipped in commit `afe70e82`

These modules exist today and are NOT to be re-created. Tasks may
*touch* them as marked in (C).

- **B1**. `parrot/human/models.py` — `EscalationActionType`,
  `EscalationTier`, `EscalationPolicy`, `HumanInteraction.policy_id`,
  `HumanInteraction.policy`, `HumanInteraction.current_tier_level`,
  payload validators.
- **B2**. `parrot/human/actions/base.py` — `EscalationAction` ABC.
- **B3**. `parrot/human/actions/notify.py` + `ticket.py` — **stub**
  implementations (to be replaced by C4).
- **B4**. `parrot/human/manager.py` — `_policies` registry, `_actions`
  dispatcher, `_escalate_to_next_tier` loop, fire-and-forget resolution,
  `asyncio.Lock` for Redis init, legacy `_escalate` fallback.
- **B5**. `parrot/human/tool.py` — `HumanToolInput.policy_id`,
  `_resolve_channel`, `_parse_options`, structured error returns.
- **B6**. `parrot/core/tools/handoff.py` — `policy_id` plumbing,
  `manager.request_human_input_async` registration (dual-path).
- **B7**. `parrot/core/exceptions.py` — `HumanInteractionInterrupt`
  with `interaction_id` + `policy_id` slots.

### (C) Completion modules — this spec's delta

#### C1: Severity + BusinessHours model + starting-tier logic

- **Path**: `parrot/human/models.py` (extends B1).
- **Responsibility**: Add `Severity` enum, `BusinessHours` model,
  `EscalationTier.min_severity`, `EscalationTier.business_hours`,
  `HumanInteraction.severity`. Add `EscalationPolicy.select_starting_tier(
  severity, now)` helper as a pure method on the model (no I/O).
- **Depends on**: B1.

#### C2: Action backends (real implementations)

- **Path**: `parrot/human/actions/backends/{email,zammad,webhook}.py` (new submodule).
- **Responsibility**:
  - `EmailBackend(ActionBackend)` — `aiosmtplib` send using existing
    SMTP config keys; renders `subject_template` / body from
    `interaction.question` + `interaction.context`. Returns
    `{"message": "[escalated:email] Notified <to>.", "to": [...], "status": "sent"}`.
  - `ZammadBackend(ActionBackend)` — `aiohttp` POST to
    `{base_url}/api/v1/tickets` with `Authorization: Token token=…`.
    Returns `{"message": "[escalated:ticket:zammad] Ticket {n} opened.", "ticket_id": ..., "url": ...}`.
  - `WebhookBackend(ActionBackend)` — generic POST of
    `{interaction_id, question, severity, user_id}`; expects
    `{deep_link: str}` back; returns `{"message": "[escalated:live_chat] {deep_link}", "deep_link": ...}`.
  - Each backend raises a typed exception on failure; caller maps to
    `EscalationActionFailed`.
- **Depends on**: C1 (for `Severity` in payloads). `aiosmtplib`, `aiohttp`.

#### C3: NotifyAction / TicketAction rewrites — dispatcher pattern

- **Path**: `parrot/human/actions/notify.py`, `parrot/human/actions/ticket.py`
  (replace B3 stub bodies).
- **Responsibility**: Each action reads `tier.action_metadata["kind"]`
  and dispatches to the corresponding `ActionBackend`:
  - `NotifyAction` knows about `kind ∈ {"email", "webhook"}`.
  - `TicketAction` knows about `kind ∈ {"zammad"}` (extension hook for
    future `"zendesk"`).
- **Backwards compat**: when `action_metadata["kind"]` is missing, fall
  back to the historical `channel="email"` / `platform="zammad"`
  defaults so the example doc in
  `documentation/hitl_tiered_escalation_example.md` keeps working
  unchanged.
- **Depends on**: B2, B3, C2.

#### C4: Manager — action-failure fix + advance_chain public + severity/hours selection

- **Path**: `parrot/human/manager.py` (extends B4).
- **Responsibility**:
  1. In `_escalate_to_next_tier`: when `action.execute()` raises, do
     NOT silently set `action_metadata = {}` and continue. Instead emit
     `hitl.tier.action_failed` and call
     `await self._escalate_to_next_tier(interaction, channel)` again
     (advance to next tier). If the chain is exhausted while every tier
     keeps failing, terminate via `_finish_with_timeout`.
  2. Add `_select_starting_tier(policy, severity, now)` — returns the
     first tier whose `min_severity` ≤ requested AND whose
     `business_hours` includes `now` (or has no window).
  3. Add public `async advance_chain(interaction_id, cause)` — invoked
     by channels (reject button) and by the integration handler.
  4. When advancing for `cause="business_hours_off"`, skip the current
     tier without dispatching its action.
  5. When `interaction.policy` is set in `request_human_input`, call
     `_select_starting_tier` and set `current_tier_level` accordingly
     BEFORE dispatching to channel.
- **Depends on**: B4, C1, C7 (events).

#### C5: RejectIntentDetector

- **Path**: `parrot/human/escalation_intent.py` (new).
- **Responsibility**: Hand-tuned regex of canned phrases (Spanish +
  English seed sets, ≥ 8 each). Optional Groq Haiku client used inline
  via `asyncio.wait_for(..., timeout=llm_timeout_seconds)` when regex
  is ambiguous. Returns `bool`. Pure helper; the manager calls it from
  `receive_response` before the normal accumulation path. **NOT a
  callback** — synchronous inline await.
- **Depends on**: optional `parrot.clients.groq`.

#### C6: Channel reject-button hook + Telegram/Web rendering

- **Path**: `parrot/human/channels/base.py`,
  `parrot/human/channels/telegram.py`, `parrot/human/channels/web.py`.
- **Responsibility**: Add class attr `render_reject_button: bool = False`
  to `HumanChannel`. Export module-level constant
  `ESCALATE_OPTION_KEY = "__escalate__"`. Telegram + Web channels set
  `render_reject_button = True` and append the reject button to every
  rendered interaction. The manager intercepts responses whose value
  equals `ESCALATE_OPTION_KEY` in `receive_response` and routes them to
  `advance_chain(cause="reject")` instead of accumulating.
- **Depends on**: C4 (`advance_chain`).

#### C7: Structured tier-transition events

- **Path**: `parrot/human/events.py` (new) + emission sites in C4.
- **Responsibility**: Pydantic models for `HitlTierEnteredEvent`,
  `HitlTierAdvancedEvent`, `HitlTierActionExecutedEvent`,
  `HitlTierActionFailedEvent`, `HitlChainExhaustedEvent`. Common
  payload fields: `interaction_id`, `policy_id`, `tier_level`,
  `cause`, `timestamp`. Manager emits via `EventEmitterMixin.emit` (or
  the equivalent it gains by inheriting from `EventEmitterMixin` if it
  doesn't already). If the manager cannot inherit from the mixin
  without breaking, expose an `on_event: Optional[Callable]` hook on
  the manager that the integration layer wires.
- **Depends on**: B4, C4, `parrot.tools.abstract.EventEmitterMixin`
  (verify inheritance path during implementation).

#### C8: HumanDecisionNode policy + severity kwargs

- **Path**: `parrot/human/node.py`.
- **Responsibility**: Add `escalation_policy_id` and `severity` ctor
  kwargs; thread them through into the built `HumanInteraction`. Update
  docstring and example in `documentation/hitl_tiered_escalation_example.md`.
- **Depends on**: C1.

#### C9: HumanTool severity input

- **Path**: `parrot/human/tool.py`.
- **Responsibility**: Add `severity: str = Field(default="normal", ...)`
  to `HumanToolInput` with constrained values via `Literal`. Convert to
  `Severity` enum in `_execute` and set
  `interaction.severity = severity_enum`. Update tool description so
  the LLM learns when to use `high`/`critical`.
- **Depends on**: C1.

#### C10: HandoffTool dedup + DeprecationWarning

- **Path**: `parrot/core/tools/handoff.py` (extends B6).
- **Responsibility**:
  1. When the manager registration succeeds AND the registered
     interaction resolves before the interrupt is raised (e.g., the
     starting tier is non-`INTERACT` so the manager resolves
     immediately), return the manager's result string and do NOT raise
     `HumanInteractionInterrupt`.
  2. When the manager registration fails (no manager configured), keep
     the legacy `raise HumanInteractionInterrupt(prompt=prompt)` path
     unchanged.
  3. Emit `DeprecationWarning` once per process on first instantiation
     of `HandoffTool`, pointing users to
     `HumanTool(..., policy_id="...")`.
- **Depends on**: B4, B6.

#### C11: Orchestrator policy-id branch hardening

- **Path**: `parrot/autonomous/orchestrator.py`.

…(truncated)…
