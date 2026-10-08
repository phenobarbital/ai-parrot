# TASK-4162: agentd: delete SingleAgentManager, register the agent as a target, hard-cut schedules.add

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4158
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, AC2, AC16. `SingleAgentManager` (`packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py:240-275`) exists only to fake the
`BotManager` surface the old scheduler touched (`_bots`, `registry.get_instance`, `get_crew`). With the registry-first
`AgentResolver`, agentd registers its one agent explicitly. The RPC `schedules.add` keeps forwarding `**params` to
`add_schedule`, so the payload hard-cut is automatic — unknown kwargs (`agent_name`) must surface as an
invalid-params RPC error.

---

## Scope

- Delete `SingleAgentManager` and its `__all__` entry (`service.py:58`).
- In the scheduler boot (`service.py:503-529`): `manager = AgentSchedulerManager()`; `manager.register_target(self.config.name, self.agent, kind='agent')`; keep `start_headless(dsn=..., use_redis=...)`, `register_bot_schedules(self.agent)` and the two listeners.
- `_handle_schedules_add`: wrap `TypeError` / `pydantic.ValidationError` / `SchedulerConfigError` / `ValueError` from `add_schedule(**params)` into the module's invalid-params `RpcHandlerError`; serialize the returned `JobDefinition` with `model_dump(mode='json')` before `_serialize_for_rpc`.
- Update `SchedulerConfig` docstring (`config.py:115`) and the module docstring of `service.py` (no SingleAgentManager).
- Create `tests/agentd/test_scheduler_boot.py`; keep `test_e2e.py::test_scheduler_interval_job_fires_and_event_emitted` passing.

**NOT in scope**: docs (`docs/agentd.md`, `docs/guides/cli-agent-daemon.md` — TASK-4163); CLI flags (`--redis/--no-redis` keep their meaning).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` | MODIFY | Delete SingleAgentManager; register_target; schedules.add error mapping |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` | MODIFY | SchedulerConfig docstring |
| `packages/ai-parrot-integrations/tests/agentd/test_scheduler_boot.py` | CREATE | Boot + RPC hard-cut tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py
"SingleAgentManager",                                         # line 58 in __all__ — delete
class SingleAgentManager:                                     # line 240-275 — delete
# boot block, lines 503-529:
        from parrot.scheduler.manager import AgentSchedulerManager          # line 509 (inside try/except ImportError)
        single_agent_manager = SingleAgentManager(self.agent, self.config.name)   # line 524
        manager = AgentSchedulerManager(bot_manager=single_agent_manager)          # line 525
        await manager.start_headless(dsn=self.config.scheduler.dsn, use_redis=self.config.scheduler.redis)
        manager.register_bot_schedules(self.agent)                         # line 529
async def _handle_schedules_add(self, session: Session, params: dict[str, Any]) -> Any:   # line 787
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py:115
class SchedulerConfig(BaseModel):   # enabled: bool = True; dsn: str | None = None; redis: bool = False
```
Find the invalid-params error code constant in `service.py` with `grep -n 'INVALID_PARAMS\|RpcHandlerError(' packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py`
before using it (verify, do not guess the name).

### Does NOT Exist
- ~~`SingleAgentManager`~~ after this task (AC2: absent from the repo).
- ~~`AgentSchedulerManager(bot_manager=...)` requirement~~ — `bot_manager` is optional.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/agentd/test_scheduler_boot.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py#SingleAgentManager",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py#AgentDaemon._handle_schedules_add",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py#SchedulerConfig"
  ]
}
```

---

## Implementation Notes

The registered target name must equal what `register_bot_schedules` uses (`bot.name`) and what RPC clients send as `target_name` — `self.config.name`. If they can differ, register under both and note it.

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
1. Delete the class and `__all__` entry — *why*: AC2.
2. Rewrite the boot block — *why*: the registry-first AgentResolver replaces the fake BotManager.
3. Map add_schedule input errors to invalid params — *why*: AC16.
4. Write the boot/RPC tests; run them with `test_e2e.py`.

### `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        manager = AgentSchedulerManager(bot_manager=single_agent_manager)' packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py)
# REPLACE lines 524-525:
        manager = AgentSchedulerManager()
        manager.register_target(self.config.name, self.agent, kind="agent")
# occurrences: 1 (verified: grep -c '^class SingleAgentManager:' packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py) — DELETE the class (240-275) and "SingleAgentManager" in __all__.
# occurrences: 1 (verified: grep -c '    async def _handle_schedules_add(self, session: Session, params: dict\[str, Any\]) -> Any:' packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py)
# FILL IN: try/except around add_schedule(**params) → RpcHandlerError(<verified invalid-params code>, str(exc)).
```

### FILL IN checklist
- [ ] Invalid-params mapping with the verified constant.
- [ ] config.py docstring.
- [ ] Boot/RPC tests.

---

## Acceptance Criteria

- [ ] `grep -rn SingleAgentManager packages/` returns nothing.
- [ ] RPC `schedules.add` with `agent_name` fails with an invalid-params error; with `target_kind='agent', target_name=<name>` it succeeds.
- [ ] `test_e2e.py::TestScheduler::test_scheduler_interval_job_fires_and_event_emitted` (or its current node id) passes.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-integrations/tests/agentd/test_scheduler_boot.py -q`
- `pytest packages/ai-parrot-integrations/tests/agentd/test_e2e.py -q`
- `pytest packages/ai-parrot-integrations/tests/agentd/test_service.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_scheduler_boot.py
async def test_agentd_boots_without_single_agent_manager(...): ...
async def test_schedules_add_rejects_agent_name(...): ...
async def test_schedules_add_target_kind_agent(...): ...
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
   `feat(scheduler-manager-base): TASK-4162 — agentd: delete SingleAgentManager, register the agent as a target, hard-cut schedules.add`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4162 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4162 — agentd: delete SingleAgentManager, register the agent as a target, hard-cut schedules.add`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
