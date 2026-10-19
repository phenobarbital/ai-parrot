"""FEAT-707 request-local active skill tests (TASK-4501)."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.bots.base import BaseBot
from parrot.bots.middleware import PromptPipeline
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, RenderPhase
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.middleware import create_skill_trigger_middleware
from parrot.skills.models import SkillDefinition
from parrot.skills.tenancy import current_active_skill, set_active_skill


def make_skill(tmp_path: Path, name: str, trigger: str, body: str) -> SkillDefinition:
    """Create a small skill definition for middleware and prompt tests."""
    return SkillDefinition(
        name=name,
        description=f"{name} description",
        triggers=[trigger],
        template_body=body,
        token_count=1,
        file_path=tmp_path / f"{name}.md",
    )


def make_registry(tmp_path: Path, skill: SkillDefinition) -> SkillFileRegistry:
    """Create an in-memory skill registry containing ``skill``."""
    registry = SkillFileRegistry(tmp_path)
    registry.add(skill)
    return registry


def make_prompt_bot() -> BaseBot:
    """Create a minimally initialized BaseBot for prompt assembly tests."""
    bot = object.__new__(BaseBot)
    bot._prompt_builder = PromptBuilder(
        [PromptLayer(name="base", priority=10, template="base", phase=RenderPhase.REQUEST)]
    )
    return bot


@pytest.fixture(autouse=True)
def clear_active_skill() -> None:
    """Keep the request-local ContextVar isolated between tests."""
    set_active_skill(None)
    yield
    set_active_skill(None)


@pytest.mark.asyncio
async def test_middleware_sets_active_skill_contextvar(tmp_path: Path) -> None:
    """A trigger sets the request-local active skill and strips its prefix."""
    skill = make_skill(tmp_path, "summary", "/summary", "Summarize only.")
    bot = MagicMock()
    middleware = create_skill_trigger_middleware(make_registry(tmp_path, skill), bot)

    assert await middleware.apply("/summary report", {}) == "report"
    assert current_active_skill() == skill
    assert bot._active_skill == skill


@pytest.mark.asyncio
async def test_middleware_uses_view_provider_and_falls_back_to_registry(tmp_path: Path) -> None:
    """The per-request view wins, while a ``None`` view uses the base registry."""
    base_skill = make_skill(tmp_path, "base", "/base", "Base body")
    tenant_skill = make_skill(tmp_path, "tenant", "/tenant", "Tenant body")
    base_registry = make_registry(tmp_path / "base", base_skill)
    tenant_registry = make_registry(tmp_path / "tenant", tenant_skill)
    bot = MagicMock()

    middleware = create_skill_trigger_middleware(
        base_registry,
        bot,
        view_provider=lambda: tenant_registry,
    )
    assert await middleware.apply("/tenant question", {}) == "question"
    assert current_active_skill() == tenant_skill

    set_active_skill(None)
    fallback = create_skill_trigger_middleware(base_registry, bot, view_provider=lambda: None)
    assert await fallback.apply("/base question", {}) == "question"
    assert current_active_skill() == base_skill


@pytest.mark.asyncio
async def test_skills_listing_uses_view(tmp_path: Path) -> None:
    """Reserved listings are resolved from the current view."""
    base_skill = make_skill(tmp_path, "base", "/base", "Base body")
    tenant_skill = make_skill(tmp_path, "tenant", "/tenant", "Tenant body")
    base_registry = make_registry(tmp_path / "base", base_skill)
    tenant_registry = make_registry(tmp_path / "tenant", tenant_skill)
    middleware = create_skill_trigger_middleware(
        base_registry,
        MagicMock(),
        view_provider=lambda: tenant_registry,
    )

    listing = await middleware.apply("/skills", {})

    assert "tenant description" in listing
    assert "base description" not in listing


@pytest.mark.asyncio
async def test_create_system_prompt_no_builder_mutation() -> None:
    """The permanent active layer is installed once and retained between calls."""
    bot = make_prompt_bot()
    initial_names = bot._prompt_builder.layer_names

    await bot.create_system_prompt()
    first_names = bot._prompt_builder.layer_names
    await bot.create_system_prompt()
    second_names = bot._prompt_builder.layer_names

    assert first_names == initial_names + ["skill_active"]
    assert second_names == first_names
    assert second_names.count("skill_active") == 1


@pytest.mark.asyncio
async def test_active_skill_body_rendered_once_then_cleared(tmp_path: Path) -> None:
    """An activated skill affects one prompt and is cleared before the next."""
    bot = make_prompt_bot()
    skill = make_skill(tmp_path, "summary", "/summary", "Use concise bullets.")
    set_active_skill(skill)

    first_prompt = await bot.create_system_prompt(active_skill_body="caller value")
    second_prompt = await bot.create_system_prompt()

    assert "Use concise bullets." in first_prompt
    assert "caller value" not in first_prompt
    assert "Use concise bullets." not in second_prompt
    assert current_active_skill() is None


@pytest.mark.asyncio
async def test_concurrent_trigger_isolation(tmp_path: Path) -> None:
    """Concurrent requests render only the skill activated in their own task."""
    bot = make_prompt_bot()
    first = make_skill(tmp_path, "first", "/first", "FIRST BODY")
    second = make_skill(tmp_path, "second", "/second", "SECOND BODY")

    async def render(skill: SkillDefinition) -> str:
        set_active_skill(skill)
        await asyncio.sleep(0)
        return await bot.create_system_prompt()

    first_prompt, second_prompt = await asyncio.gather(render(first), render(second))

    assert "FIRST BODY" in first_prompt
    assert "SECOND BODY" not in first_prompt
    assert "SECOND BODY" in second_prompt
    assert "FIRST BODY" not in second_prompt


@pytest.mark.asyncio
async def test_legacy_attribute_fallback() -> None:
    """A plain legacy ``_active_skill`` attribute still activates one prompt."""
    bot = make_prompt_bot()
    legacy_skill = make_skill(Path("/tmp"), "legacy", "/legacy", "LEGACY BODY")
    bot._active_skill = legacy_skill

    prompt = await bot.create_system_prompt()

    assert "LEGACY BODY" in prompt
    assert bot._active_skill is None
    assert current_active_skill() is None
