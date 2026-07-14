---
type: Wiki Entity
title: RoutingRule
id: class:parrot.a2a.router.RoutingRule
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Defines a routing rule for matching requests to agents.
---

# RoutingRule

Defined in [`parrot.a2a.router`](../summaries/mod:parrot.a2a.router.md).

```python
class RoutingRule
```

Defines a routing rule for matching requests to agents.

Attributes:
    pattern: Pattern to match (skill_id, tag, regex, or "*" for default)
    strategy: How to match the pattern against requests
    target_agents: List of agent names that can handle matching requests
    priority: Rule priority (higher = evaluated first)
    load_balance: Strategy for selecting among multiple targets
    weights: Optional weights for weighted load balancing
    transform_request: Optional async function to transform request before sending
    transform_response: Optional async function to transform response before returning
    enabled: Whether this rule is active
    metadata: Additional metadata for the rule
