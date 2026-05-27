"""
Unit tests for parrot.skills.prompt.render_skills_prompt_layer().

Tests the Tier 1 static prompt injection mechanism added in TASK-1292.
"""
from pathlib import Path

import pytest

from parrot.bots.prompts import RenderPhase
from parrot.skills.file_registry import SkillFileRegistry
from parrot.skills.models import SkillDefinition, SkillSource
from parrot.skills.prompt import render_skills_prompt_layer


@pytest.fixture
def empty_registry(tmp_path):
    """Empty SkillFileRegistry."""
    return SkillFileRegistry(skills_dir=tmp_path)


@pytest.fixture
def populated_registry(tmp_path):
    """SkillFileRegistry with two skills: one with triggers, one without."""
    registry = SkillFileRegistry(skills_dir=tmp_path)
    registry.add(SkillDefinition(
        name="summarize",
        description="Summarize text",
        triggers=["/resumen"],
        source=SkillSource.AUTHORED,
        template_body="Summarize.",
        token_count=3,
        file_path=tmp_path / "s.md",
    ))
    registry.add(SkillDefinition(
        name="extract-pdf",
        description="Extract tables from PDF",
        triggers=[],
        source=SkillSource.AUTHORED,
        template_body="Extract.",
        token_count=3,
        file_path=tmp_path / "e.md",
    ))
    return registry


def test_render_empty_registry(empty_registry):
    """Empty registry returns PromptLayer with empty template."""
    layer = render_skills_prompt_layer(empty_registry)
    assert layer.template == ""
    assert layer.phase == RenderPhase.CONFIGURE
    assert layer.name == "available_skills"


def test_render_phase_is_configure(populated_registry):
    """PromptLayer always has phase=RenderPhase.CONFIGURE."""
    layer = render_skills_prompt_layer(populated_registry)
    assert layer.phase == RenderPhase.CONFIGURE


def test_render_name_is_available_skills(populated_registry):
    """PromptLayer.name is 'available_skills'."""
    layer = render_skills_prompt_layer(populated_registry)
    assert layer.name == "available_skills"


def test_render_basic_xml_structure(populated_registry):
    """Template contains XML block with skill names and descriptions."""
    layer = render_skills_prompt_layer(populated_registry)
    assert "<available_skills>" in layer.template
    assert "</available_skills>" in layer.template
    assert 'name="summarize"' in layer.template
    assert 'name="extract-pdf"' in layer.template
    assert "Summarize text" in layer.template
    assert "Extract tables from PDF" in layer.template


def test_render_trigger_hint_present(populated_registry):
    """Skills with triggers include 'Also triggerable via' hint."""
    layer = render_skills_prompt_layer(populated_registry)
    assert "Also triggerable via: /resumen" in layer.template


def test_render_no_trigger_hint_for_no_triggers(populated_registry):
    """Skills without triggers do NOT include trigger hint."""
    layer = render_skills_prompt_layer(populated_registry)
    lines = layer.template.split("\n")
    # Find the section for extract-pdf and confirm no trigger line
    in_extract = False
    for line in lines:
        if 'name="extract-pdf"' in line:
            in_extract = True
        elif in_extract and "</skill>" in line:
            break
        elif in_extract:
            assert "triggerable" not in line, f"Unexpected trigger hint in: {line!r}"


def test_render_load_skill_hint(populated_registry):
    """Each skill entry includes a load_skill() hint."""
    layer = render_skills_prompt_layer(populated_registry)
    assert 'Load with: load_skill(name="summarize")' in layer.template
    assert 'Load with: load_skill(name="extract-pdf")' in layer.template


def test_render_max_entries_truncates(populated_registry):
    """max_skills parameter truncates to N entries."""
    layer = render_skills_prompt_layer(populated_registry, max_skills=1)
    assert layer.template.count("<skill ") == 1


def test_render_default_priority(populated_registry):
    """Default priority is 45 (between USER_SESSION=40 and TOOLS=50)."""
    layer = render_skills_prompt_layer(populated_registry)
    assert layer.priority == 45


def test_render_custom_priority(populated_registry):
    """Custom priority parameter is used."""
    layer = render_skills_prompt_layer(populated_registry, priority=30)
    assert layer.priority == 30


def test_render_empty_after_max_zero(tmp_path):
    """max_skills=0 returns a layer with no skill entries."""
    registry = SkillFileRegistry(skills_dir=tmp_path)
    registry.add(SkillDefinition(
        name="test", description="Test",
        triggers=[], source=SkillSource.AUTHORED,
        template_body="Body.", token_count=3,
        file_path=tmp_path / "test.md",
    ))
    layer = render_skills_prompt_layer(registry, max_skills=0)
    assert "<skill " not in layer.template
