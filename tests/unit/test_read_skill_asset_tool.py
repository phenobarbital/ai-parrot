"""
Unit tests for parrot.skills.tools.ReadSkillAssetTool.

Tests the Tier 2 sandboxed asset reader for composite skills: valid reads,
error paths (unknown skill, single-file skill, missing asset), path-traversal
rejection, the SKILL.md guard, and truncation of oversized assets.
"""
import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.tools import ReadSkillAssetTool


@pytest.fixture
def registry_with_skills(tmp_path):
    """Registry with a single-file skill and a composite skill with assets."""
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

    # Composite skill with a template asset and SKILL.md
    composite_dir = tmp_path / "extract-pdf"
    composite_dir.mkdir()
    (composite_dir / "SKILL.md").write_text("Use camelot to extract tables.")
    (composite_dir / "template.md").write_text("# Report template\n{{rows}}")
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
async def test_read_valid_asset(registry_with_skills):
    """Reading a bundled asset returns its content."""
    tool = ReadSkillAssetTool(file_registry=registry_with_skills)
    result = await tool._execute(skill_name="extract-pdf", asset="template.md")
    assert result.status == "done"
    assert "Report template" in result.result
    assert result.metadata["asset"] == "template.md"


@pytest.mark.asyncio
async def test_unknown_skill(registry_with_skills):
    """Unknown skill name returns an error."""
    tool = ReadSkillAssetTool(file_registry=registry_with_skills)
    result = await tool._execute(skill_name="nope", asset="template.md")
    assert result.status == "error"
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_single_file_skill_has_no_assets(registry_with_skills):
    """Single-file skill (no assets_dir) returns an error."""
    tool = ReadSkillAssetTool(file_registry=registry_with_skills)
    result = await tool._execute(skill_name="summarize", asset="anything.md")
    assert result.status == "error"
    assert "single-file" in result.error.lower()


@pytest.mark.asyncio
async def test_missing_asset(registry_with_skills):
    """Requesting a non-existent asset returns an error."""
    tool = ReadSkillAssetTool(file_registry=registry_with_skills)
    result = await tool._execute(skill_name="extract-pdf", asset="ghost.md")
    assert result.status == "error"
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_path_traversal_rejected(registry_with_skills, tmp_path):
    """An asset path escaping assets_dir is rejected before any read."""
    # Secret lives outside the skill directory
    (tmp_path / "secret.txt").write_text("top secret")
    tool = ReadSkillAssetTool(file_registry=registry_with_skills)
    result = await tool._execute(
        skill_name="extract-pdf", asset="../secret.txt"
    )
    assert result.status == "error"
    assert "escape" in result.error.lower()


@pytest.mark.asyncio
async def test_skill_md_is_not_readable(registry_with_skills):
    """SKILL.md is reserved for load_skill, not this tool."""
    tool = ReadSkillAssetTool(file_registry=registry_with_skills)
    result = await tool._execute(skill_name="extract-pdf", asset="SKILL.md")
    assert result.status == "error"
    assert "load_skill" in result.error


@pytest.mark.asyncio
async def test_oversized_asset_is_truncated(tmp_path):
    """Assets larger than max_bytes are truncated with a notice."""
    composite_dir = tmp_path / "big-skill"
    composite_dir.mkdir()
    (composite_dir / "SKILL.md").write_text("body")
    (composite_dir / "data.txt").write_text("x" * 5000)

    registry = SkillFileRegistry(skills_dir=tmp_path)
    registry.add(SkillDefinition(
        name="big-skill",
        description="Big",
        triggers=[],
        source=SkillSource.AUTHORED,
        template_body="body",
        token_count=1,
        file_path=composite_dir / "SKILL.md",
        assets_dir=composite_dir,
    ))

    tool = ReadSkillAssetTool(file_registry=registry, max_bytes=1000)
    result = await tool._execute(skill_name="big-skill", asset="data.txt")
    assert result.status == "done"
    assert "truncated" in result.result
    assert result.result.count("x") == 1000
