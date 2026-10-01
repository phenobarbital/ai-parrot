"""LLM contract text teaches the display hints (FEAT-623, TASK-4001)."""

import pytest

from parrot.bots.prompts import INFOGRAPHIC_SYSTEM_PROMPT_ADDON
from parrot.models.infographic import BlockType
from parrot.models.infographic_templates import BlockSpec, InfographicTemplate

REQUIRED_TERMS = ["format", "unit", "0.683", "columns", "axis", "y_axis_labels"]


def _template() -> InfographicTemplate:
    return InfographicTemplate(
        name="t",
        description="d",
        block_specs=[BlockSpec(block_type=BlockType.HERO_CARD, required=True)],
    )


@pytest.mark.parametrize("term", REQUIRED_TERMS)
def test_addon_mentions_hints(term):
    assert term in INFOGRAPHIC_SYSTEM_PROMPT_ADDON


def test_addon_keeps_string_example_and_adds_numeric():
    assert '"value": "$3.7M"' in INFOGRAPHIC_SYSTEM_PROMPT_ADDON
    assert '"value": 3700000' in INFOGRAPHIC_SYSTEM_PROMPT_ADDON
    assert "never" in INFOGRAPHIC_SYSTEM_PROMPT_ADDON and '"68.3%"' in INFOGRAPHIC_SYSTEM_PROMPT_ADDON


@pytest.mark.parametrize("term", REQUIRED_TERMS)
def test_template_instruction_mentions_hints(term):
    assert term in _template().to_prompt_instruction()


def test_template_instruction_keeps_type_line():
    assert "Each block must include the 'type' field" in _template().to_prompt_instruction()
