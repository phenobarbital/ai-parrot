# Tiered Escalation Example

This document demonstrates how to configure and use the new tiered escalation infrastructure.

## 1. Define a Policy

A policy defines the sequence of tiers. Each tier has a level, targets, and a timeout.

```python
from parrot.human.models import EscalationPolicy, EscalationTier, EscalationActionType

policy = EscalationPolicy(
    name="Critical Support Policy",
    tiers=[
        EscalationTier(
            level=1,
            name="Primary On-call",
            target_humans=["jlara"],
            timeout=300,  # 5 minutes
            action_type=EscalationActionType.INTERACT
        ),
        EscalationTier(
            level=2,
            name="Manager Notification",
            target_humans=["manager1"],
            timeout=600,  # 10 minutes
            action_type=EscalationActionType.NOTIFY,
            action_metadata={"channel": "email"}
        ),
        EscalationTier(
            level=3,
            name="External Escalation (Jira)",
            target_humans=["ops-team"],
            timeout=3600,
            action_type=EscalationActionType.TICKET,
            action_metadata={"platform": "jira", "project": "OPS"}
        )
    ]
)

# Register policy in manager
manager._policies["critical_support"] = policy
```

## 2. Use in an Agent (Handoff)

An agent can explicitly request this policy when handing off.

```python
# LLM tool call simulation
handoff_tool.execute(
    prompt="I need the production database password to proceed with the migration.",
    policy_id="critical_support"
)
```

## 3. Use in an Agent (Ask Human)

Alternatively, use the structured `ask_human` tool with the policy for secondary escalation.

```python
ask_human.execute(
    question="Approve deployment to PRODUCTION?",
    interaction_type="approval",
    policy_id="critical_support"
)
```

## How it works

1.  **Handoff / Ask Human** starts at **Tier 1**.
2.  If **Tier 1** targets don't respond within 5 minutes, the **Manager** transitions to **Tier 2**.
3.  **Tier 2** triggers a `NotifyAction` (Email). Since this is a non-interactive action, it is treated as **fire-and-forget**. The manager:
    - Resolves the interaction immediately.
    - Attaches `message: "Escalated via Email..."` to the result.
    - Resumes the agent.
4.  **The Agent** receives the result: `"[escalated] Escalated via Email to recipients: manager1."` and continues its loop.

## Behavior Nuances

- **INTERACT Tiers**: The agent remains paused at this level, waiting for a human response on the specified channel.
- **TICKET/NOTIFY Tiers**: These are "Terminal Escalations" for the current agent run. The interaction is marked as `COMPLETED` and the agent is resumed immediately once the external system confirms the action (e.g., ticket ID generated).
- **Consensus**: Consensus logic is skipped for automatic escalation actions.

---

## 4. Severity — Influencing Which Tier to Start At

Each interaction carries a `severity` level that affects how urgently the
escalation policy is applied.  Tiers can declare a `min_severity` gate:
the manager skips tiers whose `min_severity` is higher than the
interaction's severity.

```python
from parrot.human import Severity
from parrot.human.models import EscalationPolicy, EscalationTier, EscalationActionType

policy = EscalationPolicy(
    name="Severity-gated policy",
    tiers=[
        EscalationTier(
            level=1,
            name="Junior On-call (routine issues only)",
            target_humans=["junior-oncall"],
            timeout=600,
            action_type=EscalationActionType.INTERACT,
            min_severity=Severity.LOW,   # always entered
        ),
        EscalationTier(
            level=2,
            name="Senior On-call",
            target_humans=["senior-oncall"],
            timeout=300,
            action_type=EscalationActionType.INTERACT,
            min_severity=Severity.HIGH,  # skipped for LOW/NORMAL interactions
        ),
        EscalationTier(
            level=3,
            name="PagerDuty webhook",
            target_humans=[],
            timeout=120,
            action_type=EscalationActionType.NOTIFY,
            action_metadata={"kind": "webhook", "url": "https://events.pagerduty.com/..."},
            min_severity=Severity.CRITICAL,  # only for production-down
        ),
    ],
)
```

