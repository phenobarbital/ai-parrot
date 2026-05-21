---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: HITL Multi-Tier Escalation Policy (per-agent)

**Feature ID**: FEAT-194
**Date**: 2026-05-21
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.7.0

> Brainstorm source: `sdd/proposals/hitl-escalation-tier.brainstorm.md`
> (Option A — Per-Agent `EscalationPolicy` + Pluggable `EscalationAction` Strategies).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

AI-Parrot has **two parallel Human-in-the-Loop (HITL) paths** that don't share
a model of escalation:

1. `parrot.human.*` — rich, async, multi-channel (CLI / Telegram / Web).
   Provides `HumanTool`, `HumanDecisionNode`, `HumanInteractionManager`,
   consensus modes, timeouts. **Escalation today is a single flat hop**: on
   `TimeoutAction.ESCALATE`, the manager re-emits the same interaction to
   `escalation_targets` over the same channel. There is no concept of tiers,
   no concept of *changing the medium* (ticket / email / live chat link),
   and no policy declared at the agent level.

2. `parrot.core.tools.handoff.HandoffTool` — synchronous, in-band with the
   active chat (Telegram / Slack / Teams). Raises `HumanInteractionInterrupt`,
   the `AutonomousOrchestrator` catches it, suspends the agent, sends the
   prompt to the active user, then resumes. Useful for "missing parameter"
   prompts but has no targets, no consensus, no timeouts, no escalation, and
   bypasses `HumanInteractionManager` entirely.

Real-world HITL escalations are not "ask the same question to a backup
person." They follow business rules driven by **criticality + tier-specific
actions** (L0 active user, L1 on-call human, L2 open ticket, L3 live-chat
deep-link, L4 email a manager). These actions are heterogeneous and must be
declared **per-agent** (an HR agent escalates to HR managers; a Finance
agent escalates to a Finance director). The current manager cannot
represent any of this.

### Goals

- Introduce `EscalationPolicy` as a per-agent declarative artifact: ordered
  list of `EscalationTier`s, each with its own trigger, action, targets,
  optional channel override, and optional business-hours window.
- Make `EscalationAction` pluggable (strategy port). Ship four
  implementations in V1: `AskAlternateHumansAction`, `OpenTicketAction`
  (Zammad), `LiveChatHandoffAction` (generic webhook), `EmailAction`
  (aiosmtplib over the existing SMTP config keys).
- Support four triggers in V1: `TIMEOUT`, `EXPLICIT_REJECT`, `SEVERITY`
  (a-priori), `BUSINESS_HOURS_OFF`.
- Inject the policy into `HumanInteraction` at `HumanTool`/`HumanDecisionNode`
  construction time; have `HumanInteractionManager` consume the resolved
  chain when escalating. No global registry in V1.
- Keep `HandoffTool` as a deprecated alias that delegates to
  `HumanInteractionManager` — zero breakage for existing callers; emit a
  `DeprecationWarning` once per process.
- Make `HumanChannel` opt-in to a standardised "↑ Escalar" reject button.
  Telegram and Web render it; CLI doesn't. A lightweight
  `RejectIntentDetector` (regex first, Groq Haiku confirmation only when
  the regex is ambiguous) augments channels that can't render the button.
- Add a `severity` parameter to `ask_human` (low / normal / high / critical)
  so the LLM can declaratively pick a higher starting tier when appropriate.
- Maintain full backwards compatibility: `escalation_targets` (flat list)
  keeps working and is auto-converted to a single `AskAlternateHumansAction`
  tier.
- Async-action outcomes are **fire-and-forget**: a tier that opens a ticket
  or sends an email returns a confirmation string immediately
  (`"[escalated:ticket:zammad] Ticket TKT-123 opened. A human will follow
  up there."`). No cross-channel correlation in V1.
- Emit structured tier-transition events on the existing FEAT-176
  `EventEmitterMixin` bus so observability/audit tooling can subscribe.

### Non-Goals (explicitly out of scope)

- **Cross-channel correlation / agent resume on ticket reply.** When a tier
  opens a ticket, the original agent does NOT wait for the ticket to be
  resolved. A future spec can add custom-field-based correlation.
- **Zendesk adapter in V1.** Only Zammad ships in V1; Zendesk is deferred
  to V2 (resolved in brainstorm).
- **Long-lived audit log persistence beyond Redis.** V1 keeps tier-transition
  history in the same `hitl:*` Redis namespace with the existing TTL.
  Pushing to an external store / log shipper is V2.
- **Concrete live-chat vendor adapter (Intercom / Chatwoot).** V1 ships a
  generic webhook-based `LiveChatHandoffAction`; vendor-specific adapters
  are V2 sub-features.
- **Runtime policy reconfiguration via registry.** Rejected in the
  brainstorm (Option B): policies are injected at agent-construction time
  and require a restart to change. Option B may be added later without
  breaking the V1 contract.
- **LLM-driven policy interpretation.** Rejected in the brainstorm (Option D):
  V1 tiers are deterministic / structured. An LLM-driven *tier-picker* can
  be added on top later.
- **Event-bus-only escalation architecture.** Rejected in the brainstorm
  (Option C): events are *emitted* but escalation control flow remains in
  the manager.

---

## 2. Architectural Design

### Overview

The `Agent` declares an `EscalationPolicy` that contains an ordered list of
`EscalationTier`s. The `HumanTool` (or `HumanDecisionNode`) takes the
policy in its constructor; on every call, it resolves the applicable tier
chain (skipping severity-floored and off-hours tiers) and serialises it
into the `HumanInteraction.escalation_chain` field plus the policy `id`
into `HumanInteraction.escalation_policy_ref`. Both fields are persisted to
Redis along with the interaction, so the chain survives process restarts.

