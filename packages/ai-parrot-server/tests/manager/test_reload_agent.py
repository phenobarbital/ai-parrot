"""Tests for BotManager.reload_agent — hot swap of a registered agent.

FEAT-467 TASK-2510. Covers:
  - Reload of a YAML-definition agent picks up edited YAML (swap works).
  - Reload failure (corrupt YAML) leaves the old agent registered/serving.
  - Old instance's cleanup() is invoked best-effort; failures become warnings.
  - Unknown agent name -> AgentNotFoundError (handler maps to 404).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from parrot.manager.manager import (
    AgentNotFoundError,
    AgentReloadError,
    BotManager,
    ReloadResult,
)
from parrot.registry.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Fixture bot module — written fresh into tmp_path so AgentRegistry's
# create_agent_factory() can `importlib.import_module` it by name. The
# module's own source never changes between "v1"/"v2" — only the YAML
# `config.label` kwarg does, exercising a real config-driven reload.
# ---------------------------------------------------------------------------

_FIXTURE_MODULE_SOURCE = textwrap.dedent('''
    """Reload-agent test fixture bot (written per-test via tmp_path)."""
    from parrot.bots.abstract import AbstractBot


    class ReloadFixtureAgent(AbstractBot):
        """Minimal concrete AbstractBot for BotManager.reload_agent tests."""

        def __init__(self, name: str = "fixture", label: str = "v1", **kwargs):
            self._name = name
            self.label = label
            # AbstractBot already exposes `is_configured` as a read-only
            # property backed by `self._configured` — set THAT, not the
            # property itself.
            self._configured = False
            self.cleanup_calls = 0

        @property
        def name(self):
            return self._name

        async def ask(self, prompt: str, **kwargs):
            return f"{self.label}: {prompt}"

        async def ask_stream(self, prompt: str, **kwargs):
            yield f"{self.label}: {prompt}"

        async def conversation(self, prompt: str, **kwargs):
            return f"{self.label}: {prompt}"

        async def invoke(self, prompt: str, **kwargs):
            return f"{self.label}: {prompt}"

        async def configure(self, *args, **kwargs):
            self._configured = True

        async def cleanup(self):
            self.cleanup_calls += 1
    ''')

AGENT_NAME = "reload-fixture"


def _write_yaml(agents_dir: Path, *, label: str, valid: bool = True) -> Path:
    """(Re)write the single agent YAML definition used by these tests."""
    agent_dir = agents_dir / "agents" / "general"
    agent_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = agent_dir / f"{AGENT_NAME}.yaml"
    if valid:
        yaml_path.write_text(
            "agent:\n"
            f"  name: {AGENT_NAME}\n"
            "  class_name: ReloadFixtureAgent\n"
            "  module: reload_fixture_module\n"
            "  enabled: true\n"
            "  origin: repo\n"
            "  config:\n"
            f"    label: {label}\n"
        )
    else:
        # Deliberately malformed YAML (unterminated flow sequence).
        yaml_path.write_text("agent:\n  name: [unterminated\n")
    return yaml_path


@pytest.fixture
def tmp_agents_dir(tmp_path):
    """A temp AGENTS_DIR containing the fixture module + one YAML agent."""
    (tmp_path / "reload_fixture_module.py").write_text(_FIXTURE_MODULE_SOURCE)
    _write_yaml(tmp_path, label="v1")
    return tmp_path


@pytest.fixture
def manager(tmp_agents_dir):
    """BotManager wired to a real AgentRegistry over tmp_agents_dir.

    Uses ``BotManager.__new__`` (pattern: test_botmanager_ephemeral_owner.py)
    to skip ``__init__`` — no aiohttp app, Redis, or crew wiring needed for
    reload_agent's registry-origin path.
    """
    bm = BotManager.__new__(BotManager)
    bm.app = None
    bm._bots = {}
    bm._botdef = {}
    bm._bot_expiration = {}
    bm._cleaned_up = set()
    bm.logger = MagicMock()
    bm.registry = AgentRegistry(agents_dir=tmp_agents_dir)
    count = bm.registry.load_agent_definitions(tmp_agents_dir / "agents")
    assert count == 1, "fixture YAML must load exactly one agent"
    return bm


class TestReloadAgent:
    """BotManager.reload_agent — registry-origin (YAML) reload."""

    @pytest.mark.asyncio
    async def test_reload_swaps_instance(self, manager, tmp_agents_dir):
        """After editing the YAML, the swapped-in instance reflects it."""
        old_instance = await manager.registry.get_instance(AGENT_NAME)
        manager._bots[AGENT_NAME] = old_instance
        assert old_instance.label == "v1"

        _write_yaml(tmp_agents_dir, label="v2")

        result = await manager.reload_agent(AGENT_NAME)

        assert isinstance(result, ReloadResult)
        assert result.name == AGENT_NAME
        assert result.reloaded is True

        new_instance = manager._bots[AGENT_NAME]
        assert new_instance is not old_instance
        assert new_instance.label == "v2"
        assert manager._botdef[AGENT_NAME] is type(new_instance)

    @pytest.mark.asyncio
    async def test_reload_failure_keeps_old(self, manager, tmp_agents_dir):
        """Corrupt YAML -> AgentReloadError; previous instance still served."""
        old_instance = await manager.registry.get_instance(AGENT_NAME)
        manager._bots[AGENT_NAME] = old_instance
        old_metadata = manager.registry.get_metadata(AGENT_NAME)

        _write_yaml(tmp_agents_dir, label="irrelevant", valid=False)

        with pytest.raises(AgentReloadError):
            await manager.reload_agent(AGENT_NAME)

        # Previous registration + cached instance are untouched.
        assert manager._bots[AGENT_NAME] is old_instance
        assert manager.registry.get_metadata(AGENT_NAME) is old_metadata

    @pytest.mark.asyncio
    async def test_old_instance_closed(self, manager, tmp_agents_dir):
        """The previous instance's cleanup() is awaited on a successful swap."""
        old_instance = await manager.registry.get_instance(AGENT_NAME)
        manager._bots[AGENT_NAME] = old_instance

        _write_yaml(tmp_agents_dir, label="v2")
        result = await manager.reload_agent(AGENT_NAME)

        assert result.previous_instance_closed is True
        assert old_instance.cleanup_calls == 1
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_old_instance_close_failure_collects_warning(self, manager, tmp_agents_dir):
        """A raising cleanup() is swallowed (best-effort) and warned about."""
        old_instance = await manager.registry.get_instance(AGENT_NAME)
        manager._bots[AGENT_NAME] = old_instance

        async def _boom():
            raise RuntimeError("cleanup boom")

        old_instance.cleanup = _boom

        _write_yaml(tmp_agents_dir, label="v2")
        result = await manager.reload_agent(AGENT_NAME)

        assert result.reloaded is True
        assert result.previous_instance_closed is False
        assert result.warnings, "a close failure must be surfaced as a warning"

    @pytest.mark.asyncio
    async def test_reload_unknown_agent(self, manager):
        """Unknown name -> AgentNotFoundError (handler maps to 404)."""
        with pytest.raises(AgentNotFoundError):
            await manager.reload_agent("does-not-exist")

    @pytest.mark.asyncio
    async def test_reload_agent_without_reloadable_origin(self, manager):
        """An agent whose BotMetadata carries no on-disk source (file_path
        with neither a .yaml nor a .py suffix) can't be hot-reloaded —
        AgentReloadError, not a silent no-op."""
        from parrot.bots.abstract import AbstractBot

        class _NoOriginAgent(AbstractBot):
            def __init__(self, name: str = "no-origin", **kwargs):
                self._name = name

            @property
            def name(self):
                return self._name

            async def ask(self, prompt: str, **kwargs):
                return prompt

            async def ask_stream(self, prompt: str, **kwargs):
                yield prompt

            async def conversation(self, prompt: str, **kwargs):
                return prompt

            async def invoke(self, prompt: str, **kwargs):
                return prompt

            async def configure(self, *args, **kwargs):
                pass

        instance = _NoOriginAgent()
        manager.registry.register_instance("no-origin", instance)
        # register_instance() resolves file_path via inspect.getmodule() —
        # here that's this very test module (a real .py file), which would
        # exercise the module-reload branch instead of the one under test.
        # Force the genuinely-synthetic "no on-disk source" case directly.
        manager.registry.get_metadata("no-origin").file_path = Path("unknown")
        manager._bots["no-origin"] = instance

        with pytest.raises(AgentReloadError):
            await manager.reload_agent("no-origin")

        # Untouched on failure.
        assert manager._bots["no-origin"] is instance


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
