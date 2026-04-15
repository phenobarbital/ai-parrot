# TASK-709: BotConfig Policies Field

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-707
**Assigned-to**: unassigned

---

## Context

> Extends the BotConfig Pydantic model with a `policies` field so that YAML-declared
> agents can specify access rules inline. Implements Spec Module 3.

---

## Scope

- Add `policies: Optional[list[PolicyRuleConfig]] = None` field to `BotConfig` in
  `parrot/registry/registry.py`.
- Import `PolicyRuleConfig` from `parrot.auth.models`.
- Write unit test confirming BotConfig accepts policies list and serializes correctly.

**NOT in scope**: AgentRegistry changes, policy registration with PDP.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/registry/registry.py` | MODIFY | Add `policies` field to BotConfig |
| `tests/registry/test_botconfig_policies.py` | CREATE | Unit test for new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot.auth.models (created by TASK-707)
from parrot.auth.models import PolicyRuleConfig

# parrot.registry (verified: parrot/registry/__init__.py:2)
from parrot.registry import BotConfig
```

### Existing Signatures to Use
```python
# parrot/registry/registry.py:198-219
class BotConfig(BaseModel):
    name: str                                                         # line 200
    class_name: str                                                   # line 201
    module: str                                                       # line 202
    enabled: bool = True                                              # line 203
    config: Dict[str, Any] = Field(default_factory=dict)              # line 204
    tools: Optional[ToolConfig] = Field(default=None)                 # line 206
    toolkits: List[str] = Field(default_factory=list)                 # line 207
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list)   # line 208
    model: Optional[ModelConfig] = Field(default=None)                # line 209
    system_prompt: Optional[Union[str, Dict[str, Any]]] = ...        # line 210
    prompt: Optional[PromptConfig] = Field(default=None)              # line 211
    vector_store: Optional[StoreConfig] = Field(default=None)         # line 212
    tags: Optional[Set[str]] = Field(default_factory=set)             # line 214
    singleton: bool = False                                           # line 215
    at_startup: bool = False                                          # line 216
    startup_config: Dict[str, Any] = Field(default_factory=dict)      # line 217
    priority: int = 0                                                 # line 218
```

### Does NOT Exist
- ~~`BotConfig.policies`~~ — does not exist yet, must be added
- ~~`BotConfig.access_rules`~~ — does not exist, not the right name
- ~~`BotConfig.permissions`~~ — does not exist (legacy name, do not use)

---

## Implementation Notes

### Key Constraints
- Add the field after `priority` (line 218), before the class closes.
- Use `Optional[list["PolicyRuleConfig"]] = None` with string forward ref if needed
  to avoid circular imports, or import at module level if safe.
- Ensure existing BotConfig instances without `policies` still work (default None).

---

## Acceptance Criteria

- [ ] `BotConfig` has `policies: Optional[list[PolicyRuleConfig]]` field
- [ ] Existing BotConfig instances without policies still validate
- [ ] `BotConfig(name="x", class_name="y", module="z", policies=[...])` works
- [ ] Tests pass: `pytest tests/registry/test_botconfig_policies.py -v`

---

## Test Specification

```python
# tests/registry/test_botconfig_policies.py
import pytest
from parrot.registry.registry import BotConfig


class TestBotConfigPolicies:
    def test_botconfig_without_policies(self):
        cfg = BotConfig(name="test", class_name="Bot", module="parrot.bots")
        assert cfg.policies is None

    def test_botconfig_with_policies(self):
        cfg = BotConfig(
            name="test", class_name="Bot", module="parrot.bots",
            policies=[{"action": "agent:chat", "effect": "allow", "groups": ["all"]}]
        )
        assert len(cfg.policies) == 1
        assert cfg.policies[0].action == "agent:chat"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md`
2. **Check dependencies** — verify TASK-707 is done
3. **Verify** `BotConfig` is still at registry.py:198-219
4. **Implement** the field addition
5. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