`HumanInteractionManager` is refactored: the current `_escalate` becomes
`_advance_chain`. On a trigger fire (`TIMEOUT`, `EXPLICIT_REJECT`,
`SEVERITY`, `BUSINESS_HOURS_OFF`), the manager picks the next applicable
tier from the persisted chain and calls
`await tier.action.execute(interaction, tier, ctx)`. The action returns an
`EscalationOutcome`:

- `RESOLVED(value)` — a human gave an answer; resolve the future with
  `value`.
- `ASYNC_HANDLED(message)` — a ticket was opened / email sent / link
  generated; resolve the future immediately with the confirmation `message`
  and close the interaction.
- `FAILED(reason)` — action could not execute; the manager advances to the
  next tier (if any) or terminates with `TIMEOUT`/`CANCEL`.

`HandoffTool._execute` is rewritten: instead of raising
`HumanInteractionInterrupt` directly, it builds a `HumanInteraction` with
`target_humans=["__current_user__"]` and `escalation_chain=None`, then
dispatches via `HumanInteractionManager.request_human_input`. A
`DeprecationWarning` is emitted once per process. The old behaviour
(suspending the orchestrator) is preserved by having the manager resolve
the interaction through whichever channel is bound to the active chat
session.

The `AutonomousOrchestrator` gains one small change: when it catches a
`HumanInteractionInterrupt` whose `policy_id` is set, it does NOT block
waiting for resume — the tool already returned the confirmation string
directly, so the orchestrator just propagates that value to the LLM. For
unset `policy_id` (legacy path), behaviour is unchanged.

`HumanChannel` gains an opt-in class attribute
`render_reject_button: bool = False`. Channels that set `True` (Telegram,
Web) append a standard `ChoiceOption(key="__escalate__", label="↑ Escalar")`
to every rendered interaction. When the manager receives a response whose
value is `"__escalate__"`, it treats it as `EXPLICIT_REJECT` and calls
`_advance_chain(interaction_id, cause=Reject)`.

`RejectIntentDetector` runs whenever a free-text response arrives. It first
checks against a regex of canned escalation phrases (Spanish + English).
If the regex matches with high confidence → treat as `EXPLICIT_REJECT`. If
no match but the response is short/ambiguous → optional Groq Haiku call
returns a structured `is_escalate: bool` decision. The Haiku call is **not**
a callback — it's an inline await with a short timeout so it doesn't slow
down the response path noticeably. Both regex and LLM stages are off when
no escalation chain is attached.

Structured `EscalationEvent`s are emitted on `EventEmitterMixin` for every
tier transition (`hitl.tier.entered`, `hitl.tier.advanced`,
`hitl.tier.action_executed`, `hitl.chain.exhausted`). Subscribers register
through the existing event bus; no new infrastructure.

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  Agent(escalation_policy=hr_policy)                                 │
│     │                                                               │
│     └── HumanTool(escalation_policy=hr_policy)                      │
│            │ on _execute:                                           │
│            │   resolve_chain(severity, now) → List[EscalationTier]  │
│            │   build HumanInteraction with                          │
│            │     .escalation_policy_ref, .escalation_chain, .severity│
│            ▼                                                        │
│        HumanInteractionManager.request_human_input(interaction)     │
└──────────────────────────────────────┬──────────────────────────────┘
                                       │ persist + start L0 tier
                                       ▼
            ┌─────────────────────────────────────────────────┐
            │  _advance_chain loop                            │
            │   pick next applicable tier                     │
            │   call tier.action.execute(...)                 │
            └───────┬────────────────────────┬────────────────┘
                    │                        │
         ┌──────────▼──────────┐  ┌──────────▼──────────────┐
         │ AskAlternateHumans  │  │ OpenTicket / Email /    │
         │ (RESOLVED via       │  │ LiveChat (ASYNC_HANDLED)│
         │  HumanChannel reply)│  │  → return confirmation  │
         └──────────┬──────────┘  │     string immediately  │
                    │             └─────────────────────────┘
            on TIMEOUT or
            EXPLICIT_REJECT
            (from button or
             RejectIntentDetector)
                    │
                    ▼
            advance_chain → next tier
                    │
            chain exhausted → CANCEL/TIMEOUT

            ─── (in parallel) ───────────────────────────────
            EventEmitterMixin emits:
              hitl.tier.entered, hitl.tier.advanced,
              hitl.tier.action_executed, hitl.chain.exhausted
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.human.manager.HumanInteractionManager` | modifies | `_escalate` → `_advance_chain` loop + action runner; persists chain to Redis |
| `parrot.human.models.HumanInteraction` | extends | New fields: `escalation_chain`, `escalation_policy_ref`, `severity`. `escalation_targets` retained as legacy alias |
| `parrot.human.tool.HumanTool` | extends | New ctor kwarg `escalation_policy`; `HumanToolInput` adds `severity` field |
| `parrot.human.node.HumanDecisionNode` | extends | Mirrors HumanTool: new ctor kwarg `escalation_policy`; honoured in V1 (per brainstorm decision) |
| `parrot.human.channels.base.HumanChannel` | extends | New class attr `render_reject_button: bool = False`; standard reject `ChoiceOption` constant |
| `parrot.human.channels.telegram.TelegramHumanChannel` | extends | Sets `render_reject_button = True`; renders the inline button |
| `parrot.human.channels.web.WebHumanChannel` | extends | Sets `render_reject_button = True`; renders the equivalent UI affordance |
| `parrot.human.channels.cli.CLIHumanChannel` | none | Leaves `render_reject_button = False`; intent detector still applies |
| `parrot.core.tools.handoff.HandoffTool` | refactors | Becomes deprecated alias delegating to `HumanInteractionManager`; `DeprecationWarning` once per process |
| `parrot.core.exceptions.HumanInteractionInterrupt` | none | `interaction_id` and `policy_id` slots already exist |
| `parrot.autonomous.orchestrator.AutonomousOrchestrator` | minor | When `interrupt.policy_id` is set, don't re-enter suspend/resume — propagate the tool result directly |
| `parrot.integrations.manager.IntegrationBotManager` | none in V1 | Manager wiring unchanged |
| `parrot.handlers.web_hitl` | minor | Route the reject button callback to `manager.advance_chain(interaction_id, cause=REJECT)` |
| `parrot.tools.abstract.EventEmitterMixin` (FEAT-176) | uses | Emit structured tier-transition events |
| `parrot.handlers.agents.abstract` SMTP config | reuses | `EmailAction` reads existing `smtp_host`/`smtp_port`/`smtp_host_user`/`smtp_host_password` keys |

### Data Models

```python
# parrot/human/escalation/models.py (NEW)

