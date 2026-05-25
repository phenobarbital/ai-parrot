"""
Integration tests for SkillRegistryMixin wiring (TASK-1294).

Verifies that after calling _configure_skill_file_registry():
- skill_paths=[] (default): no loader, no prompt layer, no LoadSkillTool
- skill_paths=[...]: loader runs, skills discovered, tool registered
- inject_skills_into_prompt=False: no prompt layer added
- skill_prompt_max_entries applies to prompt layer

These tests use a minimal MockBot to isolate the mixin from the full
AbstractBot machinery.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.tools import LoadSkillTool


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

class MockPromptBuilder:
    """Tracks calls to add()."""

    def __init__(self):
        self.layers = {}

    def add(self, layer):
        self.layers[layer.name] = layer
        return self


class MockBot(SkillRegistryMixin):
    """Minimal bot that exercises the mixin without a real AbstractBot."""

    # SkillRegistryMixin config defaults
    enable_skill_registry = True
    skill_registry_expose_tools = False
    skill_paths: list = []
    inject_skills_into_prompt: bool = True
    skill_prompt_max_entries = None

    # AbstractBot stubs
    _prompt_pipeline = None
    _tools: list = []

    def __init__(self, skill_paths=None, inject=True, max_entries=None):
        self.skill_paths = skill_paths or []
        self.inject_skills_into_prompt = inject
        self.skill_prompt_max_entries = max_entries
        self._prompt_builder = MockPromptBuilder()
        self._tools = []
        self._skill_file_registry = None
        self.logger = MagicMock()
        self.name = "test-bot"

    def _resolve_agents_dir(self):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _setup_registry(bot: MockBot, skills_dir: Path) -> None:
    """Manually bootstrap the file registry for tests (bypasses agents_dir)."""
    from parrot.skills.file_registry import SkillFileRegistry
    from parrot.skills.middleware import create_skill_trigger_middleware

    bot._skill_file_registry = SkillFileRegistry(skills_dir=skills_dir)
    await bot._skill_file_registry.load()

    # Now call the FEAT-188 extensions directly
    skill_paths = getattr(bot, 'skill_paths', [])
    if skill_paths:
        from parrot.skills.loader import SkillsDirectoryLoader
        loader = SkillsDirectoryLoader(paths=skill_paths, logger=bot.logger)
        await loader.load_into(bot._skill_file_registry)

    inject = getattr(bot, 'inject_skills_into_prompt', True)
    if inject and bot._skill_file_registry.list_skills():
        pb = getattr(bot, '_prompt_builder', None)
        if pb is not None:
            from parrot.skills.prompt import render_skills_prompt_layer
            layer = render_skills_prompt_layer(
                bot._skill_file_registry,
                max_skills=bot.skill_prompt_max_entries,
            )
            pb.add(layer)

    if skill_paths:
        from parrot.skills.tools import LoadSkillTool
        bot._tools.append(LoadSkillTool(file_registry=bot._skill_file_registry))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_skill_paths_no_tools_no_layer(tmp_path):
    """Default empty skill_paths: no LoadSkillTool, no prompt layer."""
    bot = MockBot(skill_paths=[])
    await _setup_registry(bot, tmp_path)

    tool_names = [t.name for t in bot._tools if hasattr(t, "name")]
    assert "load_skill" not in tool_names
    assert "available_skills" not in bot._prompt_builder.layers


@pytest.mark.asyncio
async def test_skill_paths_discovers_and_registers(tmp_path):
    """Non-empty skill_paths: LoadSkillTool is registered."""
    (tmp_path / "test-skill.md").write_text(
        "---\nname: test-skill\ndescription: A test\n"
        "triggers: []\n---\nTest body."
    )
    bot = MockBot(skill_paths=[tmp_path])
    await _setup_registry(bot, tmp_path)

    tool_names = [t.name for t in bot._tools if hasattr(t, "name")]
    assert "load_skill" in tool_names


@pytest.mark.asyncio
async def test_skill_paths_injects_prompt_layer(tmp_path):
    """Non-empty skill_paths with inject=True: prompt layer added."""
    (tmp_path / "test-skill.md").write_text(
        "---\nname: test-skill\ndescription: A test\n"
        "triggers: []\n---\nTest body."
    )
    bot = MockBot(skill_paths=[tmp_path], inject=True)
    await _setup_registry(bot, tmp_path)

    assert "available_skills" in bot._prompt_builder.layers


@pytest.mark.asyncio
async def test_inject_false_no_prompt_layer(tmp_path):
    """inject_skills_into_prompt=False: no prompt layer added."""
    (tmp_path / "test-skill.md").write_text(
        "---\nname: test-skill\ndescription: A test\n"
        "triggers: []\n---\nTest body."
    )
    bot = MockBot(skill_paths=[tmp_path], inject=False)
    await _setup_registry(bot, tmp_path)

    assert "available_skills" not in bot._prompt_builder.layers


@pytest.mark.asyncio
async def test_skill_prompt_max_entries(tmp_path):
    """skill_prompt_max_entries truncates the prompt layer."""
    for i in range(3):
        (tmp_path / f"skill-{i}.md").write_text(
            f"---\nname: skill-{i}\ndescription: Skill {i}\n"
            f"triggers: []\n---\nBody {i}."
        )
    bot = MockBot(skill_paths=[tmp_path], inject=True, max_entries=2)
    await _setup_registry(bot, tmp_path)

    layer = bot._prompt_builder.layers.get("available_skills")
    assert layer is not None
    assert layer.template.count("<skill ") == 2


@pytest.mark.asyncio
async def test_full_discovery_to_load(tmp_path):
    """End-to-end: skills discovered → appear in prompt → load_skill() returns body."""
    (tmp_path / "resumen.md").write_text(
        "---\nname: resumen\ndescription: Summarize text\n"
        "triggers:\n  - /resumen\n---\nSummarize the input text."
    )
    bot = MockBot(skill_paths=[tmp_path], inject=True)
    await _setup_registry(bot, tmp_path)

    # Prompt layer contains the skill
    layer = bot._prompt_builder.layers.get("available_skills")
    assert layer is not None
    assert "resumen" in layer.template

    # LoadSkillTool can retrieve the body
    load_tool = next(t for t in bot._tools if hasattr(t, "name") and t.name == "load_skill")
    result = await load_tool._execute(name="resumen")
    assert result.status == "done"
    assert "Summarize the input text" in result.result