Declare severity when calling `ask_human` (via `HumanTool`):

```python
# LLM invocation (structured tool call)
ask_human(
    question="Production database is unreachable. Approve emergency failover?",
    interaction_type="approval",
    policy_id="severity-gated",
    severity="critical",   # skips level-1 and level-2; starts at level-3
)
```

To teach the LLM when to pick each level, add a fragment like this to the
agent's system prompt:

```
When calling ask_human, set severity based on the impact of the request:
- low:      advisory questions, preferences, non-blocking input
- normal:   routine decisions that can wait a few hours
- high:     irreversible operations, production data writes, compliance actions
- critical: production-down, data-loss risk, safety incidents — use sparingly
```

---

## 5. Business Hours — Skipping Off-Hours Tiers

`EscalationTier` supports an optional `business_hours` filter.  When an
interaction would enter a tier outside the configured hours, that tier is
skipped automatically.

```python
from parrot.human.models import BusinessHours

business_hours = BusinessHours(
    timezone="Europe/Madrid",
    weekdays=[0, 1, 2, 3, 4],  # Monday–Friday (0=Mon, 6=Sun)
    start_hour=9,
    end_hour=18,
)

tier = EscalationTier(
    level=1,
    name="Support team (office hours)",
    target_humans=["support-team"],
    timeout=900,
    action_type=EscalationActionType.INTERACT,
    business_hours=business_hours,
)
```

**Boundary semantics**: The check is made at **tier-entry time**.  If the
current local time in `timezone` is outside `[start_hour, end_hour)` on a
day not in `weekdays`, the tier is skipped and the chain advances to the
next tier immediately.

---

## 6. Real Action Kinds — Email, Webhook, Zammad

Non-interactive escalation tiers use `action_type=NOTIFY` (fire-and-forget)
or `action_type=TICKET` (creates an issue and attaches the ticket URL).
The `kind` key in `action_metadata` selects the backend.

### Email (NOTIFY)

```python
EscalationTier(
    level=2,
    name="Email manager",
    target_humans=["manager@example.com"],
    timeout=1800,
    action_type=EscalationActionType.NOTIFY,
    action_metadata={
        "kind": "email",
        "to": ["manager@example.com", "backup@example.com"],
        "subject": "HITL Escalation: {interaction_id}",
    },
)
```

### Webhook (NOTIFY)

```python
EscalationTier(
    level=3,
    name="PagerDuty / Slack webhook",
    target_humans=[],
    timeout=300,
    action_type=EscalationActionType.NOTIFY,
    action_metadata={
        "kind": "webhook",
        "url": "https://hooks.slack.com/services/T000/B000/xxxx",
    },
)
```

### Zammad (TICKET)

```python
EscalationTier(
    level=4,
    name="Open Zammad ticket",
    target_humans=[],
    timeout=3600,
    action_type=EscalationActionType.TICKET,
    action_metadata={
        "kind": "zammad",
        "queue": "support",
        "priority": "2 normal",
    },
)
```

**Legacy back-compat**: The original `channel="email"` and
`platform="jira"` keys in `action_metadata` continue to work alongside
the new `kind` key.

---

## 7. Reject UX — "Escalar" Button and Intent Detector

When an interaction has a policy attached, channels that support it render
an extra "Escalar" (escalate) button alongside the normal reply options.
Pressing it immediately triggers `advance_chain(cause="reject")`, moving
the interaction to the next tier without waiting for the timeout.

### Telegram

The Telegram channel renders the button automatically for `APPROVAL`,
`SINGLE_CHOICE`, and `FREE_TEXT` interactions when `interaction.policy`
is set.  No extra configuration is needed.

### Web

The web channel injects an extra option with
`key="__escalate__"` / `label="↑ Escalar"` into the payload sent to the
frontend.  When the user submits this value, the
`HITLResponseHandler.post()` routes to `advance_chain` instead of
`receive_response`.

### Free-text reject intent detection

For channels that cannot render custom buttons (e.g., plain-text SMS or
legacy integrations), the `RejectIntentDetector` analyses the human's
free-text reply and escalates if it detects phrases like "speak to an
agent", "human please", "escalar", etc.:

