# TASK-4158: AgentSchedulerManager as a SchedulerManager subclass with AgentResolver and CrewResolver

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4157
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `manager.py` shrinks to the agent-specific layer: `AgentResolver` (registry → `bot_manager.get_bots()`
→ `await bot_manager.registry.get_instance()`; never the private `_bots`), `CrewResolver` (AWAITS the async
`BotManager.get_crew()` — fixing the un-awaited calls at `packages/ai-parrot-server/src/parrot/scheduler/manager.py:681` and `:1170`), the `@schedule` / report decorators,
`register_bot_schedules`, and `AgentSchedulerManager(SchedulerManager)`. Everything else is deleted, including the
duplicate `SchedulerHandler` view (`packages/ai-parrot-server/src/parrot/scheduler/manager.py:2098-2219`, design research S10).

After this task the legacy test modules that reference `AgentSchedule` / `agent_name` break until TASK-4159/4160
migrate them — this task's Validation Commands exclude them on purpose.

---

## Scope

- Rewrite `manager.py` to: module docstring; imports; re-exports `from .base import ScheduleType, SchedulerRunNowConflictError, SchedulerManager, TargetRegistry, _RUN_NOW_JOB_PREFIX` and `from .models import schedule_fingerprint`; the decorators and env parsers (manager.py:98-325 kept verbatim); `AgentResolver`; `CrewResolver`; `AgentSchedulerManager`.
- `AgentResolver.build_call`: `method_name` set ⇒ same rules as `RegistryResolver` (public, callable) + `apply_prompt_signature` + `inject_fire_context`; `method_name` None and `prompt` set ⇒ target method is `chat` with `prompt` as the single positional arg; neither ⇒ `ValueError('Either prompt or method_name must be provided')`. `derive_target_id` → `getattr(agent, 'chatbot_id', None)`.
- `CrewResolver`: `entry = await bot_manager.get_crew(name)`; returns `entry[0]` or None; `derive_target_id` → crew_def `crew_id` (store the def on resolve); `build_call` maps the prompt to `initial_task` (run_flow/run_loop), `query` (run_sequential), `tasks` (run_parallel, list only) — move of manager.py:421-427 — falling back to `apply_prompt_signature`.
- `AgentSchedulerManager.__init__(bot_manager=None, **kwargs)` installs both resolvers with a `bot_manager_getter` so `on_startup` can set `self.bot_manager` later; `register_bot_schedules(bot)` resolves report env timing (`_resolve_report_schedule`) into the method's `_schedule_config` copy then calls `register_object_schedules(bot, bot.name)`; `on_startup` = `super().on_startup` + `app.get('bot_manager')` fallback + `register_bot_schedules` for `get_bots()`.
- Make the `ServiceSchedule` jobs' manager the agent one: nothing to do — `registered_name` default unchanged.
- Write `tests/scheduler/test_resolvers.py`.

**NOT in scope**: migrating the legacy test modules (TASK-4159/4160); HTTP handler and SavedExecutionService (TASK-4161); agentd (TASK-4162); removing `AgentSchedule` from models.py (TASK-4164).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | Shrink to decorators + AgentResolver + CrewResolver + AgentSchedulerManager subclass; delete legacy code and SchedulerHandler |
| `packages/ai-parrot-server/tests/scheduler/test_resolvers.py` | CREATE | Agent/crew resolver and subclass tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from .base import (SchedulerManager, ScheduleType, SchedulerRunNowConflictError, TargetRegistry,
                   apply_prompt_signature, inject_fire_context, _RUN_NOW_JOB_PREFIX)   # TASK-4154/4155
from .models import JobDefinition, FireContext, schedule_fingerprint                  # TASK-4147
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:98-325 — KEEP verbatim: _DEFAULT_REPORT_*, schedule(), _report_decorator_factory, schedule_daily_report,
#   schedule_weekly_report, _parse_daily_schedule, _parse_weekly_schedule, _resolve_report_schedule(agent_id, report_type) (line 294)
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1290-1358 register_bot_schedules — report-type branch to keep:
#   if hasattr(method, "_schedule_report_type"): agent_id = chatbot_id or agent_id or name; schedule_config = _resolve_report_schedule(...)
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:421-427 crew prompt map: run_flow/run_loop → "initial_task", run_sequential → "query", run_parallel → "tasks" (list only)
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                                    # line 212
    def get_bots(self) -> Dict[str, AbstractBot]: ...                # line 1257 (public)
    async def get_crew(self, identifier: str, as_new: bool = False, tenant: Optional[str] = None
                       ) -> Optional[Tuple[AgentCrew, CrewDefinition]]: ...   # line 3019 — ASYNC
# packages/ai-parrot/src/parrot/registry/registry.py:85
    async def get_instance(self, *args, **kwargs) -> AbstractBot: ...
```
Delete from manager.py: `_SchedulerNotification` (moved), `schedule_fingerprint` def (re-exported from models),
the whole old `AgentSchedulerManager` body (moved to base by TASK-4155/4156/4157), `SchedulerHandler` (2098-2219).

### Does NOT Exist
- ~~`BotManager.get_bot(name)`~~ — not verified; use `get_bots().get(name)`.
- ~~a synchronous `BotManager.get_crew`~~ — it is async; await it (AC4).
- ~~`bot_manager._bots`~~ — must not appear anywhere in the new manager.py.
- ~~`SchedulerHandler`~~ — deleted here; routes are registered by `SchedulerManager.setup()` (TASK-4155).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_resolvers.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.register_bot_schedules",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.on_startup",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._prepare_call_arguments",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#_resolve_report_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#SchedulerHandler",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.get_crew",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.get_bots",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_instance"
  ]
}
```

