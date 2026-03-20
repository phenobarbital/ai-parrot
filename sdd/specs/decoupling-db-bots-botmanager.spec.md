# Feature Specification: BotManager Initialization Flags Decoupling

**Feature ID**: FEAT-042
**Date**: 2026-03-10
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement
`BotManager` currently hard-wires its startup behaviour to three module-level
constants imported from `parrot.conf` (`ENABLE_CREWS`, `ENABLE_DASHBOARDS`,
`ENABLE_SWAGGER`). Two additional expensive subsystems — database bot loading and
the full `AgentRegistry` machinery — are **always** executed at startup with no
mechanism to disable them.

This creates three concrete problems:

1. **Test friction**: Unit and integration tests must spin up database connections,
   Redis pools, and filesystem discovery passes even when they only need a single
   in-memory bot — slowing suites and introducing fragile environment dependencies.

2. **Lightweight deployments**: A deployment that only uses registry-discovered
   agents (no DB, no crews) still pays the cost of `_load_database_bots()` and
   its required `app['database']` key, crashing if the database is absent.

3. **No per-instance control**: All `BotManager` instances in the same process
   share the same global flags, making it impossible to have two managers with
   different subsystem profiles (e.g., one for production traffic, one for an
   admin-only API endpoint).

### Goals
- Add `enable_database_bots: bool` flag to `BotManager.__init__` (default
  `False` via new `ENABLE_DATABASE_BOTS` config var) that gates
  `_load_database_bots()` execution
- Add `enable_crews: bool` flag to `BotManager.__init__` (default: value of
  existing `ENABLE_CREWS` config var) that replaces the global constant usage
  for both `CrewRedis` init and `load_crews()` call
- Add `enable_registry_bots: bool` flag to `BotManager.__init__` (default
  `True` via new `ENABLE_REGISTRY_BOTS` config var) that gates the entire
  `AgentRegistry` machinery (`load_modules`, `discover_config_agents`,
  `load_agent_definitions`, `instantiate_startup_agents`)
- Add `ENABLE_DATABASE_BOTS` and `ENABLE_REGISTRY_BOTS` boolean config
  variables to `parrot/conf.py` following the existing `getboolean()` pattern
- Keep 100% backward compatibility: existing deployments with no code changes
  continue to behave identically (defaults match current behaviour except
  `enable_database_bots` which was previously always-on — see Migration below)
- add `enable_swagger_api` flag to `BotManager.__init__` (default value of False and `ENABLE_SWAGGER`)

### Non-Goals (explicitly out of scope)
- Adding per-instance control of `ENABLE_DASHBOARDS`
  (those affect route registration in `setup()` which is structurally different)
- Changing the `IntegrationBotManager` (Telegram/Teams/Slack/WhatsApp) startup
- Lazy-loading or dependency-injection refactor of the entire manager
- Any changes to `AgentRegistry` internal logic

---

## 2. Architectural Design

### Overview
Three `bool` parameters are added to `BotManager.__init__`. Each stores its
value as an instance attribute (`self.enable_database_bots`,
`self.enable_crews`, `self.enable_registry_bots`). The methods that depend on
each flag (`load_bots`, `_load_database_bots`, `on_startup`) check the
instance attribute rather than the module-level constant.

Two new module-level constants are added to `parrot/conf.py` following the
established `config.getboolean(key, fallback=...)` pattern.

### Component Diagram
```
parrot/conf.py
    ENABLE_DATABASE_BOTS = False   ← NEW
    ENABLE_REGISTRY_BOTS = True    ← NEW
    ENABLE_CREWS          = False  ← existing, unchanged

parrot/manager/manager.py
    BotManager.__init__(
        enable_database_bots = ENABLE_DATABASE_BOTS,   ← NEW param
        enable_crews         = ENABLE_CREWS,           ← NEW param (was global)
        enable_registry_bots = ENABLE_REGISTRY_BOTS,  ← NEW param
    )
    │
    ├── self.enable_database_bots → gates _load_database_bots()
    ├── self.enable_crews         → gates CrewRedis init + load_crews()
    └── self.enable_registry_bots → gates load_modules() + discover_config_agents()
                                       + load_agent_definitions()
                                       + instantiate_startup_agents()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/conf.py` | modified | Add `ENABLE_DATABASE_BOTS`, `ENABLE_REGISTRY_BOTS` |
