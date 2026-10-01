# TASK-3943: BotManager.studio, get_studio_bot, GLOBAL get_bot fallback and setup() hooks

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Runtime + cache + lifecycle + builder (M7, part 5: BotManager.studio wiring)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3942
**Assigned-to**: unassigned

---

## Context

Spec §2.7 "Studio methods" and "The only additive fallback" (Q9), §2.7a (hooks installed by `BotManager.setup()`),
§2.11 (plain host: new agents reachable by bare name through `get_bot`), X7.

---

## Scope

- `BotManager.studio: StudioAgentRuntime | None = None` (set in `__init__`).
- `async get_studio_bot(key, *, new=False, session_id="", request=None)`: `new=False` → `studio.get(key)` then
  `enforce_agent_access(evaluator, key.qualified, request)`; `new=True` → PBAC first, then `studio.get_session`.
  `studio is None` ⇒ raise `StudioStorageUnavailable`.
- `get_bot(name)` tail fallback: only when `new=False`, nothing else found, backend `database`, and the app has no
  installed scope resolver ⇒ `await self.studio.get(StudioAgentKey(None, name))` (never added to `_bots`).
- `setup()`: call `add_studio_runtime_hooks(self.app)` next to the `_cleanup_all_bots` registration.

**NOT in scope**: `setup_registry_only` (FEAT-605 W0.2/W2.2); tenant rows by name (P13 follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | studio attribute, get_studio_bot, GLOBAL fallback, setup() hook call |
| `packages/ai-parrot-server/tests/manager/test_manager_studio_lookup.py` | CREATE | warm-cache isolation + fallback tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.manager.studio_runtime import add_studio_runtime_hooks, StudioAgentRuntime   # TASK-3942 (import inside setup())
from parrot.auth.agent_guard import enforce_agent_access                                 # agent_guard.py:172
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                                # :183 ; _bots :216 ; _botdef :217 ; _cleaned_up :220
    async def get_bot(self, name, new=False, session_id="", request=None, **kwargs)   # :744 ; new branch :767-837 (PBAC :772);
                                                                 #   _bots :842-849 ; registry :850-867 ; None at tail
    def get_bots(self) -> Dict[str, AbstractBot]                 # :1170
    def setup(                                                   # :2239
        self.app.on_cleanup.append(self._cleanup_all_bots)       # :2288 (occurrences: 1) ← anchor
```
How "installed scope resolver" is detected before FEAT-605 lands: `app.get("scope_resolver") or
app.get("ui_surfaces_scope_resolver")` (X9 names); once FEAT-605 W0.1 merges use its `has_installed_resolver(app)`.

### Does NOT Exist
- ~~`has_installed_resolver`~~ — FEAT-605 W0.1 (may or may not be on `dev` when this runs; see note).
- ~~`_load_database_bots` changes~~ — must stay untouched (AC17).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_manager_studio_lookup.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.setup"
  ]
}
```

---

## Implementation Notes

- Parallelism: calls StudioAgentRuntime/add_studio_runtime_hooks from TASK-3942 (manager/studio_runtime.py); second FEAT-621 edit of manager/manager.py after TASK-3941 (transitive)
- Cross-feature ordering: X16 — `manager/manager.py` edits serialise with FEAT-605 W0.2, W1.1, W2.1, W2.2, W3.6
  (whichever first). FEAT-605 W2.2 needs this task merged. If FEAT-605 W0.1 merged first, use
  `has_installed_resolver(app)` instead of the two-key check.
- The warm-cache test is the R2 regression: warm tenant `acme/sales` (base + session) and GLOBAL `helper` first.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self.app.on_cleanup.append(self._cleanup_all_bots)' manager.py)
# AFTER — insert below `        self.app.on_cleanup.append(self._cleanup_all_bots)` (verified: manager.py:2288)
        from .studio_runtime import add_studio_runtime_hooks
        add_studio_runtime_hooks(self.app)
# __init__: self.studio = None   (FILL IN: next to self._cleaned_up, :220)
# get_bot tail (before the final `return None`): FILL IN the GLOBAL fallback — bounded by test_get_bot_global_fallback.
# FILL IN: async def get_studio_bot(self, key, *, new=False, session_id="", request=None) — PBAC before any build.
```

### `packages/ai-parrot-server/tests/manager/test_manager_studio_lookup.py` (CREATE)
```python
"""FEAT-621 R2 / Q9 (AC9, AC18)."""
# FILL IN: test_warm_cache_unreachable_from_legacy (get_bot('sales'), get_bot('studio:acme:sales'),
#   get_bot('studio:acme:sales_<sid>'), same with new=True, get_bots(), _botdef, reload_agent('sales'),
#   _cleanup_all_bots → never return/clone/list/clean a Studio instance; get_bot('helper') returns the GLOBAL
#   instance without adding it to _bots; mutation: store entries in _bots ⇒ RED);
#   test_get_bot_global_fallback (tenant-NULL agent on a fresh pod; not with a resolver installed);
#   test_get_studio_bot_pbac_before_build; test_setup_registers_hooks_once.
```

---

## Acceptance Criteria

- [ ] With a warm cache, no legacy lookup, clone, enumeration, reload or cleanup reaches a Studio instance (`test_warm_cache_unreachable_from_legacy`, AC9).
- [ ] GLOBAL bare-name fallback works without a resolver and never with one; tenant rows unreachable by name (AC18).
- [ ] `setup()` registers the runtime hooks once; `_load_database_bots` untouched (AC17).
- [ ] Regression: `pytest packages/ai-parrot-server/tests/manager/test_manager_studio_guards.py -q` (from TASK-3941) still green.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/manager/test_manager_studio_lookup.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_warm_cache_unreachable_from_legacy` | AC9 (R2) |
| `test_get_bot_global_fallback` | AC18, Q9 |
| `test_get_studio_bot_pbac_before_build` | §2.7 |
| `test_setup_registers_hooks_once` | X8 |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3943 — BotManager.studio, get_studio_bot, GLOBAL get_bot fallback and setup() hooks`.
8. Close with `scripts/sdd/close_task.sh TASK-3943 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sonnet)
**Date**: 2026-10-01
**Notes**: manager.py: BotManager.studio (None until install_studio_runtime sets it), get_studio_bot(key, *, new, session_id, request) (new=False: studio.get then PBAC on key.qualified; new=True: PBAC first, then get_session; StudioStorageUnavailable when no runtime; ValueError for new=True without a session_id, because an empty id would share one test session between users), the single additive get_bot fallback (_studio_global_fallback: runtime installed AND no scope resolver per handlers.scope.has_installed_resolver -> studio.get(StudioAgentKey(None, name)), PBAC on the bare name, a failed/refused build is 'not served' = None, instance never added to _bots/_botdef), and add_studio_runtime_hooks(self.app) in setup(). _load_database_bots untouched (asserted). Finding: legacy get_bot(name, new=True) on an UNKNOWN bare name builds a default BasicAgent session clone and registers it in _bots (pre-existing behaviour); the warm-cache test asserts that clone is never a Studio instance rather than None. 9 tests; 12 mutations RED, 1 equivalent (the studio-is-None early exit; the AttributeError is caught by the same except). Whole tests/manager: 125 pass.

**Deviations from spec**: none
