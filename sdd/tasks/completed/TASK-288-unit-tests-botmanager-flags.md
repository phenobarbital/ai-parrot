# TASK-288: Unit Tests for BotManager initialization flags

**Feature**: BotManager Initialization Flags Decoupling (FEAT-042)
**Spec**: `sdd/specs/decoupling-db-bots-botmanager.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-282, TASK-283, TASK-284, TASK-285, TASK-286, TASK-287
**Assigned-to**: claude-session

---

## Context

> Validates all four flags independently gate the correct code paths without
> requiring real DB connections or Redis.
> Implements spec Section 6 — Test Specification (15 unit tests).

---

## Scope

Create `tests/test_botmanager_flags.py` with all 15 unit tests from the spec.
Use `unittest.mock` patches to avoid real connections.

**NOT in scope**: Integration tests that spin up a real aiohttp app.

---

## Files to Create

| File | Action |
|---|---|
| `tests/test_botmanager_flags.py` | CREATE |

---

## Test Cases

### Fixtures
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.manager.manager import BotManager

@pytest.fixture
def bot_manager_no_db():
    """BotManager with all expensive subsystems disabled."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
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

### Test cases from spec Section 6

```python
def test_defaults_match_config():
    """BotManager() instance attrs equal config constants."""
    from parrot.conf import ENABLE_DATABASE_BOTS, ENABLE_CREWS, ENABLE_REGISTRY_BOTS, ENABLE_SWAGGER
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager()
    assert bm.enable_database_bots == ENABLE_DATABASE_BOTS
    assert bm.enable_crews == ENABLE_CREWS
    assert bm.enable_registry_bots == ENABLE_REGISTRY_BOTS
    assert bm.enable_swagger_api == ENABLE_SWAGGER

@pytest.mark.asyncio
async def test_enable_registry_bots_false_skips_load_modules(mock_app):
    """registry.load_modules not called when flag is False."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(enable_registry_bots=False, enable_database_bots=False, enable_crews=False)
        await bm.load_bots(mock_app)
    mock_registry.load_modules.assert_not_called()

@pytest.mark.asyncio
async def test_enable_registry_bots_false_skips_discover_config(mock_app):
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(enable_registry_bots=False, enable_database_bots=False, enable_crews=False)
        await bm.load_bots(mock_app)
    mock_registry.discover_config_agents.assert_not_called()

@pytest.mark.asyncio
async def test_enable_registry_bots_false_skips_instantiate(mock_app):
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(enable_registry_bots=False, enable_database_bots=False, enable_crews=False)
        await bm.load_bots(mock_app)
    mock_registry.instantiate_startup_agents.assert_not_called()

@pytest.mark.asyncio
async def test_enable_registry_bots_true_calls_all(mock_app):
    """All three registry methods called when flag is True."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        mock_registry.load_modules = AsyncMock()
        mock_registry.discover_config_agents = MagicMock(return_value=0)
        mock_registry.instantiate_startup_agents = AsyncMock(return_value=[])
        mock_registry.agents_dir = MagicMock()
        mock_registry.agents_dir.__truediv__ = MagicMock(return_value=MagicMock(is_dir=MagicMock(return_value=False)))
        bm = BotManager(enable_registry_bots=True, enable_database_bots=False, enable_crews=False)
        await bm.load_bots(mock_app)
    mock_registry.load_modules.assert_called_once()
    mock_registry.discover_config_agents.assert_called_once()
    mock_registry.instantiate_startup_agents.assert_called_once()

@pytest.mark.asyncio
async def test_enable_database_bots_false_skips_db(mock_app):
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(enable_registry_bots=False, enable_database_bots=False, enable_crews=False)
        bm._load_database_bots = AsyncMock()
        await bm.load_bots(mock_app)
    bm._load_database_bots.assert_not_called()

@pytest.mark.asyncio
async def test_enable_database_bots_true_calls_db(mock_app):
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(enable_registry_bots=False, enable_database_bots=True, enable_crews=False)
        bm._load_database_bots = AsyncMock()
        await bm.load_bots(mock_app)
    bm._load_database_bots.assert_called_once_with(mock_app)

def test_enable_crews_false_no_crew_redis():
    with patch("parrot.manager.manager.CrewRedis") as mock_crew_redis, \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(enable_crews=False)
    assert bm.crew_redis is None
    mock_crew_redis.assert_not_called()