| `BotManager.__init__` | modified | Add 3 params; store as instance attrs |
| `BotManager.load_bots` | modified | Guard registry steps behind `enable_registry_bots`; guard `_load_database_bots` behind `enable_database_bots` |
| `BotManager.on_startup` | modified | Use `self.enable_crews` instead of global `ENABLE_CREWS` |
| `BotManager.crew_redis` init (line 71) | modified | Use `self.enable_crews` instead of global |
| `app.py` (project root) | **no change** | `BotManager()` with no args still works |

### Data Models
No new data models. The three new instance attributes are plain `bool`.

### New Public Interface
```python
class BotManager:
    def __init__(
        self,
        enable_database_bots: bool = ENABLE_DATABASE_BOTS,
        enable_crews: bool = ENABLE_CREWS,
        enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
    ) -> None:
        ...
        self.enable_database_bots: bool = enable_database_bots
        self.enable_crews: bool = enable_crews
        self.enable_registry_bots: bool = enable_registry_bots
        # CrewRedis now keyed off instance attr (not global):
        self.crew_redis = CrewRedis() if self.enable_crews else None
```

---

## 3. Module Breakdown

### Module 1: Config variables (`parrot/conf.py`)
- **Path**: `parrot/conf.py`
- **Action**: MODIFY
- **Responsibility**: Add two new boolean config vars immediately after
  the existing `ENABLE_CREWS` line (line 44):
  ```python
  ENABLE_DATABASE_BOTS = config.getboolean("ENABLE_DATABASE_BOTS", fallback=False)
  ENABLE_REGISTRY_BOTS = config.getboolean("ENABLE_REGISTRY_BOTS", fallback=True)
  ```
- **Depends on**: Nothing

### Module 2: `BotManager.__init__` signature and attribute storage
- **Path**: `parrot/manager/manager.py`
- **Action**: MODIFY lines 44 (import) and 59–73 (`__init__`)
- **Responsibility**:
  - Add `ENABLE_DATABASE_BOTS`, `ENABLE_REGISTRY_BOTS` to the `from ..conf import`
    line (line 44)
  - Add three keyword parameters to `__init__` with defaults from the new
    (and existing) config constants
  - Store each as a `self.*` instance attribute
  - Replace global `ENABLE_CREWS` reference on line 71 with `self.enable_crews`
- **Depends on**: Module 1

### Module 3: `BotManager.load_bots` gating
- **Path**: `parrot/manager/manager.py`
- **Action**: MODIFY method `load_bots` (lines 194–223)
- **Responsibility**:
  - Wrap the entire `AgentRegistry` block (steps 1–3) in
    `if self.enable_registry_bots:`
  - Wrap step 4 (`_load_database_bots`) call in
    `if self.enable_database_bots:`
  - When `enable_registry_bots=False`, log a single info-level message
    and skip to step 5
  - When `enable_database_bots=False`, log a debug-level message and skip
- **Depends on**: Module 2

### Module 4: `BotManager.on_startup` gating
- **Path**: `parrot/manager/manager.py`
- **Action**: MODIFY method `on_startup` (lines 743–769)
- **Responsibility**:
  - Replace global `ENABLE_CREWS` reference on line 750 with
    `self.enable_crews`
  - No other changes to `on_startup` in this spec
- **Depends on**: Module 2

### Module 5: Unit Tests
- **Path**: `tests/test_botmanager_flags.py`
- **Responsibility**: Verify each flag independently gates the correct
  code paths, with no real DB / Redis connections
- **Depends on**: Modules 1–4

---

## 4. Detailed Change Specifications

### `parrot/conf.py` additions
Insert after line 44 (`ENABLE_CREWS = ...`):
```python
ENABLE_DATABASE_BOTS = config.getboolean("ENABLE_DATABASE_BOTS", fallback=False)
ENABLE_REGISTRY_BOTS = config.getboolean("ENABLE_REGISTRY_BOTS", fallback=True)
```

### `parrot/manager/manager.py` — import line (line 44)
```python
# Before:
from ..conf import ENABLE_SWAGGER, ENABLE_DASHBOARDS, ENABLE_CREWS

# After:
from ..conf import (
    ENABLE_SWAGGER,
    ENABLE_DASHBOARDS,
    ENABLE_CREWS,
    ENABLE_DATABASE_BOTS,
    ENABLE_REGISTRY_BOTS,
)
```