class Severity(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class BusinessHours(BaseModel):
    tz: str                              # IANA, e.g. "Europe/Madrid"
    days: str                            # "mon-fri" | "mon-sun" | "mon,wed,fri"
    hours: str                           # "09:00-18:00"


class EscalationTrigger(BaseModel):
    """Discriminated union via `type` field."""
    type: Literal[
        "timeout", "reject", "severity", "business_hours_off"
    ]
    # Per-type fields:
    seconds: Optional[float] = None      # type=timeout
    min_severity: Optional[Severity] = None  # type=severity


class EscalationActionConfig(BaseModel):
    """Discriminated union via `type` field — defines an action without instantiating it."""
    type: Literal[
        "ask_alternate_humans", "open_ticket",
        "live_chat_handoff", "email"
    ]
    # Per-type fields (subset shown):
    targets: Optional[List[str]] = None
    platform: Optional[Literal["zammad"]] = None   # open_ticket — V1: zammad only
    queue: Optional[str] = None                     # open_ticket
    title_template: Optional[str] = None            # open_ticket
    webhook_url: Optional[str] = None               # live_chat_handoff
    to: Optional[List[str]] = None                  # email
    subject_template: Optional[str] = None          # email


class EscalationTier(BaseModel):
    level: int                                    # 1, 2, 3...
    label: str                                    # "HR on-call"
    trigger: EscalationTrigger
    action: EscalationActionConfig
    channel: Optional[str] = None                 # channel override
    business_hours: Optional[BusinessHours] = None


class EscalationPolicy(BaseModel):
    id: str                                       # stable identifier, used in logs/audit
    tiers: List[EscalationTier]                   # must be non-empty; validator enforces

    def resolve_chain(
        self, severity: Severity, now: datetime,
    ) -> List[EscalationTier]:
        """Return the ordered applicable tiers, skipping severity-floored
        and off-hours ones. Pure function — easy to unit-test."""


class EscalationOutcome(BaseModel):
    """Returned by EscalationAction.execute."""
    status: Literal["resolved", "async_handled", "failed"]
    value: Any = None                             # human answer (resolved) or confirmation string (async_handled)
    reason: Optional[str] = None                  # failed reason

# parrot/human/models.py — EXTENDED fields on existing HumanInteraction:
class HumanInteraction(BaseModel):
    # ... existing fields unchanged ...
    severity: Optional[Severity] = None                          # NEW
    escalation_policy_ref: Optional[str] = None                  # NEW — policy.id
    escalation_chain: Optional[List[EscalationTier]] = None      # NEW — resolved snapshot
    current_tier_level: Optional[int] = None                     # NEW — runtime cursor
    # escalation_targets: Optional[List[str]] kept as legacy alias;
    #   auto-converted to a single AskAlternateHumansAction tier when set.
```

### New Public Interfaces

```python
# parrot/human/escalation/actions/base.py (NEW)
class EscalationAction(ABC):
    """Pluggable strategy: do something with an interaction at a given tier."""
    @abstractmethod
    async def execute(
        self,
        interaction: "HumanInteraction",
        tier: "EscalationTier",
        ctx: "EscalationContext",
    ) -> EscalationOutcome: ...


# parrot/human/escalation/intent.py (NEW)
class RejectIntentDetector:
    def __init__(
        self,
        regex_phrases: Optional[List[str]] = None,
        llm_client: Optional["AbstractClient"] = None,
        llm_timeout_seconds: float = 1.5,
    ) -> None: ...
    async def is_escalation_intent(self, text: str) -> bool: ...


# parrot/human/tool.py — extended ctor
class HumanTool(AbstractTool):
    def __init__(
        self,
        manager: Any = None,
        *,
        default_channel: str = "telegram",
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        escalation_policy: Optional["EscalationPolicy"] = None,   # NEW
        **kwargs: Any,
    ) -> None: ...


# parrot/human/node.py — extended ctor
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
        escalation_policy: Optional["EscalationPolicy"] = None,   # NEW
    ) -> None: ...


# parrot/human/manager.py — new public method
class HumanInteractionManager:
    async def advance_chain(
        self,
        interaction_id: str,
        cause: Literal["timeout", "reject", "severity", "business_hours_off", "action_failed"],
    ) -> None:
        """Public entry point for channels to trigger explicit escalation."""
