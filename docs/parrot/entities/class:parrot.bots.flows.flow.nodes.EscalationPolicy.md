---
type: Wiki Entity
title: EscalationPolicy
id: class:parrot.bots.flows.flow.nodes.EscalationPolicy
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Defines when and how to escalate to HITL.
---

# EscalationPolicy

Defined in [`parrot.bots.flows.flow.nodes`](../summaries/mod:parrot.bots.flows.flow.nodes.md).

```python
class EscalationPolicy(BaseModel)
```

Defines when and how to escalate to HITL.

Attributes:
    enabled: Whether escalation is enabled.
    on_low_confidence: Confidence threshold below which to escalate.
    on_split_vote: Whether to escalate on evenly split votes.
    on_explicit_keyword: Whether to escalate when decision is ESCALATE.
    hitl_manager: HumanInteractionManager instance (not serialized).
    target_humans: List of human identifiers for escalation.
    timeout_seconds: Timeout for HITL response.
    fallback_decision: Decision to use if HITL unavailable or times out.