### `BotManager.__init__` — new signature
```python
def __init__(
    self,
    enable_database_bots: bool = ENABLE_DATABASE_BOTS,
    enable_crews: bool = ENABLE_CREWS,
    enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
) -> None:
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
    # Initialize Redis persistence for crews — keyed off instance attr
    self.crew_redis = CrewRedis() if self.enable_crews else None
    # Integration manager
    self._integration_manager: Optional[IntegrationBotManager] = None
```

### `BotManager.load_bots` — gated execution
```python
async def load_bots(self, app: web.Application) -> None:
    """Enhanced bot loading using the registry."""
    self.logger.info("Starting bot loading with global registry")

    if self.enable_registry_bots:
        # Step 1: Import modules to trigger decorator registration
        await self.registry.load_modules()

        # Step 2: Register config-based agents
        config_count = self.registry.discover_config_agents()
        self.logger.info(f"Registered {config_count} agents from config")

        # Step 2b: Load YAML agent definitions from agents/agents/
        definitions_dir = self.registry.agents_dir / "agents"
        if definitions_dir.is_dir():
            def_count = self.registry.load_agent_definitions(definitions_dir)
            self.logger.info(f"Loaded {def_count} agents from YAML definitions")

        # Step 3: Instantiate startup agents
        startup_results = await self.registry.instantiate_startup_agents(app)
        await self._process_startup_results(startup_results)
    else:
        self.logger.info(
            "AgentRegistry loading skipped (enable_registry_bots=False)"
        )

    # Step 4: Load database bots
    if self.enable_database_bots:
        await self._load_database_bots(app)
    else:
        self.logger.debug(
            "Database bot loading skipped (enable_database_bots=False)"
        )

    # Step 5: Report final state
    self._log_final_state()
```

### `BotManager.on_startup` — replace global with instance attr
```python
# Line 750 — Before:
if ENABLE_CREWS:
    await self.load_crews()

# After:
if self.enable_crews:
    await self.load_crews()
```

---

## 5. Migration / Backward Compatibility

| Flag | Old behaviour | New default | Impact |
|---|---|---|---|
| `enable_registry_bots` | Always on | `True` (via `ENABLE_REGISTRY_BOTS=True`) | No change |
| `enable_crews` | `ENABLE_CREWS` global | Same value from `ENABLE_CREWS` | No change |
| `enable_database_bots` | **Always on** | `False` (via `ENABLE_DATABASE_BOTS=False`) | **Breaking for DB bots** |

> **Important**: `enable_database_bots` defaults to `False`. Any deployment
> that relies on database-defined bots **must** either:
> - Set `ENABLE_DATABASE_BOTS=True` in their environment/config file, OR
> - Pass `BotManager(enable_database_bots=True)` explicitly in `app.py`
>
> The current project `app.py` should be updated to pass
> `enable_database_bots=True` if database bots are in use.

---

## 6. Test Specification

### Unit Tests
| Test | Description |
|---|---|
| `test_defaults_match_config` | `BotManager()` instance attrs equal config constants |
| `test_enable_registry_bots_false_skips_load_modules` | `registry.load_modules` not called when flag is False |
| `test_enable_registry_bots_false_skips_discover_config` | `registry.discover_config_agents` not called |
| `test_enable_registry_bots_false_skips_instantiate` | `registry.instantiate_startup_agents` not called |
| `test_enable_registry_bots_true_calls_all` | All three registry methods called when flag is True |
| `test_enable_database_bots_false_skips_db` | `_load_database_bots` not called when flag is False |
| `test_enable_database_bots_true_calls_db` | `_load_database_bots` called when flag is True |
| `test_enable_crews_false_no_crew_redis` | `self.crew_redis is None` when flag is False |
| `test_enable_crews_true_creates_crew_redis` | `self.crew_redis` is a `CrewRedis` instance when True |
| `test_enable_crews_false_skips_load_crews` | `load_crews` not called in `on_startup` when False |
| `test_enable_crews_true_calls_load_crews` | `load_crews` called in `on_startup` when True |
| `test_explicit_override_ignores_config` | `BotManager(enable_database_bots=True)` overrides `ENABLE_DATABASE_BOTS=False` |
| `test_all_flags_false_load_bots_noop` | `load_bots()` with all flags False only logs and returns |
| `test_config_env_var_database_bots` | Setting `ENABLE_DATABASE_BOTS=True` env var changes default |
| `test_config_env_var_registry_bots` | Setting `ENABLE_REGISTRY_BOTS=False` env var changes default |

