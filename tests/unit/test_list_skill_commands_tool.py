"""
Unit tests for the ``list_skill_commands`` tool of
parrot.skills.tools.SkillFileToolkit.

Verifies the live listing of file-based skills with their descriptions and
/trigger commands, including skills hot-added after toolkit creation.
"""
from pathlib import Path

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.tools import SkillFileToolkit


@pytest.fixture
def registry(tmp_path):
    """Empty SkillFileRegistry backed by a temp directory."""
    return SkillFileRegistry(skills_dir=tmp_path)


@pytest.fixture
def registry_with_skills(registry, tmp_path):
    """Registry with one triggered skill and one trigger-less skill."""
    registry.add(SkillDefinition(
        name="summarize",
        description="Summarize text",
        triggers=["/resumen", "/summary"],
        source=SkillSource.AUTHORED,
        template_body="Summarize the input text concisely.",
        token_count=8,
        file_path=tmp_path / "summarize.md",
    ))
    registry.add(SkillDefinition(
        name="extract-pdf",
        description="Extract tables",
        triggers=[],
        source=SkillSource.AUTHORED,
        template_body="Use camelot to extract tables.",
        token_count=7,
        file_path=tmp_path / "extract-pdf.md",
    ))
    return registry


@pytest.mark.asyncio
async def test_list_skill_commands_empty_registry(registry):
    """Empty registry returns status='done' with count=0."""
    toolkit = SkillFileToolkit(file_registry=registry)
    result = await toolkit.list_skill_commands()
    assert result.status == "done"
    assert result.metadata["count"] == 0
    assert result.metadata["skills"] == []


@pytest.mark.asyncio
async def test_list_skill_commands_lists_triggers(registry_with_skills):
    """Listing includes skill names, descriptions and /trigger commands."""
    toolkit = SkillFileToolkit(file_registry=registry_with_skills)
    result = await toolkit.list_skill_commands()
    assert result.status == "done"
    assert result.metadata["count"] == 2
    assert "summarize" in result.result
    assert "/resumen" in result.result
    assert "/summary" in result.result


@pytest.mark.asyncio
async def test_list_skill_commands_triggerless_skill_hint(registry_with_skills):
    """Skills without triggers point to load_skill instead."""
    toolkit = SkillFileToolkit(file_registry=registry_with_skills)
    result = await toolkit.list_skill_commands()
    assert "extract-pdf" in result.result
    assert "load_skill" in result.result


@pytest.mark.asyncio
async def test_list_skill_commands_structured_metadata(registry_with_skills):
    """Metadata carries a machine-readable skills list with triggers."""
    toolkit = SkillFileToolkit(file_registry=registry_with_skills)
    result = await toolkit.list_skill_commands()
    by_name = {s["name"]: s for s in result.metadata["skills"]}
    assert by_name["summarize"]["triggers"] == ["/resumen", "/summary"]
    assert by_name["summarize"]["description"] == "Summarize text"
    assert by_name["extract-pdf"]["triggers"] == []


@pytest.mark.asyncio
async def test_list_skill_commands_sees_hot_added_skills(registry, tmp_path):
    """Skills added after toolkit creation appear in the listing (live read)."""
    toolkit = SkillFileToolkit(file_registry=registry)
    result = await toolkit.list_skill_commands()
    assert result.metadata["count"] == 0

    registry.add(SkillDefinition(
        name="learned-skill",
        description="A learned skill",
        triggers=["/aprendido"],
        source=SkillSource.LEARNED,
        template_body="Learned body.",
        token_count=3,
        file_path=tmp_path / "learned" / "learned-skill.md",
    ))
    result = await toolkit.list_skill_commands()
    assert result.metadata["count"] == 1
    assert "/aprendido" in result.result


def test_list_skill_commands_registered_as_tool(registry):
    """The toolkit exposes a tool named 'list_skill_commands'."""
    toolkit = SkillFileToolkit(file_registry=registry)
    names = {t.name for t in toolkit.get_tools()}
    assert "list_skill_commands" in names
