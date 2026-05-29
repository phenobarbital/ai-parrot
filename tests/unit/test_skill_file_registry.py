"""
Unit tests for parrot.skills.file_registry.

Tests the get_by_name() method added in TASK-1290.
"""
from pathlib import Path

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource


@pytest.fixture
def registry_with_skill(tmp_path):
    """SkillFileRegistry pre-loaded with one authored skill."""
    registry = SkillFileRegistry(skills_dir=tmp_path)
    skill = SkillDefinition(
        name="test-skill",
        description="A test skill",
        triggers=["/test"],
        source=SkillSource.AUTHORED,
        template_body="Do the thing.",
        token_count=5,
        file_path=tmp_path / "test-skill.md",
    )
    registry.add(skill)
    return registry


@pytest.fixture
def empty_registry(tmp_path):
    """Empty SkillFileRegistry."""
    return SkillFileRegistry(skills_dir=tmp_path)


def test_get_by_name_found(registry_with_skill):
    """get_by_name returns the skill for a known name."""
    result = registry_with_skill.get_by_name("test-skill")
    assert result is not None
    assert result.name == "test-skill"


def test_get_by_name_not_found(registry_with_skill):
    """get_by_name returns None for an unknown name."""
    result = registry_with_skill.get_by_name("nonexistent")
    assert result is None


def test_get_by_name_empty_registry(empty_registry):
    """get_by_name returns None on an empty registry."""
    result = empty_registry.get_by_name("anything")
    assert result is None


@pytest.mark.asyncio
async def test_load_discovers_composite_skill(tmp_path):
    """load() discovers both single-file and composite {name}/SKILL.md layouts."""
    # Single-file skill
    (tmp_path / "summarize.md").write_text(
        "---\nname: summarize\ndescription: Summarize text\n"
        "triggers:\n  - /resumen\n---\nSummarize the input."
    )
    # Composite skill with an adjacent asset
    composite = tmp_path / "extract-pdf"
    composite.mkdir()
    (composite / "SKILL.md").write_text(
        "---\nname: extract-pdf\ndescription: Extract tables\n"
        "triggers:\n  - /extract\n---\nExtract tables from PDF."
    )
    (composite / "script.py").write_text("# helper")

    registry = SkillFileRegistry(skills_dir=tmp_path)
    await registry.load()

    names = {s.name for s in registry.list_skills()}
    assert names == {"summarize", "extract-pdf"}

    composite_skill = registry.get_by_name("extract-pdf")
    assert composite_skill.assets_dir is not None
    assert composite_skill.assets_dir.name == "extract-pdf"
    assert registry.get_by_name("summarize").assets_dir is None


@pytest.mark.asyncio
async def test_load_excludes_learned_subdir_as_composite(tmp_path):
    """The learned/ subdir is scanned separately, never as a composite skill."""
    learned = tmp_path / "learned"
    learned.mkdir()
    # A learned single-file skill lives inside learned/
    (learned / "remember.md").write_text(
        "---\nname: remember\ndescription: Recall a fact\n"
        "triggers:\n  - /remember\nsource: learned\n---\nRecall."
    )

    registry = SkillFileRegistry(skills_dir=tmp_path)
    await registry.load()

    names = {s.name for s in registry.list_skills()}
    # Only the learned skill is registered; "learned" itself is not a skill
    assert names == {"remember"}


def test_get_by_name_returns_correct_skill(tmp_path):
    """get_by_name returns the exact skill object that was added."""
    registry = SkillFileRegistry(skills_dir=tmp_path)
    skill_a = SkillDefinition(
        name="skill-a", description="First skill",
        triggers=["/a"], source=SkillSource.AUTHORED,
        template_body="A body.", token_count=3,
        file_path=tmp_path / "a.md",
    )
    skill_b = SkillDefinition(
        name="skill-b", description="Second skill",
        triggers=["/b"], source=SkillSource.AUTHORED,
        template_body="B body.", token_count=3,
        file_path=tmp_path / "b.md",
    )
    registry.add(skill_a)
    registry.add(skill_b)

    assert registry.get_by_name("skill-a") is skill_a
    assert registry.get_by_name("skill-b") is skill_b
    assert registry.get_by_name("skill-c") is None
