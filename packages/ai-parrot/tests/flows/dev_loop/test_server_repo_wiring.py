"""Tests: Demo server repo wiring (FEAT-253 TASK-004).

Verifies that ``_on_startup`` builds a ``GitToolkit``, calls
``parse_repo_specs(conf.DEV_LOOP_REPOS)``, and passes both as
``git_toolkit=`` and ``repos=`` to ``build_dev_loop_flow``.

Uses monkeypatching to replace ``build_dev_loop_flow`` with a capture
stub and drives ``_on_startup`` with a fake aiohttp app dict — no real
Redis / aiohttp app is started.

The ``examples/dev_loop/server.py`` module is loaded via
``importlib.util.spec_from_file_location`` so it doesn't need the
``examples`` directory to be a Python package.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.flows.dev_loop.models import RepoSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_server_module():
    """Load examples/dev_loop/server.py as a Python module."""
    server_path = (
        Path(__file__).parents[5] / "examples" / "dev_loop" / "server.py"
    )
    if not server_path.exists():
        pytest.skip(f"server.py not found at {server_path}")
    module_name = "_dev_loop_server_under_test"
    # Force reload to pick up any monkeypatching
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeApp(dict):
    """Minimal stand-in for ``aiohttp.web.Application``."""


def _make_fake_redis() -> MagicMock:
    redis = MagicMock()
    redis.aclose = AsyncMock()
    return redis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_builds_flow_with_repos(monkeypatch) -> None:
    """With DEV_LOOP_REPOS set, _on_startup passes non-empty repos + git_toolkit."""
    captured: dict[str, Any] = {}

    def fake_build_flow(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(conf, "DEV_LOOP_REPOS", ["phenobarbital/ai-parrot"])

    server_mod = _load_server_module()

    monkeypatch.setattr(server_mod, "build_dev_loop_flow", fake_build_flow)
    monkeypatch.setattr(server_mod, "_build_log_toolkits", lambda: {})
    monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
    monkeypatch.setattr(
        server_mod.aioredis,
        "from_url",
        lambda url, **kw: _make_fake_redis(),
    )
    monkeypatch.setattr(
        server_mod,
        "ClaudeCodeDispatcher",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        server_mod,
        "DevLoopRunner",
        MagicMock(return_value=MagicMock(max_concurrent_runs=1)),
    )

    app = _FakeApp()
    app["redis_url"] = "redis://localhost:6379/0"
    await server_mod._on_startup(app)

    assert "git_toolkit" in captured, "git_toolkit not passed to build_dev_loop_flow"
    assert captured["git_toolkit"] is not None, "git_toolkit must not be None"
    assert "repos" in captured, "repos not passed to build_dev_loop_flow"
    assert len(captured["repos"]) > 0, "repos should be non-empty"
    assert isinstance(captured["repos"][0], RepoSpec)
    assert captured["repos"][0].alias == "ai-parrot"


@pytest.mark.asyncio
async def test_server_local_fallback_no_repos(monkeypatch) -> None:
    """With DEV_LOOP_REPOS unset, build_dev_loop_flow is called with repos=[] (local fallback)."""
    captured: dict[str, Any] = {}

    def fake_build_flow(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(conf, "DEV_LOOP_REPOS", [])

    server_mod = _load_server_module()

    monkeypatch.setattr(server_mod, "build_dev_loop_flow", fake_build_flow)
    monkeypatch.setattr(server_mod, "_build_log_toolkits", lambda: {})
    monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
    monkeypatch.setattr(
        server_mod.aioredis,
        "from_url",
        lambda url, **kw: _make_fake_redis(),
    )
    monkeypatch.setattr(
        server_mod,
        "ClaudeCodeDispatcher",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        server_mod,
        "DevLoopRunner",
        MagicMock(return_value=MagicMock(max_concurrent_runs=1)),
    )

    app = _FakeApp()
    app["redis_url"] = "redis://localhost:6379/0"
    await server_mod._on_startup(app)

    assert "repos" in captured, "repos not passed to build_dev_loop_flow"
    assert captured["repos"] == [], (
        f"Expected empty repos for local fallback, got {captured['repos']!r}"
    )
    assert "git_toolkit" in captured, (
        "git_toolkit should still be passed even when repos=[]"
    )


@pytest.mark.asyncio
async def test_server_grok_agent_startup(monkeypatch) -> None:
    """With DEV_LOOP_DEVELOPMENT_AGENT=grok, _on_startup builds GrokCodeDispatcher."""
    captured: dict[str, Any] = {}

    def fake_build_flow(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(conf, "DEV_LOOP_REPOS", [])

    class _MockConfig:
        def get(self, name: str, fallback: Any = None) -> Any:
            if name == "DEV_LOOP_DEVELOPMENT_AGENT":
                return "grok"
            if name == "DEV_LOOP_GROK_MODEL":
                return "grok-build-0.1"
            return fallback

        def getint(self, name: str, fallback: Any = None) -> Any:
            return fallback

    monkeypatch.setattr(conf, "config", _MockConfig())

    server_mod = _load_server_module()

    monkeypatch.setattr(server_mod, "build_dev_loop_flow", fake_build_flow)
    monkeypatch.setattr(server_mod, "_build_log_toolkits", lambda: {})
    monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
    monkeypatch.setattr(
        server_mod.aioredis,
        "from_url",
        lambda url, **kw: _make_fake_redis(),
    )
    monkeypatch.setattr(
        server_mod,
        "ClaudeCodeDispatcher",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        server_mod,
        "GrokCodeDispatcher",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        server_mod,
        "DevLoopRunner",
        MagicMock(return_value=MagicMock(max_concurrent_runs=1)),
    )

    app = _FakeApp()
    app["redis_url"] = "redis://localhost:6379/0"
    await server_mod._on_startup(app)

    assert "development_dispatcher" in captured
    assert "development_profile" in captured
    assert captured["development_profile"].model == "grok-build-0.1"


@pytest.mark.asyncio
async def test_server_zai_agent_startup(monkeypatch) -> None:
    """With DEV_LOOP_DEVELOPMENT_AGENT=zai, _on_startup builds ZaiCodeDispatcher."""
    captured: dict[str, Any] = {}

    def fake_build_flow(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(conf, "DEV_LOOP_REPOS", [])
    monkeypatch.setenv("ZAI_API_KEY", "test-key")

    class _MockConfig:
        def get(self, name: str, fallback: Any = None) -> Any:
            if name == "DEV_LOOP_DEVELOPMENT_AGENT":
                return "zai"
            if name == "DEV_LOOP_ZAI_MODEL":
                return "glm-5.2"
            if name == "DEV_LOOP_ZAI_REASONING_EFFORT":
                return "max"
            return fallback

        def getint(self, name: str, fallback: Any = None) -> Any:
            return fallback

        def getboolean(self, name: str, fallback: Any = None) -> Any:
            if name == "DEV_LOOP_ZAI_ENABLE_THINKING":
                return True
            return fallback

    monkeypatch.setattr(conf, "config", _MockConfig())

    server_mod = _load_server_module()

    monkeypatch.setattr(server_mod, "build_dev_loop_flow", fake_build_flow)
    monkeypatch.setattr(server_mod, "_build_log_toolkits", lambda: {})
    monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
    monkeypatch.setattr(
        server_mod.aioredis,
        "from_url",
        lambda url, **kw: _make_fake_redis(),
    )
    monkeypatch.setattr(
        server_mod,
        "ClaudeCodeDispatcher",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        server_mod,
        "DevLoopRunner",
        MagicMock(return_value=MagicMock(max_concurrent_runs=1)),
    )

    app = _FakeApp()
    app["redis_url"] = "redis://localhost:6379/0"
    await server_mod._on_startup(app)

    assert "development_dispatcher" in captured
    assert "development_profile" in captured
    assert isinstance(captured["development_dispatcher"], server_mod.ZaiCodeDispatcher)
    assert isinstance(captured["development_profile"], server_mod.ZaiCodeDispatchProfile)
    assert captured["development_profile"].model == "glm-5.2"
    assert captured["development_profile"].enable_thinking is True
    assert captured["development_profile"].reasoning_effort == "max"


@pytest.mark.asyncio
async def test_server_moonshot_agent_startup(monkeypatch) -> None:
    """With DEV_LOOP_DEVELOPMENT_AGENT=moonshot, _on_startup builds MoonshotCodeDispatcher."""
    captured: dict[str, Any] = {}

    def fake_build_flow(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(conf, "DEV_LOOP_REPOS", [])

    class _MockConfig:
        def get(self, name: str, fallback: Any = None) -> Any:
            if name == "DEV_LOOP_DEVELOPMENT_AGENT":
                return "moonshot"
            if name == "DEV_LOOP_MOONSHOT_MODEL":
                return "kimi-k3"
            if name == "DEV_LOOP_MOONSHOT_REASONING_EFFORT":
                return "max"
            return fallback

        def getint(self, name: str, fallback: Any = None) -> Any:
            return fallback

        def getboolean(self, name: str, fallback: Any = None) -> Any:
            return fallback

    monkeypatch.setattr(conf, "config", _MockConfig())

    server_mod = _load_server_module()

    monkeypatch.setattr(server_mod, "build_dev_loop_flow", fake_build_flow)
    monkeypatch.setattr(server_mod, "_build_log_toolkits", lambda: {})
    monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
    monkeypatch.setattr(
        server_mod.aioredis,
        "from_url",
        lambda url, **kw: _make_fake_redis(),
    )
    monkeypatch.setattr(
        server_mod,
        "ClaudeCodeDispatcher",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        server_mod,
        "DevLoopRunner",
        MagicMock(return_value=MagicMock(max_concurrent_runs=1)),
    )

    app = _FakeApp()
    app["redis_url"] = "redis://localhost:6379/0"
    await server_mod._on_startup(app)

    assert "development_dispatcher" in captured
    assert "development_profile" in captured
    assert isinstance(
        captured["development_dispatcher"], server_mod.MoonshotCodeDispatcher
    )
    assert isinstance(
        captured["development_profile"], server_mod.MoonshotCodeDispatchProfile
    )
    assert captured["development_profile"].model == "kimi-k3"
    assert captured["development_profile"].llm == "moonshot:kimi-k3"
    assert captured["development_profile"].reasoning_effort == "max"


@pytest.mark.asyncio
async def test_server_invalid_agent_lists_zai(monkeypatch) -> None:
    """An unknown DEV_LOOP_DEVELOPMENT_AGENT raises RuntimeError mentioning 'zai'."""
    monkeypatch.setattr(conf, "DEV_LOOP_REPOS", [])

    class _MockConfig:
        def get(self, name: str, fallback: Any = None) -> Any:
            if name == "DEV_LOOP_DEVELOPMENT_AGENT":
                return "not-a-real-agent"
            return fallback

        def getint(self, name: str, fallback: Any = None) -> Any:
            return fallback

        def getboolean(self, name: str, fallback: Any = None) -> Any:
            return fallback

    monkeypatch.setattr(conf, "config", _MockConfig())

    server_mod = _load_server_module()

    monkeypatch.setattr(server_mod, "_build_log_toolkits", lambda: {})
    monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
    monkeypatch.setattr(
        server_mod.aioredis,
        "from_url",
        lambda url, **kw: _make_fake_redis(),
    )
    monkeypatch.setattr(
        server_mod,
        "ClaudeCodeDispatcher",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        server_mod,
        "DevLoopRunner",
        MagicMock(return_value=MagicMock(max_concurrent_runs=1)),
    )

    app = _FakeApp()
    app["redis_url"] = "redis://localhost:6379/0"
    with pytest.raises(RuntimeError, match="zai"):
        await server_mod._on_startup(app)