```

---

## 3. Module Breakdown

> Each module below maps to one or more Task Artifacts in Phase 2.

### Module 1: Escalation data models

- **Path**: `parrot/human/escalation/models.py`
- **Responsibility**: Pydantic models for `Severity`, `BusinessHours`,
  `EscalationTrigger`, `EscalationActionConfig`, `EscalationTier`,
  `EscalationPolicy`, `EscalationOutcome`, plus `EscalationPolicy.resolve_chain`.
- **Depends on**: stdlib `datetime`, `zoneinfo` (with `pytz` fallback for
  Windows), `pydantic` ≥ 2.

### Module 2: Escalation action port + foundation tier

- **Path**: `parrot/human/escalation/actions/base.py` and
  `parrot/human/escalation/actions/ask_alternate_humans.py`.
- **Responsibility**: `EscalationAction` ABC + `EscalationContext`
  dataclass. `AskAlternateHumansAction` is the V1 refactor of the current
  `_escalate` behaviour — re-emits the interaction to alternate targets via
  the manager.
- **Depends on**: Module 1.

### Module 3: HumanInteraction model extension + Redis schema

- **Path**: `parrot/human/models.py`
- **Responsibility**: Add `severity`, `escalation_policy_ref`,
  `escalation_chain`, `current_tier_level` fields. Add an auto-conversion
  validator so legacy `escalation_targets` becomes a one-tier
  `AskAlternateHumansAction` chain.
- **Depends on**: Module 1, Module 2.

### Module 4: Manager refactor — `_advance_chain` loop + `advance_chain` public API

- **Path**: `parrot/human/manager.py`
- **Responsibility**: Rename `_escalate` to `_advance_chain`. Add tier
  selection logic, action invocation, outcome handling, public
  `advance_chain` method for channel-driven escalation. Preserve
  consensus, timeout, and ownership-validation semantics for tiers whose
  action is `AskAlternateHumansAction`. Persist the active chain + cursor
  to Redis with each transition.
- **Depends on**: Modules 1, 2, 3.

### Module 5: `OpenTicketAction` + Zammad async REST client

- **Path**: `parrot/human/escalation/actions/open_ticket.py` and
  `parrot/clients/zammad.py`.
- **Responsibility**: Zammad REST adapter (auth via token, create-ticket
  API). `OpenTicketAction` formats `title_template` / `body` from the
  interaction, calls the client, returns
  `EscalationOutcome.async_handled(f"[escalated:ticket:zammad] Ticket {n} opened.")`.
- **Depends on**: Module 1, Module 2 (port). `aiohttp` (existing).

### Module 6: `EmailAction`

- **Path**: `parrot/human/escalation/actions/email.py`
- **Responsibility**: aiosmtplib-backed async email sender. Reads existing
  SMTP config keys (`smtp_host`, `smtp_port`, `smtp_host_user`,
  `smtp_host_password`) from the agent/integration config. Formats
  `subject_template` / body, sends, returns
  `EscalationOutcome.async_handled(...)`.
- **Depends on**: Module 1, Module 2 (port). `aiosmtplib` ≥ 3.0.

### Module 7: `LiveChatHandoffAction` (generic webhook)

- **Path**: `parrot/human/escalation/actions/live_chat.py`
- **Responsibility**: POST a JSON payload (interaction_id, question,
  user_id, severity) to a configured `webhook_url`. Expects the webhook to
  return a `deep_link` string. Returns
  `EscalationOutcome.async_handled(f"[escalated:live_chat] {deep_link}")`.
- **Depends on**: Module 1, Module 2 (port). `aiohttp` (existing).

### Module 8: `RejectIntentDetector`

- **Path**: `parrot/human/escalation/intent.py`
- **Responsibility**: Regex stage with a curated Spanish + English phrase
  list (e.g., "pasame con un humano", "I need a human", "escalate me").
  Optional Groq Haiku stage when the regex is ambiguous and a client is
  configured. Returns `bool`. **Not a callback** — synchronous inline
  await with a short timeout (default 1.5s).
- **Depends on**: `parrot.clients.groq` (optional).

### Module 9: `HumanChannel` reject-button hook + Telegram/Web implementations

- **Path**: `parrot/human/channels/base.py`,
  `parrot/human/channels/telegram.py`, `parrot/human/channels/web.py`
- **Responsibility**: Add `render_reject_button: bool = False` class attr
  on `HumanChannel`. Define module-level constant
  `ESCALATE_OPTION = ChoiceOption(key="__escalate__", label="↑ Escalar")`.
  Telegram and Web channels set `render_reject_button = True` and inject
  `ESCALATE_OPTION` into every rendered interaction. CLI is unchanged.
- **Depends on**: Module 1 (key constant).

### Module 10: Web HITL handler — reject callback route

- **Path**: `parrot/handlers/web_hitl.py`
- **Responsibility**: When a response comes in with value `"__escalate__"`,
  call `manager.advance_chain(interaction_id, cause="reject")` instead of
  the normal `receive_response` flow.
- **Depends on**: Module 4, Module 9.

### Module 11: `HumanTool` + `HumanDecisionNode` policy injection + severity input

- **Path**: `parrot/human/tool.py`, `parrot/human/node.py`
- **Responsibility**: Add `escalation_policy` ctor kwarg to both. Add
  `severity` field to `HumanToolInput`. On `_execute`, both call
  `policy.resolve_chain(severity, now)` and attach the result to the
  `HumanInteraction`. Tool description is updated to teach the LLM about
  `severity`.
- **Depends on**: Module 1, Module 3.

### Module 12: `HandoffTool` deprecation alias

- **Path**: `parrot/core/tools/handoff.py`
- **Responsibility**: Rewrite `_execute` / `_aexecute` to build a
  `HumanInteraction` with `target_humans=["__current_user__"]`,
  `escalation_policy=None`, and dispatch via the process-wide
  `HumanInteractionManager` (`get_default_human_manager()`). Emit
  `DeprecationWarning` once per process. Existing callers
  (`parrot/agents/demo.py:194`) continue working.
- **Depends on**: Module 4.

### Module 13: Orchestrator policy-aware interrupt handling

- **Path**: `parrot/autonomous/orchestrator.py`
- **Responsibility**: When a caught `HumanInteractionInterrupt` carries a
  non-null `policy_id`, treat as already-handled: do NOT re-enter
  suspend/resume — propagate the tool's return value to the LLM. Legacy
  (null `policy_id`) path is unchanged.
- **Depends on**: Module 4.

### Module 14: Structured escalation events

- **Path**: `parrot/human/escalation/events.py`
- **Responsibility**: Define `EscalationEvent` Pydantic models for
  `hitl.tier.entered`, `hitl.tier.advanced`, `hitl.tier.action_executed`,
  `hitl.chain.exhausted`. Wire emission from inside `_advance_chain`
  using `EventEmitterMixin`.
- **Depends on**: Module 4. `parrot.tools.abstract.EventEmitterMixin`
  (FEAT-176).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_escalation_policy_resolve_chain_severity_floor` | 1 | `severity=critical` skips L0/L1 tiers |
