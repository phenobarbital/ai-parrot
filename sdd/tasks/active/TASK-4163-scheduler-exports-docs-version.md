# TASK-4163: Lazy exports, docs, SQL example, report-builder inventory and ai-parrot-server 1.3.0

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4158, TASK-4161, TASK-4162
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, AC19, AC20. Documentation and public surface for the hard-cut: the new lazy exports in core
`parrot.scheduler`, the migration note (DDL for `navigator.service_scheduler`, `DROP TABLE navigator.agents_scheduler`,
Redis key rename invalidating armed reminders), backends + catch-up semantics, agentd examples, the SQL example and
the four report-builder inventory pages, and the version bump.

---

## Scope

- Core `packages/ai-parrot/src/parrot/scheduler/__init__.py`: add `SchedulerManager`, `TargetRegistry`, `ServiceSchedule`, `JobDefinition` to `_SERVER_CLASSES` and `__all__`.
- `docs/scheduler/multi-worker.md`: replace '## Redis jobstore is not coordination' with '## Backends and coordination' (db | redis | code, forced redis coordinator, namespaced keys, `SCHEDULER_REDIS_DB`, `SCHEDULER_MAX_CONSECUTIVE_FAILURES`, `SCHEDULER_ALERT_RECIPIENTS`); add '## Missed fires and catch-up'; add '## Migration to ai-parrot-server 1.3.0' (DDL verbatim from the `ServiceSchedule` docstring, drop note, Redis key rename + re-arm reminders, `metadata` no longer holds run state); fix the 'Fail-closed behaviour' paragraph (`last_status` is a column now).
- `docs/agentd.md`, `docs/guides/cli-agent-daemon.md`: `schedules.add` examples with `target_kind`/`target_name`/`backend`; no SingleAgentManager.
- `examples/database/agents_scheduler_market_analysis.sql`: rewrite against `navigator.service_scheduler`.
- `docs/report-builder/inventory/_admin_bots.md`, `P1-parrot-endpoints.md`, `P2-parrot-components-models.md`, `docs/report-builder/inventory-and-analysis.md`: table/model/payload names updated.
- `packages/ai-parrot-server/src/parrot/server/version.py`: `1.3.0`.
- `packages/ai-parrot-server/tests/test_namespace_imports.py`: add `("scheduler/base.py", "SchedulerManager")` to the mapping.

**NOT in scope**: code behaviour; tenant enforcement docs beyond 'persisted, not enforced (see spec §8 Q1)'.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/scheduler/__init__.py` | MODIFY | Lazy exports |
| `packages/ai-parrot-server/src/parrot/server/version.py` | MODIFY | 1.3.0 |
| `packages/ai-parrot-server/tests/test_namespace_imports.py` | MODIFY | base.py export mapping |
| `docs/scheduler/multi-worker.md` | MODIFY | Backends, catch-up, migration note |
| `docs/agentd.md` | MODIFY | schedules.add examples |
| `docs/guides/cli-agent-daemon.md` | MODIFY | schedules.add examples |
| `examples/database/agents_scheduler_market_analysis.sql` | MODIFY | service_scheduler |
| `docs/report-builder/inventory/_admin_bots.md` | MODIFY | New names |
| `docs/report-builder/inventory/P1-parrot-endpoints.md` | MODIFY | New payload |
| `docs/report-builder/inventory/P2-parrot-components-models.md` | MODIFY | New model |
| `docs/report-builder/inventory-and-analysis.md` | MODIFY | New names |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/scheduler/__init__.py:12-43
_SERVER_CLASSES = {"ScheduleType": ("parrot.scheduler.manager", "ScheduleType"), ...,
                   "AgentSchedulerManager": ("parrot.scheduler.manager", "AgentSchedulerManager"), ...}   # line 17
def __getattr__(name: str): ... load_satellite_attr(name, module_path, install="ai-parrot-server[scheduler]", attr=cls_name)
__all__ = ["ScheduleType", "schedule", "schedule_daily_report", "schedule_weekly_report", "AgentSchedulerManager"]
# packages/ai-parrot-server/src/parrot/server/version.py:3 — __version__ = "1.2.0"
# docs/scheduler/multi-worker.md:35 — "## Redis jobstore is not coordination"
# packages/ai-parrot-server/tests/test_namespace_imports.py:38 — ("scheduler/manager.py", "AgentSchedulerManager"),
```

### Does NOT Exist
- ~~a DDL migration tool~~ — the DDL is documentation; operators run it by hand.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/scheduler/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/server/version.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/test_namespace_imports.py",
      "action": "MODIFY"
    },
    {
      "path": "docs/scheduler/multi-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/agentd.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/guides/cli-agent-daemon.md",
      "action": "MODIFY"
    },
    {
      "path": "examples/database/agents_scheduler_market_analysis.sql",
      "action": "MODIFY"
    },
    {
      "path": "docs/report-builder/inventory/_admin_bots.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/report-builder/inventory/P1-parrot-endpoints.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/report-builder/inventory/P2-parrot-components-models.md",
      "action": "MODIFY"
    },
    {
      "path": "docs/report-builder/inventory-and-analysis.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/scheduler/__init__.py#__getattr__"
  ]
}
```

---

## Implementation Notes

Copy the DDL from the merged `ServiceSchedule` docstring, not from the spec, so docs and code cannot drift. Run `rg -n 'agents_scheduler|agent_name|is_crew|scheduler_type' docs/ examples/database/` afterwards; remaining hits must be in the migration note only.

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
1. Exports + version + namespace test.
2. multi-worker.md sections.
3. agentd docs.
4. SQL example.
5. Inventory pages.
6. rg check.

### `packages/ai-parrot/src/parrot/scheduler/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "AgentSchedulerManager": ("parrot.scheduler.manager", "AgentSchedulerManager"),' packages/ai-parrot/src/parrot/scheduler/__init__.py)
# AFTER that line — insert:
    "SchedulerManager": ("parrot.scheduler.base", "SchedulerManager"),
    "TargetRegistry": ("parrot.scheduler.base", "TargetRegistry"),
    "ServiceSchedule": ("parrot.scheduler.models", "ServiceSchedule"),
    "JobDefinition": ("parrot.scheduler.models", "JobDefinition"),
# and append the four names to __all__.
```
### `packages/ai-parrot-server/src/parrot/server/version.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^__version__ = "1.2.0"' packages/ai-parrot-server/src/parrot/server/version.py)
__version__ = "1.3.0"
```
### Docs / SQL / inventory (MODIFY)
```markdown
<!-- FILL IN per Scope; DDL copied from the ServiceSchedule docstring -->
```

### FILL IN checklist
- [ ] multi-worker.md three sections.
- [ ] agentd docs examples.
- [ ] SQL example.
- [ ] Inventory pages.

---

## Acceptance Criteria

- [ ] `from parrot.scheduler import SchedulerManager, TargetRegistry, ServiceSchedule, JobDefinition` works (AC1 lazy export).
- [ ] `__version__ == '1.3.0'`.
- [ ] The rg check leaves legacy names only inside the migration note.
- [ ] The migration note tells operators that Redis keys moved (armed ReminderToolkit reminders must be re-armed, AC20).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/test_namespace_imports.py -q`
- `pytest packages/ai-parrot/tests/test_lazy_imports.py -q`

---

## Test Specification

Covered by the two existing import test modules plus the added mapping row.

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
   `feat(scheduler-manager-base): TASK-4163 — Lazy exports, docs, SQL example, report-builder inventory and ai-parrot-server 1.3.0`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4163 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4163 — Lazy exports, docs, SQL example, report-builder inventory and ai-parrot-server 1.3.0`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
