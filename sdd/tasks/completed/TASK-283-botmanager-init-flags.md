# TASK-283: BotManager.__init__ — Add 4 flags and store as instance attributes

**Feature**: BotManager Initialization Flags Decoupling (FEAT-042)
**Spec**: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-282
**Assigned-to**: claude-session

---

## Context

> Adds four keyword parameters to `BotManager.__init__`, stores them as
> instance attributes, and replaces the global `ENABLE_CREWS` reference in the
> `CrewRedis` init line with the new instance attribute. Also adds
> `enable_swagger_api` per the user's requirement (spec line 51).
> Implements spec Section 3 Module 2, Section 4 "__init__ signature".

---

## Scope

Modify `parrot/manager/manager.py`:

1. Extend the `from ..conf import` statement to include `ENABLE_DATABASE_BOTS`
   and `ENABLE_REGISTRY_BOTS`.
2. Add four keyword parameters to `BotManager.__init__`:
   - `enable_database_bots: bool = ENABLE_DATABASE_BOTS`
   - `enable_crews: bool = ENABLE_CREWS`
   - `enable_registry_bots: bool = ENABLE_REGISTRY_BOTS`
   - `enable_swagger_api: bool = ENABLE_SWAGGER`
3. Store each as a `self.*` instance attribute.
4. Replace `CrewRedis() if ENABLE_CREWS else None` with
   `CrewRedis() if self.enable_crews else None`.
5. Update the docstring on `__init__` (Google-style) to document the four
   new parameters.

**NOT in scope**: Changes to `load_bots`, `on_startup`, or `setup()`.

---

## Files to Modify

| File | Action |
|---|---|
| `parrot/manager/manager.py` | MODIFY |

---

## Change Specification

### Import line (currently line 44)
```python
# Before:
from ..conf import ENABLE_SWAGGER, ENABLE_DASHBOARDS, ENABLE_CREWS

# After (alphabetical order):
from ..conf import (
    ENABLE_CREWS,
    ENABLE_DATABASE_BOTS,
    ENABLE_DASHBOARDS,
    ENABLE_REGISTRY_BOTS,
    ENABLE_SWAGGER,
)
```

### `__init__` signature
```python
def __init__(
    self,
    enable_database_bots: bool = ENABLE_DATABASE_BOTS,
    enable_crews: bool = ENABLE_CREWS,
    enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
    enable_swagger_api: bool = ENABLE_SWAGGER,
) -> None:
    """Initialize BotManager.

    Args:
        enable_database_bots: When True, load bots from the database via
            ``_load_database_bots()``. Defaults to ``ENABLE_DATABASE_BOTS``
            (False unless overridden in config/env).
        enable_crews: When True, initialize ``CrewRedis`` and call
            ``load_crews()`` during startup. Defaults to ``ENABLE_CREWS``.
        enable_registry_bots: When True, run the full ``AgentRegistry``
            pipeline (load_modules, discover_config_agents,
            load_agent_definitions, instantiate_startup_agents). Defaults
            to ``ENABLE_REGISTRY_BOTS`` (True).
        enable_swagger_api: When True, register the OpenAPI/Swagger routes
            via ``setup_swagger()``. Defaults to ``ENABLE_SWAGGER``.
    """
    self.app = None
    self._bots: Dict[str, AbstractBot] = {}
    self._botdef: Dict[str, Type] = {}
    self._bot_expiration: Dict[str, float] = {}
    self._cleanup_task: Optional[asyncio.Task] = None
    self.logger = logging.getLogger(name='Parrot.Manager')
    self.registry: AgentRegistry = agent_registry
    self._crews: Dict[str, Tuple[AgentCrew, CrewDefinition]] = {}
    # Store flags as instance attributes
    self.enable_database_bots: bool = enable_database_bots
    self.enable_crews: bool = enable_crews
    self.enable_registry_bots: bool = enable_registry_bots
    self.enable_swagger_api: bool = enable_swagger_api
    # Initialize Redis persistence for crews — keyed off instance attr
    self.crew_redis = CrewRedis() if self.enable_crews else None
    # Integration manager
    self._integration_manager: Optional[IntegrationBotManager] = None
```

---

## Acceptance Criteria

- [ ] `BotManager.__init__` accepts all four keyword parameters
- [ ] Each is stored as `self.enable_*` instance attribute
- [ ] `self.crew_redis` is `None` when `enable_crews=False`
- [ ] `self.crew_redis` is a `CrewRedis` instance when `enable_crews=True`
- [ ] No global `ENABLE_CREWS` reference remains in `__init__`
- [ ] Import line lists all 5 constants alphabetically
- [ ] `ruff check parrot/manager/manager.py` passes

---

## Agent Instructions

1. Read `parrot/manager/manager.py` (lines 1–80)
2. Update the `from ..conf import` line
3. Replace `__init__` per the change spec above
4. Run `ruff check parrot/manager/manager.py` and fix issues
5. Update `sdd/tasks/.index.json` → `"done"`
6. Move this file to `sdd/tasks/completed/TASK-283-botmanager-init-flags.md`
7. Fill in the Completion Note below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Updated `from ..conf import` to alphabetically list all 5 constants (ENABLE_CREWS, ENABLE_DATABASE_BOTS, ENABLE_DASHBOARDS, ENABLE_REGISTRY_BOTS, ENABLE_SWAGGER). Added 4 keyword params to `__init__` with defaults from config constants. Stored each as `self.*` instance attribute. Replaced global `ENABLE_CREWS` with `self.enable_crews` in the `CrewRedis` init line. Added Google-style docstring. Two pre-existing ruff F401 warnings at line 1171 (unused `List`, `Any` inside a nested function) are out of scope.
