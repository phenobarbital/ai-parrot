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
- **Responsibility**: In the catch block at orchestrator.py:541-564
  (and the mirror at 824), when `interrupt.policy_id` is set AND
  `interrupt.interaction_id` is set, before re-entering suspend/resume,
  call `await manager.get_result(interaction_id)` once. If a result
  exists, propagate its `consolidated_value` /
  `action_metadata["message"]` to the LLM and skip suspension. If not,
  legacy suspend path runs.
- **Depends on**: C10.

#### C12: Web HITL reject route

- **Path**: `parrot/handlers/web_hitl.py`.
- **Responsibility**: When a response payload arrives with
  `value="__escalate__"`, call `manager.advance_chain(interaction_id, cause="reject")`
  instead of `manager.receive_response(...)`. Same authorisation check
  (`is_valid_respondent`) applies.
- **Depends on**: C4, C6.

#### C13: Documentation update

- **Path**: `documentation/hitl_tiered_escalation_example.md`.
- **Responsibility**: Expand with examples for `severity`,
  `business_hours`, the reject button, and the real action kinds
  (`kind=email|webhook|zammad`). Note the `HandoffTool` deprecation.
- **Depends on**: C1, C2, C3, C5, C6, C9, C10.

---

## 4. Test Specification

### Unit Tests (new — for C1–C13)

