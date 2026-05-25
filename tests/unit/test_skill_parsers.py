"""
Unit tests for parrot.skills.parsers.

Tests the parse_skill_directory() function added in TASK-1289,
as well as the empty-triggers allowance in parse_skill_file().
"""
from pathlib import Path

import pytest

from parrot.skills.parsers import parse_skill_directory, parse_skill_file


@pytest.fixture
def composite_skill_dir(tmp_path):
    """Composite skill directory with SKILL.md and an asset."""
    skill_dir = tmp_path / "extract-pdf"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: extract-pdf\ndescription: Extract tables from PDF\n"
        "triggers: []\n---\nUse camelot to extract tables."
    )
    (skill_dir / "script.py").write_text("# extraction script")
    return skill_dir


@pytest.fixture
def single_file_skill(tmp_path):
    """A single .md skill file with a trigger."""
    skill_file = tmp_path / "summarize.md"
    skill_file.write_text(
        "---\nname: summarize\ndescription: Summarize text\n"
        "triggers:\n  - /resumen\n---\nSummarize the input text concisely."
    )
    return skill_file


def test_parse_skill_directory_valid(composite_skill_dir):
    """Valid composite skill dir returns SkillDefinition with assets_dir set."""
    skill = parse_skill_directory(composite_skill_dir)
    assert skill.name == "extract-pdf"
    assert skill.description == "Extract tables from PDF"
    assert skill.assets_dir == composite_skill_dir


def test_parse_skill_directory_missing_skill_md(tmp_path):
    """Directory without SKILL.md raises FileNotFoundError."""
    empty_dir = tmp_path / "no-skill"
    empty_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="Missing SKILL.md"):
        parse_skill_directory(empty_dir)


def test_parse_skill_directory_inherits_fields(composite_skill_dir):
    """Frontmatter fields (name, description, body) are parsed from SKILL.md."""
    skill = parse_skill_directory(composite_skill_dir)
    assert skill.template_body == "Use camelot to extract tables."
    assert skill.file_path == composite_skill_dir / "SKILL.md"
    assert skill.triggers == []


def test_parse_skill_directory_assets_dir_is_dir(composite_skill_dir):
    """assets_dir is set to the skill directory (not SKILL.md)."""
    skill = parse_skill_directory(composite_skill_dir)
    assert skill.assets_dir.is_dir()
    assert skill.assets_dir != skill.file_path


def test_parse_skill_file_empty_triggers_allowed(tmp_path):
    """parse_skill_file accepts an explicitly empty triggers list."""
    skill_file = tmp_path / "no-triggers.md"
    skill_file.write_text(
        "---\nname: no-triggers\ndescription: A skill without triggers\n"
        "triggers: []\n---\nSome body."
    )
    skill = parse_skill_file(skill_file)
    assert skill.triggers == []
    assert skill.name == "no-triggers"


def test_parse_skill_file_missing_triggers_raises(tmp_path):
    """parse_skill_file raises ValueError when triggers key is absent."""
    skill_file = tmp_path / "missing-triggers.md"
    skill_file.write_text(
        "---\nname: missing-triggers\ndescription: Missing triggers key\n---\nBody."
    )
    with pytest.raises(ValueError, match="missing 'triggers'"):
        parse_skill_file(skill_file)