| `test_escalation_policy_resolve_chain_business_hours_off` | 1 | Off-hours tiers are skipped at chain build time |
| `test_escalation_policy_empty_tiers_rejected` | 1 | Constructing a policy with zero tiers raises |
| `test_business_hours_boundary_at_tier_entry` | 1 | Boundary is evaluated at tier-entry time, not mid-flight |
| `test_ask_alternate_humans_action_resolved_outcome` | 2 | Returns `RESOLVED(value)` when a human replies |
| `test_human_interaction_legacy_escalation_targets_auto_converted` | 3 | Setting `escalation_targets=["x"]` produces a one-tier chain |
| `test_advance_chain_picks_next_applicable_tier` | 4 | Cursor moves forward correctly on timeout |
| `test_advance_chain_skips_off_hours_tier_at_runtime` | 4 | Off-hours re-evaluation at advance time |
| `test_advance_chain_exhausted_falls_back_to_cancel_or_default` | 4 | Terminal state when chain runs out |
| `test_advance_chain_action_failed_advances_to_next_tier` | 4 | `FAILED` outcome triggers next tier |
| `test_open_ticket_action_zammad_success_returns_async_handled` | 5 | Returns confirmation with ticket number |
| `test_open_ticket_action_zammad_http_failure_returns_failed` | 5 | HTTP failure → `FAILED`, next tier picked |
| `test_email_action_smtp_send_returns_async_handled` | 6 | Mocked aiosmtplib send returns confirmation |
| `test_email_action_smtp_failure_returns_failed` | 6 | SMTP refusal → `FAILED` |
| `test_live_chat_handoff_webhook_returns_deep_link` | 7 | Webhook returns link, action returns confirmation |
| `test_reject_intent_detector_regex_match_es` | 8 | "pasame con un humano" → True |
| `test_reject_intent_detector_regex_match_en` | 8 | "I need a human" → True |
| `test_reject_intent_detector_llm_fallback_on_ambiguous` | 8 | Mocked Groq Haiku response is honoured |
| `test_reject_intent_detector_llm_timeout_returns_false` | 8 | LLM timeout doesn't escalate |
| `test_telegram_channel_renders_reject_button` | 9 | Inline keyboard contains `__escalate__` option |
| `test_cli_channel_does_not_render_reject_button` | 9 | Reject option absent on CLI |
| `test_web_hitl_reject_callback_routes_to_advance_chain` | 10 | `value="__escalate__"` triggers escalation |
| `test_human_tool_severity_routes_to_starting_tier` | 11 | `severity="critical"` skips lower tiers |
| `test_human_decision_node_with_escalation_policy` | 11 | Node honours policy at flow time |
| `test_handoff_tool_emits_deprecation_warning_once` | 12 | `DeprecationWarning` fires exactly once per process |
| `test_handoff_tool_delegates_to_manager` | 12 | Old behaviour reproduced via new path |
| `test_orchestrator_skips_suspend_for_policy_handled_interrupt` | 13 | `policy_id` set → no suspend/resume |
| `test_escalation_event_emitted_on_tier_advance` | 14 | Event with correct payload observed on the bus |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_telegram_tier_chain_timeout_to_ticket` | L1 (Telegram) times out → L2 opens Zammad ticket → tool returns confirmation string to LLM |
| `test_e2e_web_reject_button_advances_to_email_tier` | Web user taps "↑ Escalar" → L3 email is sent → agent receives confirmation |
| `test_e2e_severity_critical_skips_to_l3_email` | Agent calls `ask_human(severity="critical")` → manager picks L3 email directly |
| `test_e2e_handoff_tool_legacy_callsite_still_works` | Existing `HandoffTool` callsite from `parrot/agents/demo.py` works end-to-end with only a deprecation warning |
| `test_e2e_chain_exhaustion_returns_cancel_message` | All tiers fail / time out → final return is the documented "no human available" string |
| `test_e2e_redis_persistence_chain_survives_manager_restart` | Kill manager mid-flight; restart; advance_chain on the surviving interaction succeeds |

### Test Data / Fixtures

```python
# tests/human/escalation/conftest.py — new fixtures
@pytest.fixture
def hr_policy() -> EscalationPolicy:
    """3-tier HR policy: L1 alternate humans, L2 Zammad ticket, L3 email."""

@pytest.fixture
def mock_zammad_server(aiohttp_server):
    """Stub Zammad REST endpoint returning {ticket_id: 'TKT-123'}."""

@pytest.fixture
def mock_smtp_server():
    """In-memory aiosmtplib server."""

