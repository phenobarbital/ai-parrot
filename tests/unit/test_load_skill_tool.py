"""
Unit tests for the ``load_skill`` tool of parrot.skills.tools.SkillFileToolkit.

Tests the Tier 2 on-demand skill retrieval tool (originally TASK-1293),
now a method of the unified SkillFileToolkit.
"""
from pathlib import Path

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.tools import SkillFileToolkit


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


@pytest.fixture
def toolkit(registry_with_skills):
    """SkillFileToolkit sharing the populated registry."""
    return SkillFileToolkit(file_registry=registry_with_skills)


@pytest.mark.asyncio
async def test_load_skill_found(toolkit):
    """Found skill returns status='done' with template_body as result."""
    result = await toolkit.load_skill(name="summarize")
    assert result.status == "done"
    assert "Summarize the input text" in result.result


@pytest.mark.asyncio
async def test_load_skill_not_found(toolkit):
    """Unknown skill name returns status='error'."""
    result = await toolkit.load_skill(name="nonexistent")
    assert result.status == "error"
    assert result.error is not None


@pytest.mark.asyncio
async def test_load_skill_composite_manifest(toolkit):
    """Composite skill returns asset manifest and is_composite=True."""
    result = await toolkit.load_skill(name="extract-pdf")
    assert result.status == "done"
    assert result.metadata["is_composite"] is True
    assert "script.py" in result.metadata["assets"]


@pytest.mark.asyncio
async def test_load_skill_single_file_no_assets(toolkit):
    """Single-file skill has empty assets list and is_composite=False."""
    result = await toolkit.load_skill(name="summarize")
    assert result.metadata["is_composite"] is False
    assert result.metadata["assets"] == []


@pytest.mark.asyncio
async def test_load_skill_metadata_fields(toolkit):
    """Result metadata contains skill_name and category."""
    result = await toolkit.load_skill(name="summarize")
    assert result.metadata["skill_name"] == "summarize"
    assert "category" in result.metadata


def test_load_skill_registered_as_tool(registry_with_skills):
    """The toolkit exposes a tool named 'load_skill'."""
    toolkit = SkillFileToolkit(file_registry=registry_with_skills)
    names = {t.name for t in toolkit.get_tools()}
    assert "load_skill" in names


def test_save_learned_skill_excluded_without_learned_dir(registry_with_skills, tmp_path):
    """save_learned_skill is exposed only when a learned_dir is configured."""
    without = SkillFileToolkit(file_registry=registry_with_skills)
    assert "save_learned_skill" not in {t.name for t in without.get_tools()}

    learned = SkillFileToolkit(
        file_registry=registry_with_skills, learned_dir=tmp_path / "learned"
    )
    names = {t.name for t in learned.get_tools()}
    assert "save_learned_skill" in names
    assert {"load_skill", "read_skill_asset"} <= names
