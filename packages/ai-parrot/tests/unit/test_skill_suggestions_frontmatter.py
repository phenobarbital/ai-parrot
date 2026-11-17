"""Unit tests for skill follow-up suggestion frontmatter."""

import pytest

from parrot.skills.parsers import parse_skill_file

SKILL = """---
name: sales-analyst
description: Monthly sales analysis helpers
triggers: [/sales]
suggestions:
  - label: "vs last month"
    prompt: "Compare the same figures against the previous month"
  - label: "As KPI"
    prompt: "Show the headline number as a KPI card"
    output_mode: card
---
Body.
"""


def test_skill_frontmatter_suggestions_parsed(tmp_path):
    f = tmp_path / "sales.md"
    f.write_text(SKILL)
    skill = parse_skill_file(f)

    assert [suggestion.label for suggestion in skill.suggestions] == ["vs last month", "As KPI"]
    assert skill.suggestions[1].output_mode == "card"


def test_skill_frontmatter_suggestions_absent(tmp_path):
    f = tmp_path / "sales.md"
    f.write_text(
        SKILL.replace(
            'suggestions:\n  - label: "vs last month"\n    prompt: "Compare the same figures against the previous month"\n  - label: "As KPI"\n    prompt: "Show the headline number as a KPI card"\n    output_mode: card\n',
            "",
        )
    )

    skill = parse_skill_file(f)

    assert skill.suggestions == []


def test_skill_frontmatter_suggestions_not_a_list(tmp_path):
    f = tmp_path / "sales.md"
    f.write_text(
        SKILL.replace(
            'suggestions:\n  - label: "vs last month"\n    prompt: "Compare the same figures against the previous month"\n  - label: "As KPI"\n    prompt: "Show the headline number as a KPI card"\n    output_mode: card',
            "suggestions: x",
        )
    )

    with pytest.raises(ValueError, match="suggestions") as exc_info:
        parse_skill_file(f)

    assert str(f) in str(exc_info.value)
