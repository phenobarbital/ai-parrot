"""Deterministic experience-memory reducer regression tests."""

from pathlib import Path

import pytest

from parrot.knowledge.wiki.experience.models import ExperienceConfig, ExperienceEvent
from parrot.knowledge.wiki.experience.reducer import match_score, reduce_events


LESSON_ID = "pit-reducer"
REVISION_ONE = "rev-one"
REVISION_TWO = "rev-two"


def _event(
    kind: str,
    payload: dict[str, object],
    event_id: str,
    session: str,
    *,
    shared: bool = False,
    ts: str = "2026-11-13T12:00:00Z",
) -> ExperienceEvent:
    """Build a deterministic event for reduction tests."""
    event = ExperienceEvent(
        event_id=event_id,
        kind=kind,
        lesson_id=LESSON_ID,
        session=session,
        actor="codex",
        ts=ts,
        payload=payload,
    )
    event._shared_attestation = shared
    return event


def _record(
    revision: str = REVISION_ONE,
    session: str = "recording-session",
    *,
    event_id: str = "record",
    ts: str = "2026-11-13T12:00:00Z",
) -> ExperienceEvent:
    """Build a recorded lesson event with a revision-specific solution."""
    return _event(
        "lesson.recorded",
        {
            "draft": {
                "trigger": {
                    "executable": "gh",
                    "subcommand": "pr edit",
                    "error_signature": "permission denied token",
                },
                "solution": f"Use the repository token for {revision}.",
                "fix_example": "gh pr edit 1",
            },
            "solution_rev": revision,
            "tier": "repo",
            "source": "authored",
        },
        event_id,
        session,
        ts=ts,
    )


def _evidence(kind: str, revision: str, event_id: str, session: str, *, shared: bool = False) -> ExperienceEvent:
    """Build a revision-scoped evidence or lifecycle event."""
    payload: dict[str, object] = {"solution_rev": revision}
    if kind in {"lesson.validated", "lesson.refuted"}:
        payload["via"] = "trigger_family"
    return _event(kind, payload, event_id, session, shared=shared)


def test_reduce_candidate_to_confirmed(tmp_path: Path) -> None:
    """Ignore recording-session validation and confirm independent evidence."""
    config = ExperienceConfig(confirm_sessions=2)
    events = [
        _record(),
        _evidence("lesson.validated", REVISION_ONE, "self-validation", "recording-session"),
        _evidence("lesson.validated", REVISION_ONE, "validation-one", "session-one"),
    ]

    candidate = reduce_events(events, config)[LESSON_ID]
    assert candidate.state == "candidate"
    assert candidate.validations == 1

    confirmed = reduce_events(events + [_evidence("lesson.validated", REVISION_ONE, "validation-two", "session-two")], config)[
        LESSON_ID
    ]
    assert confirmed.state == "confirmed"
    assert confirmed.validations == 2


def test_reduce_refutations_quarantine(tmp_path: Path) -> None:
    """Keep quarantine sticky even when validation evidence is later added."""
    events = [
        _record(),
        _evidence("lesson.refuted", REVISION_ONE, "refutation-one", "session-one"),
        _evidence("lesson.refuted", REVISION_ONE, "refutation-two", "session-two"),
        _evidence("lesson.validated", REVISION_ONE, "validation-one", "session-three"),
        _evidence("lesson.validated", REVISION_ONE, "validation-two", "session-four"),
        _evidence("lesson.validated", REVISION_ONE, "validation-three", "session-five"),
    ]

    lesson = reduce_events(events, ExperienceConfig())[LESSON_ID]
    assert lesson.state == "quarantined"
    assert lesson.refutations == 2


def test_reduce_permutation_invariant(tmp_path: Path) -> None:
    """Produce identical reductions for fifty rotations with a duplicate event."""
    events = [
        _record(),
        _record(session="rediscovery-session", event_id="rediscovery", ts="2026-11-13T12:01:00Z"),
        _evidence("lesson.injected", REVISION_ONE, "injected", "session-one"),
        _evidence("lesson.validated", REVISION_ONE, "validation", "session-two"),
    ]
    events.append(events[2].model_copy(deep=True))
    expected = reduce_events(events, ExperienceConfig())[LESSON_ID].model_dump()

    for offset in range(50):
        rotated = [events[(offset + index) % len(events)] for index in range(len(events))]
        assert reduce_events(rotated, ExperienceConfig())[LESSON_ID].model_dump() == expected

    assert expected["validations"] == 2
    assert expected["hits"] == 1


def test_reduce_ignores_forged_local_attestation(tmp_path: Path) -> None:
    """Honor lifecycle attestations only when the loader marked them shared."""
    local_confirmation = _evidence("lesson.confirmed", REVISION_ONE, "forged-confirmation", "local-session")
    local_quarantine = _evidence("lesson.quarantined", REVISION_ONE, "forged-quarantine", "local-session")
    candidate = reduce_events([_record(), local_confirmation, local_quarantine], ExperienceConfig())[LESSON_ID]
    assert candidate.state == "candidate"

    shared = _evidence("lesson.confirmed", REVISION_ONE, "shared-confirmation", "shared-session", shared=True)
    confirmed = reduce_events([_record(), local_confirmation, local_quarantine, shared], ExperienceConfig())[LESSON_ID]
    assert confirmed.state == "confirmed"


def test_reduce_retired_is_terminal(tmp_path: Path) -> None:
    """Retire a known signature regardless of other lifecycle evidence."""
    events = [
        _record(),
        _evidence("lesson.confirmed", REVISION_ONE, "shared-confirmation", "shared-session", shared=True),
        _event("lesson.retired", {"reason": "Fixed upstream."}, "retired", "maintainer"),
    ]

    lesson = reduce_events(events, ExperienceConfig())[LESSON_ID]
    assert lesson.state == "retired"


def test_solution_revision_owns_evidence(tmp_path: Path) -> None:
    """Choose the revision with more evidence without inheriting another's counts."""
    events = [
        _record(REVISION_ONE, event_id="record-one"),
        _record(REVISION_TWO, event_id="record-two", ts="2026-11-13T12:01:00Z"),
        _evidence("lesson.validated", REVISION_ONE, "old-validation", "old-session"),
        _evidence("lesson.injected", REVISION_TWO, "new-injected", "new-session"),
        _evidence("lesson.validated", REVISION_TWO, "new-validation-one", "new-session-one"),
        _evidence("lesson.validated", REVISION_TWO, "new-validation-two", "new-session-two"),
    ]

    lesson = reduce_events(events, ExperienceConfig())[LESSON_ID]
    assert lesson.solution_rev == REVISION_TWO
    assert lesson.revisions == [REVISION_TWO, REVISION_ONE]
    assert lesson.validations == 2
    assert lesson.hits == 1


def test_match_requires_family_and_jaccard(tmp_path: Path) -> None:
    """Require an exact command family and score normalized-error token overlap."""
    lesson = reduce_events([_record()], ExperienceConfig())[LESSON_ID]

    assert match_score(lesson, "git", "pr edit", "permission denied token") == 0.0
    assert match_score(lesson, "gh", "pr list", "permission denied token") == 0.0
    assert match_score(lesson, "gh", "pr edit", "permission denied token") == 1.0
    assert match_score(lesson, "gh", "pr edit", "permission denied missing") == pytest.approx(0.5)
    assert match_score(lesson, "gh", "pr edit", "network timeout") == 0.0
