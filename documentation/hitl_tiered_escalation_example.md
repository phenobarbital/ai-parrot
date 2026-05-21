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