---

## Implementation Notes

`AgentResolver.resolve(name)`: `self._registry.get(name, kind="agent")` → `bm = self._bot_manager_getter()`; if `bm`:
`bm.get_bots().get(name)` → `await bm.registry.get_instance(name)` inside `try` (exception ⇒ log debug, return
None — the base turns None into `target_missing`). Return None when nothing found.

agentd (TASK-4162) constructs `AgentSchedulerManager()` with no bot_manager and registers its single agent with
`register_target(name, agent, kind="agent")` — the registry-first order is what makes that work.

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
1. Copy manager.py:1-325 header/decorators into the new file shape, trimming unused imports — *why*: decorators and report env parsing are public API (`parrot.scheduler.schedule`).
2. Write `AgentResolver` and `CrewResolver` — *why*: AC4 (await get_crew) and no private `_bots` access.
3. Write `AgentSchedulerManager` (init, register_bot_schedules, on_startup) — *why*: G2.
4. Delete everything else (old class body, SchedulerHandler) — *why*: hard-cut (S10).
5. Write `test_resolvers.py`; run it plus the report-decorator and base suites.

### `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^class AgentSchedulerManager:' packages/ai-parrot-server/src/parrot/scheduler/manager.py) — REPLACE from this line to end of file.
class AgentResolver:
    """``agent`` kind: registry → BotManager.get_bots() → AgentRegistry.get_instance()."""

    kind: str = "agent"

    def __init__(self, registry: TargetRegistry, bot_manager_getter: Callable[[], Any | None]) -> None:
        self._registry = registry
        self._bot_manager_getter = bot_manager_getter

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
        """Never touches ``bot_manager._bots``."""
        # FILL IN: Implementation Notes.

    def derive_target_id(self, target: Any) -> str | None:
        return getattr(target, "chatbot_id", None)

    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]:
        """method_name rules as RegistryResolver; prompt-only → chat(prompt)."""
        # FILL IN — the caller (base._execute_job) uses ``definition.method_name or "chat"`` as the attribute.


class CrewResolver:
    """``crew`` kind: ``await bot_manager.get_crew(name)`` (verified async: manager/manager.py:3019)."""

    kind: str = "crew"
    # FILL IN: __init__(registry, bot_manager_getter), resolve (await get_crew; remember crew_def for derive_target_id),
    #          derive_target_id (crew_def.crew_id), build_call (crew prompt map, else apply_prompt_signature).


class AgentSchedulerManager(SchedulerManager):
    """SchedulerManager plus agent/crew resolution, ``@schedule`` bot scanning and BotManager auto-wiring."""

    def __init__(self, bot_manager: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.bot_manager = bot_manager
        self.register_resolver(AgentResolver(self.targets, lambda: self.bot_manager))
        self.register_resolver(CrewResolver(self.targets, lambda: self.bot_manager))

    def register_bot_schedules(self, bot: Any) -> int:
        """Resolve report-decorator env timing, then ``register_object_schedules(bot, bot.name)``."""
        # FILL IN: keep manager.py:1317-1327 report branch; never mutate the shared decorator config dict in place.

    async def on_startup(self, app: web.Application, conn: Callable) -> None:
        """Base startup, then BotManager fallback (app['bot_manager']) and bot schedule registration."""
        # FILL IN: move manager.py:2058-2075.
```
**Why**: `base._execute_job` calls `getattr(target, definition.method_name or "chat")` — keep that contract consistent
with `AgentResolver.build_call` (TASK-4157 implements the base side; if it does not handle `None`, adjust
`_execute_job` minimally and note it).

### FILL IN checklist
- [ ] `AgentResolver.resolve` / `build_call` (chat fallback).
- [ ] `CrewResolver` — await get_crew, crew prompt map.
- [ ] `register_bot_schedules` — report env branch preserved.
- [ ] `on_startup` — bot_manager fallback + registration.
- [ ] Delete old class body + SchedulerHandler; keep decorators verbatim.

---

## Acceptance Criteria

- [ ] `AgentSchedulerManager` is a subclass of `SchedulerManager`; `registered_name` default is `scheduler_manager`.
- [ ] `grep -n '_bots' manager.py` and `grep -n 'class SchedulerHandler' manager.py` return nothing.
- [ ] `CrewResolver` resolves a crew from a `BotManager` stub whose `get_crew` is `async def` (AC4).
- [ ] `from parrot.scheduler.manager import ScheduleType, schedule, schedule_daily_report, SchedulerRunNowConflictError, AgentSchedulerManager` works.
- [ ] `packages/ai-parrot/tests/test_scheduler_report_decorators.py` passes unchanged (job ids `auto_<bot>_<method>`).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_resolvers.py -q`
- `pytest packages/ai-parrot/tests/test_scheduler_report_decorators.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_resolvers.py
async def test_agent_resolver_order(): ...                  # registry → get_bots() → registry.get_instance(); _bots never read
async def test_agent_resolver_prompt_only_uses_chat(): ...
async def test_crew_resolver_awaits_get_crew(): ...         # async def get_crew stub (regression for the un-awaited call)
async def test_crew_prompt_mapping(): ...                    # run_flow/run_loop/run_sequential/run_parallel
def test_agent_scheduler_manager_is_subclass(): ...
async def test_report_decorators_still_register(): ...
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
   `feat(scheduler-manager-base): TASK-4158 — AgentSchedulerManager as a SchedulerManager subclass with AgentResolver and CrewResolver`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4158 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4158 — AgentSchedulerManager as a SchedulerManager subclass with AgentResolver and CrewResolver`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
