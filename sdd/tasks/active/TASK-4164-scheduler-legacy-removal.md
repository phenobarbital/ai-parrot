# TASK-4164: Remove AgentSchedule, normalize_jobstore_alias and agents_scheduler references

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4159, TASK-4160, TASK-4161
**Assigned-to**: unassigned

---

## Context

Spec AC5: after the hard-cut neither `AgentSchedule` nor the string `agents_scheduler` may appear under
`packages/*/src`. This task removes the last legacy definitions once nothing imports them, and points
`sanitize._known_schedule_types` at `base.ScheduleType` (manager.py only re-exports it now).

---

## Scope

- Delete `class AgentSchedule` from `models.py`.
- Delete `normalize_jobstore_alias` (and its `__all__` entry) from `sanitize.py`; delete its tests from `test_sanitize.py`.
- `sanitize._known_schedule_types`: `from .base import ScheduleType`.
- Fix docstrings mentioning `navigator.agents_scheduler` / `scheduler_type` in `sanitize.py`; rewrite the two `AgentSchedule`-pattern docstring mentions in `handlers/models/studio_drafts.py:18` and `handlers/models/skills_catalog.py:19` to `ServiceSchedule`.
- Run the full AC5 grep and the scheduler suite.

**NOT in scope**: any behaviour change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/models.py` | MODIFY | Delete AgentSchedule |
| `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` | MODIFY | Delete normalize_jobstore_alias; ScheduleType from base; docstrings |
| `packages/ai-parrot-server/tests/scheduler/test_sanitize.py` | MODIFY | Delete normalize_jobstore_alias tests |
| `packages/ai-parrot-server/src/parrot/handlers/models/studio_drafts.py` | MODIFY | Docstring mention |
| `packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py` | MODIFY | Docstring mention |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/models.py:7 — class AgentSchedule(Model)  (delete)
# packages/ai-parrot-server/src/parrot/scheduler/sanitize.py:275 — def normalize_jobstore_alias(  (delete); __all__ lines 53-62
# packages/ai-parrot-server/src/parrot/scheduler/sanitize.py:332-340 — def _known_schedule_types(): from .manager import ScheduleType  → from .base import ScheduleType
# packages/ai-parrot-server/src/parrot/handlers/models/studio_drafts.py:18 and skills_catalog.py:19 — docstrings say "AgentSchedule`` pattern"
```

### Does NOT Exist
- ~~any remaining importer of `AgentSchedule` / `normalize_jobstore_alias`~~ — verify with the AC5 grep BEFORE deleting; if one exists, stop and report.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/sanitize.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_sanitize.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/models/studio_drafts.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/models/skills_catalog.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/models.py#AgentSchedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#normalize_jobstore_alias",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/sanitize.py#_known_schedule_types"
  ]
}
```

---

## Implementation Notes

AC5 grep: `rg -n 'AgentSchedule\b|agents_scheduler|normalize_jobstore_alias' packages/*/src packages/*/tests tests` must return nothing after this task (docs are TASK-4163's).

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
1. Run the AC5 grep first — if any importer remains, stop.
2. Delete and repoint.
3. Re-run the grep and the suites.

### `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    from .manager import ScheduleType  # local import' packages/ai-parrot-server/src/parrot/scheduler/sanitize.py)
    from .base import ScheduleType  # local import — avoids a circular import
# occurrences: 1 (verified: grep -c '^def normalize_jobstore_alias(' packages/ai-parrot-server/src/parrot/scheduler/sanitize.py) — DELETE the function and its __all__ entry.
```
### `packages/ai-parrot-server/src/parrot/scheduler/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^class AgentSchedule(Model):' packages/ai-parrot-server/src/parrot/scheduler/models.py) — DELETE the class.
```

### FILL IN checklist
- [ ] Docstring rewrites (sanitize module docstring, two handler model docstrings).

---

## Acceptance Criteria

- [ ] The AC5 grep returns nothing.
- [ ] All scheduler test modules pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_sanitize.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_fire_recheck.py -q`

---

## Test Specification

Deletions only; existing suites guard it.

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
   `feat(scheduler-manager-base): TASK-4164 — Remove AgentSchedule, normalize_jobstore_alias and agents_scheduler references`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4164 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4164 — Remove AgentSchedule, normalize_jobstore_alias and agents_scheduler references`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
