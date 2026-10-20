"""FEAT-707 hardening follow-ups (TASK-4507, issue:8ea16e60de56)."""

from contextvars import ContextVar
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.basic import BasicBot
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, RenderPhase
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.models import SkillDefinition
from parrot.skills.prompt import global_layer_condition, render_skills_prompt_layer, tenant_layer_condition
from parrot.skills.tenancy import (
    bind_skill_tenant,
    current_active_skill,
    current_skill_tenant,
    enter_active_skill_scope,
    exit_active_skill_scope,
    reset_skill_tenant,
    set_active_skill,
)

_tenant_var: ContextVar = ContextVar("hardening_tenant_var", default=None)
_ASK_KW = dict(use_conversation_history=False, use_vector_context=False, use_tools=False)


def _skill(tmp_path: Path, description: str = "summarize things") -> SkillDefinition:
    return SkillDefinition(
        name="summary",
        description=description,
        triggers=["/summary"],
        template_body="Summarize only.",
        token_count=1,
        file_path=tmp_path / "summary.md",
    )


def _registry(tmp_path: Path, skill: SkillDefinition) -> SkillFileRegistry:
    registry = SkillFileRegistry(tmp_path)
    registry.add(skill)
    return registry


def _make_bot() -> BasicBot:
    with patch("parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector") as shared:
        det = MagicMock()
        det.detect_injection.return_value = (False, 0.0)
        shared.return_value = det
        bot = BasicBot(name="HardeningBot")
    bot._enter_skill_tenant = lambda tenant, ctx: _tenant_var.set(tenant)
    bot._exit_skill_tenant = lambda token: _tenant_var.reset(token)
    return bot


@pytest.fixture(autouse=True)
def _clean_contextvars():
    set_active_skill(None)
    yield
    set_active_skill(None)


# ── (1) active skill never outlives a failed ask ────────────────────────


def test_active_skill_scope_restores_previous_value(tmp_path: Path) -> None:
    token = enter_active_skill_scope()
    set_active_skill(_skill(tmp_path))
    exit_active_skill_scope(token)
    assert current_active_skill() is None


@pytest.mark.asyncio
async def test_failed_ask_does_not_leak_trigger_skill(tmp_path: Path) -> None:
    bot = _make_bot()
    skill = _skill(tmp_path)

    async def trigger_then_fail(*a, **k):
        set_active_skill(skill)  # what the /trigger middleware does mid-call
        raise RuntimeError("guardrail exploded")

    bot._run_input_pipeline = trigger_then_fail
    with pytest.raises(RuntimeError):
        await bot.ask("/summary hello", tenant="acme", **_ASK_KW)
    assert current_active_skill() is None
    assert _tenant_var.get() is None


@pytest.mark.asyncio
async def test_failed_ask_stream_does_not_leak_trigger_skill(tmp_path: Path) -> None:
    bot = _make_bot()
    skill = _skill(tmp_path)

    async def trigger_then_fail(*a, **k):
        set_active_skill(skill)
        raise RuntimeError("guardrail exploded")

    bot._run_input_pipeline = trigger_then_fail
    with pytest.raises(RuntimeError):
        async for _chunk in bot.ask_stream("/summary hello", tenant="acme", **_ASK_KW):
            pass
    assert current_active_skill() is None
    assert _tenant_var.get() is None


# ── (2) tenant reset runs before the other finally steps ────────────────


@pytest.mark.asyncio
async def test_tenant_reset_survives_failing_later_cleanup() -> None:
    bot = _make_bot()

    async def fail(*a, **k):
        raise RuntimeError("primary")

    def broken_exit(_turn):
        raise LookupError("cleanup broke")

    bot._run_input_pipeline = fail
    bot._exit_task_turn = broken_exit
    with pytest.raises(LookupError):
        await bot.ask("hello", tenant="acme", **_ASK_KW)
    assert _tenant_var.get() is None


# ── (3) skill text is never $-substituted ───────────────────────────────


def test_literal_layer_render_and_partial_render() -> None:
    layer = PromptLayer(name="x", priority=1, template="cost $user_context", literal=True)
    assert layer.render({"user_context": "SECRET"}) == "cost $user_context"
    partial = layer.partial_render({"user_context": "SECRET"})
    assert partial.literal is True
    assert partial.render({"user_context": "SECRET"}) == "cost $user_context"


@pytest.mark.parametrize("configure_first", [True, False])
def test_skill_description_dollar_not_expanded(tmp_path: Path, configure_first: bool) -> None:
    registry = _registry(tmp_path, _skill(tmp_path, description="Costs $user_context and $$5"))
    builder = PromptBuilder([PromptLayer(name="base", priority=10, template="base", phase=RenderPhase.REQUEST)])
    builder.add(render_skills_prompt_layer(registry))
    if configure_first:
        builder.configure({"user_context": "SECRET"})
    prompt = builder.build({"user_context": "SECRET"})
    assert "Costs $user_context and $$5" in prompt
    assert "SECRET" not in prompt


# ── (4) tenant layer conditions honour the instance default tenant ──────


def test_conditions_use_resolver() -> None:
    assert tenant_layer_condition("acme", lambda: "acme")({}) is True
    assert tenant_layer_condition("acme", lambda: None)({}) is False
    assert global_layer_condition({"acme"}, lambda: "acme")({}) is False
    assert global_layer_condition({"acme"}, lambda: None)({}) is True


def test_conditions_default_to_bound_tenant() -> None:
    token = bind_skill_tenant("acme")
    try:
        assert tenant_layer_condition("acme")({}) is True
        assert global_layer_condition({"acme"})({}) is False
    finally:
        reset_skill_tenant(token)


def _write_skill(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: {name} desc\ntriggers:\n  - /{name}\n---\n\nBody of {name}\n")


def _host(tmp_path: Path, **kw) -> SkillRegistryMixin:
    class Host(SkillRegistryMixin):
        name = "troc_finance"
        enable_skill_registry = False

    host = Host(**kw)
    host._agents_dir = tmp_path
    return host


@pytest.mark.asyncio
async def test_layers_follow_instance_default_tenant_outside_ask(tmp_path: Path) -> None:
    root = tmp_path / "troc_finance"
    _write_skill(root / "skills" / "glob.md", "glob")
    _write_skill(root / "tenants" / "pokemon" / "skills" / "poke.md", "poke")
    host = _host(tmp_path, tenant_based=True, tenant_id="pokemon")
    await host._configure_skill_file_registry()
    host._prompt_builder = PromptBuilder([])
    host._install_skill_prompt_layers()

    assert current_skill_tenant() is None
    assert host._layer_tenant() == "pokemon"
    prompt = host._prompt_builder.build({})
    # Tenant layer only (the tenant view also lists global skills); global layer hidden.
    assert '<skill name="poke">' in prompt
    assert prompt.count('<skill name="glob">') == 1
    assert host.current_skill_view() is host._tenant_views["pokemon"]

    token = bind_skill_tenant("epson")  # unknown tenant bound explicitly wins
    try:
        assert host._layer_tenant() == "epson"
        prompt = host._prompt_builder.build({})
        assert '<skill name="glob">' in prompt
        assert '<skill name="poke">' not in prompt
    finally:
        reset_skill_tenant(token)


def test_layer_tenant_none_when_not_tenant_based(tmp_path: Path) -> None:
    host = _host(tmp_path, tenant_id="pokemon")
    assert host._layer_tenant() is None