```python
from parrot.human import HumanInteractionManager
from parrot.human.escalation_intent import RejectIntentDetector

detector = RejectIntentDetector(
    # optional: add custom phrases in addition to the built-in list
    regex_phrases=[r"\bsupport please\b"],
    # optional: LLM fallback for ambiguous inputs
    # llm_client=my_llm_client,
    # llm_timeout_seconds=1.5,
)

manager = HumanInteractionManager(
    redis=redis_client,
    reject_detector=detector,
)
```

---

## 8. HumanDecisionNode — Wiring Inside an AgentsFlow

`HumanDecisionNode` acts as a first-class flow node that pauses the FSM
and waits for a human.  Use `escalation_policy_id` and `severity` to
attach the tiered policy:

```python
from parrot.human import HumanDecisionNode, Severity

approval_gate = HumanDecisionNode(
    name="approve_deploy",
    manager=hitl_manager,
    escalation_policy_id="critical-support",
    severity=Severity.HIGH,
)

# In an AgentsFlow definition:
flow.add_node(approval_gate)
flow.add_transition("plan", "approve_deploy", condition=lambda r: r.needs_approval)
flow.add_transition("approve_deploy", "deploy", condition=lambda r: r is True)
flow.add_transition("approve_deploy", "abort",  condition=lambda r: r is not True)
```

When `severity != NORMAL` or `escalation_policy_id` is not `None`, the
constructor value takes precedence over any value set on
`interaction_config`.

---

## 9. HandoffTool Deprecation

`HandoffTool` is deprecated.  It raises `HumanInteractionInterrupt`,
forcing the orchestrator to suspend the agent even when the interaction
resolves immediately (e.g., a Notify tier that fires within milliseconds).

**Prefer `HumanTool` with `policy_id` for all new code:**

```python
from parrot.human import HumanTool, HumanInteractionManager

human_tool = HumanTool(
    manager=hitl_manager,
    default_targets=["tg:12345"],
)

# LLM call — no suspend/resume cycle:
result = await human_tool._execute(
    question="Deploy to PROD?",
    interaction_type="approval",
    policy_id="critical-support",
    severity="high",
)
```

`HumanTool` awaits the interaction directly.  If the first tier is a
non-interactive `NOTIFY` or `TICKET` action that resolves in < 2 seconds,
the tool returns the result inline and the agent is never suspended.

If you must keep `HandoffTool` for backward compatibility, note that it
now emits a `DeprecationWarning` on the first instantiation per process:

```
DeprecationWarning: HandoffTool is deprecated; prefer HumanTool with
policy_id for tiered escalation.
```

---

## 10. Observability — Tier-Transition Events

The manager emits structured Pydantic events at every tier transition.
Wire a subscriber via the `on_event` constructor kwarg:

```python
from parrot.human.events import (
    HitlTierEnteredEvent,
    HitlTierAdvancedEvent,
    HitlTierActionExecutedEvent,
    HitlTierActionFailedEvent,
    HitlChainExhaustedEvent,
)

async def my_audit_subscriber(event_name: str, payload) -> None:
    print(f"[HITL] {event_name}: {payload.model_dump()}")
    # Forward to your logging / metrics / alerting system

manager = HumanInteractionManager(
    redis=redis_client,
    on_event=my_audit_subscriber,
)
```

| Event name                  | When fired                                      |
|-----------------------------|-------------------------------------------------|
| `hitl.tier.entered`         | Manager enters a tier (initial or advanced)     |
| `hitl.tier.advanced`        | Chain advances to the next tier                 |
| `hitl.tier.action_executed` | A NOTIFY or TICKET action completed             |
| `hitl.tier.action_failed`   | A NOTIFY or TICKET action raised or returned error |
| `hitl.chain.exhausted`      | All tiers exhausted; interaction timed out      |

Subscriber exceptions are caught and logged; they never abort the manager
flow.

For deeper details on the policy DSL, tier semantics, and the V2 roadmap
(audit storage, Zendesk, LiveChat), see
`sdd/specs/hitl-escalation-tier.spec.md`.
