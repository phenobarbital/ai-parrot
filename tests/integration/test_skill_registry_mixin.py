"""
Integration tests for SkillRegistryMixin wiring (TASK-1294).

Verifies that after calling _configure_skill_file_registry():
- skill_paths=[] (default): no loader, no prompt layer, no LoadSkillTool
- skill_paths=[...]: loader runs, skills discovered, tool registered
- inject_skills_into_prompt=False: no prompt layer added
- skill_prompt_max_entries applies to prompt layer

These tests call _configure_skill_file_registry() directly so they exercise
the real mixin logic (not a bypass helper).  agents_dir is forced to None via
the overridden _resolve_agents_dir() so the FEAT-188 extensions are the only
code path under test.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.skills.mixin import SkillRegistryMixin


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
        """Return None so only FEAT-188 extensions run."""
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_skill_paths_no_tools_no_layer(tmp_path):
    """Default empty skill_paths: no LoadSkillTool, no prompt layer."""
    bot = MockBot(skill_paths=[])
    await bot._configure_skill_file_registry()

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
    await bot._configure_skill_file_registry()

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
    await bot._configure_skill_file_registry()

    assert "available_skills" in bot._prompt_builder.layers


@pytest.mark.asyncio
async def test_inject_false_no_prompt_layer(tmp_path):
    """inject_skills_into_prompt=False: no prompt layer added."""
    (tmp_path / "test-skill.md").write_text(
        "---\nname: test-skill\ndescription: A test\n"
        "triggers: []\n---\nTest body."
    )
    bot = MockBot(skill_paths=[tmp_path], inject=False)
    await bot._configure_skill_file_registry()

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
    await bot._configure_skill_file_registry()

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
    await bot._configure_skill_file_registry()

    # Prompt layer contains the skill
    layer = bot._prompt_builder.layers.get("available_skills")
    assert layer is not None
    assert "resumen" in layer.template

    # LoadSkillTool can retrieve the body
    load_tool = next(t for t in bot._tools if hasattr(t, "name") and t.name == "load_skill")
    result = await load_tool._execute(name="resumen")
    assert result.status == "done"
    assert "Summarize the input text" in result.result
