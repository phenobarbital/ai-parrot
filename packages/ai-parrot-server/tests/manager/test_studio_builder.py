"""FEAT-621 M7 builder (AC10, AC11, AC13, AC4). Asserts on the built instance, never on JSON."""
import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from parrot.bots.abstract import AbstractBot
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAgentRecord,
    StudioAgentSnapshot,
    StudioAssetRecord,
    StudioModelParams,
    StudioPartition,
    StudioToolingRecord,
    StudioToolingRefused,
)
from parrot.handlers.studio.storage.services._common import StudioToolingGate, studio_runtime_dir
from parrot.manager.manager import AgentReloadError
from parrot.manager.studio_builder import StudioAgentBuilder
from parrot.registry import agent_registry

NOW = datetime.now(timezone.utc)
ACME = StudioPartition("acme")
GLOBAL = StudioPartition.GLOBAL


@pytest.fixture
def configure(monkeypatch):
    """``AbstractBot.configure`` is replaced: these tests are about the constructor map, not LLM start-up."""
    mock = AsyncMock()
    monkeypatch.setattr(AbstractBot, "configure", mock)
    return mock


@pytest.fixture
def no_subprocess(monkeypatch):
    async def _refuse(*a, **k):
        raise AssertionError("a process was started")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _refuse)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "runtime"


def _builder(root):
    return StudioAgentBuilder(agent_registry, root, StudioToolingGate({}))


def _snapshot(*, tenant=None, name="a1", version=1, agent_id=None, assets=(), tooling=(), **definition):
    aid = agent_id or uuid.uuid4()
    rec = StudioAgentRecord(aid, tenant, name, "u1", "private", (), StudioAgentDefinition(**definition), "active",
                            version, NOW, NOW)
    arows = tuple(StudioAssetRecord(aid, k, n, c, "text/markdown", len(c), "x", None, NOW) for k, n, c in assets)
    trows = tuple(StudioToolingRecord(aid, k, s, p, cfg, {}, None, NOW) for k, s, p, cfg in tooling)
    return StudioAgentSnapshot(rec, arows, trows)


async def test_builder_constructor_settings(configure, root):
    snap = _snapshot(
        llm="openai:gpt-4o-mini", model_params=StudioModelParams(temperature=0.3, max_tokens=1000),
        system_prompt="Be concise.", description="Sales helper",
        assets=[("identity", "role.md", "You are the sales role.")],
        tooling=[("mcp", "docs", 0, {"url": "https://m.example/mcp"})],
    )
    bot, directory = await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert bot.name == "a1" and bot._llm_raw == "openai:gpt-4o-mini"
    assert bot._model_config == {"temperature": 0.3, "max_tokens": 1000}   # the canonical channel, not bare kwargs
    assert bot._llm_kwargs["temperature"] == 0.3 and bot._llm_kwargs["max_tokens"] == 1000   # not ModelConfig's 8192
    assert bot.role == "You are the sales role." and bot.description == "Sales helper"
    assert "Be concise." in bot.system_prompt_template
    assert [s.name for s in bot._pending_mcp_specs] == ["docs"]
    newer = _snapshot(agent_id=snap.record.agent_id, version=2, llm="openai:gpt-4o-mini",
                      model_params=StudioModelParams(temperature=0.7, max_tokens=1000))
    other, _ = await _builder(root).build(newer, web.Application(), part=GLOBAL)
    assert other._llm_kwargs["temperature"] == 0.7 and other._llm_kwargs["max_tokens"] == 1000
    unset, _ = await _builder(root).build(_snapshot(), web.Application(), part=GLOBAL)
    assert unset._llm_kwargs["max_tokens"] != 8192            # unset params fall to the class defaults
    assert directory == root / str(snap.record.agent_id) / "v1"


async def test_builder_never_uses_bot_config_model_or_config(configure, root, monkeypatch):
    seen = {}
    real = agent_registry.create_agent_factory

    def spy(cfg):
        seen["cfg"] = cfg
        return real(cfg)

    monkeypatch.setattr(agent_registry, "create_agent_factory", spy)
    snap = _snapshot(llm="openai:gpt-4o-mini", model_params=StudioModelParams(temperature=0.3), tools=["a_tool"])
    await _builder(root).build(snap, web.Application(), part=GLOBAL)
    cfg = seen["cfg"]
    assert cfg.model is None and cfg.config == {} and cfg.startup_config == {} and cfg.origin == "factory"
    assert cfg.name == "a1" and cfg.class_name == "BasicBot" and cfg.tools.tools == [{"name": "a_tool"}]


