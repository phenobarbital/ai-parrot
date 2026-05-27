"""
Unit tests for parrot.skills.loader.SkillsDirectoryLoader.

Tests filesystem discovery of both single-file (.md) and composite
(dir/SKILL.md) skill layouts, as well as error handling.
"""
from pathlib import Path

import pytest

from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.loader import SkillsDirectoryLoader


@pytest.fixture
def skill_dir(tmp_path):
    """Directory with a single-file, a composite skill, and a non-skill file."""
    # Single-file skill
    (tmp_path / "summarize.md").write_text(
        "---\nname: summarize\ndescription: Summarize text\n"
        "triggers:\n  - /resumen\n---\nSummarize the input."
    )
    # Composite skill
    composite = tmp_path / "extract-pdf"
    composite.mkdir()
    (composite / "SKILL.md").write_text(
        "---\nname: extract-pdf\ndescription: Extract tables\n"
        "triggers: []\n---\nExtract tables from PDF."
    )
    (composite / "script.py").write_text("# script")
    # Non-skill file (should be ignored)
    (tmp_path / "README.txt").write_text("ignore me")
    # Subdirectory without SKILL.md (should be ignored)
    extra_dir = tmp_path / "not-a-skill"
    extra_dir.mkdir()
    (extra_dir / "notes.txt").write_text("just notes")
    return tmp_path


@pytest.fixture
def malformed_dir(tmp_path):
    """Directory with one malformed and one valid skill file."""
    (tmp_path / "bad.md").write_text("no frontmatter here")
    (tmp_path / "good.md").write_text(
        "---\nname: good\ndescription: A good skill\n"
        "triggers: []\n---\nBody."
    )
    return tmp_path


@pytest.mark.asyncio
async def test_discover_single_file(skill_dir):
    """Discovers single-file .md skills."""
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    names = {s.name for s in skills}
    assert "summarize" in names


@pytest.mark.asyncio
async def test_discover_composite(skill_dir):
    """Discovers composite dir/SKILL.md skills."""
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    names = {s.name for s in skills}
    assert "extract-pdf" in names


@pytest.mark.asyncio
async def test_discover_mixed(skill_dir):
    """Discovers both single-file and composite skills from the same directory."""
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    assert len(skills) == 2


@pytest.mark.asyncio
async def test_discover_nonexistent_path():
    """Non-existent path is logged and skipped without crashing."""
    loader = SkillsDirectoryLoader(paths=[Path("/nonexistent/path")])
    skills = await loader.discover()
    assert skills == []


@pytest.mark.asyncio
async def test_discover_skips_malformed(malformed_dir):
    """Malformed skill file is skipped; valid skill is still loaded."""
    loader = SkillsDirectoryLoader(paths=[malformed_dir])
    skills = await loader.discover()
    assert len(skills) == 1
    assert skills[0].name == "good"


@pytest.mark.asyncio
async def test_load_into_registry(skill_dir):
    """load_into() hot-adds discovered skills to registry and returns count."""
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    registry = SkillFileRegistry(skills_dir=skill_dir)
    count = await loader.load_into(registry)
    assert count == 2
    assert len(registry.list_skills()) == 2


@pytest.mark.asyncio
async def test_load_into_returns_zero_for_empty_dir(tmp_path):
    """load_into() returns 0 for an empty directory."""
    loader = SkillsDirectoryLoader(paths=[tmp_path])
    registry = SkillFileRegistry(skills_dir=tmp_path)
    count = await loader.load_into(registry)
    assert count == 0


@pytest.mark.asyncio
async def test_composite_skill_has_assets_dir(skill_dir):
    """Composite skill has assets_dir pointing to its directory."""
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    composite = next(s for s in skills if s.name == "extract-pdf")
    assert composite.assets_dir is not None
    assert composite.assets_dir.name == "extract-pdf"


@pytest.mark.asyncio
async def test_single_file_skill_no_assets_dir(skill_dir):
    """Single-file skill has assets_dir=None."""
    loader = SkillsDirectoryLoader(paths=[skill_dir])
    skills = await loader.discover()
    single = next(s for s in skills if s.name == "summarize")
    assert single.assets_dir is None