| Test | Module | Description |
|---|---|---|
| `test_severity_enum_ordering` | C1 | `LOW < NORMAL < HIGH < CRITICAL` for comparisons |
| `test_business_hours_includes_now` | C1 | TZ-correct boundary at 9:00 / 17:59 / 18:00 / 18:01 |
| `test_policy_select_starting_tier_severity_floor` | C1 | `severity=critical` returns first tier with `min_severity<=critical` |
| `test_policy_select_starting_tier_skips_off_hours` | C1 | Off-hours tier at start time is skipped |
| `test_email_backend_aiosmtplib_send_returns_message` | C2 | Mocked SMTP returns confirmation containing recipients |
| `test_email_backend_smtp_failure_raises_typed_exception` | C2 | SMTP error → typed exception |
| `test_zammad_backend_create_ticket_returns_id_and_url` | C2 | Mocked Zammad REST returns ticket id + url in message |
| `test_zammad_backend_http_failure_raises_typed_exception` | C2 | Non-2xx → typed exception |
| `test_webhook_backend_posts_payload_returns_deep_link` | C2 | Mocked webhook returns deep_link in message |
| `test_notify_action_dispatches_to_email_backend` | C3 | `kind=email` routes correctly |
| `test_notify_action_dispatches_to_webhook_backend` | C3 | `kind=webhook` routes correctly |
| `test_notify_action_legacy_no_kind_falls_back_to_email` | C3 | Back-compat with shipped example doc |
| `test_ticket_action_dispatches_to_zammad_backend` | C3 | `kind=zammad` routes correctly |
| `test_advance_chain_on_action_failed_advances_to_next_tier` | C4 | Failure no longer silently continues |
| `test_advance_chain_on_action_failed_chain_exhausted_terminates` | C4 | All tiers fail → terminal `TIMEOUT`/`CANCEL` |
| `test_advance_chain_public_method_routes_by_cause` | C4 | Reject cause vs timeout cause produce same advance |
| `test_select_starting_tier_called_on_request_human_input` | C4 | Severity-driven starting tier picked before dispatch |
| `test_advance_chain_skips_off_hours_at_runtime` | C4 | Re-evaluation at advance time, not just chain build |
| `test_reject_intent_detector_regex_match_es` | C5 | "pasame con un humano" / "necesito un humano" → True |
| `test_reject_intent_detector_regex_match_en` | C5 | "I need a human" / "please escalate" → True |
| `test_reject_intent_detector_negative_cases` | C5 | "thanks" / "ok" / unrelated free-text → False |
| `test_reject_intent_detector_llm_fallback_on_ambiguous` | C5 | Mocked Groq Haiku response is honoured |
| `test_reject_intent_detector_llm_timeout_returns_false` | C5 | `asyncio.wait_for` timeout → False, no exception |
| `test_telegram_channel_renders_escalate_option` | C6 | Inline keyboard contains `__escalate__` key |
| `test_web_channel_renders_escalate_option` | C6 | Web UI affordance present |
| `test_cli_channel_does_not_render_escalate_option` | C6 | Reject button absent in CLI |
| `test_manager_intercepts_escalate_value_in_receive_response` | C6 | Value `"__escalate__"` routes to `advance_chain` not `accumulate` |
| `test_events_emitted_on_tier_entered` | C7 | Event observed with correct payload |
| `test_events_emitted_on_action_executed_and_failed` | C7 | Separate event types for success / failure |
| `test_events_emitted_on_chain_exhausted` | C7 | Terminal event fires once |
| `test_decision_node_propagates_policy_id_and_severity` | C8 | Built interaction carries both |
| `test_human_tool_severity_input_sets_interaction_severity` | C9 | `severity="critical"` propagated to manager |
| `test_human_tool_severity_invalid_returns_actionable_error` | C9 | Bad value → structured LLM error |
| `test_handoff_tool_emits_deprecation_warning_once` | C10 | `warnings.simplefilter('always')` catches one warning per process |
| `test_handoff_tool_returns_manager_result_when_async_resolved` | C10 | When non-INTERACT tier resolves immediately, no interrupt is raised |
| `test_handoff_tool_falls_back_to_interrupt_with_no_manager` | C10 | Legacy path unchanged |
| `test_orchestrator_consumes_existing_result_without_suspending` | C11 | Result-in-Redis short-circuit |
| `test_web_hitl_routes_escalate_value_to_advance_chain` | C12 | End-to-end reject button |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_telegram_tier_timeout_to_zammad_ticket` | L1 Telegram interactive times out → L2 Zammad ticket via real REST stub → LLM gets confirmation |
| `test_e2e_web_reject_button_advances_to_email_tier` | Web user taps reject → next tier sends email via aiosmtplib stub → LLM gets confirmation |
| `test_e2e_severity_critical_skips_lower_tiers` | `ask_human(severity="critical")` → manager starts at first tier with `min_severity<=critical` |
| `test_e2e_business_hours_off_skips_tier` | Frozen-clock fixture at 22:00 outside L1 hours → manager skips L1 directly to L2 |
| `test_e2e_handoff_tool_with_policy_id_unifies_path` | `HandoffTool(prompt, policy_id=...)` against a non-INTERACT starting tier → no suspend, returns confirmation string |
| `test_e2e_handoff_tool_legacy_no_manager_still_suspends` | Old behaviour preserved when manager is None |
| `test_e2e_chain_all_tiers_action_fails_terminates_cleanly` | Two non-INTERACT tiers both fail → terminal CANCEL/TIMEOUT |
| `test_e2e_events_bus_records_full_chain` | All `hitl.tier.*` events observed in order |

### Test Data / Fixtures

```python
# tests/human/escalation/conftest.py — new fixtures
@pytest.fixture
def critical_support_policy() -> EscalationPolicy:
    """3-tier mirror of the example doc, but with real action kinds."""

@pytest.fixture
def frozen_business_hours_clock(monkeypatch):
    """Patch datetime.now used by select_starting_tier."""

@pytest.fixture
async def mock_zammad_server(aiohttp_server):
    """Stub Zammad REST that returns a deterministic ticket id."""

@pytest.fixture
def mock_smtp_server():
    """In-memory aiosmtplib server / asyncmock for send."""

@pytest.fixture
def mock_groq_haiku_client():
    """Stub AbstractClient returning {is_escalate: bool}."""

@pytest.fixture
def telegram_channel_capture():
    """Captures rendered inline keyboards from TelegramHumanChannel."""