def test_enable_crews_true_creates_crew_redis():
    with patch("parrot.manager.manager.CrewRedis") as mock_crew_redis, \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(enable_crews=True)
    assert bm.crew_redis is mock_crew_redis.return_value
    mock_crew_redis.assert_called_once()

@pytest.mark.asyncio
async def test_enable_crews_false_skips_load_crews(mock_app):
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"), \
         patch("parrot.manager.manager.BotConfigStorage"):
        bm = BotManager(enable_crews=False, enable_registry_bots=False, enable_database_bots=False)
        bm.load_crews = AsyncMock()
        bm.load_bots = AsyncMock()
        await bm.on_startup(mock_app)
    bm.load_crews.assert_not_called()

@pytest.mark.asyncio
async def test_enable_crews_true_calls_load_crews(mock_app):
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"), \
         patch("parrot.manager.manager.BotConfigStorage"):
        bm = BotManager(enable_crews=True, enable_registry_bots=False, enable_database_bots=False)
        bm.load_crews = AsyncMock()
        bm.load_bots = AsyncMock()
        await bm.on_startup(mock_app)
    bm.load_crews.assert_called_once()

def test_explicit_override_ignores_config():
    """BotManager(enable_database_bots=True) overrides ENABLE_DATABASE_BOTS=False."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(enable_database_bots=True)
    assert bm.enable_database_bots is True

@pytest.mark.asyncio
async def test_all_flags_false_load_bots_noop(mock_app):
    """load_bots() with all flags False only logs and returns."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=False)
        bm._log_final_state = MagicMock()
        await bm.load_bots(mock_app)
    mock_registry.load_modules.assert_not_called()
    bm._log_final_state.assert_called_once()

def test_config_env_var_database_bots(monkeypatch):
    """Setting ENABLE_DATABASE_BOTS=True env var changes default."""
    monkeypatch.setenv("ENABLE_DATABASE_BOTS", "True")
    import importlib
    import parrot.conf as conf_module
    importlib.reload(conf_module)
    assert conf_module.ENABLE_DATABASE_BOTS is True
    # Restore
    importlib.reload(conf_module)

def test_config_env_var_registry_bots(monkeypatch):
    """Setting ENABLE_REGISTRY_BOTS=False env var changes default."""
    monkeypatch.setenv("ENABLE_REGISTRY_BOTS", "False")
    import importlib
    import parrot.conf as conf_module
    importlib.reload(conf_module)
    assert conf_module.ENABLE_REGISTRY_BOTS is False
    # Restore
    importlib.reload(conf_module)
```

---

## Acceptance Criteria

- [ ] All 15 tests from spec Section 6 are implemented
- [ ] `pytest tests/test_botmanager_flags.py -v` passes with 0 failures
- [ ] No real database or Redis connections are made during tests
- [ ] `ruff check tests/test_botmanager_flags.py` passes

---

## Agent Instructions

1. Read the spec at `sdd/specs/decoupling-db-bots-botmanager.spec.md` Section 6
2. Verify all TASK-282 through TASK-287 are `"done"` in the index
3. Create `tests/test_botmanager_flags.py` per the test cases above
4. Run `pytest tests/test_botmanager_flags.py -v` and fix any failures
5. Run `ruff check tests/test_botmanager_flags.py` and fix lint issues
6. Update `sdd/tasks/.index.json` → `"done"`
7. Move this file to `sdd/tasks/completed/TASK-288-unit-tests-botmanager-flags.md`
8. Fill in the Completion Note below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Created `tests/test_botmanager_flags.py` with all 15 unit tests. All 15 pass, ruff clean.
Key implementation notes:
- Module-level `import parrot.manager.manager` required so `patch("parrot.manager.manager.*")` can resolve the target by dotted path.
- The import chain of `parrot.manager.manager` required adding several missing stubs to `tests/conftest.py`: `asyncdb.AsyncPool`, `asyncdb.exceptions.UninitializedError` + more exceptions, `asyncdb.exceptions.exceptions` sub-module, `navigator.conf.exclude_list`, `navigator.types.WebApp`, `navigator.applications` and `navigator.applications.base.BaseApplication`.
- `on_startup` tests mock `IntegrationBotManager` to return an object with `startup = AsyncMock()` to avoid `TypeError: object MagicMock can't be used in 'await' expression`.
- Non-fatal RuntimeWarning about `_cleanup_expired_bots` coroutine not awaited (background task in `asyncio.create_task` mock) — acceptable for unit tests.
- Existing tests (67 tests across `test_setup_wizard.py` + `test_chatbot_handler.py`) remain unaffected.
