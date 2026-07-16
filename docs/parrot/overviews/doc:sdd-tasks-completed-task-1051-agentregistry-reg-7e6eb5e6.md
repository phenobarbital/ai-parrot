---
type: Wiki Overview
title: 'TASK-1051: AgentRegistry.register_db_bot_policies'
id: doc:sdd-tasks-completed-task-1051-agentregistry-register-db-bot-policies-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 Module 3. Adds the public method on `AgentRegistry` that
relates_to:
- concept: mod:parrot.auth.agent_guard
  rel: mentions
- concept: mod:parrot.auth.models
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

# TASK-1051: AgentRegistry.register_db_bot_policies

**Feature**: FEAT-153 — botmanager-pbac-permissions
**Spec**: `sdd/specs/botmanager-pbac-permissions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1049
**Assigned-to**: unassigned

---

## Context

Implements §3 Module 3. Adds the public method on `AgentRegistry` that
DB-loaded bots use to register their `permissions` policies into the
shared `PolicyEvaluator`. The goal is **parity**: a bot loaded from
`navigator.ai_bots` must produce a policy dict byte-equal to the
same rule declared in YAML `BotConfig.policies` so the evaluator can
treat them identically.

The method mirrors the existing `_collect_and_register_policies`
(`registry.py:337-415`) which already handles the YAML/code path. The
new method is the DB-side sibling: takes the raw `bot_model.permissions`
value, parses it via `parse_bot_permissions` (TASK-1049), converts each
rule via `PolicyRuleConfig.to_resource_policy(name)`
(`auth/models.py:108`), and calls `self._evaluator.load_policies(...)`.

---

## Scope

- Add a new public async-or-sync method on `AgentRegistry` (sync is
  sufficient — `load_policies` is sync):

  ```python
  def register_db_bot_policies(
      self,
      name: str,
      permissions: dict | list | None,
  ) -> int:
  ```

  Returns the number of policy dicts loaded into the evaluator
  (0 means public / no-op).
- Behaviour:
  - When `self._evaluator is None` → return 0, no log, no error.
  - When `permissions` is empty/None → return 0.
  - When `permissions` is malformed → propagate `ValueError` raised
    by `parse_bot_permissions`. Caller (TASK-1052) is responsible for
    the WARNING log and skip-the-bot decision.
  - When `permissions` is well-formed and non-empty:
    1. Parse via `parse_bot_permissions(permissions)`.
    2. Convert each `PolicyRuleConfig` to a policy dict via
       `rule.to_resource_policy(name)`.
    3. Call `self._evaluator.load_policies(policy_dicts)`.
    4. Log INFO line with the count, mirroring `registry.py:406-409`.
- Place the new method right after `_collect_and_register_policies`
  (around `registry.py:415`) so the two siblings live next to each
  other.
- Add unit tests in `packages/ai-parrot/tests/registry/test_register_db_bot_policies.py`.

**NOT in scope**:
- Calling `register_db_bot_policies` from `BotManager` (TASK-1052).
- Enforcement at `get_instance` (TASK-1054).
- Any change to `_collect_and_register_policies`. The two paths must
  remain independent so YAML loads keep working unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | Add `register_db_bot_policies` after `_collect_and_register_policies` (line ~415). |
| `packages/ai-parrot/tests/registry/test_register_db_bot_policies.py` | CREATE | Unit + parity tests (4 tests). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Inside parrot/registry/registry.py — already imported, do not re-add
from parrot.auth.models import PolicyRuleConfig   # already used at registry.py:370

# New import for this task
from parrot.auth.agent_guard import parse_bot_permissions
# verified: TASK-1049 creates parrot/auth/agent_guard.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:                               # line 226
    self._evaluator: Any = None                    # line 278
    # set by setup_pbac integration at line 327
    # may be None when PBAC disabled — must no-op gracefully

    def _collect_and_register_policies(            # line 337
        self,
        name: str,
        factory: type,
        bot_config: Optional["BotConfig"],
    ) -> None:
        # PATTERN TO MIRROR — registry.py:337-415:
        if self._evaluator is None:                # line 356
            return
        policy_dicts: List[Dict[str, Any]] = []
        # ... build dicts via PolicyRuleConfig(**rule).to_resource_policy(name) ...
        if not policy_dicts:                       # line 400
            return
        try:
            self._evaluator.load_policies(policy_dicts)   # line 405
            self.logger.info(
                "AgentRegistry: registered %d policy rule(s) for agent '%s'",
                len(policy_dicts), name,                  # line 406-409
            )
        except Exception as exc:
            self.logger.warning(
                "AgentRegistry: failed to register policies for %s: %s",
                name, exc,
            )
```

