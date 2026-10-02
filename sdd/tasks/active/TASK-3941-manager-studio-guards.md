# TASK-3941: BotManager: cleanup_bot_instance extraction, get_bot prefix refusal, add_bot refusal

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W2 — Runtime + cache + lifecycle + builder (M7, part 3: BotManager legacy guards)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3922
**Assigned-to**: unassigned

---

## Context

Spec §2.7 "Legacy paths cannot reach it" (R2), §2.7a `cleanup_bot_instance` row, X7. Today `get_bot` returns
`_bots[name]` before anything else and `get_bot(new=True)` clones `_bots`/`_botdef`; `_safe_cleanup` guards by name.

---

## Scope

- Module-level `async def cleanup_bot_instance(bot, *, label) -> bool` extracted from `_safe_cleanup` (timeout +
  exception isolation, never raises); `_safe_cleanup` keeps its name guard and calls it.
- `get_bot`: first statement returns `None` for any `name` starting with `studio:` or `studio-agent:` (with or
  without `new=True`), before touching `_bots`, `_botdef` or the registry.
- `add_bot`: raise `ValueError` for an instance carrying `_studio_key`.

**NOT in scope**: `BotManager.studio`, `get_studio_bot`, the GLOBAL fallback and the hook call in `setup()` (TASK-3943).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | cleanup_bot_instance; get_bot prefix guard; add_bot refusal |
| `packages/ai-parrot-server/tests/manager/test_manager_studio_guards.py` | CREATE | guard unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.models import STUDIO_KEY_PREFIX, STUDIO_TOOLING_REF_PREFIX  # TASK-3922 (import lazily
                                                                                                 # inside get_bot or define
                                                                                                 # local tuple — manager must
                                                                                                 # not import handlers at module load)
from parrot.conf import BOT_CLEANUP_TIMEOUT                                                     # conf.py:223
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
    def add_bot(self, bot: AbstractBot) -> None:                          # :738 (occurrences: 1)
    async def get_bot(                                                     # :744 (occurrences: 1); body starts :768 `if new:`
    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool:    # :1722 (occurrences: 1); guard :1737, add :1755
```

### Does NOT Exist
- ~~`cleanup_bot_instance`~~ — created here.

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
      "path": "packages/ai-parrot-server/tests/manager/test_manager_studio_guards.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.get_bot",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.add_bot",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._safe_cleanup"
  ]
}
```

---

## Implementation Notes

- Parallelism: imports STUDIO_KEY_PREFIX/STUDIO_TOOLING_REF_PREFIX from TASK-3922 (storage/models.py); first FEAT-621 writer of manager/manager.py (TASK-3943 follows); TASK-3942 imports cleanup_bot_instance
- Cross-feature ordering: X16 — `manager/manager.py` also carries FEAT-605 W0.2, W1.1, W2.1, W2.2, W3.6 edits (small,
  non-overlapping): serialise, whichever merges first, and rebase onto the other.
- Keep the prefix check import-free at module load (a local constant `_STUDIO_PREFIXES = ("studio:", "studio-agent:")`
  asserted equal to the models constants in the test is acceptable and avoids a manager → handlers import).

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
# occurrences: 1 (verified: grep -c '    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool:' manager.py)
# BEFORE `class BotManager` — module level:
_STUDIO_PREFIXES = ("studio:", "studio-agent:")


async def cleanup_bot_instance(bot: "AbstractBot", *, label: str) -> bool:
    """Run bot.cleanup() with BOT_CLEANUP_TIMEOUT and exception isolation. Never raises."""
    # FILL IN: move the try/except body of _safe_cleanup here (logger = logging.getLogger(...) at module level).
    raise NotImplementedError
# _safe_cleanup: keep `if name in self._cleaned_up` guard; `ok = await cleanup_bot_instance(bot, label=name)`;
#   add to _cleaned_up only when ok.
# get_bot (:744) — first statement of the body:
        if isinstance(name, str) and name.startswith(_STUDIO_PREFIXES):
            return None
# add_bot (:738) — first statement:
        if getattr(bot, "_studio_key", None) is not None:
            raise ValueError("Studio agents live in StudioRuntimeCache, never in BotManager._bots")
```

### `packages/ai-parrot-server/tests/manager/test_manager_studio_guards.py` (CREATE)
```python
"""FEAT-621 R2 guards (AC9, AC18)."""
# FILL IN: test_get_bot_refuses_studio_prefixes (studio:acme:sales, studio:-:x_ab12, studio-agent:<uuid>; new=False and
#   new=True → None; _bots/_botdef untouched); test_add_bot_refuses_studio_instance; test_cleanup_bot_instance_isolation
#   (timeout and exception → False, no raise; _safe_cleanup keeps its name guard); test_prefixes_match_models.
```

---

## Acceptance Criteria

- [ ] `get_bot` returns `None` for `studio:`/`studio-agent:` names with or without `new=True`, touching nothing (`test_get_bot_refuses_studio_prefixes`, AC9/AC18).
- [ ] `add_bot` raises `ValueError` for a Studio instance (`test_add_bot_refuses_studio_instance`, AC9).
- [ ] `cleanup_bot_instance` isolates timeout/exception; `_safe_cleanup` behaviour unchanged (`test_cleanup_bot_instance_isolation`).
- [ ] `get_bot` behaviour for every existing (non-prefixed) name unchanged (AC18): existing manager tests pass.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/manager/test_manager_studio_guards.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_reload_agent.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_get_bot_refuses_studio_prefixes` | AC9, AC18 |
| `test_add_bot_refuses_studio_instance` | AC9 |
| `test_cleanup_bot_instance_isolation` | §2.7a |
| `test_prefixes_match_models` | consistency |

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
   `feat(agentstudio-db-storage): TASK-3941 — BotManager: cleanup_bot_instance extraction, get_bot prefix refusal, add_bot refusal`.
8. Close with `scripts/sdd/close_task.sh TASK-3941 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
