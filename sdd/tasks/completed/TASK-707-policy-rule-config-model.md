# TASK-707: PolicyRuleConfig Pydantic Model

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the foundation data model for the entire feature. All other modules depend on
> `PolicyRuleConfig` for type hints and the `to_resource_policy()` conversion method.
> Implements Spec Module 1.

---

## Scope

- Create `parrot/auth/models.py` with `PolicyRuleConfig` Pydantic model.
- Fields: `action` (str), `effect` (Literal["allow","deny"], default "allow"),
  `groups` (Optional[list[str]]), `roles` (Optional[list[str]]),
  `priority` (int, default 10), `description` (Optional[str]),
  `conditions` (Optional[dict[str,Any]], reserved for future extensibility).
- Implement `to_resource_policy(agent_name: str) -> ResourcePolicy` method that converts
  the simple rule into a navigator-auth `ResourcePolicy` object.
- Export `PolicyRuleConfig` from `parrot/auth/__init__.py`.
- Write unit tests.

**NOT in scope**: Integration with AbstractBot, BotConfig, or AgentRegistry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/auth/models.py` | CREATE | PolicyRuleConfig model + to_resource_policy() |
| `parrot/auth/__init__.py` | MODIFY | Export PolicyRuleConfig |
| `tests/auth/test_policy_rule_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# navigator-auth (verified: parrot/auth/pbac.py:85-88)
from navigator_auth.abac.policies.resources import ResourceType      # AGENT, TOOL enum
from navigator_auth.abac.policies.abstract import PolicyEffect       # ALLOW, DENY enum

# parrot.auth existing exports (verified: parrot/auth/__init__.py:29-37, 39)
from parrot.auth import (
    UserSession, PermissionContext,
    AbstractPermissionResolver, DefaultPermissionResolver,
    PBACPermissionResolver,
    setup_pbac,
)
```

### Existing Signatures to Use
```python
# navigator_auth.abac.policies.resource_policy (external package)
# ResourcePolicy constructor — use the YAML policy dict format that PolicyEvaluator expects.
# The evaluator's load_policies() accepts a list of policy dicts matching the YAML schema:
# {name, effect, resources, actions, subjects, priority, ...}

# Existing YAML policy format reference (policies/agents.yaml:28-44):
# - name: engineering_agents_business_hours
#   effect: allow
#   resources: ["agent:*"]
#   actions: ["agent:chat"]
#   subjects:
#     groups: ["engineering"]
#   priority: 20
```

### Does NOT Exist
- ~~`parrot/auth/models.py`~~ — file does not exist yet, must be created
- ~~`PolicyRuleConfig`~~ — class does not exist yet
- ~~`ResourcePolicy` direct constructor~~ — use policy dict format for `load_policies()`
- ~~`PolicyEvaluator.add_policy()`~~ — does not exist; use `load_policies(list)` (batch API)

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing YAML policy schema (policies/agents.yaml) for the dict format
# that to_resource_policy() should produce. The PolicyEvaluator.load_policies()
# accepts a list of dicts matching this schema.

from pydantic import BaseModel, Field
from typing import Any, Literal, Optional

class PolicyRuleConfig(BaseModel):
    action: str
    effect: Literal["allow", "deny"] = "allow"
    groups: Optional[list[str]] = None
    roles: Optional[list[str]] = None
    priority: int = 10
    description: Optional[str] = None
    conditions: Optional[dict[str, Any]] = None

    def to_resource_policy(self, agent_name: str) -> dict:
        """Convert to navigator-auth policy dict format."""
        ...
```

### Key Constraints
- Use Pydantic v2 (BaseModel with Field)
- Validate that `action` is non-empty
- Default `priority=10` (below operator YAML at 20+)
- `conditions` is reserved for future extensibility — pass through to policy dict if present

---

## Acceptance Criteria

- [ ] `parrot/auth/models.py` exists with `PolicyRuleConfig` class
- [ ] `to_resource_policy("my_bot")` returns a valid policy dict
- [ ] `from parrot.auth import PolicyRuleConfig` works
- [ ] Unit tests pass: `pytest tests/auth/test_policy_rule_config.py -v`
- [ ] Validation rejects empty `action`, invalid `effect`

---

## Test Specification

```python
# tests/auth/test_policy_rule_config.py
import pytest
from parrot.auth.models import PolicyRuleConfig


class TestPolicyRuleConfig:
    def test_valid_creation(self):
        rule = PolicyRuleConfig(action="agent:chat", groups=["engineering"])
        assert rule.effect == "allow"
        assert rule.priority == 10

    def test_deny_effect(self):
        rule = PolicyRuleConfig(action="agent:chat", effect="deny", groups=["contractors"])
        assert rule.effect == "deny"

    def test_to_resource_policy(self):
        rule = PolicyRuleConfig(action="agent:chat", effect="allow", groups=["finance"])
        policy = rule.to_resource_policy("finance_bot")
        assert policy["resources"] == ["agent:finance_bot"]
        assert policy["actions"] == ["agent:chat"]
        assert policy["effect"] == "allow"
        assert policy["subjects"]["groups"] == ["finance"]
        assert policy["priority"] == 10

    def test_to_resource_policy_with_roles(self):
        rule = PolicyRuleConfig(action="agent:configure", roles=["admin"])
        policy = rule.to_resource_policy("my_bot")
        assert policy["subjects"]["roles"] == ["admin"]

    def test_invalid_effect_rejected(self):
        with pytest.raises(Exception):
            PolicyRuleConfig(action="agent:chat", effect="maybe")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `parrot/auth/__init__.py` exports before modifying
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-707-policy-rule-config-model.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