```python
# packages/ai-parrot/src/parrot/auth/models.py
class PolicyRuleConfig(BaseModel):                 # line 32
    def to_resource_policy(self, agent_name: str) -> dict:   # line 108
        # produces:
        # {
        #   "name": f"code_rule_{agent_name}_{action}",
        #   "effect": ...,
        #   "resources": [f"agent:{agent_name}"],
        #   "actions": [action],
        #   "subjects": {"groups": [...], "roles": [...]},
        #   "priority": ...,
        # }
```

### Does NOT Exist

- ~~`AgentRegistry.register_bot_policies`~~ (without `_db`) — does
  not exist; the YAML path is `_collect_and_register_policies` (private).
  Keep names distinct.
- ~~`PolicyEvaluator.load_policy` (singular)~~ — the API is
  `load_policies` (plural) per `registry.py:405`.
- ~~`PolicyRuleConfig.to_dict()`~~ — does not exist; use
  `to_resource_policy(name)` to get the canonical policy dict shape.

---

## Implementation Notes

### Method skeleton

```python
def register_db_bot_policies(
    self,
    name: str,
    permissions: dict | list | None,
) -> int:
    """Register policies for a DB-loaded bot.

    Mirrors :meth:`_collect_and_register_policies` for the DB path.
    Takes the raw value of ``navigator.ai_bots.permissions``, parses
    it via :func:`parrot.auth.agent_guard.parse_bot_permissions`, and
    loads the resulting rules into ``self._evaluator``.

    Args:
        name: The bot name (used as resource identifier — matches the
            same convention as the YAML/code path).
        permissions: Raw value of ``BotModel.permissions``. Accepted
            shapes are documented on :func:`parse_bot_permissions`.

    Returns:
        Number of policy dicts loaded into the evaluator. ``0`` means
        public (no rules) or PBAC disabled.

    Raises:
        ValueError: When ``permissions`` has a malformed shape. The
            caller is responsible for catching and logging.
    """
    if self._evaluator is None:
        return 0
    rules = parse_bot_permissions(permissions)   # may raise ValueError
    if not rules:
        return 0
    policy_dicts = [rule.to_resource_policy(name) for rule in rules]
    try:
        self._evaluator.load_policies(policy_dicts)
    except Exception as exc:  # pylint: disable=broad-except
        self.logger.warning(
            "AgentRegistry: failed to register DB policies for %s: %s",
            name, exc,
        )
        return 0
    self.logger.info(
        "AgentRegistry: registered %d DB policy rule(s) for agent '%s'",
        len(policy_dicts), name,
    )
    return len(policy_dicts)
```

### Parity test design

The parity test (`test_db_bot_policy_parity_with_yaml`) must build the
same logical rule via two paths and compare the policy dicts written
into the evaluator:

1. Build a `BotConfig(policies=[...])` and call
   `_collect_and_register_policies(name, factory, bot_config)`.
2. Build the same rule as a JSON dict shape and call
   `register_db_bot_policies(name, {"permissions": [<same rule>]})`.
3. Assert the policy dicts produced by each path are equal (use a mock
   `evaluator.load_policies` that records calls).

### Patterns to Follow

- Use `self.logger` (already initialized at `registry.py:271`).
- Keep the new method right next to its sibling so future readers see
  both paths together.

---

## Acceptance Criteria

- [ ] `AgentRegistry.register_db_bot_policies(name, permissions)` is
  callable and returns an `int`.