### Test Data / Fixtures
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def bot_manager_no_db():
    """BotManager with all expensive subsystems disabled."""
    with patch("parrot.manager.manager.CrewRedis"):
        with patch("parrot.manager.manager.agent_registry"):
            return BotManager(
                enable_database_bots=False,
                enable_crews=False,
                enable_registry_bots=False,
            )

@pytest.fixture
def mock_app():
    """Minimal aiohttp Application mock."""
    app = MagicMock()
    app.__getitem__ = MagicMock(return_value=MagicMock())
    return app
```

---

## 7. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `ENABLE_DATABASE_BOTS` constant exists in `parrot/conf.py` with `fallback=False`
- [ ] `ENABLE_REGISTRY_BOTS` constant exists in `parrot/conf.py` with `fallback=True`
- [ ] Both are exported from `parrot/conf.py` (importable)
- [ ] `BotManager.__init__` accepts `enable_database_bots`, `enable_crews`,
      `enable_registry_bots` keyword parameters
- [ ] All three are stored as `self.*` instance attributes
- [ ] `self.crew_redis` is `None` when `enable_crews=False`
- [ ] `self.crew_redis` is a `CrewRedis` instance when `enable_crews=True`
- [ ] `load_bots()` skips all `AgentRegistry` steps when `enable_registry_bots=False`
- [ ] `load_bots()` skips `_load_database_bots()` when `enable_database_bots=False`
- [ ] `on_startup()` uses `self.enable_crews` (not global `ENABLE_CREWS`)
- [ ] `BotManager()` with no args behaves identically to current production
      (except `_load_database_bots` is now skipped by default)
- [ ] `BotManager(enable_database_bots=True)` calls `_load_database_bots`
- [ ] All 15 unit tests pass: `pytest tests/test_botmanager_flags.py -v`
- [ ] No ruff linting errors on modified files
- [ ] Google-style docstrings updated on `__init__` and `load_bots`

---

## 8. Implementation Notes & Constraints

### Ordering of changes
1. `parrot/conf.py` first (Module 1) — provides the constants
2. `BotManager.__init__` (Module 2) — uses the constants, stores attrs
3. `load_bots` (Module 3) — reads `self.*` attrs
4. `on_startup` (Module 4) — reads `self.enable_crews`
5. Tests (Module 5) — validates all four

### Import order in manager.py
The new constants must be added to the existing `from ..conf import` statement.
Keep alphabetical order within the import list.

### No global state mutation
The implementation must NOT modify the module-level constants `ENABLE_CREWS`,
`ENABLE_DATABASE_BOTS`, or `ENABLE_REGISTRY_BOTS` at runtime — they are
read-only defaults for the `__init__` parameters.

### Logging contract
- When `enable_registry_bots=False`: log at `INFO` level — "AgentRegistry
  loading skipped (enable_registry_bots=False)"
- When `enable_database_bots=False`: log at `DEBUG` level (common case, not
  worth INFO noise)
- When `enable_crews=False`: existing behaviour (no log change needed)

### Known Risks
- Projects currently relying on database bots MUST set `ENABLE_DATABASE_BOTS=True`
  — this is the one breaking change; it is intentional and documented.
- Tests that directly instantiate `BotManager()` without mocking `CrewRedis` and
  `agent_registry` will still trigger real connections if `ENABLE_CREWS=True` in
  the test environment. Use the provided fixture.

---

## 9. Open Questions

- [ ] Should `app.py` (project root) be updated in this spec to pass
      `enable_database_bots=True` explicitly, or left to the deployer via env var?
      — *Owner: Jesus Lara*: update app.py as well.
- [ ] Should `ENABLE_REGISTRY_BOTS=False` also skip `BotConfigStorage` init
      (line 748 of `on_startup`)? Currently out of scope but related.
      — *Owner: engineer*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-10 | Claude | Initial draft |
