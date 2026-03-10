"""Unit tests for BotManager initialization flags (FEAT-042).

Tests verify that each flag independently gates the correct code paths
without requiring real DB, Redis, or network connections.
"""
from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import the manager module so patch() can resolve it by dotted path.
import parrot.manager.manager  # noqa: F401
from parrot.manager.manager import BotManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app():
    """Minimal aiohttp Application mock."""
    app = MagicMock()
    app.__getitem__ = MagicMock(return_value=MagicMock())
    app.__setitem__ = MagicMock()
    return app


def _make_manager(**kwargs):
    """Instantiate BotManager with CrewRedis and agent_registry patched out."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
        return BotManager(**kwargs)


# ---------------------------------------------------------------------------
# 1. Default values match config constants
# ---------------------------------------------------------------------------


def test_defaults_match_config():
    """BotManager() instance attrs equal config constants."""
    from parrot.conf import (
        ENABLE_CREWS,
        ENABLE_DATABASE_BOTS,
        ENABLE_REGISTRY_BOTS,
        ENABLE_SWAGGER,
    )
    bm = _make_manager()
    assert bm.enable_database_bots == ENABLE_DATABASE_BOTS
    assert bm.enable_crews == ENABLE_CREWS
    assert bm.enable_registry_bots == ENABLE_REGISTRY_BOTS
    assert bm.enable_swagger_api == ENABLE_SWAGGER


# ---------------------------------------------------------------------------
# 2. Registry gating — enable_registry_bots=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enable_registry_bots_false_skips_load_modules(mock_app):
    """registry.load_modules not called when flag is False."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(
            enable_registry_bots=False,
            enable_database_bots=False,
            enable_crews=False,
        )
        await bm.load_bots(mock_app)
    mock_registry.load_modules.assert_not_called()


@pytest.mark.asyncio
async def test_enable_registry_bots_false_skips_discover_config(mock_app):
    """registry.discover_config_agents not called when flag is False."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(
            enable_registry_bots=False,
            enable_database_bots=False,
            enable_crews=False,
        )
        await bm.load_bots(mock_app)
    mock_registry.discover_config_agents.assert_not_called()


@pytest.mark.asyncio
async def test_enable_registry_bots_false_skips_instantiate(mock_app):
    """registry.instantiate_startup_agents not called when flag is False."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(
            enable_registry_bots=False,
            enable_database_bots=False,
            enable_crews=False,
        )
        await bm.load_bots(mock_app)
    mock_registry.instantiate_startup_agents.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Registry gating — enable_registry_bots=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enable_registry_bots_true_calls_all(mock_app):
    """All three registry methods called when flag is True."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        mock_registry.load_modules = AsyncMock()
        mock_registry.discover_config_agents = MagicMock(return_value=0)
        mock_registry.instantiate_startup_agents = AsyncMock(return_value={})
        agents_dir_mock = MagicMock()
        agents_dir_mock.__truediv__ = MagicMock(
            return_value=MagicMock(is_dir=MagicMock(return_value=False))
        )
        mock_registry.agents_dir = agents_dir_mock

        bm = BotManager(
            enable_registry_bots=True,
            enable_database_bots=False,
            enable_crews=False,
        )
        await bm.load_bots(mock_app)

    mock_registry.load_modules.assert_called_once()
    mock_registry.discover_config_agents.assert_called_once()
    mock_registry.instantiate_startup_agents.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Database gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enable_database_bots_false_skips_db(mock_app):
    """_load_database_bots not called when flag is False."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(
            enable_registry_bots=False,
            enable_database_bots=False,
            enable_crews=False,
        )
        bm._load_database_bots = AsyncMock()
        await bm.load_bots(mock_app)
    bm._load_database_bots.assert_not_called()


