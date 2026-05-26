"""
Unit tests for parrot.skills.tools.LoadSkillTool.

Tests the Tier 2 on-demand skill retrieval tool added in TASK-1293.
"""
from pathlib import Path

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.tools import LoadSkillTool


@pytest.fixture
def registry_with_skills(tmp_path):
    """SkillFileRegistry with a single-file and a composite skill."""
    registry = SkillFileRegistry(skills_dir=tmp_path)

    # Single-file skill (no assets_dir)
    registry.add(SkillDefinition(
        name="summarize",
        description="Summarize text",
        triggers=["/resumen"],
        source=SkillSource.AUTHORED,
        template_body="Summarize the input text concisely.",
        token_count=8,
        file_path=tmp_path / "summarize.md",
    ))

    # Composite skill with assets
    composite_dir = tmp_path / "extract-pdf"
    composite_dir.mkdir()
    (composite_dir / "script.py").write_text("# extraction script")
    (composite_dir / "SKILL.md").write_text("placeholder")
    registry.add(SkillDefinition(
        name="extract-pdf",
        description="Extract tables",
        triggers=[],
        source=SkillSource.AUTHORED,
        template_body="Use camelot to extract tables.",
        token_count=7,
        file_path=composite_dir / "SKILL.md",
        assets_dir=composite_dir,
    ))

    return registry


@pytest.mark.asyncio
async def test_load_skill_found(registry_with_skills):
    """Found skill returns status='done' with template_body as result."""
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="summarize")
    assert result.status == "done"
    assert "Summarize the input text" in result.result


@pytest.mark.asyncio
async def test_load_skill_not_found(registry_with_skills):
    """Unknown skill name returns status='error'."""
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="nonexistent")
    assert result.status == "error"
    assert result.error is not None


@pytest.mark.asyncio
async def test_load_skill_composite_manifest(registry_with_skills):
    """Composite skill returns asset manifest and is_composite=True."""
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="extract-pdf")
    assert result.status == "done"
    assert result.metadata["is_composite"] is True
    assert "script.py" in result.metadata["assets"]


@pytest.mark.asyncio
async def test_load_skill_single_file_no_assets(registry_with_skills):
    """Single-file skill has empty assets list and is_composite=False."""
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="summarize")
    assert result.metadata["is_composite"] is False
    assert result.metadata["assets"] == []


@pytest.mark.asyncio
async def test_load_skill_metadata_fields(registry_with_skills):
    """Result metadata contains skill_name and category."""
    tool = LoadSkillTool(file_registry=registry_with_skills)
    result = await tool._execute(name="summarize")
    assert result.metadata["skill_name"] == "summarize"
    assert "category" in result.metadata


@pytest.mark.asyncio
async def test_load_skill_tool_name():
    """LoadSkillTool.name is 'load_skill'."""
    registry = SkillFileRegistry(skills_dir=Path("/tmp"))
    tool = LoadSkillTool(file_registry=registry)
    assert tool.name == "load_skill"
