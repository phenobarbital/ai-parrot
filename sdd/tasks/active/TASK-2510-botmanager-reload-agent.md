# TASK-2510: BotManager.reload_agent — hot swap of a registered agent

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2509
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Resolved in brainstorm: reload **swaps the shared
registered agent** — all consumers get new behavior immediately, no server
restart. No reload/restart primitive exists anywhere today (verified:
`importlib.reload` never called in `registry/`/`manager/`). This task adds
the manager-level primitive that the Studio reload endpoint (TASK-2512) and
toolkit assignment (TASK-2518) will call.

---

## Scope

- Add `async def reload_agent(self, name: str) -> ReloadResult` to
  `BotManager`:
  - Resolve the agent's origin: YAML definition (re-run
    `load_agent_definitions` on its directory), decorator/module agent
    (re-import via `AgentRegistry._import_module_from_path`), or DB agent
    (re-read `BotModel` and rebuild).
  - Rebuild FIRST; only after a successful rebuild evict
    `self._bots[name]` and swap the registry entry
    (`register(..., replace=True)` from TASK-2509).
  - Best-effort close of the previous instance (`cleanup()`/`close()` if
    present, wrapped in try/except with warning logs).
  - On ANY failure: leave the previous registration and instance serving;
    raise a typed error the handler maps to 422.
- Define a small `ReloadResult` Pydantic model (name, reloaded,
  previous_instance_closed, warnings).
- Unit tests: swap works; failure keeps old agent; old instance closed.

**NOT in scope**: the HTTP endpoint (TASK-2512); migrating conversation/
working memory between instances (documented as not migrated).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | add `reload_agent` + `ReloadResult` (or models module) |
| `packages/ai-parrot-server/tests/manager/test_reload_agent.py` | CREATE | swap / failure / cleanup tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import agent_registry           # registry/__init__.py:7-12
from parrot.registry.registry import AgentRegistry   # registry.py:252
# BotManager lives at packages/ai-parrot-server/src/parrot/manager/manager.py:109
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:  # :109
    # self.registry: AgentRegistry = agent_registry  (:150, global singleton)
    async def load_bots(self, app: web.Application) -> None: ...  # :336
    def remove_bot(self, name): ...  # :811 — del self._bots[name]; keeps class
    def setup(self, app: web.Application) -> web.Application: ...  # :1686
        # self.app['bot_manager'] = self  (:1702)

# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:
    def register(self, name, factory, *, replace=False, bot_config=None, **kw) -> None: ...  # :522
    def unregister(self, name: str) -> bool: ...   # NEW from TASK-2509
    async def get_instance(self, name, request=None, **kwargs) -> Optional[AbstractBot]: ...  # :635
    def load_agent_definitions(self, definitions_dir: Optional[Path] = None) -> int: ...  # :962
    def _import_module_from_path(self, path: Path, *, base_dir=None,
        package_hint: str = "parrot.dynamic_agents") -> ModuleType: ...  # :1131
    def get_metadata(self, name) -> Optional[BotMetadata]: ...  # :624
# BotMetadata (:43): fields name, factory, module_path, file_path, bot_config, _instance

# DB origin: packages/ai-parrot-server/src/parrot/handlers/models/bots.py:20
class BotModel(Model): ...  # Meta: driver 'pg', table navigator.ai_bots (:393-395)
```

### Does NOT Exist
- ~~`BotManager.reload_agent` / `restart_agent` / `reload_bots`~~ — THIS
  task creates the first one.
- ~~`importlib.reload` usage in registry/manager~~ — re-import goes through
  `_import_module_from_path` (fresh spec/exec), not `importlib.reload`.
- ~~Working-memory migration between instances~~ — explicitly NOT done;
  document in the docstring.
- ~~`AbstractBot.reload()`~~ — no such method on bots.

---

## Implementation Notes

### Pattern to Follow
Origin detection via `registry.get_metadata(name)`: `bot_config.origin`
("factory"/"repo"), `metadata.file_path` suffix (`.yaml` vs `.py`), and DB
fallback through `self._bots` / `BotModel` (see `_load_database_bots`,
manager.py:386). Swap sequence:

```python
new_meta_ok = rebuild(...)          # never touches live state
old = self._bots.pop(name, None)   # evict manager cache
self.registry.register(name, ..., replace=True)  # swaps registry entry
await _best_effort_close(old)
```

### Key Constraints
- Failure atomicity: an exception anywhere before the swap must leave
  everything untouched (assert in tests).
- `ReloadResult.warnings` collects non-fatal issues (e.g. close failure).
- async throughout; `self.logger` at each phase.

### References in Codebase
- `packages/ai-parrot-server/tests/test_botmanager_ephemeral_owner.py` —
  BotManager test setup pattern.
- `parrot/bots/factory/tools/finalize.py:51` — existing "re-scan directory"
  precedent (`load_agent_definitions(yaml_path.parent)`).

---

## Acceptance Criteria

- [ ] Reload of a YAML-definition agent picks up edited YAML.
- [ ] Reload failure (corrupt YAML / import error) leaves the old agent
      registered and serving; typed error raised.
- [ ] Old instance's `cleanup()`/`close()` invoked best-effort.
- [ ] `pytest packages/ai-parrot-server/tests/manager/test_reload_agent.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/manager/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/manager/test_reload_agent.py
import pytest

class TestReloadAgent:
    async def test_reload_swaps_instance(self, manager, tmp_agents_dir):
        """After editing the YAML, get_instance returns rebuilt agent."""

    async def test_reload_failure_keeps_old(self, manager, tmp_agents_dir):
        """Corrupt YAML → typed error; previous instance still served."""

    async def test_old_instance_closed(self, manager):
        """Previous instance close() called; warning collected if it raises."""

    async def test_reload_unknown_agent(self, manager):
        """Unknown name → typed not-found error (handler maps to 404)."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2509 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
