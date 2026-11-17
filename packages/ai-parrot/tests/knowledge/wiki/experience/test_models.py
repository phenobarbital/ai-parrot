"""Deterministic experience-memory regression tests."""

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.experience import models
from parrot.knowledge.wiki.experience.fastpath import normalize_error


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


def _recorded_payload() -> dict[str, object]:
    """Build a minimally valid recorded-lesson payload."""
    return {
        "draft": {
            "trigger": {
                "executable": "gh",
                "subcommand": "pr edit",
                "error_signature": "permission denied at /tmp/project",
                "error_excerpt": "permission denied",
                "command_example": "gh pr edit 1",
            },
            "solution": "Use the repository token.",
            "fix_example": "gh api -X PATCH repos/example/project",
        },
        "solution_rev": "a1b2c3d4",
        "tier": "repo",
        "source": "paired",
    }


def _event(kind: str, payload: dict[str, object], **overrides: object) -> dict[str, object]:
    """Build a raw event line for schema validation tests."""
    event: dict[str, object] = {
        "schema_version": 1,
        "event_id": "untrusted-input",
        "kind": kind,
        "lesson_id": "pit-123",
        "session": "session-1",
        "observation_id": "observation-1",
        "actor": "codex",
        "seat": "codex",
        "ts": "2026-11-13T12:00:00Z",
        "payload": payload,
    }
    event.update(overrides)
    return event


def test_validate_event_schemas(tmp_path: Path) -> None:
    """Validate each per-kind payload and reject malformed or oversized lines."""
    payloads = {
        "lesson.recorded": _recorded_payload(),
        "failure.observed": {
            "executable": "gh",
            "subcommand": "pr edit",
            "error_signature": "permission denied",
        },
        "lesson.injected": {"solution_rev": "a1b2c3d4", "state_at_injection": "candidate"},
        "lesson.validated": {"solution_rev": "a1b2c3d4", "via": "fix_family"},
        "lesson.refuted": {"solution_rev": "a1b2c3d4", "via": "trigger_family"},
        "lesson.confirmed": {"solution_rev": "a1b2c3d4"},
        "lesson.quarantined": {"solution_rev": "a1b2c3d4"},
        "lesson.graduated": {"solution_rev": "a1b2c3d4", "issue_id": "ledger-12", "ledger": "ai-parrot"},
        "lesson.retired": {"reason": "Issue was resolved."},
    }

    assert tuple(payloads) == models.ExperienceEventKind.__args__
    for kind, payload in payloads.items():
        event = models.validate_event(_event(kind, payload))
        assert event is not None
        assert event.kind == kind
        assert isinstance(event.payload, dict)
        assert event._shared_attestation is False

    valid = _event("lesson.retired", payloads["lesson.retired"])
    assert models.validate_event({**valid, "unknown": str(tmp_path)}) is None
    assert models.validate_event({**valid, "schema_version": 2}) is None
    assert models.validate_event({**valid, "schema_version": True}) is None
    assert models.validate_event({**valid, "schema_version": 1.0}) is None
    assert models.validate_event({**valid, "kind": "lesson.unknown"}) is None
    assert models.validate_event(_event("lesson.retired", {"reason": "closed", "unknown": True})) is None
    assert models.validate_event({**valid, "actor": "é" * 4096}) is None


def test_event_redaction_before_identity(tmp_path: Path) -> None:
    """Re-redact persisted text, reject JSON-attested provenance, and stabilize identity."""
    payload = _recorded_payload()
    draft = payload["draft"]
    assert isinstance(draft, dict)
    trigger = draft["trigger"]
    assert isinstance(trigger, dict)
    trigger["error_excerpt"] = "Authorization: Bearer top-secret-token"
    draft["solution"] = f"Use token at {tmp_path}/secret"
    draft["fix_example"] = "API_TOKEN=abcdefghijklmnopqrstuvwxyz gh pr edit 1"

    event = models.validate_event(_event("lesson.recorded", payload))
    assert event is not None
    rendered = str(event.model_dump(mode="json"))
    assert "top-secret-token" not in rendered
    assert "abcdefghijklmnopqrstuvwxyz" not in rendered
    assert "[REDACTED]" in rendered
    assert event.event_id != "untrusted-input"
    assert models.validate_event(event.model_dump(mode="json")) == event
    assert models.validate_event({**event.model_dump(mode="json"), "_shared_attestation": True}) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/home/alice/repo/x.py", "~/repo/x.py"),
        ("PYTHONPATH=/home/alice/p:/home/alice/q", "PYTHONPATH=~/p:~/q"),
        ("/Users/bob", "~"),
        ("/var/home/carol/.cache", "~/.cache"),
        ("C:/Users/dave/src", "~/src"),
        ("(/home/alice)", "(~)"),
        ("src/home/alice/x", "src/home/alice/x"),
        ("/srv/home/alice", "/srv/home/alice"),
        ("/tmp/project", "/tmp/project"),
        ("~/x", "~/x"),
    ],
)
def test_strip_home_normalizes_home_prefixes(raw: str, expected: str) -> None:
    """Replace home-directory prefixes with ``~`` idempotently, leaving other paths alone."""
    assert models._strip_home(raw) == expected
    assert models._strip_home(expected) == expected
    assert models._strip_home({"k": [raw]}) == {"k": [expected]}


def test_event_strips_home_paths_before_identity() -> None:
    """Drop home prefixes from stored text without changing the failure signature or identity."""
    error = "No such file: /home/alice/repo/missing.py"
    payload = _recorded_payload()
    draft = payload["draft"]
    assert isinstance(draft, dict)
    trigger = draft["trigger"]
    assert isinstance(trigger, dict)
    trigger["error_signature"] = error
    trigger["error_excerpt"] = error
    trigger["command_example"] = "/home/alice/repo/.venv/bin/python -m pytest"
    draft["solution"] = "Run the shared interpreter at /home/alice/repo/.venv/bin/python."
    draft["fix_example"] = "PYTHONPATH=/home/alice/repo/src pytest"
    draft["scope_paths"] = ["/home/alice/repo/src/app.py"]

    event = models.validate_event(_event("lesson.recorded", payload))

    assert event is not None
    rendered = json.dumps(event.model_dump(mode="json"))
    assert "/home/alice" not in rendered
    assert "~/repo/.venv/bin/python" in rendered
    assert event.payload["draft"]["trigger"]["error_signature"] == normalize_error(error)
    assert models.validate_event(event.model_dump(mode="json")) == event


def test_solution_revision_identity(tmp_path: Path) -> None:
    """Hash normalized solution text and the parsed fix-command family only."""
    first = models.LessonDraft(
        trigger=models.LessonTrigger(executable="gh"),
        solution="  Use   the existing token.  ",
        fix_example=f"gh pr edit {tmp_path.name}",
    )
    whitespace_variant = first.model_copy(update={"solution": "Use the existing token."})
    other_family = first.model_copy(update={"fix_example": "gh api -X PATCH repos/example/project"})

    revision = models.solution_rev_for(first)
    assert len(revision) == 8
    assert revision == models.solution_rev_for(whitespace_variant)
    assert revision != models.solution_rev_for(other_family)
