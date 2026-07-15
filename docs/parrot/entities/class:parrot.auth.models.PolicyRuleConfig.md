---
type: Wiki Entity
title: PolicyRuleConfig
id: class:parrot.auth.models.PolicyRuleConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Simple policy rule format for bot-level declaration.
---

# PolicyRuleConfig

Defined in [`parrot.auth.models`](../summaries/mod:parrot.auth.models.md).

```python
class PolicyRuleConfig(BaseModel)
```

Simple policy rule format for bot-level declaration.

Represents a single access-control rule that can be declared on an
AbstractBot subclass or in a BotConfig YAML ``policies:`` section.

Rules default to ``priority=10``, which is below operator YAML files
(``priority >= 20``) so that operators can always override code-declared rules.

Attributes:
    action: The action this rule controls, e.g. ``"agent:chat"``,
        ``"agent:configure"``, ``"agent:list"``, ``"tool:list"``.
    effect: ``"allow"`` (default) or ``"deny"``.
    groups: Subject groups this rule applies to. ``None`` means any group.
    roles: Subject roles this rule applies to. ``None`` means any role.
    priority: Evaluation priority — higher number evaluated first.
        Default is ``10`` (below operator YAML at ``>= 20``).
    description: Human-readable description of this rule.
    conditions: Reserved for future extensibility (time windows, IP
        restrictions, etc.). Passed through to the policy dict if present.

Example::

    rule = PolicyRuleConfig(
        action="agent:chat",
        effect="allow",
        groups=["engineering"],
        priority=10,
    )
    policy_dict = rule.to_resource_policy("my_finance_bot")

## Methods

- `def action_must_be_nonempty(cls, v: str) -> str` — Validate that action is non-empty string.
- `def to_resource_policy(self, agent_name: str) -> dict` — Convert this rule to a navigator-auth policy dict.