```

---

## 5. Acceptance Criteria

> Baseline checkboxes that are already satisfied by `afe70e82` are
> pre-checked; completion criteria for this spec are unchecked.

### Baseline (verified at HEAD; preserved by C-work)

- [x] `EscalationPolicy`, `EscalationTier`, `EscalationActionType` exist
  and are exported from `parrot.human.models`.
- [x] `HumanInteractionManager._policies` registry accepts policies by
  `policy_id`.
- [x] `_escalate_to_next_tier` advances `current_tier_level` and
  dispatches via the `_actions[EscalationActionType]` map.
- [x] Non-`INTERACT` tiers resolve fire-and-forget with
  `action_metadata["message"]` propagated to the LLM.
- [x] Legacy `escalation_targets` keeps working via the fallback path
  in `_handle_timeout`.
- [x] `HumanTool` exposes `policy_id` in its input schema.
- [x] `HandoffTool` accepts `policy_id` and forwards it.
- [x] `HumanInteractionInterrupt.policy_id` slot is consumed.
- [x] `EscalationPolicy` validator rejects non-contiguous tier levels.

### Completion (this spec)

- [ ] All unit tests in §4 (C1–C13) pass.
- [ ] All integration tests in §4 pass.
- [ ] `Severity` enum, `BusinessHours` model, `EscalationTier.min_severity`,
  `EscalationTier.business_hours`, `HumanInteraction.severity` exist
  and are exported.
- [ ] `EscalationPolicy.select_starting_tier(severity, now)` is a pure
  method covered by ≥ 6 unit tests including boundary cases.
- [ ] `EmailBackend` against a stub SMTP server returns a confirmation
  message whose body contains the original `interaction.question`.
- [ ] `ZammadBackend` against a stub REST server returns a confirmation
  message containing the ticket id and ticket URL.
- [ ] `WebhookBackend` POSTs the documented payload shape and surfaces
  the returned `deep_link` in its message.
- [ ] `NotifyAction` / `TicketAction` dispatch by
  `action_metadata["kind"]` with backwards-compatible defaults for
  callers that omit `"kind"`.
- [ ] `_escalate_to_next_tier` advances to the next tier on action
  failure (no silent continuation with empty metadata).
- [ ] Manager exposes public `advance_chain(interaction_id, cause)`.
- [ ] `RejectIntentDetector` returns `True` for at least 8 canned
  phrases (4 Spanish + 4 English) and `False` for clearly unrelated
  free-text. LLM-fallback path honours its `llm_timeout_seconds`.
- [ ] `TelegramHumanChannel` and `WebHumanChannel` render the reject
  affordance with key `__escalate__`. CLI channel does not.
- [ ] Tapping the reject button advances the chain through
  `advance_chain(cause="reject")`.
- [ ] `HumanDecisionNode` accepts `escalation_policy_id` and `severity`
  ctor kwargs.
- [ ] `HumanToolInput` accepts `severity` with constrained values and
  produces an actionable error for invalid inputs.
- [ ] `HandoffTool` returns the manager result without raising
  `HumanInteractionInterrupt` when the manager-registered interaction
  resolves immediately (non-INTERACT starting tier).
- [ ] `HandoffTool` emits `DeprecationWarning` exactly once per process.
- [ ] `AutonomousOrchestrator` short-circuits to the manager result when
  `interrupt.policy_id` and `interaction_id` are set and a result is
  already persisted in Redis.
- [ ] Structured events
  (`hitl.tier.entered`, `hitl.tier.advanced`,
  `hitl.tier.action_executed`, `hitl.tier.action_failed`,
  `hitl.chain.exhausted`) are emitted with the documented payload shape.
- [ ] `documentation/hitl_tiered_escalation_example.md` documents
  severity, business hours, the reject button, and the real action
  kinds.
- [ ] `ruff check packages/ai-parrot/src/parrot/human/` passes.
- [ ] `mypy packages/ai-parrot/src/parrot/human/` passes for new modules.
- [ ] No new dependency added beyond `aiosmtplib`. (`aiohttp` and
  `pydantic` already present.)

---

## 6. Codebase Contract

> Verified at HEAD after commit `afe70e82` (2026-05-21).
> Implementation agents MUST NOT reference imports, attributes, or
> methods not listed here without first verifying via `grep` / `read`.

### Verified Imports

```python
# Confirmed working at HEAD:
from parrot.human import (
    HumanInteractionManager, HumanInteraction, HumanResponse,
    HumanChannel, InteractionType, InteractionStatus, TimeoutAction,
    ConsensusMode, ChoiceOption, HumanTool, HumanDecisionNode,
    set_default_human_manager, get_default_human_manager,
)                                          # parrot/human/__init__.py:10-87
from parrot.human.models import (
    EscalationActionType, EscalationTier, EscalationPolicy,
    InteractionResult,
)                                          # parrot/human/models.py:12-24 (__all__)
from parrot.human.actions.base import EscalationAction
from parrot.human.actions.notify import NotifyAction
from parrot.human.actions.ticket import TicketAction
from parrot.human.channels.base import HumanChannel
from parrot.human.channels.cli import CLIHumanChannel, CLIDaemonHumanChannel
from parrot.human.channels.web import WebHumanChannel
from parrot.human.tool import HumanTool, HumanToolInput
from parrot.human.node import HumanDecisionNode
from parrot.core.tools.handoff import HandoffTool, HandoffToolSchema
from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
```

### Existing Class Signatures (post-`afe70e82`)

```python
# parrot/human/models.py:77-82
class EscalationActionType(str, Enum):
    INTERACT = "interact"        # bi-directional human interaction
    NOTIFY = "notify"            # one-way notification (email/SMS/webhook)
    TICKET = "ticket"            # open ticket in external system