@pytest.fixture
def mock_groq_haiku_client():
    """Stub AbstractClient that returns structured {is_escalate: bool}."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests in §4 pass (`pytest packages/ai-parrot/tests/human/escalation/ -v`).
- [ ] All integration tests in §4 pass.
- [ ] `HandoffTool` continues to work with zero callsite changes (verified
  by re-running existing `tests/core/tools/test_handoff_tool.py` and
  `tests/agents/test_demo.py` without modification).
- [ ] Legacy `escalation_targets: List[str]` field continues to work; an
  existing `HumanInteraction(escalation_targets=[...])` payload from before
  this feature still escalates correctly.
- [ ] `EscalationPolicy` with zero tiers raises at construction (Pydantic
  validator).
- [ ] `severity="critical"` on `ask_human` causes the manager to skip lower
  tiers per the policy's severity floors.
- [ ] Tier with `business_hours` set is skipped when `now` falls outside
  the window at the moment of entry.
- [ ] `OpenTicketAction` against a stub Zammad server returns a
  confirmation string containing the ticket id.
- [ ] `EmailAction` against an in-memory SMTP server returns a confirmation
  string and the email body contains the original `interaction.question`.
- [ ] `LiveChatHandoffAction` POSTs to the configured webhook with the
  documented payload shape and returns the deep-link in the confirmation.
- [ ] Telegram channel renders the "↑ Escalar" inline button on every
  interaction; tapping it advances the chain.
- [ ] Web channel renders the equivalent affordance and routes through
  `advance_chain`.
- [ ] CLI channel is unaffected and continues to render only the
  interaction's own options.
- [ ] `RejectIntentDetector` returns `True` for at least 8 canned phrases
  (4 Spanish + 4 English) and `False` for clearly unrelated free-text.
- [ ] LLM-fallback path of `RejectIntentDetector` honours its
  `llm_timeout_seconds` and returns `False` on timeout (does not block the
  response).
- [ ] `HumanInteractionInterrupt` raised inside an escalation-enabled tool
  does NOT cause the orchestrator to suspend the agent (verified by
  asserting no suspend/resume entries in the orchestrator history).
- [ ] Structured events (`hitl.tier.entered`, `hitl.tier.advanced`,
  `hitl.tier.action_executed`, `hitl.chain.exhausted`) are emitted on the
  `EventEmitterMixin` bus with the documented payload shape.
- [ ] `DeprecationWarning` is emitted exactly once per process when
  `HandoffTool` is instantiated.
- [ ] No new external dependency is added other than `aiosmtplib`
  (Zammad / live-chat / events use `aiohttp` / stdlib / existing
  `EventEmitterMixin`).
- [ ] `ruff check packages/ai-parrot/src/parrot/human/escalation/` passes.
- [ ] `mypy packages/ai-parrot/src/parrot/human/escalation/` passes.
- [ ] Docs added under `docs/human/escalation/` covering: declaring an
  `EscalationPolicy`, the four V1 actions, the four V1 triggers, and the
  `severity` parameter.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the
> codebase. Implementation agents MUST NOT reference imports, attributes,
> or methods not listed here without first verifying via `grep` or `read`.

### Verified Imports

```python
# All confirmed at HEAD:
from parrot.human import (
    HumanInteractionManager, HumanInteraction, HumanResponse,
    HumanChannel, InteractionType, InteractionStatus, TimeoutAction,
    ConsensusMode, ChoiceOption, HumanTool, HumanDecisionNode,
    set_default_human_manager, get_default_human_manager,
)                                        # parrot/human/__init__.py:10-87
from parrot.human.channels.base import HumanChannel
from parrot.human.channels.cli import CLIHumanChannel, CLIDaemonHumanChannel
from parrot.human.channels.telegram import TelegramHumanChannel  # lazy via __getattr__
from parrot.human.channels.web import WebHumanChannel
from parrot.human.manager import HumanInteractionManager
from parrot.human.tool import HumanTool, HumanToolInput
from parrot.human.node import HumanDecisionNode
from parrot.human.models import (
    InteractionType, InteractionStatus, TimeoutAction, ConsensusMode,
    ChoiceOption, HumanInteraction, HumanResponse, InteractionResult,
)
from parrot.core.tools.handoff import HandoffTool, HandoffToolSchema
from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
```

### Existing Class Signatures

```python
# parrot/human/models.py:60-90
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

# parrot/human/models.py:22-32
class InteractionStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    PARTIAL = "partial"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ESCALATED = "escalated"          # already reserved
    CANCELLED = "cancelled"

# parrot/human/models.py:34-41
class TimeoutAction(str, Enum):
    CANCEL = "cancel"
    DEFAULT = "default"
    ESCALATE = "escalate"            # drives the current single-hop escalation
    RETRY = "retry"

# parrot/human/manager.py:34-67
class HumanInteractionManager:
    def __init__(
        self,
        channels: Optional[Dict[str, HumanChannel]] = None,  # line 58
        redis_url: Optional[str] = None,                     # line 59
    ) -> None: ...

# parrot/human/manager.py:634-699 — to be REPLACED by _advance_chain
async def _escalate(
    self, interaction: HumanInteraction, channel: str,
) -> None: ...

# parrot/human/tool.py:98-139
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

# parrot/human/channels/base.py:11-57
class HumanChannel(ABC):
    channel_type: str = "base"                                         # line 19
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
    ) -> None: return None  # default no-op

# parrot/core/exceptions.py:11-40 — ALREADY has policy_id slot
class HumanInteractionInterrupt(ParrotError):
    def __init__(
        self,
        prompt: str,
        interaction_id: Optional[str] = None,                          # line 22
        policy_id: Optional[str] = None,                               # line 23 — reserved for THIS feature
        *args, **kwargs
    ): ...

# parrot/core/tools/handoff.py:18-44
class HandoffTool(AbstractTool):
    name: str = "handoff_to_human"
    args_schema: Type[BaseModel] = HandoffToolSchema
    def _execute(self, prompt: str, **kwargs: Any) -> Any: ...
    async def _aexecute(self, prompt: str, **kwargs: Any) -> Any: ...

# parrot/tools/abstract.py:78 — base
class AbstractTool(EventEmitterMixin, ABC): ...
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `EscalationPolicy` | `HumanTool.__init__` | new kwarg `escalation_policy` | parrot/human/tool.py:126-139 |
| `EscalationPolicy` | `HumanDecisionNode.__init__` | new kwarg `escalation_policy` | parrot/human/node.py:78-99 |
| `EscalationPolicy.resolve_chain()` | `HumanTool._execute` | called inline before building `HumanInteraction` | parrot/human/tool.py:141-205 |
| `HumanInteraction.escalation_chain` | `HumanInteractionManager._advance_chain` | read at trigger fire | parrot/human/manager.py:634-699 (current `_escalate`) |
| `EscalationAction.execute()` | `_advance_chain` | called per tier | parrot/human/manager.py (new method) |
| `EscalationEvent` | `EventEmitterMixin.emit` | called from `_advance_chain` | parrot/tools/abstract.py:78 |
| `RejectIntentDetector` | `HumanInteractionManager.receive_response` | called before normal accumulation | parrot/human/manager.py:368-441 |
| `__escalate__` ChoiceOption value | `manager.advance_chain(cause="reject")` | intercepted before accumulation | parrot/human/manager.py:368-441 |
| `HandoffTool._execute` | `HumanInteractionManager.request_human_input` | delegation | parrot/human/manager.py:192-240 |
| Orchestrator `policy_id` branch | `HumanInteractionInterrupt.policy_id` | conditional path | parrot/autonomous/orchestrator.py:541-564 (catch block) |
| `EmailAction` | SMTP config keys | reads `smtp_host`, `smtp_port`, `smtp_host_user`, `smtp_host_password` | parrot/handlers/agents/abstract.py:581-584 |
| `IntegrationBotManager._ensure_human_manager` | `HumanInteractionManager` | unchanged; manager singleton continues to be the entry point | parrot/integrations/manager.py:154-168 |
| Redis namespace | `hitl:interaction:{id}`, `hitl:responses:{id}`, `hitl:result:{id}` | reused; chain piggybacks on interaction blob | parrot/human/manager.py:88-138 |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.human.EscalationPolicy`~~ — to be created at
  `parrot/human/escalation/models.py`.
- ~~`parrot.human.EscalationTier`~~ — to be created (same file).
- ~~`parrot.human.escalation`~~ — submodule does not exist; to be created.
- ~~`parrot.human.escalation.actions`~~ — submodule does not exist; to be created.
- ~~`parrot.tools.zammad`~~ — no Zammad adapter exists today.
- ~~`parrot.clients.zammad`~~ — to be created at `parrot/clients/zammad.py`.
- ~~`parrot.tools.zendesk`~~ / ~~`parrot.clients.zendesk`~~ — **out of scope
  for V1** (Zendesk deferred to V2).
- ~~`HumanInteraction.severity`~~ — not a real field today; to be added.
- ~~`HumanInteraction.escalation_chain`~~ — to be added.
- ~~`HumanInteraction.escalation_policy_ref`~~ — to be added.
- ~~`HumanInteraction.current_tier_level`~~ — to be added.
- ~~`HumanTool.escalation_policy`~~ — not a real ctor kwarg today.
- ~~`HumanDecisionNode.escalation_policy`~~ — not a real ctor kwarg today.
- ~~`HumanChannel.render_reject_button`~~ — not a real attribute today.
- ~~`HumanInteractionManager.advance_chain`~~ — not a real method today
  (current name is the private `_escalate`).
- ~~`InteractionStatus.REJECTED`~~ — does not exist; `EXPLICIT_REJECT` is
  a *trigger*, not a status. Post-reject interactions are `ESCALATED` (or
  `COMPLETED` once the next tier resolves).
- ~~`PolicyRegistry`~~ — explicitly NOT in V1 (Option B rejected). Reserve
  the name for a future spec.
- ~~`parrot.events.EventBus`~~ — events are emitted on the existing
  `EventEmitterMixin` (parrot/tools/abstract.py:78), not on a separate bus.
- ~~`HandoffTool` removal~~ — explicitly preserved as a deprecated alias.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- All new classes are Pydantic v2 models with strict typing, per
  `.claude/rules/python-development.md`.
- async/await everywhere: no `requests` / `httpx` — use `aiohttp` for
  Zammad and live-chat webhook; `aiosmtplib` for email.
- Inherit `AbstractTool` for tools, `AbstractToolkit` if a toolkit emerges.
- Logger pattern: `self.logger = logging.getLogger("parrot.human.escalation.<sub>")`.
- Discriminated unions for `EscalationTrigger` and `EscalationActionConfig`
  via Pydantic v2 `Field(discriminator="type")` so the manager can fan out
  to the right strategy without isinstance chains.
- `EscalationPolicy.resolve_chain` is a **pure function** — no I/O, no
  side effects. Easy to test exhaustively.
- `EscalationAction.execute` MUST swallow no exception silently: convert
  every failure into `EscalationOutcome.failed(reason=str(exc))` so the
  manager can decide whether to advance.
- Reject-button option uses a stable sentinel key (`"__escalate__"`) so
  channels and manager can compare without ambiguity.
- Telemetry events use a single namespace (`hitl.tier.*`, `hitl.chain.*`)
  so subscribers can filter with one prefix.

### Known Risks / Gotchas

- **Tier chain exhausted with no terminal action**: chain runs out and no
  `TimeoutAction.DEFAULT` is set → resolve with the documented
  *"no human available"* message. Don't leave the future hanging.
- **Concurrent reject + timeout fire**: the manager must serialise via an
  asyncio lock on the `interaction_id`; whichever cause arrives first wins;
  the other is a no-op.
- **Severity downgrade across tiers**: severity is set once at `ask_human`
  time and only *raises* the starting floor. It does not lower it
  mid-chain. Document this.
- **Business-hours boundary**: evaluated at *tier-entry time*, not
  mid-flight. A tier that enters at 17:55 with a 1h timeout will time out
  at 18:55 even if hours end at 18:00. Document this.
- **`OpenTicketAction` HTTP failure** with no next tier: terminate with
  `TIMEOUT` and log loudly. Do not silently drop the interaction.
- **`EmailAction` SMTP refused**: same as above; advance or terminate.
- **`RejectIntentDetector` LLM-fallback latency**: must NOT block the
  response-ingestion path beyond the configured `llm_timeout_seconds`.
  Wrap with `asyncio.wait_for`.
- **Channels without reject button** (CLI): the agent's policy still works
  via TIMEOUT / SEVERITY triggers; only `EXPLICIT_REJECT` is unreachable
  through the UI. Intent detector still tries to recover it from free-text.
- **`HandoffTool` callers in non-integration contexts** (e.g., direct unit
  tests that don't have a manager): when `get_default_human_manager()`
  returns `None`, fall back to the legacy
  `raise HumanInteractionInterrupt(...)` path so we don't regress those
  callers.
- **Redis key TTL** for in-flight chains: `interaction.timeout + 60s` may
  be too short when an early tier has a short timeout but a later tier's
  action is slow. Compute TTL as `sum(tier.timeout for tier in chain) + 60s`
  with a 24h cap to avoid memory leaks.
- **Policy `id` collisions**: managed by the agent author (no global
  registry in V1). Document that IDs only matter for logs/audit.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiosmtplib` | `>=3.0` | Async SMTP send for `EmailAction`. Reuses existing `smtp_host` config keys |
| `aiohttp` | existing | Zammad REST client + live-chat webhook |
| `pydantic` | existing (`>=2`) | All escalation data models |
| `python-dateutil` / `pytz` | existing | Timezone math for `BusinessHours`; `zoneinfo` alone has Windows quirks |
| `redis.asyncio` | existing | Persistence (no change in connection management) |
| `parrot.clients.groq` | existing | Optional Groq Haiku client for `RejectIntentDetector` LLM fallback |

---

## 8. Open Questions

> Resolved questions are carried forward from the brainstorm with `[x]`.
> Unresolved questions remain `[ ]` and are owned by Jesus Lara unless noted.

- [x] Granularity of `EscalationPolicy` (per-agent vs per-toolkit vs per-interaction) — *Resolved in brainstorm*: per-agent.
- [x] Wiring model (`HumanTool` injection vs registry vs hybrid) — *Resolved in brainstorm*: injection in `HumanTool`.
- [x] V1 action set — *Resolved in brainstorm*: AskAlternateHumans + OpenTicket (Zammad first) + LiveChatHandoff + Email.
- [x] V1 trigger set — *Resolved in brainstorm*: TIMEOUT + EXPLICIT_REJECT + SEVERITY + BUSINESS_HOURS_OFF.
- [x] Async-action resolution semantics — *Resolved in brainstorm*: fire-and-forget, agent gets a confirmation string immediately.
- [x] Cross-channel correlation (ticket reply → resume agent) — *Resolved in brainstorm*: out of scope for V1; future spec.
- [x] `HandoffTool` fate — *Resolved in brainstorm*: keep as deprecated alias delegating to `HumanInteractionManager`.
- [x] Business-hours model — *Resolved in brainstorm*: per-tier `business_hours` declaration.
- [x] Severity API — *Resolved in brainstorm*: `severity` parameter on `ask_human` input; policy maps severity → starting tier.
- [x] `EXPLICIT_REJECT` UX — *Resolved in brainstorm*: standardised "↑ Escalar" button on opt-in channels **plus** lightweight LLM intent detection on free-text (regex first, LLM confirmation only on doubt).
- [x] Live-chat platform for `LiveChatHandoffAction` V1 — *Resolved in brainstorm*: **generic webhook** in V1; vendor-specific adapters deferred.
- [x] Zendesk in V1? — *Resolved in brainstorm*: **punt to V2**; Zammad only in V1.
- [x] Audit-log persistence beyond Redis — *Resolved in brainstorm*: **Redis only for now**; external storage deferred.
- [x] Reject-intent detector V1 implementation — *Resolved in brainstorm*: regex first, Groq Haiku confirmation only when regex ambiguous; inline `await` (not callback) with short timeout.
- [x] Should `HumanDecisionNode` get `escalation_policy` in V1? — *Resolved in brainstorm*: **yes**, included in V1.
- [x] Telemetry / observability hook — *Resolved in brainstorm*: **yes**, emit structured `hitl.tier.*` / `hitl.chain.*` events on `EventEmitterMixin`.
- [ ] Default `llm_timeout_seconds` for `RejectIntentDetector` — proposing 1.5s; confirm during implementation.
- [ ] Exact regex phrase list for `RejectIntentDetector` V1 (Spanish + English seed sets) — decide during Module 8 implementation; ship at least 8 phrases (per acceptance criteria).
- [ ] Zammad REST auth method — token vs OAuth2; assume **token** (`Authorization: Token token=...`) per Zammad defaults, but verify against the target deployment.
- [ ] Live-chat webhook payload schema — V1 freezes a minimal schema (`{interaction_id, question, user_id, severity}` → `{deep_link}`); confirm with whoever runs the live-chat platform.

---

## Worktree Strategy

- **Default isolation**: **per-spec** (all tasks sequential in a single
  worktree).
- **Rationale**: Modules 1–4 (data models + action port + interaction
  extension + manager refactor) form a hard dependency chain. Every
  subsequent module (5–14) depends on Module 4. Splitting into per-task
  worktrees would force constant rebasing onto an evolving foundation with
  little parallelism upside. Single worktree, commit task-by-task, one PR
  against `dev`.
- **Cross-feature dependencies**: none blocking. FEAT-045
  (`handoff-tool-for-integrations-agents.spec.md`) is in production and
  we extend it. FEAT-176 `EventEmitterMixin` is already merged and is
  consumed by Module 14.
- **Worktree creation** (from `dev`, follows CLAUDE.md policy):
  ```bash
  git checkout dev
  git worktree add -b feat-194-hitl-escalation-tier \
    .claude/worktrees/feat-194-hitl-escalation-tier HEAD
  cd .claude/worktrees/feat-194-hitl-escalation-tier
  ```
- **In-flight code reconciliation note**: at spec-time there are
  uncommitted modifications to `parrot/core/exceptions.py`,
  `parrot/core/tools/handoff.py`, `parrot/human/manager.py`,
  `parrot/human/models.py`, `parrot/human/tool.py`,
  `packages/ai-parrot/tests/conftest.py`, and an untracked
  `packages/ai-parrot/src/parrot/human/actions/` directory. These appear
  to be early in-progress work toward this feature. Before opening the
  worktree, reconcile that work against this spec (either commit it on
  `dev` so the worktree inherits it, or stash and re-apply inside the
  worktree). The Codebase Contract above reflects HEAD, not those
  uncommitted changes.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-21 | Jesus Lara (with Claude) | Initial draft, derived from `hitl-escalation-tier.brainstorm.md` Option A |
