"""
Unit tests for parrot.skills.models.

Tests the SkillDefinition model, focusing on the assets_dir field
added in TASK-1288.
"""
from pathlib import Path

import pytest

from parrot.skills.models import SkillDefinition, SkillSource


def test_skill_definition_assets_dir_default():
    """assets_dir defaults to None for single-file skills."""
    skill = SkillDefinition(
        name="test",
        description="desc",
        triggers=[],
        template_body="body",
        token_count=5,
        file_path=Path("/tmp/test.md"),
    )
    assert skill.assets_dir is None


def test_skill_definition_assets_dir_set():
    """assets_dir accepts a Path value for composite skills."""
    skill = SkillDefinition(
        name="test",
        description="desc",
        triggers=[],
        template_body="body",
        token_count=5,
        file_path=Path("/tmp/test.md"),
        assets_dir=Path("/tmp/my-skill/"),
    )
    assert skill.assets_dir == Path("/tmp/my-skill/")


def test_skill_definition_backward_compatible():
    """Existing SkillDefinition instantiation without assets_dir still works."""
    skill = SkillDefinition(
        name="backward-compat",
        description="Tests backward compatibility",
        triggers=["/test"],
        source=SkillSource.AUTHORED,
        template_body="Do the thing.",
        token_count=5,
        file_path=Path("/tmp/backward.md"),
    )
    assert skill.name == "backward-compat"
    assert skill.assets_dir is None


def test_skill_definition_assets_dir_model_dump():
    """model_dump() includes assets_dir field."""
    skill = SkillDefinition(
        name="test",
        description="desc",
        triggers=[],
        template_body="body",
        token_count=5,
        file_path=Path("/tmp/test.md"),
        assets_dir=Path("/tmp/assets/"),
    )
    data = skill.model_dump()
    assert "assets_dir" in data
    assert data["assets_dir"] == Path("/tmp/assets/")
