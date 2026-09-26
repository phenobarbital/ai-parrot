# TASK-3805: Default data-plane guard wiring — app["dataplane_guard"] + bot._dataplane_guard

**Feature**: FEAT-598 — A2UI Linked Surfaces
**Spec**: `sdd/specs/a2ui-linked-surfaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: none (code-independent of the other FEAT-598 tasks; TASK-3796 documents the keys this task fills)
**Assigned-to**: unassigned

---

## Context

Escalation resolution (owner decision, 2026-09-26): FEAT-598's persistence lanes fail CLOSED —
`LinkedSurfaceService` answers 403 (`LinkedGuardRequired`) whenever no guard is configured
(TASK-3781/3787/3788). Verified at task time: **nothing in-tree ever provides one** — no caller of
`setup_pbac` exists in `ai-parrot-server`, and no code sets `app["dataplane_guard"]` or
`bot._dataplane_guard`. Without this task, linked surfaces answer 403 on EVERY deployment until an
operator hand-wires a guard. The owner chose to ship default wiring: build a
`DataPlanePolicyGuard` at server startup **when PBAC can actually initialize** (navigator-auth
importable + policy dir present), and leave the key unset otherwise so the fail-closed 403 is
preserved on bare installs. Deliberately NOT `guard = DataPlanePolicyGuard()` unconditionally: the
guard itself fails OPEN without navigator-auth (`dataplane_guard.py:219-222`), so wiring one on a
bare install would silently disable the owner check — absence of the key is the safe state there.

---

## Scope

- New helper `setup_dataplane_guard(app, *, policy_dir=..., cache_ttl=30)` in
  `parrot/auth/pbac.py`: run `setup_pbac(...)`; when it yields an evaluator, build
  `DataPlanePolicyGuard(evaluator=evaluator, rls_registry=RlsRegistry())`, set
  `app["dataplane_guard"]`, and return the guard; when PBAC is unavailable
  (`(None, None, None)`), set NOTHING and return `None`. Idempotent: an existing
  `app["dataplane_guard"]` is respected and returned as-is.
- New conf constant `PARROT_PBAC_POLICY_DIR` (fallback `"policies"`) in `parrot/conf.py`.
- Call the helper from `BotManager.setup()` via an `on_startup` callback (same deferred pattern as
  `_register_oauth2_providers`).
- Inject the app guard into managed bots: after bot loading, every bot that has no
  `_dataplane_guard` of its own gets the app's (`bot._dataplane_guard = guard`), so
  TASK-3788's `getattr(self, "_dataplane_guard", None)` lanes work out of the box. A bot's own
  pre-set guard is never overwritten.
- Unit tests for the helper (monkeypatched `setup_pbac`) and the injection rule.

**NOT in scope**: changing `DataPlanePolicyGuard` / `setup_pbac` semantics; `LinkedSurfaceService`
(TASK-3781); handler behavior (TASK-3787); shipping policy YAML files; `PARROT_SAAS_MODE`
semantics (already handled inside `setup_pbac` → `_fail_open_or_closed`, which raises when true).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/pbac.py` | MODIFY | add `setup_dataplane_guard()` |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | add `PARROT_PBAC_POLICY_DIR` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | on_startup wiring + bot injection |
| `packages/ai-parrot/tests/auth/test_dataplane_guard_wiring.py` | CREATE | helper unit tests |
| `packages/ai-parrot-server/tests/manager/test_dataplane_guard_wiring.py` | CREATE | manager wiring tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.pbac import setup_pbac                          # pbac.py:67 (sync; returns (pdp, evaluator, guardian) or (None, None, None))
from parrot.auth.dataplane_guard import DataPlanePolicyGuard     # dataplane_guard.py:45
from parrot.auth.rls_registry import RlsRegistry                 # rls_registry.py:87 (no-arg constructor)
from parrot.conf import PARROT_SAAS_MODE                         # conf.py:111 (config.getboolean pattern to copy)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/pbac.py
def setup_pbac(app, policy_dir: str = "policies", cache_ttl: int = 30, default_effect=None)   # L67
# _fail_open_or_closed (L37): returns (None, None, None) when PARROT_SAAS_MODE is false,
# RAISES RuntimeError when true — setup_dataplane_guard must let that propagate.

