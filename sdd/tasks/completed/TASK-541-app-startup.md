# TASK-541: App Startup Integration

**Feature**: policy-based-access-control
**Spec**: `sdd/specs/policy-based-access-control.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-535, TASK-536
**Assigned-to**: unassigned

---

## Context

> Wires `setup_pbac()` into ai-parrot's `app.py` startup sequence. Initializes the
> full PBAC stack and sets `PBACPermissionResolver` as the default resolver on BotManager.
> Conditional: only activates PBAC if policy directory exists.
>
> Implements Spec Module 8.

---

## Scope

- In `app.py` `Main` class, call `setup_pbac()` during app initialization
  (after AuthHandler setup, before BotManager setup)
- If PBAC initialized successfully:
  - Create `PBACPermissionResolver(evaluator=evaluator)`
  - Set as default resolver on `BotManager` via `bot_manager.set_resolver(resolver)`
  - Or configure on individual bots as they're created
- If PBAC not initialized (no policies):
  - Log info message
  - Continue with existing behavior (AllowAllResolver or no resolver)
- Policy directory path from configuration (environment variable or config file)
- Bump `navigator-auth` dependency to `>= 0.19.0` in `pyproject.toml`

**NOT in scope**:
- setup_pbac() implementation (TASK-535)
- PBACPermissionResolver implementation (TASK-536)
- Handler modifications (TASK-537, 538, 539, 540)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `app.py` | MODIFY | Add `setup_pbac()` call in Main initialization |
| `pyproject.toml` | MODIFY | Bump navigator-auth to >= 0.19.0 |

---

## Implementation Notes

### Pattern to Follow
```python
# In app.py Main class, after AuthHandler setup:

from parrot.auth.pbac import setup_pbac
from parrot.auth.resolver import PBACPermissionResolver

class Main(AppHandler):
    async def on_startup(self, app):
        # ... existing setup ...

        # Auth handler (already exists)
        auth = AuthHandler()
        auth.setup(self.app)

        # PBAC setup (new)
        policy_dir = self.app.get('policy_dir', 'policies')
        pdp, evaluator, guardian = await setup_pbac(
            self.app, policy_dir=policy_dir
        )
        if evaluator is not None:
            resolver = PBACPermissionResolver(evaluator=evaluator)
            self.bot_manager.set_default_resolver(resolver)
            self.logger.info("PBAC enabled with resolver on BotManager")
        else:
            self.logger.info("PBAC not configured — using default permissions")

        # Bot manager (already exists)
        self.bot_manager = BotManager(enable_database_bots=True)
        self.bot_manager.setup(self.app)
```

### Key Constraints
- PBAC setup must happen AFTER AuthHandler (needs auth middleware registered)
- PBAC setup must happen BEFORE or DURING BotManager setup (resolver needed for bots)
- Policy directory path must be configurable (not hardcoded)
- Graceful degradation: no policies = system works as before
- navigator-auth >= 0.19.0 must be in pyproject.toml

### References in Codebase
- `app.py` — Main class, `on_startup` method
- `parrot/bots/manager.py` — BotManager class, resolver setting

---

## Acceptance Criteria

- [ ] `setup_pbac()` called during app startup
- [ ] `PBACPermissionResolver` set as default resolver on BotManager when PBAC active
- [ ] Policy directory path configurable
- [ ] No policies → system works exactly as before (backward compatible)
- [ ] `navigator-auth >= 0.19.0` in pyproject.toml
- [ ] App starts successfully with and without policies configured
- [ ] Guardian registered as `app['security']`

---

## Test Specification

```python
# Integration test — verify app starts with PBAC
class TestAppStartupPBAC:
    async def test_app_starts_with_policies(self, app_with_policies):
        """App starts and has Guardian registered."""
        assert 'security' in app_with_policies

    async def test_app_starts_without_policies(self, app_without_policies):
        """App starts without PBAC — no Guardian, no error."""
        assert 'security' not in app_without_policies
        # BotManager works with default resolver
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-541-app-startup.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-04-03
**Notes**: Added setup_pbac() call in on_startup(). PBAC conditional on policy dir existence.
PBACPermissionResolver stored in app['pbac_resolver']. BotManager.set_default_resolver()
called if method exists (not yet present, uses hasattr check). Policy dir configurable
via POLICY_DIR env var, cache TTL via PBAC_CACHE_TTL. Bumped navigator-auth to >= 0.19.0.

**Deviations from spec**: BotManager.set_default_resolver() is not yet implemented;
the code uses hasattr() check for forward compatibility.