async def test_memory_key_is_agent_id(configure, root):
    snap = _snapshot(name="same-name")
    other = _snapshot(name="same-name")                       # delete + recreate: a new agent_id, same name
    bot, _ = await _builder(root).build(snap, web.Application(), part=GLOBAL)
    bot2, _ = await _builder(root).build(other, web.Application(), part=GLOBAL)
    assert bot.chatbot_id == str(snap.record.agent_id) and bot.memory_key_id == str(snap.record.agent_id)
    assert bot2.memory_key_id == str(other.record.agent_id) != bot.memory_key_id


async def test_stamps_and_policy_binding_before_configure(configure, root):
    seen = {}

    async def _configure(app):
        seen["subject"] = bot_box[0]._tooling_subject
        seen["applied"] = getattr(bot_box[0], "_tooling_applied", False)

    bot_box: list = []
    snap = _snapshot(tenant="acme", name="a1", version=4)
    real_factory = agent_registry.create_agent_factory

    def spy(cfg):
        factory = real_factory(cfg)

        async def wrapped(**kw):
            bot = await factory(**kw)
            bot_box.append(bot)
            bot.configure = _configure
            return bot

        return wrapped

    agent_registry.create_agent_factory, original = spy, agent_registry.create_agent_factory
    try:
        bot, _ = await _builder(root).build(snap, web.Application(), part=ACME)
    finally:
        agent_registry.create_agent_factory = original
    rec = snap.record
    assert (bot._studio_key, bot._studio_version, bot._studio_agent_id) == (rec.key, 4, rec.agent_id)
    assert bot._tooling_ref == f"studio-agent:{rec.agent_id}" == rec.tooling_ref
    subject = seen["subject"]
    assert (subject.tenant, subject.agent_id, subject.phase) == ("acme", rec.agent_id, "build")
    assert seen["applied"] is False and bot._tooling_owner == "u1"


async def test_confirmation_guard_installed_when_the_host_set_one(configure, root):
    guard = object()
    app = web.Application()
    app["studio_confirmation_guard"] = guard
    bot, _ = await _builder(root).build(_snapshot(), app, part=GLOBAL)
    assert bot.tool_manager._confirmation_guard is guard
    plain, _ = await _builder(root).build(_snapshot(), web.Application(), part=GLOBAL)
    assert plain.tool_manager._confirmation_guard is not guard


async def test_build_refused_by_policy(configure, root, monkeypatch, no_subprocess):
    factory_calls = []
    monkeypatch.setattr(agent_registry, "create_agent_factory", lambda cfg: factory_calls.append(cfg))
    stdio = ("mcp", "s", 0, {"transport": "stdio", "command": "/bin/sh"})
    snap = _snapshot(tenant="acme", tooling=[stdio], assets=[("kb", "k.md", "text")])
    with pytest.raises(StudioToolingRefused) as exc:
        await _builder(root).build(snap, web.Application(), part=ACME)
    assert exc.value.code == "tooling_not_permitted"
    assert factory_calls == [] and configure.await_count == 0 and not root.exists()


async def test_unresolvable_toolkit_is_skipped_not_fatal(configure, root):
    snap = _snapshot(tooling=[("toolkit", "no_such_toolkit_xyz", 0, {})])
    bot, _ = await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert [s.slug for s in bot._pending_toolkit_specs] == ["no_such_toolkit_xyz"]
    assert await bot.apply_tooling_specs() == []                 # skipped, no exception: the agent still serves


async def test_kb_and_skills_written_where_the_core_hooks_read_them(configure, root):
    snap = _snapshot(assets=[("kb", "k.md", "kb body"), ("kb", "sub/n.txt", "more"),
                             ("skills", "s1.md", "skill body"), ("identity", "role.md", "R")])
    bot, directory = await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert bot._agents_dir == directory == root / str(snap.record.agent_id) / "v1"
    assert (bot._get_agent_kb_directory() / "k.md").read_text() == "kb body"
    assert (bot._get_agent_kb_directory() / "sub" / "n.txt").read_text() == "more"
    assert (bot._agents_dir / "a1" / "skills" / "s1.md").read_text() == "skill body"
    assert not (directory / "a1" / "identity").exists()           # identity is a constructor kwarg, not a file


async def test_runtime_dir_not_in_agents_dir(configure, tmp_path, monkeypatch):
    from parrot.conf import AGENTS_DIR

    agents = Path(AGENTS_DIR)
    before = sorted(str(p) for p in agents.rglob("*")) if agents.exists() else []
    monkeypatch.setenv("STUDIO_RUNTIME_DIR", str(tmp_path / "rt"))
    snap = _snapshot(assets=[("kb", "k.md", "x")])
    _, directory = await _builder(studio_runtime_dir()).build(snap, web.Application(), part=GLOBAL)
    assert agents.resolve() not in directory.resolve().parents and directory.is_relative_to(tmp_path / "rt")
    assert (sorted(str(p) for p in agents.rglob("*")) if agents.exists() else []) == before


