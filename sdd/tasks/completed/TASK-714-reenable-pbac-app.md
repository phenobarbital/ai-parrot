# TASK-714: Re-enable PBAC in app.py

**Feature**: policy-rules-abstractbot
**Spec**: `sdd/specs/policy-rules-abstractbot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-710, TASK-711
**Assigned-to**: unassigned

---

## Context

> The PBAC setup block in app.py has been commented out since the navigator-auth Rust
> evaluator bug. That bug is now fixed. This task uncomments and wires the block,
> ensuring correct startup ordering. Implements Spec Module 8.

---

## Scope

- Uncomment the PBAC setup block in `app.py` (lines 201-224).
- Ensure the startup ordering is:
  1. `setup_pbac(app)` → registers `app['abac']`, `app['security']`
  2. `BotManager.setup(app)` → already exists, registers signals
  3. `load_bots(app)` → calls `registry.setup(app)` (from TASK-711), then loads agents
- Remove the temporary "PBAC disabled" log message (line 222-224).
- The `BotManager.set_default_resolver()` line in the commented block should be removed
  or replaced — that method does not exist. Instead, just store the resolver in
  `app['pbac_resolver']` for reference.
- Verify imports at top of app.py include `setup_pbac` and `PBACPermissionResolver`.

**NOT in scope**: Handler changes, AbstractBot changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `app.py` | MODIFY | Uncomment PBAC block, fix wiring |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot.auth (verified: parrot/auth/__init__.py:37, 31)
from parrot.auth import setup_pbac, PBACPermissionResolver
```

### Existing Signatures to Use
```python
# app.py:201-224 (currently commented out)
# policy_dir = self.app.get('policy_dir') or config.get('POLICY_DIR', fallback='policies')
# pdp, evaluator, guardian = setup_pbac(
#     self.app,
#     policy_dir=policy_dir,
#     cache_ttl=int(config.get('PBAC_CACHE_TTL', fallback=30)),
# )
# if evaluator is not None:
#     resolver = PBACPermissionResolver(evaluator=evaluator)
#     if self.bot_manager is not None and hasattr(self.bot_manager, 'set_default_resolver'):
#         self.bot_manager.set_default_resolver(resolver)
#     self.app['pbac_resolver'] = resolver

# parrot/auth/pbac.py:35-40
def setup_pbac(app, policy_dir="policies", cache_ttl=30, default_effect=None)
    -> tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]: ...
```

### Does NOT Exist
- ~~`BotManager.set_default_resolver()`~~ — does NOT exist; remove that line
- ~~`self.bot_manager.resolver`~~ — does not exist

---

## Implementation Notes

### Key Constraints
- `setup_pbac()` MUST be called BEFORE `BotManager.setup(app)` (which triggers `on_startup`
  → `load_bots` → `registry.setup(app)` reading `app['abac']`).
- Check current ordering in app.py to ensure PBAC setup is placed correctly relative to
  `auth.setup(self.app)` and `BotManager.setup()`.
- If `setup_pbac` returns `(None, None, None)`, log info and continue (fail-open).

---

## Acceptance Criteria

- [ ] PBAC setup block is uncommented and functional
- [ ] `app['abac']` is registered when policies dir exists
- [ ] `app['pbac_resolver']` stores PBACPermissionResolver
- [ ] `BotManager.set_default_resolver()` line is removed (method doesn't exist)
- [ ] App starts without errors when policies/ dir exists
- [ ] App starts without errors when policies/ dir is missing (fail-open)

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/policy-rules-abstractbot.spec.md`
2. **Check dependencies** — verify TASK-710 and TASK-711 are done
3. **Read app.py:190-230** to see current state
4. **Uncomment** the PBAC block, fix the `set_default_resolver` line
5. **Verify** startup ordering is correct
6. **Move** to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*
