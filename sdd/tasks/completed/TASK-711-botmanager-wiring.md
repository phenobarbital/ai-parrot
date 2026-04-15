# TASK-711: BotManager Wiring — Call registry.setup(app)

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-710
**Assigned-to**: unassigned

---

## Context

> Wires `AgentRegistry.setup(app)` into BotManager's `load_bots()` method so the
> registry has access to the aiohttp Application before any agents are registered.
> Implements Spec Module 5.

---

## Scope

- In `BotManager.load_bots(app)` (manager.py:238), call `self.registry.setup(app)`
  as the first step, before `await self.registry.load_modules()`.
- This ensures the registry has the `app` reference (and thus access to the PDP evaluator)
  before decorator-based or config-based agents trigger `register()`.
- Write a minimal unit test.

**NOT in scope**: app.py changes, handler changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/manager/manager.py` | MODIFY | Add registry.setup(app) call in load_bots() |
| `tests/manager/test_botmanager_wiring.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot.registry (verified: parrot/registry/__init__.py:2)
from parrot.registry import AgentRegistry
```

### Existing Signatures to Use
```python
# parrot/manager/manager.py:238-266
async def load_bots(self, app: web.Application) -> None:
    """Load and register all bots using the registry and optional database."""
    self.logger.info("Starting bot loading with global registry")

    if self.enable_registry_bots:
        # Step 1: Import modules to trigger decorator registration  (line 248)
        await self.registry.load_modules()

        # Step 2: Register config-based agents  (line 251)
        config_count = self.registry.discover_config_agents()

        # Step 2b: Load YAML agent definitions  (line 257)
        # Step 3: Instantiate startup agents  (line 264-265)
        startup_results = await self.registry.instantiate_startup_agents(app)
```

### Does NOT Exist
- ~~`BotManager.set_default_resolver()`~~ — does not exist, not needed for this task
- ~~`AgentRegistry.setup(app)`~~ — created by TASK-710, will exist when this task runs

---

## Implementation Notes

### Key Constraints
- Insert `self.registry.setup(app)` BEFORE `await self.registry.load_modules()` (line 248).
- This must be inside the `if self.enable_registry_bots:` block — no point setting up
  the registry if registry bots are disabled.

---

## Acceptance Criteria

- [ ] `load_bots()` calls `self.registry.setup(app)` before `load_modules()`
- [ ] Existing bot loading still works correctly
- [ ] Tests pass: `pytest tests/manager/test_botmanager_wiring.py -v`

---

## Test Specification

```python
# tests/manager/test_botmanager_wiring.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBotManagerWiring:
    async def test_load_bots_calls_registry_setup(self):
        """load_bots() calls registry.setup(app) before load_modules()."""

    async def test_load_bots_setup_before_modules(self):
        """registry.setup(app) is called before registry.load_modules()."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md`
2. **Check dependencies** — verify TASK-710 is done
3. **Verify** `load_bots()` is still at manager.py:238
4. **Implement** the single line addition
5. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
