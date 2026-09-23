"""Tests for deferred application of agent-level tooling specifications."""

import logging
from unittest.mock import AsyncMock

import pytest

import parrot.interfaces.tools as tools_module
import parrot.tools.spec as spec_module
from parrot.interfaces.tools import ToolInterface
from parrot.tools.manager import ToolManager, get_toolkit_owner
from parrot.tools.spec import ToolkitSpec
from parrot.tools.toolkit import AbstractToolkit


class _EchoKit(AbstractToolkit):
    """Minimal toolkit used to verify deferred construction."""

    def __init__(self, prefix: str = "", token: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.prefix = prefix
        self.token = token

    async def echo(self, text: str) -> str:
        """Echo text with the configured prefix."""
        return self.prefix + text


class _DatasetManager(AbstractToolkit):
    """Minimal dataset manager used to verify replay and reuse semantics."""

    def __init__(self, setting: str = "", **kwargs):
        super().__init__(**kwargs)
        self.setting = setting
        self.replayed: list[object] = []

    async def replay_datasources(self, datasources: list[object]) -> list[str]:
        """Record datasource descriptors for assertions."""
        self.replayed.extend(datasources)
        return []

    async def dataset_tool(self) -> str:
        """Return a marker tool value."""
        return "dataset"


class _Bot(ToolInterface):
    """Small ToolInterface host backed by a real ToolManager."""

    def __init__(self):
        self.logger = logging.getLogger("test_apply_tooling_specs")
        self.tool_manager = ToolManager()


@pytest.fixture
def bot(monkeypatch):
    """Build a bot whose spec resolver returns the local test toolkit."""
    monkeypatch.setattr(
        _Bot,
        "_resolve_spec_class",
        staticmethod(lambda slug: _EchoKit if slug == "echo" else _DatasetManager if slug == "dataset_manager" else None),
    )
    return _Bot()


@pytest.mark.asyncio
async def test_registers_with_hydrated_secret(bot, monkeypatch):
    """Deferred application hydrates accepted params and drops unknown params."""
    monkeypatch.setattr(spec_module, "retrieve_vault_credential", AsyncMock(return_value={"token": "secret"}))
    bot._initialize_tools(
        [ToolkitSpec(slug="echo", params={"prefix": ">", "bogus": 1}, secret_refs={"token": "v"}, vault_owner="1")]
    )

    assert bot.tool_manager.tool_count() == 0
    names = await bot.apply_tooling_specs()

    assert names
    assert bot._tooling_revision
    tool = bot.tool_manager.get_tool(names[0])
    owner = get_toolkit_owner(tool)
    assert owner.prefix == ">"
    assert owner.token == "secret"
    assert "bogus" not in owner._init_kwargs


@pytest.mark.asyncio
async def test_idempotent(bot):
    """A second application does not register colliding tools."""
    bot._initialize_tools([ToolkitSpec(slug="echo")])

    assert await bot.apply_tooling_specs()
    assert await bot.apply_tooling_specs() == []


@pytest.mark.asyncio
async def test_missing_vault_skips_one_spec_and_applies_others(bot, monkeypatch):
    """A missing vault credential warns and does not stop following specifications."""
    monkeypatch.setattr(spec_module, "retrieve_vault_credential", AsyncMock(side_effect=KeyError("missing")))
    bot._initialize_tools(
        [
            ToolkitSpec(slug="echo", secret_refs={"token": "v"}, vault_owner="1"),
            ToolkitSpec(slug="echo"),
        ]
    )

    names = await bot.apply_tooling_specs()

    assert names


@pytest.mark.asyncio
async def test_dataset_manager_reuses_existing_instance(bot, monkeypatch):
    """An existing dataset manager receives replayed datasources without re-registration."""
    monkeypatch.setattr(tools_module, "DatasetManager", _DatasetManager)
    existing = _DatasetManager()
    bot._dataset_manager = existing
    bot._initialize_tools([ToolkitSpec(slug="dataset_manager", params={"datasources": [{"name": "orders"}]})])

    assert await bot.apply_tooling_specs() == []
    assert bot._dataset_manager is existing
    assert existing.replayed == [{"name": "orders"}]
    assert bot.tool_manager.tool_count() == 0


@pytest.mark.asyncio
async def test_dataset_manager_registers_new_instance(bot, monkeypatch):
    """A new dataset manager is registered, retained, and receives datasource replay."""
    monkeypatch.setattr(tools_module, "DatasetManager", _DatasetManager)
    bot._initialize_tools(
        [ToolkitSpec(slug="dataset_manager", params={"setting": "configured", "datasources": [{"name": "orders"}]})]
    )

    names = await bot.apply_tooling_specs()

    assert names
    assert isinstance(bot._dataset_manager, _DatasetManager)
    assert bot._dataset_manager.setting == "configured"
    assert bot._dataset_manager.replayed == [{"name": "orders"}]
