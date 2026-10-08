# TASK-4153: Scheduler callbacks take target_name instead of agent_name

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. The hard-cut renames the keyword every delivery callback receives: `BaseSchedulerCallback.run(result,
*, schedule_id, agent_name, **kwargs)` becomes `run(result, *, schedule_id, target_name, **kwargs)` (spec AC15/G7).
To keep the legacy `AgentSchedulerManager` working until TASK-4158 replaces it, this task also updates its single call
site (`packages/ai-parrot-server/src/parrot/scheduler/manager.py:782`).

---

## Scope

- Rename the keyword `agent_name` → `target_name` on `BaseSchedulerCallback.run` and `__call__` and on the four subclasses' `run` (functions/__init__.py lines 97, ~100, 108, 155, 169, 215), including every use inside the bodies.
- Rename it on `RunInfographicRecipeCallback.run` (infographic_recipes.py:348).
- Update the legacy call site `callback(result, schedule_id=schedule_id, agent_name=agent_name)` (manager.py:782) to `target_name=agent_name`.
- Update `test_callback_delivery.py` and `tests/handlers/test_infographic_recipes.py` call sites; add a test that `agent_name=` now raises `TypeError`.

**NOT in scope**: any other manager.py change (TASK-4158); `_job_context` keys (TASK-4157).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` | MODIFY | agent_name → target_name on 5 run() + __call__ |
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | MODIFY | RunInfographicRecipeCallback.run keyword |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | Legacy call site at line 782 passes target_name= |
| `packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py` | MODIFY | Call sites use target_name= |
| `packages/ai-parrot-server/tests/handlers/test_infographic_recipes.py` | MODIFY | Call sites use target_name= |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
class BaseSchedulerCallback(NotificationMixin):                       # line 17
    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:   # line 97
    async def __call__(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:  # ~line 100
class SendEmailReportCallback(BaseSchedulerCallback):   # line 104 — run at 108
class CreateFileCallback(BaseSchedulerCallback):        # line 151 — run at 155
class SaveDataCallback(BaseSchedulerCallback):          # line 165 — run at 169
class SendNotifyReportCallback(BaseSchedulerCallback):  # line 211 — run at 215
# packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py
class RunInfographicRecipeCallback(BaseSchedulerCallback):   # line 323 — `async def run(` at 348, keyword at 349
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:782 (inside _handle_job_success)
                response = await callback(result, schedule_id=schedule_id, agent_name=agent_name)
```
Anchor `    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:` has
**5 occurrences** in functions/__init__.py — edit each in its class (lines 97/108/155/169/215); `grep -n 'agent_name'`
the file afterwards must return nothing.

### Does NOT Exist
- ~~a deprecated `agent_name` alias~~ — hard-cut; do not accept both.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_infographic_recipes.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#BaseSchedulerCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#SendEmailReportCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#CreateFileCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#SaveDataCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#SendNotifyReportCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py#RunInfographicRecipeCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._handle_job_success"
  ]
}
```

---

## Implementation Notes

Use `grep -n agent_name` on each file before and after; bodies may interpolate `agent_name` into email subjects or paths — rename those variables too, keeping the produced text identical.

### Key Constraints
- Async-first; never block the event loop. `self.logger` / module `logger`, never `print`.
- Google-style docstrings and strict type hints; 120-column lines; `ruff check` (TID251) must pass on every touched file.
- Every timestamp the scheduler writes goes through `utcnow()` (UTC-aware) — never `datetime.now()` (spec AC7).
- Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes (they come from the
> spec's §3 Interface Skeletons). Anchors were re-verified with `grep -c` at task-generation time.

### Steps (in order)
1. Rename the keyword in all five `run` signatures, `__call__`, and every body reference — *why*: hard-cut (spec G7).
2. Rename in `RunInfographicRecipeCallback.run` — *why*: it is registered in `CALLBACK_REGISTRY` and called the same way.
3. Change manager.py:782 to pass `target_name=agent_name` — *why*: keeps the legacy manager green until TASK-4158.
4. Update the two test files and add the TypeError test.

### `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` (MODIFY)
```python
# occurrences: 5 (verified: grep -c 'async def run(self, result: Any, \*, schedule_id: str, agent_name: str' packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py)
# FILL IN: disambiguate — edit each occurrence inside its own class (BaseSchedulerCallback:97, SendEmailReportCallback:108,
#          CreateFileCallback:155, SaveDataCallback:169, SendNotifyReportCallback:215) to:
    async def run(self, result: Any, *, schedule_id: str, target_name: str, **kwargs) -> Dict[str, Any]:
# and BaseSchedulerCallback.__call__ to:
    async def __call__(self, result: Any, *, schedule_id: str, target_name: str, **kwargs) -> Dict[str, Any]:
        return await self.run(result, schedule_id=schedule_id, target_name=target_name, **kwargs)
```
### `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'agent_name' — re-run; the keyword is on line 349 inside `async def run(` at 348)
# FILL IN: rename the keyword-only parameter `agent_name` → `target_name` and its uses in the body.
```
### `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'response = await callback(result, schedule_id=schedule_id, agent_name=agent_name)' packages/ai-parrot-server/src/parrot/scheduler/manager.py)
# REPLACE (manager.py:782):
                response = await callback(result, schedule_id=schedule_id, target_name=agent_name)
```
**Why**: one rename across producer and consumers in a single commit keeps the tree green; the legacy manager's
internal variable stays `agent_name` because TASK-4158 deletes that method anyway.

### FILL IN checklist
- [ ] Rename inside each of the 5 classes' bodies.
- [ ] infographic_recipes.py keyword + body uses.

---

## Acceptance Criteria

- [ ] `grep -n agent_name` on `functions/__init__.py` and `handlers/infographic_recipes.py` returns nothing.
- [ ] Every `CALLBACK_REGISTRY` entry accepts `target_name=`; `agent_name=` raises `TypeError`.
- [ ] `test_callback_delivery.py`, `test_delivery_outcomes.py` and `tests/handlers/test_infographic_recipes.py` pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_infographic_recipes.py -q`

---

## Test Specification

```python
# addition to packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py
@pytest.mark.parametrize("name", sorted(CALLBACK_REGISTRY))
async def test_callbacks_receive_target_name(name): ...   # inspect.signature(cls.run) has target_name, not agent_name
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug scheduler-manager-base --feature-id FEAT-644 --spec sdd/specs/scheduler-manager-base.spec.md --index sdd/tasks/index/scheduler-manager-base.json`)
2. **Read the spec** at `sdd/specs/scheduler-manager-base.spec.md` (§2 Overview, the CRUD matrix, Data Models, and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/scheduler-manager-base.json`
4. **Verify the Codebase Contract** — re-`grep` every anchor and signature before writing code; if one moved, fix
   the contract in this file first; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** — `ruff check` the touched files and run every Validation Command
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(scheduler-manager-base): TASK-4153 — Scheduler callbacks take target_name instead of agent_name`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4153 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4153 — Scheduler callbacks take target_name instead of agent_name`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