async def test_failed_configure_cleans_once_and_removes_the_directory(configure, root, monkeypatch):
    configure.side_effect = RuntimeError("llm exploded")
    cleanups = []
    real = agent_registry.create_agent_factory

    def spy(cfg):
        factory = real(cfg)

        async def wrapped(**kw):
            bot = await factory(**kw)
            bot.cleanup = AsyncMock()
            cleanups.append(bot)
            return bot

        return wrapped

    monkeypatch.setattr(agent_registry, "create_agent_factory", spy)
    snap = _snapshot(assets=[("kb", "k.md", "x")])
    with pytest.raises(AgentReloadError):
        await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert len(cleanups) == 1 and cleanups[0].cleanup.await_count == 1
    assert not (root / str(snap.record.agent_id) / "v1").exists()


async def test_cancelled_build_is_cleaned_and_propagates(configure, root):
    configure.side_effect = asyncio.CancelledError()
    snap = _snapshot(assets=[("kb", "k.md", "x")])
    with pytest.raises(asyncio.CancelledError):
        await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert not (root / str(snap.record.agent_id) / "v1").exists()


async def test_tenant_class_outside_the_allowlist_is_refused(configure, root):
    snap = _snapshot(tenant="acme", bot_class="NotAnAllowedClass")
    with pytest.raises(AgentReloadError):
        await _builder(root).build(snap, web.Application(), part=ACME)
    assert configure.await_count == 0 and not root.exists()
    ok = _snapshot(tenant="acme", bot_class="BasicBot")
    bot, _ = await _builder(root).build(ok, web.Application(), part=ACME)
    assert type(bot).__name__ == "BasicBot"


async def test_asset_path_traversal_is_refused_and_cleaned(configure, root):
    snap = _snapshot(assets=[("kb", "../../escape.md", "x")])
    with pytest.raises(AgentReloadError):
        await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert not (root / "escape.md").exists() and not (root / str(snap.record.agent_id) / "v1").exists()


async def test_class_allowlist_is_enforced_at_build(configure, root, monkeypatch):
    import parrot.bots as bots_module

    monkeypatch.setattr(bots_module, "__all__", [n for n in bots_module.__all__ if n != "BasicBot"])
    snap = _snapshot(tenant="acme", bot_class="BasicBot")            # resolvable, but no longer allowlisted
    with pytest.raises(AgentReloadError):
        await _builder(root).build(snap, web.Application(), part=ACME)
    assert configure.await_count == 0 and not root.exists()
    bot, _ = await _builder(root).build(_snapshot(bot_class="BasicBot"), web.Application(), part=GLOBAL)
    assert type(bot).__name__ == "BasicBot"                            # the non-tenant partition is not allowlisted


async def test_gate_runs_with_phase_build_and_no_actor(configure, root):
    calls = []
    gate = StudioToolingGate({})
    real = gate.enforce

    def spy(part, tooling, *, agent_id, actor, phase):
        calls.append((part, agent_id, actor, phase))
        return real(part, tooling, agent_id=agent_id, actor=actor, phase=phase)

    gate.enforce = spy
    snap = _snapshot(tenant="acme")
    await StudioAgentBuilder(agent_registry, root, gate).build(snap, web.Application(), part=ACME)
    assert calls == [(ACME, snap.record.agent_id, None, "build")]


async def test_only_identity_assets_feed_identity_kwargs(configure, root):
    snap = _snapshot(assets=[("kb", "role.md", "kb file called role.md"), ("identity", "goal.md", "  the goal  ")])
    bot, _ = await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert bot.goal == "the goal" and bot.role != "kb file called role.md"


async def test_failed_rebuild_keeps_a_version_directory_other_entries_use(configure, root):
    snap = _snapshot(assets=[("kb", "k.md", "kb body")])
    bot, directory = await _builder(root).build(snap, web.Application(), part=GLOBAL)    # e.g. the live base entry
    configure.side_effect = RuntimeError("session build exploded")
    with pytest.raises(AgentReloadError):                                                 # e.g. a session build
        await _builder(root).build(snap, web.Application(), part=GLOBAL)
    assert (bot._get_agent_kb_directory() / "k.md").read_text() == "kb body" and directory.exists()


def test_runtime_dir_property(root):
    assert _builder(root).runtime_dir == root