@pytest.mark.asyncio
async def test_enable_database_bots_true_calls_db(mock_app):
    """_load_database_bots called when flag is True."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(
            enable_registry_bots=False,
            enable_database_bots=True,
            enable_crews=False,
        )
        bm._load_database_bots = AsyncMock()
        await bm.load_bots(mock_app)
    bm._load_database_bots.assert_called_once_with(mock_app)


# ---------------------------------------------------------------------------
# 5. Crew Redis initialisation
# ---------------------------------------------------------------------------


def test_enable_crews_false_no_crew_redis():
    """crew_redis is None when enable_crews=False."""
    with patch("parrot.manager.manager.CrewRedis") as mock_crew_redis, \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(enable_crews=False)
    assert bm.crew_redis is None
    mock_crew_redis.assert_not_called()


def test_enable_crews_true_creates_crew_redis():
    """crew_redis is a CrewRedis instance when enable_crews=True."""
    with patch("parrot.manager.manager.CrewRedis") as mock_crew_redis, \
         patch("parrot.manager.manager.agent_registry"):
        bm = BotManager(enable_crews=True)
    assert bm.crew_redis is mock_crew_redis.return_value
    mock_crew_redis.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Crew gating in on_startup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enable_crews_false_skips_load_crews(mock_app):
    """load_crews not called in on_startup when enable_crews=False."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"), \
         patch("parrot.manager.manager.BotConfigStorage"), \
         patch("parrot.manager.manager.ChatStorage"), \
         patch("parrot.manager.manager.IntegrationBotManager"), \
         patch("asyncio.create_task"):
        bm = BotManager(
            enable_crews=False,
            enable_registry_bots=False,
            enable_database_bots=False,
        )
        bm.load_crews = AsyncMock()
        bm.load_bots = AsyncMock()
        await bm.on_startup(mock_app)
    bm.load_crews.assert_not_called()


@pytest.mark.asyncio
async def test_enable_crews_true_calls_load_crews(mock_app):
    """load_crews called in on_startup when enable_crews=True."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry"), \
         patch("parrot.manager.manager.BotConfigStorage"), \
         patch("parrot.manager.manager.ChatStorage"), \
         patch("parrot.manager.manager.IntegrationBotManager"), \
         patch("asyncio.create_task"):
        bm = BotManager(
            enable_crews=True,
            enable_registry_bots=False,
            enable_database_bots=False,
        )
        bm.load_crews = AsyncMock()
        bm.load_bots = AsyncMock()
        await bm.on_startup(mock_app)
    bm.load_crews.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Explicit override ignores config default
# ---------------------------------------------------------------------------


def test_explicit_override_ignores_config():
    """BotManager(enable_database_bots=True) overrides ENABLE_DATABASE_BOTS=False."""
    bm = _make_manager(enable_database_bots=True)
    assert bm.enable_database_bots is True


# ---------------------------------------------------------------------------
# 8. All flags False — load_bots is a no-op (only logs + final state)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_flags_false_load_bots_noop(mock_app):
    """load_bots() with all flags False only logs and calls _log_final_state."""
    with patch("parrot.manager.manager.CrewRedis"), \
         patch("parrot.manager.manager.agent_registry") as mock_registry:
        bm = BotManager(
            enable_database_bots=False,
            enable_crews=False,
            enable_registry_bots=False,
        )
        bm._log_final_state = MagicMock()
        await bm.load_bots(mock_app)
    mock_registry.load_modules.assert_not_called()
    bm._log_final_state.assert_called_once()


# ---------------------------------------------------------------------------
# 9. Config env var overrides
# ---------------------------------------------------------------------------


def test_config_env_var_database_bots(monkeypatch):
    """Setting ENABLE_DATABASE_BOTS=True env var changes the config default."""
    monkeypatch.setenv("ENABLE_DATABASE_BOTS", "True")
    import parrot.conf as conf_module
    importlib.reload(conf_module)
    try:
        assert conf_module.ENABLE_DATABASE_BOTS is True
    finally:
        # Always restore to avoid polluting other tests
        monkeypatch.delenv("ENABLE_DATABASE_BOTS", raising=False)
        importlib.reload(conf_module)


def test_config_env_var_registry_bots(monkeypatch):
    """Setting ENABLE_REGISTRY_BOTS=False env var changes the config default."""
    monkeypatch.setenv("ENABLE_REGISTRY_BOTS", "False")
    import parrot.conf as conf_module
    importlib.reload(conf_module)
    try:
        assert conf_module.ENABLE_REGISTRY_BOTS is False
    finally:
        monkeypatch.delenv("ENABLE_REGISTRY_BOTS", raising=False)
        importlib.reload(conf_module)