# parrot/human/models.py:85-112
class EscalationTier(BaseModel):
    level: int                                  # ge=1
    name: str
    channel_type: Optional[str] = None
    target_humans: List[str] = Field(default_factory=list)
    timeout: float = Field(default=3600.0, gt=0)
    action_type: EscalationActionType = EscalationActionType.INTERACT
    action_metadata: Dict[str, Any] = Field(default_factory=dict)
    # validator: INTERACT requires non-empty target_humans

# parrot/human/models.py:115-132
class EscalationPolicy(BaseModel):
    policy_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    tiers: List[EscalationTier] = Field(default_factory=list)
    # validator: levels must be contiguous starting at 1

# parrot/human/models.py:135-185 — HumanInteraction (subset, NEW fields marked)
class HumanInteraction(BaseModel):
    interaction_id: str = Field(default_factory=lambda: str(uuid4()))
    question: str
    context: Optional[str] = None
    interaction_type: InteractionType = InteractionType.FREE_TEXT
    options: Optional[List[ChoiceOption]] = None
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None
    target_humans: List[str] = Field(default_factory=list)
    consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE
    timeout: float = Field(default=7200.0, gt=0)
    timeout_action: TimeoutAction = TimeoutAction.CANCEL
    escalation_targets: List[str] = Field(default_factory=list)
    policy_id: Optional[str] = None                           # SHIPPED
    policy: Optional[EscalationPolicy] = None                 # SHIPPED
    current_tier_level: int = Field(default=0, ge=0)          # SHIPPED
    source_agent: Optional[str] = None
    source_flow: Optional[str] = None
    source_node: Optional[str] = None
    status: InteractionStatus = InteractionStatus.PENDING

# parrot/human/models.py:238-248
class InteractionResult(BaseModel):
    interaction_id: str
    status: InteractionStatus
    responses: List[HumanResponse] = Field(default_factory=list)
    consolidated_value: Any = None
    timed_out: bool = False
    escalated: bool = False
    tier_level: int = Field(default=0, ge=0)                  # SHIPPED
    action_metadata: Dict[str, Any] = Field(default_factory=dict)  # SHIPPED

# parrot/human/actions/base.py:9-22
class EscalationAction(ABC):
    @abstractmethod
    async def execute(
        self,
        interaction: HumanInteraction,
        tier: EscalationTier,
    ) -> Dict[str, Any]: ...

# parrot/human/actions/notify.py:6-25 — STUB to be replaced (C3)
class NotifyAction(EscalationAction):
    async def execute(self, interaction, tier) -> Dict[str, Any]:
        # Currently: logs and returns simulated dict.
        # Will dispatch by tier.action_metadata["kind"] in C3.