- [ ] Returns `0` when `self._evaluator is None`.
- [ ] Returns `0` for `None` / `{}` / `{"permissions": []}` input.
- [ ] Loads N policies and returns `N` for non-empty valid input.
- [ ] Propagates `ValueError` on malformed input (caller handles).
- [ ] DB-path and YAML-path produce byte-equal policy dicts for the
  same logical rule (parity test).
- [ ] Logs INFO with count on success; WARNING on
  `load_policies` exception.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/registry/test_register_db_bot_policies.py -v`.
- [ ] `ruff check` passes on `parrot/registry/registry.py`.

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_register_db_bot_policies.py
import pytest
from unittest.mock import MagicMock

from parrot.registry.registry import AgentRegistry


@pytest.fixture
def registry_with_mock_evaluator():
    reg = AgentRegistry()
    reg._evaluator = MagicMock()
    return reg


class TestRegisterDbBotPolicies:
    def test_loads_into_evaluator(self, registry_with_mock_evaluator):
        n = registry_with_mock_evaluator.register_db_bot_policies(
            "finance_bot",
            {"permissions": [
                {"action": "agent:resolve", "effect": "allow",
                 "groups": ["finance"]},
            ]},
        )
        assert n == 1
        registry_with_mock_evaluator._evaluator.load_policies.assert_called_once()

    def test_empty_no_op(self, registry_with_mock_evaluator):
        assert registry_with_mock_evaluator.register_db_bot_policies("b", {}) == 0
        registry_with_mock_evaluator._evaluator.load_policies.assert_not_called()

    def test_no_evaluator_no_op(self):
        reg = AgentRegistry()
        reg._evaluator = None
        assert reg.register_db_bot_policies("b", {"permissions": [...]}) == 0

    def test_malformed_raises(self, registry_with_mock_evaluator):
        with pytest.raises(ValueError):
            registry_with_mock_evaluator.register_db_bot_policies(
                "b", {"permissions": "not-a-list"},
            )

    def test_db_path_parity_with_yaml_path(self):
        """DB-loaded and YAML-loaded same rule produce identical policy dicts."""
        # Build via DB path
        reg_db = AgentRegistry()
        reg_db._evaluator = MagicMock()
        reg_db.register_db_bot_policies(
            "finance_bot",
            {"permissions": [
                {"action": "agent:resolve", "effect": "allow",
                 "groups": ["finance"], "priority": 10},
            ]},
        )
        db_dicts = reg_db._evaluator.load_policies.call_args[0][0]

        # Build via YAML path (BotConfig.policies → _collect_and_register_policies)
        reg_yaml = AgentRegistry()
        reg_yaml._evaluator = MagicMock()
        # ... construct minimal BotConfig with same rule, call
        # _collect_and_register_policies("finance_bot", ..., bot_config)
        yaml_dicts = reg_yaml._evaluator.load_policies.call_args[0][0]

        assert db_dicts == yaml_dicts
```

---

## Agent Instructions

When you pick up this task:

1. Confirm TASK-1049 is done; verify
   `from parrot.auth.agent_guard import parse_bot_permissions` works.
2. Re-read `registry.py:337-415` to make sure your method matches the
   logging tone and exception handling of its sibling.
3. Implement `register_db_bot_policies`.
4. Write the 5 unit tests, paying special attention to the parity test.
5. Run pytest + ruff.
6. Move this file to `sdd/tasks/completed/`, update the per-spec
   index, fill the Completion Note.

---

## Completion Note

Implemented by sdd-worker (claude-sonnet-4-6) on 2026-05-07.

Added `register_db_bot_policies(name, permissions) -> int` to `AgentRegistry`
immediately after `_collect_and_register_policies` (line ~415). Method:
- No-ops when `self._evaluator is None` → returns 0.
- No-ops for empty/None permissions → returns 0.
- Parses via `parse_bot_permissions` (may raise ValueError — caller catches).
- Converts each rule via `PolicyRuleConfig.to_resource_policy(name)`.
- Calls `self._evaluator.load_policies(policy_dicts)`.
- Logs INFO on success, WARNING on `load_policies` exception.

8 tests written and passing including parity test vs `_collect_and_register_policies`.
ruff introduced no new errors (1 pre-existing F841 at line 102).
