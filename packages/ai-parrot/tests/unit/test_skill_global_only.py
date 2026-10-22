"""FEAT-707 — `global_only` frontmatter parsing (TASK-4493)."""

from pathlib import Path

import pytest

from parrot.skills.models import SkillDefinition
from parrot.skills.parsers import parse_skill_directory, parse_skill_file


def _write_skill(path: Path, extra: str = "") -> Path:
    """Write a minimal valid skill file and return its path."""
    path.write_text(
        "---\nname: revenue\ndescription: Revenue by division\ntriggers:\n  - /revenue\n"
        f"{extra}---\n\nCompute revenue.\n"
    )
    return path


def test_default_is_false(tmp_path: Path) -> None:
    """Skills without frontmatter guard remain tenant-shadowable."""
    skill = parse_skill_file(_write_skill(tmp_path / "revenue.md"))
    assert skill.global_only is False


@pytest.mark.parametrize("raw,expected", [("true", True), ("false", False), ('"false"', False), ("yes", True)])
def test_parses_global_only(tmp_path: Path, raw: str, expected: bool) -> None:
    """The frontmatter guard is coerced to the expected boolean value."""
    skill = parse_skill_file(_write_skill(tmp_path / "revenue.md", f"global_only: {raw}\n"))
    assert skill.global_only is expected


def test_composite_inherits_global_only(tmp_path: Path) -> None:
    """Composite skills keep the guard parsed from their SKILL.md file."""
    skill_dir = tmp_path / "revenue"
    skill_dir.mkdir()
    _write_skill(skill_dir / "SKILL.md", "global_only: true\n")

    skill = parse_skill_directory(skill_dir)

    assert skill.global_only is True
    assert skill.assets_dir == skill_dir


def test_model_default() -> None:
    """The model default preserves existing skill construction calls."""
    skill = SkillDefinition(
        name="revenue",
        description="Revenue by division",
        triggers=["/revenue"],
        template_body="Compute revenue.",
        token_count=3,
        file_path=Path("revenue.md"),
    )
    assert skill.global_only is False
