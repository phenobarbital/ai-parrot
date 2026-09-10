"""Executable contract for the FEAT-545 templates (spec §4)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TPL = _REPO_ROOT / "sdd" / "templates"
_SCHEMA = _TPL / "design_research.schema.json"
_PROMPT = _TPL / "design_research.prompt.md"
_PLACEHOLDERS = {
    "problem_statement",
    "constraints_and_goals",
    "recommended_option_or_scope",
    "code_context_paths",
    "open_questions",
    "question",
}


@pytest.fixture
def schema() -> dict:
    return json.loads(_SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture
def sample_suggestions() -> dict:
    return {
        "summary": "Two suggestions on the accepted design.",
        "suggestions": [
            {
                "id": "S1",
                "kind": "architecture",
                "title": "Stage output under sdd/state",
                "rationale": "artifacts/ is gitignored.",
                "affected_paths": [".gitignore"],
                "risk": "low",
                "confidence": "high",
            },
            {
                "id": "S2",
                "kind": "testing",
                "title": "Add twin parity test",
                "rationale": "Twins drift silently.",
                "affected_paths": [".agent/workflows/sdd-spec.md"],
                "risk": "medium",
                "confidence": "medium",
            },
        ],
    }


def test_schema_is_valid_draft_2020_12(schema: dict) -> None:
    Draft202012Validator.check_schema(schema)


def test_sample_suggestions_validate(schema: dict, sample_suggestions: dict) -> None:
    Draft202012Validator(schema).validate(sample_suggestions)


def test_unknown_kind_rejected(schema: dict, sample_suggestions: dict) -> None:
    sample_suggestions["suggestions"][0]["kind"] = "perf"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(sample_suggestions)


def test_prompt_has_all_placeholders() -> None:
    found = set(re.findall(r"{{([a-z_]+)}}", _PROMPT.read_text(encoding="utf-8")))
    assert found == _PLACEHOLDERS


def test_task_template_has_blueprint_section() -> None:
    text = (_TPL / "task.md").read_text(encoding="utf-8")
    for needle in ("## Implementation Blueprint", "### Steps (in order)", "### FILL IN checklist"):
        assert needle in text, needle
    assert text.index("## Implementation Blueprint") < text.index("## Acceptance Criteria")


def test_spec_template_has_skeleton_and_section_9() -> None:
    text = (_TPL / "spec.md").read_text(encoding="utf-8")
    assert "Interface Skeleton" in text
    assert "## 9. Design Research Cross-Check" in text
    assert (
        text.index("## 8. Open Questions")
        < text.index("## 9. Design Research Cross-Check")
        < text.index("## Revision History")
    )


def test_task_template_modify_block_states_occurrence_count() -> None:
    text = (_TPL / "task.md").read_text(encoding="utf-8")
    assert "# occurrences:" in text