# packages/ai-parrot/src/parrot/auth/dataplane_guard.py
class DataPlanePolicyGuard:                                       # L45
    def __init__(self, evaluator, rls_registry, sensitive_drivers=frozenset(), logger=None)     # L71

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager: ...                                             # L179
    def setup(self, app, *, agent_mount_config=None, ...)         # L2235; self.app["bot_manager"] = self;
                                                                  # deferred pattern: self.app.on_startup.append(self._register_oauth2_providers)
    async def load_bots(self, app) -> None                        # L392; Step 3 instantiate_startup_agents / Step 4 _load_database_bots
    async def _cleanup_all_bots(...)                              # iterates the same managed-bot collection the injection must walk
```

### Does NOT Exist
- ~~any in-tree caller of `setup_pbac`~~ — this task adds the first one; nothing else sets
  `app['security']`/`app['abac']`, so double-registration is not a live concern (still be idempotent).
- ~~`app["dataplane_guard"]` / `bot._dataplane_guard` writers~~ — only readers exist/are planned
  (`databasequery/tool.py:257` kwarg, `dataset_manager/tool.py:557` kwarg, TASK-3787/3788 getattr lanes).
- ~~an async `setup_pbac`~~ — it is synchronous; the on_startup callback wrapping it is async only
  because aiohttp requires it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/pbac.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_dataplane_guard_wiring.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/manager/test_dataplane_guard_wiring.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/pbac.py#setup_pbac",
    "sym:packages/ai-parrot/src/parrot/auth/dataplane_guard.py#DataPlanePolicyGuard",
    "sym:packages/ai-parrot/src/parrot/auth/rls_registry.py#RlsRegistry",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never wire a vacuous guard**: `setup_pbac → (None, None, None)` ⇒ `app["dataplane_guard"]`
  stays ABSENT (linked saves keep answering 403). Log one INFO line saying linked surfaces are
  disabled until PBAC is configured, naming `PARROT_PBAC_POLICY_DIR`.
- **`PARROT_SAAS_MODE=true`**: `setup_pbac` raises on init failure — let it propagate (startup
  must fail loudly in SaaS mode, per FEAT-446).
- **Idempotent + respectful**: existing `app["dataplane_guard"]` (e.g. injected by tests or an
  operator) wins; a bot's own `_dataplane_guard` wins.
- **Injection point**: walk the same managed-bot collection `_cleanup_all_bots` iterates, AFTER
  `load_bots` completes, inside the on_startup callback (startup callbacks run in append order —
  verify `load_bots` is among them or call the injection after the existing loading step; do not
  invent a second loading path).
- The helper lives in core `parrot.auth`; only the wiring call lives in `ai-parrot-server`
  (one-way dependency preserved).
- TASK-3796 documents these keys — keep the names exactly `app["dataplane_guard"]` /
  `bot._dataplane_guard`.

---

## Acceptance Criteria

- [ ] Evaluator available ⇒ `app["dataplane_guard"]` is a `DataPlanePolicyGuard` built with a
      fresh `RlsRegistry()`; helper returns it.
- [ ] PBAC unavailable (legacy mode) ⇒ key absent, helper returns `None`, one INFO log; linked
      saves still 403 (fail-closed preserved).
- [ ] `PARROT_SAAS_MODE=true` + PBAC init failure ⇒ startup raises (no silent fail-open).
- [ ] Pre-existing `app["dataplane_guard"]` and pre-set `bot._dataplane_guard` are never
      overwritten; bots without one receive the app guard after loading.
- [ ] `ruff check` clean; no behavior change for baked surfaces.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_dataplane_guard_wiring.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_dataplane_guard_wiring.py -q`

---

## Agent Instructions

1. Read spec §7 (S2 exfiltration risk, fail-closed guard) and TASK-3781's Context (why
   fail-closed), TASK-3787 L113 / TASK-3788 L106 (the reader lanes this task feeds).
2. Verify the Codebase Contract lines still hold.
3. Index → `"in-progress"`; implement; tests.
4. Run the Validation Commands (worktree: `PYTHONPATH=packages/ai-parrot/src` plus
   `packages/ai-parrot-server/src` for the manager test).
5. Move to `sdd/tasks/completed/`, index → `"done"`, Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
