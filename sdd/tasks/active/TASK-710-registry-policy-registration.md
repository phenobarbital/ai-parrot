# TASK-710: AgentRegistry Policy Registration

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-707, TASK-708, TASK-709
**Assigned-to**: unassigned

---

## Context

> Adds the `setup(app)` method to AgentRegistry and wires policy collection into
> `register()`. When a bot is registered, its policy_rules (class attribute) and
> BotConfig policies are collected, converted to policy dicts, and loaded into the
> PDP evaluator. Implements Spec Module 4.

---

## Scope

- Add `setup(self, app: web.Application) -> None` method to `AgentRegistry`.
  Stores `self._app = app`. Extracts evaluator from `app.get('abac')`.
- Add `_collect_and_register_policies(self, name, factory, bot_config)` private method:
  1. Collect `factory.policy_rules` class attribute (if non-empty list).
  2. Collect `bot_config.policies` (if bot_config has policies).
  3. Convert each rule to policy dict via `PolicyRuleConfig(**rule).to_resource_policy(name)`.
  4. If evaluator available, call `evaluator.load_policies(policy_dicts)`.
  5. Log registered count.
- Call `_collect_and_register_policies()` at the end of `register()`.
- Handle case where `setup()` hasn't been called yet (evaluator is None) — log warning, skip.
- Write unit tests.

**NOT in scope**: BotManager changes, app.py changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/registry/registry.py` | MODIFY | Add setup(app), _collect_and_register_policies() |
| `tests/registry/test_registry_policy.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot.auth.models (created by TASK-707)
from parrot.auth.models import PolicyRuleConfig

# parrot.registry (verified: parrot/registry/__init__.py:2)
from parrot.registry import AgentRegistry, BotConfig, BotMetadata
```

### Existing Signatures to Use
```python
# parrot/registry/registry.py:221
class AgentRegistry:
    # line 315-329
    def register(
        self,
        name: str,
        factory: Type[AbstractBot],
        *,
        singleton: bool = False,
        tags: Optional[Iterable[str]] = None,
        priority: int = 0,
        dependencies: Optional[List[str]] = None,
        replace: bool = False,
        at_startup: bool = False,
        startup_config: Optional[Dict[str, Any]] = None,
        bot_config: Optional["BotConfig"] = None,
        **kwargs: Any
    ) -> None: ...

    # line 312-313
    def get_metadata(self, name: str) -> Optional[BotMetadata]: ...

# PDP/evaluator access pattern (verified: parrot/auth/pbac.py:152, 156)
# app['abac'] = PDP instance
# pdp._evaluator = PolicyEvaluator instance
# evaluator.load_policies(list_of_policy_dicts) — batch load
```

### Does NOT Exist
- ~~`AgentRegistry.app`~~ — no app reference currently, must be added
- ~~`AgentRegistry.setup(app)`~~ — does not exist yet, must be added
- ~~`AgentRegistry._evaluator`~~ — does not exist, get from app['abac']._evaluator
- ~~`PolicyEvaluator.add_policy()`~~ — does not exist; use `load_policies(list)`

---

## Implementation Notes

### Pattern to Follow
```python
def setup(self, app: web.Application) -> None:
    """Store app reference for PDP policy registration."""
    self._app = app
    pdp = app.get('abac')
    self._evaluator = getattr(pdp, '_evaluator', None) if pdp else None
    if self._evaluator:
        self.logger.info("AgentRegistry: PDP evaluator available for policy registration")
    else:
        self.logger.info("AgentRegistry: No PDP evaluator — bot policies will not be auto-registered")
```

### Key Constraints
- `setup()` must be called AFTER `setup_pbac(app)` in the startup sequence.
- If `_evaluator` is None when `register()` is called, log and skip policy registration (don't fail).
- Validate `PolicyRuleConfig` at registration time — invalid rules logged as warnings and skipped.
- `_app` and `_evaluator` default to None in `__init__`.

---

## Acceptance Criteria

- [ ] `AgentRegistry.setup(app)` stores app and extracts evaluator
- [ ] `register()` collects and registers policies from factory.policy_rules and bot_config.policies
- [ ] Invalid policy rules are logged and skipped (not fatal)
- [ ] Works correctly when setup() not called (evaluator is None)
- [ ] Tests pass: `pytest tests/registry/test_registry_policy.py -v`

---

## Test Specification

```python
# tests/registry/test_registry_policy.py
import pytest
from unittest.mock import MagicMock, patch
from parrot.registry.registry import AgentRegistry


class TestRegistryPolicyRegistration:
    def test_setup_stores_app(self):
        """setup(app) stores the Application reference."""

    def test_setup_extracts_evaluator(self):
        """setup(app) gets evaluator from app['abac']._evaluator."""

    def test_register_collects_class_policies(self):
        """register() reads factory.policy_rules and loads into evaluator."""

    def test_register_collects_botconfig_policies(self):
        """register() reads bot_config.policies and loads into evaluator."""

    def test_register_no_evaluator_skips(self):
        """register() skips policy loading when evaluator is None."""

    def test_register_invalid_rule_skipped(self):
        """Invalid policy_rules entries are logged and skipped."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md`
2. **Check dependencies** — verify TASK-707, 708, 709 are done
3. **Verify** `AgentRegistry.register()` is still at registry.py:315-329
4. **Implement** setup(app) and _collect_and_register_policies()
5. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
