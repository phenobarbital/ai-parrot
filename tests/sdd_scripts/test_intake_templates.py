"""Executable contract for the FEAT-577 intake schemas (spec §4, Modules 1-2)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, Draft202012Validator, ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TPL = _REPO_ROOT / "sdd" / "templates"
_INTAKE_SCHEMA = _TPL / "intake.schema.json"
_STATE_SCHEMA = _TPL / "state.schema.json"


@pytest.fixture
def intake_schema() -> dict:
    return json.loads(_INTAKE_SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture
def state_schema() -> dict:
    return json.loads(_STATE_SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture
def intake_sample() -> dict:
    """A complete intake.json record at phase 'rounds_complete' with full research."""
    return {
        "schema_version": "1.0",
        "run_id": "20260919T101500Z-12345",
        "feature_slug": "my-feature",
        "feat_id": None,
        "started_at": "2026-09-19T10:15:00Z",
        "updated_at": "2026-09-19T10:45:00Z",
        "phase": "rounds_complete",
        "flow": {"type": "feature", "base_branch": "dev"},
        "research": {
            "depth": "full",
            "gate": True,
            "budget": "default",
            "degraded_from": None,
            "failure_reason": None,
            "synthesis_path": "synthesis.json",
            "handoff_declined": False,
        },
        "answers": {
            "feature_name": "My Feature",
            "projects": ["ai-parrot"],
            "tags": [],
            "overview": "A feature that does something useful.",
            "problem": "Users cannot currently do this thing.",
            "why_important": "It unblocks a whole workflow.",
            "jira": {"mode": "existing", "key": "NAV-1234"},
        },
        "rounds": [
            {
                "round": 1,
                "questions": [
                    {"id": "Q1", "question": "What is the primary user?", "source": "gap", "answer": "Engineers."},
                ],
            },
            {
                "round": 2,
                "questions": [
                    {
                        "id": "Q2",
                        "question": "Should this integrate with X?",
                        "source": "synthesis",
                        "answer": None,
                    },
                ],
            },
        ],
        "spec_path": None,
        "errors": [],
    }


@pytest.fixture
def intake_state_sample() -> dict:
    """A state.json for an intake-mode research run: feat_id None, source.kind 'intake'."""
    return {
        "schema_version": "1.0",
        "feat_id": None,
        "feature_slug": "my-feature",
        "started_at": "2026-09-19T10:15:00Z",
        "updated_at": "2026-09-19T10:16:00Z",
        "source": {
            "kind": "intake",
            "raw_path": "sdd/state/.intake/my-feature-20260919T101500Z-12345/source.md",
        },
        "mode": "auto",
        "phase": "source_resolved",
        "phases": {},
        "budget": {
            "profile": "default",
            "max_files_read": 40,
            "max_grep_calls": 25,
            "max_git_calls": 10,
            "max_depth": 2,
            "max_wall_seconds": 300,
        },
        "consumed": {
            "files_read": 0,
            "grep_calls": 0,
            "git_calls": 0,
            "wall_seconds": 0,
        },
    }


def _old_state_schema(new: dict) -> dict:
    """The pre-FEAT-577 state schema, derived by narrowing the widened one."""
    old = copy.deepcopy(new)
    old["properties"]["feat_id"]["type"] = "string"
    old["properties"]["source"]["properties"]["kind"]["enum"] = ["jira", "inline", "file"]
    return old


def test_intake_schema_is_valid_draft_2020_12(intake_schema: dict) -> None:
    Draft202012Validator.check_schema(intake_schema)


def test_intake_sample_validates(intake_schema: dict, intake_sample: dict) -> None:
    Draft202012Validator(intake_schema).validate(intake_sample)


def test_intake_rejects_bad_feat_id(intake_schema: dict, intake_sample: dict) -> None:
    validator = Draft202012Validator(intake_schema)

    bad = copy.deepcopy(intake_sample)
    bad["feat_id"] = "FEAT-1"
    with pytest.raises(ValidationError):
        validator.validate(bad)

    null_ok = copy.deepcopy(intake_sample)
    null_ok["feat_id"] = None
    validator.validate(null_ok)

    valid_ok = copy.deepcopy(intake_sample)
    valid_ok["feat_id"] = "FEAT-123"
    validator.validate(valid_ok)


def test_intake_rejects_unknown_keys(intake_schema: dict, intake_sample: dict) -> None:
    validator = Draft202012Validator(intake_schema)

    top_level = copy.deepcopy(intake_sample)
    top_level["unexpected_top_level_key"] = "nope"
    with pytest.raises(ValidationError):
        validator.validate(top_level)

    nested = copy.deepcopy(intake_sample)
    nested["research"]["unexpected_nested_key"] = "nope"
    with pytest.raises(ValidationError):
        validator.validate(nested)


def test_intake_rejects_bad_enums(intake_schema: dict, intake_sample: dict) -> None:
    validator = Draft202012Validator(intake_schema)

    bad_phase = copy.deepcopy(intake_sample)
    bad_phase["phase"] = "not_a_real_phase"
    with pytest.raises(ValidationError):
        validator.validate(bad_phase)

    bad_depth = copy.deepcopy(intake_sample)
    bad_depth["research"]["depth"] = "medium"
    with pytest.raises(ValidationError):
        validator.validate(bad_depth)

    bad_jira_mode = copy.deepcopy(intake_sample)
    bad_jira_mode["answers"]["jira"]["mode"] = "maybe"
    with pytest.raises(ValidationError):
        validator.validate(bad_jira_mode)

    bad_question_source = copy.deepcopy(intake_sample)
    bad_question_source["rounds"][0]["questions"][0]["source"] = "hallucinated"
    with pytest.raises(ValidationError):
        validator.validate(bad_question_source)


def test_intake_schema_accepts_handed_off(intake_schema: dict, intake_sample: dict) -> None:
    handed_off = copy.deepcopy(intake_sample)
    handed_off["phase"] = "handed_off"
    handed_off["research"]["handoff_declined"] = True
    Draft202012Validator(intake_schema).validate(handed_off)


def test_state_schema_accepts_null_feat_id_and_intake_kind(state_schema: dict, intake_state_sample: dict) -> None:
    Draft7Validator(state_schema).validate(intake_state_sample)


def test_existing_state_files_still_validate(state_schema: dict) -> None:
    """Widening is additive: every committed state.json valid under the old schema stays valid.

    52 of 76 committed files already failed the pre-FEAT-577 schema (missing schema_version,
    undeclared wiki_available, ...). They are pre-existing drift, so they are excluded by
    construction rather than by a hard-coded list.
    """
    old_schema = _old_state_schema(state_schema)
    old_validator = Draft7Validator(old_schema)
    new_validator = Draft7Validator(state_schema)

    state_files = sorted((_REPO_ROOT / "sdd" / "state").glob("FEAT-*/state.json"))
    if not state_files:
        pytest.skip("no committed sdd/state/FEAT-*/state.json files found")

    checked_any_old_valid = False
    for path in state_files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not old_validator.is_valid(doc):
            continue
        checked_any_old_valid = True
        assert new_validator.is_valid(doc), f"{path} was valid under the old schema but not the widened one"

    assert checked_any_old_valid, "expected at least one committed state.json to be valid under the old schema"