# parrot/human/actions/ticket.py:7-28 — STUB to be replaced (C3)
class TicketAction(EscalationAction):
    async def execute(self, interaction, tier) -> Dict[str, Any]:
        # Currently: returns {"ticket_id": "SIM-12345", ...}
        # Will dispatch by tier.action_metadata["kind"] in C3.

# parrot/human/manager.py:60-76
class HumanInteractionManager:
    def __init__(
        self,
        channels: Optional[Dict[str, HumanChannel]] = None,
        redis_url: Optional[str] = None,
    ) -> None:
        # ...
        self._actions: Dict[EscalationActionType, Any] = {
            EscalationActionType.TICKET: TicketAction(),
            EscalationActionType.NOTIFY: NotifyAction(),
        }
        self._policies: Dict[str, EscalationPolicy] = {}

# parrot/human/manager.py:698-780 — _escalate_to_next_tier (current behaviour)
async def _escalate_to_next_tier(
    self, interaction: HumanInteraction, channel: str,
) -> None:
    # picks next_tier; runs action; for INTERACT re-dispatches; for
    # NOTIFY/TICKET resolves immediately with action_metadata.
    # BUG (C4): on action.execute() exception, sets action_metadata={} and
    #           still resolves as if success. Must instead emit
    #           hitl.tier.action_failed and recurse to next tier.

# parrot/human/tool.py:120-123
class HumanToolInput(AbstractToolArgsSchema):
    # ... existing fields ...
    policy_id: Optional[str] = Field(default=None, ...)       # SHIPPED

