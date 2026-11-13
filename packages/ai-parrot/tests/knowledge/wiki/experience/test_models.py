"""Deterministic experience-memory regression tests."""

from pathlib import Path

import pytest

from parrot.knowledge.wiki.experience import models


def _lesson(
    draft: models.LessonDraft,
    *,
    tier: str = "repo",
    state: str = "candidate",
    **extra: object,
) -> models.Lesson:
    """Build a complete reduced lesson for schema-boundary tests."""
    return models.Lesson(
        lesson_id="pit-123",
        draft=draft,
        solution_rev="solution-1",
        revisions=["solution-1"],
        tier=tier,
        state=state,
        hits=0,
        validations=0,
        refutations=0,
        sessions=1,
        recorded_by="codex",
        recorded_at="2026-11-13T12:00:00Z",
        **extra,
    )


def test_domain_defaults_and_factories(tmp_path: Path) -> None:
    """Verify domain defaults, literal sets, and independent list factories."""
    first = models.LessonDraft(trigger=models.LessonTrigger(executable="gh"), solution="Use the existing branch.")
    second = models.LessonDraft(trigger=models.LessonTrigger(executable="gh"), solution="Use the existing branch.")
    first.scope_paths.append(str(tmp_path / "first.py"))

    assert first.category == "pitfall"
    assert first.trigger.model_dump() == {
        "executable": "gh",
        "subcommand": "",
        "error_signature": "",
        "error_excerpt": "",
        "command_example": "",
    }
    assert second.scope_paths == []

    first_config = models.ExperienceConfig()
    second_config = models.ExperienceConfig()
    first_config.pairing_excluded_executables.append("custom-tool")
    assert second_config.model_dump() == {
        "enabled": True,
        "confirm_sessions": 2,
        "quarantine_refutations": 2,
        "graduate_hits": 5,
        "graduate_sessions": 3,
        "brief_max_entries": 5,
        "brief_token_budget": 400,
        "inject_min_score": 0.35,
        "advice_cooldown_seconds": 600,
        "max_triggers_bytes": 262144,
        "max_transcript_tail_bytes": 262144,
        "max_session_pending": 32,
        "pairing_excluded_executables": [
            "pytest",
            "ruff",
            "mypy",
            "black",
            "pylint",
            "vitest",
            "cargo",
            "grep",
            "rg",
            "ls",
            "cat",
            "find",
            "test",
            "head",
            "tail",
            "wc",
        ],
    }

    for tier in ("repo", "global"):
        for state in ("candidate", "confirmed", "quarantined", "retired"):
            assert _lesson(second, tier=tier, state=state).tier == tier
            assert _lesson(second, tier=tier, state=state).state == state

    assert models.LessonCategory.__args__ == ("pitfall",)
    assert models.LessonState.__args__ == ("candidate", "confirmed", "quarantined", "retired")
    assert models.LessonTier.__args__ == ("repo", "global")
    assert models.LessonSource.__args__ == ("paired", "authored", "mined")

    with pytest.raises(ValueError):
        models.LessonDraft(trigger=models.LessonTrigger(executable="gh"), solution="x", category="invalid")
    with pytest.raises(ValueError):
        _lesson(second, tier="invalid")
    with pytest.raises(ValueError):
        _lesson(second, state="invalid")


def test_domain_extra_fields_forbidden(tmp_path: Path) -> None:
    """Verify every input model except reduced lessons rejects unknown fields."""
    draft = models.LessonDraft(trigger=models.LessonTrigger(executable="git"), solution=str(tmp_path))

    with pytest.raises(ValueError):
        models.LessonTrigger(executable="git", unknown=True)
    with pytest.raises(ValueError):
        models.LessonDraft(trigger=models.LessonTrigger(executable="git"), solution="x", unknown=True)
    with pytest.raises(ValueError):
        models.CommandOutcome(command="git status", ok=True, unknown=True)
    with pytest.raises(ValueError):
        models.ExperienceConfig(unknown=True)

    lesson = _lesson(draft, unexpected="accepted-by-default")
    assert lesson.model_extra is None


def test_command_outcome_unknown(tmp_path: Path) -> None:
    """Verify command outcomes preserve their tri-state execution result."""
    outcomes = [
        models.CommandOutcome(command=f"git status {tmp_path.name}", ok=True),
        models.CommandOutcome(command="git status", ok=False, error="failed"),
        models.CommandOutcome(command="git status", ok=None, observation_id="missing-host-status"),
    ]

    assert [outcome.ok for outcome in outcomes] == [True, False, None]
    assert outcomes[2].model_dump() == {
        "command": "git status",
        "ok": None,
        "error": "",
        "observation_id": "missing-host-status",
    }