# parrot/human/tool.py:155-168
class HumanTool(AbstractTool):
    def __init__(
        self,
        manager: Any = None,
        *,
        default_channel: Optional[str] = "telegram",
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...

# parrot/human/node.py:78-100
class HumanDecisionNode:
    is_configured: bool = True
    def __init__(
        self,
        name: str,
        manager: Any,
        interaction_config: Optional[HumanInteraction] = None,
        *,
        channel: str = "telegram",
        target_humans: Optional[List[str]] = None,
        consensus_mode: ConsensusMode = ConsensusMode.FIRST_RESPONSE,
        source_agent: Optional[str] = None,
        source_flow: Optional[str] = None,
    ) -> None: ...

# parrot/human/channels/base.py:11-70
class HumanChannel(ABC):
    channel_type: str = "base"
    @abstractmethod
    async def send_interaction(
        self, interaction: HumanInteraction, recipient: str,
    ) -> bool: ...
    @abstractmethod
    async def register_response_handler(
        self, callback: Callable[[HumanResponse], Awaitable[None]],
    ) -> None: ...
    async def register_cancel_handler(
        self, callback: Callable[[str], Awaitable[bool]],
    ) -> None: return None

# parrot/core/exceptions.py:12-41
class HumanInteractionInterrupt(ParrotError):
    def __init__(
        self,
        prompt: str,
        interaction_id: Optional[str] = None,
        policy_id: Optional[str] = None,
        *args, **kwargs
    ): ...

# parrot/core/tools/handoff.py:22-76
class HandoffTool(AbstractTool):
    name: str = "handoff_to_human"
    args_schema: Type[BaseModel] = HandoffToolSchema   # includes policy_id
    def __init__(self, manager: Any = None, **kwargs): ...
    async def _aexecute(self, prompt, policy_id=None, **kwargs):
        # Current: registers with manager via request_human_input_async
        # (if available) AND raises HumanInteractionInterrupt unconditionally.
        # C10 will change this so it returns the manager result string
        # instead of raising when the registered interaction resolves
        # immediately.
    def _execute(self, prompt, **kwargs):
        raise HumanInteractionInterrupt(prompt=prompt)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Severity` enum | `HumanToolInput`, `HumanInteraction.severity` | new field | parrot/human/models.py:135-185 |
| `BusinessHours` | `EscalationTier.business_hours` | new field | parrot/human/models.py:85-112 |
| `EscalationPolicy.select_starting_tier` | `HumanInteractionManager.request_human_input` | called pre-dispatch | parrot/human/manager.py:192-262 |
| `EmailBackend` / `ZammadBackend` / `WebhookBackend` | `NotifyAction.execute` / `TicketAction.execute` | dispatcher by `action_metadata["kind"]` | parrot/human/actions/{notify,ticket}.py |
| `_escalate_to_next_tier` bug fix | itself | recurse on action exception | parrot/human/manager.py:733-740 |
| `manager.advance_chain(id, cause)` | channels (reject button), web_hitl handler | public method | parrot/human/manager.py |
| `RejectIntentDetector` | `HumanInteractionManager.receive_response` | inline `await` before accumulation | parrot/human/manager.py:368-441 |
| `__escalate__` ChoiceOption value | `manager.advance_chain(cause="reject")` | intercepted in `receive_response` | parrot/human/manager.py:368-441 |
| `HandoffTool._aexecute` | `HumanInteractionManager.get_result` | post-registration short-circuit | parrot/human/manager.py:354-362 |
| Orchestrator `policy_id` short-circuit | `HumanInteractionInterrupt.policy_id` + `interaction_id` | conditional path | parrot/autonomous/orchestrator.py:541-564 + 824 |
| `EmailBackend` | SMTP config keys | reads existing `smtp_host`/`smtp_port`/`smtp_host_user`/`smtp_host_password` | parrot/handlers/agents/abstract.py:581-584 |
| Tier events | `EventEmitterMixin.emit` | inheritance OR `on_event` hook on manager | parrot/tools/abstract.py:78 |
| Redis namespace | unchanged | reuse `hitl:interaction:{id}`, `hitl:responses:{id}`, `hitl:result:{id}` | parrot/human/manager.py:88-138 |

### Does NOT Exist (Anti-Hallucination)

- ~~`AskAlternateHumansAction` / `OpenTicketAction` / `LiveChatHandoffAction` / `EmailAction` as standalone classes~~ — the shipped baseline uses
  the `EscalationActionType` enum + `action_metadata["kind"]` dispatcher
  pattern. Do not introduce new top-level `*Action` classes that mirror
  the enum.
- ~~`EscalationActionConfig` discriminated union~~ — explicitly NOT in
  V1 (rejected in favour of the shipped enum + dict shape).
- ~~`HumanTool.escalation_policy` ctor kwarg~~ — the V1 contract is
  `policy_id` only; the policy itself lives in `manager._policies`.
- ~~`EscalationPolicy.resolve_chain`~~ — replaced by
  `select_starting_tier(severity, now)` returning a single starting
  tier (the rest of the chain is the policy's `tiers` list).
- ~~`PolicyRegistry` as a separate class~~ — the registry is just
  `manager._policies: Dict[str, EscalationPolicy]`. No standalone class.
- ~~`escalation_chain` field on `HumanInteraction`~~ — the snapshot is
  the whole `HumanInteraction.policy` field (already shipped).
- ~~`InteractionStatus.REJECTED`~~ — does not exist; reject is a *cause*
  for `advance_chain`, the resulting status is still `ESCALATED` /
  `COMPLETED`.
- ~~`parrot.events.EventBus` as a separate bus~~ — events flow on the
  existing `EventEmitterMixin` (parrot/tools/abstract.py:78). The
  manager either inherits from it OR exposes an `on_event` hook;
  decide during C7 implementation.
- ~~Zendesk client / `parrot.clients.zendesk`~~ — out of scope for V1.
- ~~Cross-channel correlation by ticket custom field~~ — out of scope
  for V1.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- All new code is async/await with `aiohttp` / `aiosmtplib`. No
  `requests`/`httpx`.
- Pydantic v2 models for `Severity`, `BusinessHours`, action backend
  payload schemas. Use `Field` constraints and `model_validator` for
  cross-field invariants.
- Loggers: `self.logger = logging.getLogger("parrot.human.<sub>")`.
- Backends raise typed exceptions (`EmailBackendError`,
  `ZammadBackendError`, `WebhookBackendError` — all subclasses of a
  shared `ActionBackendError`); the dispatcher (`NotifyAction` /
  `TicketAction`) catches `ActionBackendError` and re-raises as a
  generic failure that the manager translates into a tier advance.
- Reject button option uses the stable sentinel
  `ESCALATE_OPTION_KEY = "__escalate__"`; channels and manager compare
  against this constant rather than string literals.
- `select_starting_tier` is a pure method — no I/O, no logging — so
  it's exhaustively unit-testable.

### Known Risks / Gotchas

- **Action-failure silent continuation (C4)**: the shipped
  `_escalate_to_next_tier` swallows `action.execute()` exceptions and
  still resolves the future with `action_metadata={}`. The LLM sees
  `"(no response provided)"`. Fix: emit
  `hitl.tier.action_failed`, advance via recursive call to the next
  tier, terminate if chain exhausts.
- **`HandoffTool` dual-path race**: today `_aexecute` (a) calls
  `request_human_input_async` (which schedules the timeout task), then
  (b) raises `HumanInteractionInterrupt` — so the orchestrator suspends
  the agent regardless. If the registered interaction has a non-INTERACT
  starting tier, the manager resolves it almost immediately. C10 + C11
  must coordinate so the orchestrator notices the resolved result
  before re-entering suspend.
- **Tier business-hours boundary**: evaluated at *tier-entry time*. A
  tier that enters at 17:55 with a 1h timeout times out at 18:55 even
  if hours end at 18:00. Document this in §6 of the example doc.
- **Severity is set once**: `HumanInteraction.severity` does not change
  mid-chain. Document this. `min_severity` on tiers acts as a *floor*
  for the starting tier only; it doesn't gate later-tier advancement.
- **Backwards compat with the example doc**: the example doc uses
  `action_metadata={"channel": "email"}` and
  `action_metadata={"platform": "jira", "project": "OPS"}`. The
  dispatcher in C3 must accept both legacy keys (`channel`, `platform`)
  AND the new `kind` key. Treat `channel=email` ≡ `kind=email`;
  treat `platform=jira` as `kind=jira` (which is NOT in V1 — log a
  warning and fall back to `kind=zammad` so existing examples don't
  crash).
- **Reject button on channels without it (CLI)**: free-text path must
  also work — `RejectIntentDetector` runs in `receive_response`
  regardless of channel.
- **Redis TTL**: chain advancement extends the lifetime of the
  interaction. Use `max(interaction.timeout, sum(t.timeout for t in
  policy.tiers)) + 60` with a 24h cap. The current TTL formula
  (`interaction.timeout + 60`) is too short for multi-tier chains.
- **Groq Haiku optional dependency**: `RejectIntentDetector` MUST
  accept `llm_client=None` and fall back to regex-only when no client
  is configured. No hard import of `parrot.clients.groq` at module top.
- **EmailBackend recipient validation**: validate the `to` list with
  `email_validator` (already in the dep tree via Pydantic) or a simple
  regex; reject empty lists with a typed exception.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiosmtplib` | `>=3.0` | `EmailBackend` async SMTP send |
| `aiohttp` | existing | `ZammadBackend` + `WebhookBackend` |
| `pydantic` | existing (`>=2`) | All new models |
| `python-dateutil` / `pytz` | existing | `BusinessHours` timezone math |
| `redis.asyncio` | existing | Unchanged |
| `parrot.clients.groq` | existing | Optional Groq Haiku for `RejectIntentDetector` |

---

## 8. Open Questions

> Resolved questions from the brainstorm are carried forward; new
> ones surfaced during the reconciliation are unchecked.

- [x] Granularity of `EscalationPolicy` — *Resolved in brainstorm*: per-agent / per-policy_id.
- [x] Wiring model — *Resolved by shipped implementation*: registry on `manager._policies` (Option B in brainstorm). Spec ratifies this.
- [x] V1 action set — *Resolved*: Email + Webhook (live chat) + Zammad. Mapped onto `EscalationActionType.NOTIFY` + `TICKET` via `action_metadata["kind"]` dispatcher.
- [x] V1 trigger set — *Resolved*: TIMEOUT (shipped) + EXPLICIT_REJECT + SEVERITY + BUSINESS_HOURS_OFF (this spec).
- [x] Async-action resolution semantics — *Resolved by shipped implementation*: fire-and-forget with `action_metadata["message"]`.
- [x] Cross-channel correlation — *Resolved*: out of scope for V1.
- [x] `HandoffTool` fate — *Resolved*: keep with `DeprecationWarning`, dedup dual-path via C10/C11.
- [x] Business-hours model — *Resolved in brainstorm*: per-tier `business_hours`.
- [x] Severity API — *Resolved in brainstorm*: `severity` parameter on `ask_human` + `HumanInteraction.severity`.
- [x] `EXPLICIT_REJECT` UX — *Resolved in brainstorm*: standardised button (Telegram/Web) + `RejectIntentDetector` with regex-first / Groq-Haiku-on-doubt.
- [x] Live-chat platform — *Resolved*: generic webhook V1.
- [x] Zendesk in V1 — *Resolved*: no, V2.
- [x] Audit logs — *Resolved*: Redis only.
- [x] Reject detector implementation — *Resolved*: regex first, Groq Haiku inline confirmation on doubt, not callback.
- [x] HumanDecisionNode policy — *Resolved*: include in V1.
- [x] Telemetry hook — *Resolved*: emit `hitl.tier.*` / `hitl.chain.*` on `EventEmitterMixin`.
- [ ] Should the manager inherit from `EventEmitterMixin` directly, or expose an `on_event: Optional[Callable]` hook the integration layer wires? Decide during C7.
- [ ] Default `llm_timeout_seconds` for `RejectIntentDetector` — proposing 1.5s; confirm during C5.
- [ ] Initial regex phrase list for `RejectIntentDetector` (Spanish + English seeds) — decide during C5; ship ≥ 8 phrases per language.
- [ ] Zammad REST auth method — assume `Authorization: Token token=…` per Zammad default; verify against the target deployment during C2.
- [ ] Webhook payload schema for `WebhookBackend` — V1 freezes `{interaction_id, question, severity, user_id}` → `{deep_link}`; confirm with the live-chat operator.
- [ ] Treatment of legacy `action_metadata={"platform": "jira"}` from the example doc — proposal: log warning and treat as `kind=zammad`. Decide during C3.

---

## Worktree Strategy

- **Default isolation**: **per-spec** (all C-tasks sequential in one
  worktree).
- **Rationale**: C1 (models) and C4 (manager refactor + bug fix)
  underpin everything else. C2/C3 (backends + dispatcher) depend on C1.
  C6/C12 depend on C4. C7 depends on C4. C10/C11 depend on C4.
  Splitting per-task produces a rebase storm with negligible
  parallelism win.
- **Cross-feature dependencies**: none blocking. FEAT-045 (handoff
  baseline) is in production. FEAT-176 (`EventEmitterMixin`) is
  available for C7.
- **Worktree creation**:
  ```bash
  git checkout dev
  git worktree add -b feat-194-hitl-escalation-tier \
    .claude/worktrees/feat-194-hitl-escalation-tier HEAD
  ```
- **Baseline reconciliation**: the V1 baseline lives in commit
  `afe70e82`, already on `dev`. The worktree will branch from `HEAD`
  and inherit it. No stashing/reapplying needed.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-21 | Jesus Lara (with Claude) | Initial draft from brainstorm Option A (discriminated `*Action` classes + HumanTool injection). |
| 0.2 | 2026-05-21 | Jesus Lara (with Claude) | Reset against shipped commit `afe70e82`. Ratify Option-B-style registry + enum + `action_metadata` dispatcher as V1 baseline. Reframe spec as baseline (B1–B7) + completion delta (C1–C13): real action backends, EXPLICIT_REJECT/SEVERITY/BUSINESS_HOURS_OFF triggers, reject UX, structured events, HandoffTool dedup, action-failure bug fix. |
