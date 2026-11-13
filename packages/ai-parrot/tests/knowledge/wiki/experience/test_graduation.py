"""Deterministic experience-memory graduation regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.experience.fastpath import append_event
from parrot.knowledge.wiki.experience.graduation import graduate, graduation_issue_id
from parrot.knowledge.wiki.experience.models import Lesson, LessonDraft, LessonTrigger, validate_event
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.ledger.service import LedgerService


def _services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ExperienceService, LedgerService, Path, Path]:
    """Create isolated experience and ledger services sharing one root."""
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    plane = primary / ".parrot" / "experience"
    plane.mkdir(parents=True)
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    return (
        ExperienceService.from_root(primary),
        LedgerService.from_dir(primary / ".parrot" / "ledger"),
        primary,
        plane,
    )


def _event(
    *,
    kind: str,
    lesson_id: str,
    session: str,
    payload: dict[str, str],
    sequence: int,
) -> dict[str, object]:
    """Build one validated event mapping with deterministic test time."""
    event = validate_event(
        {
            "schema_version": 1,
            "event_id": "",
            "kind": kind,
            "lesson_id": lesson_id,
            "session": session,
            "actor": "agent:test",
            "ts": f"2026-11-13T12:{sequence // 60:02d}:{sequence % 60:02d}Z",
            "payload": payload,
        }
    )
    assert event is not None
    return event.model_dump(mode="json")


def _append_shared_confirmation(primary: Path, lesson: Lesson, *, sequence: int) -> None:
    """Append a reviewed confirmation for the lesson's current revision."""
    shared = primary / "sdd" / "experience" / "lessons" / "confirmed.jsonl"
    shared.parent.mkdir(parents=True, exist_ok=True)
    event = _event(
        kind="lesson.confirmed",
        lesson_id=lesson.lesson_id,
        session=f"review-{sequence}",
        payload={"solution_rev": lesson.solution_rev},
        sequence=sequence,
    )
    with shared.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")


def _append_injections(
    plane: Path,
    lesson: Lesson,
    *,
    count: int,
    offset: int = 10,
    session_count: int = 3,
) -> None:
    """Append current-revision injection hits across three sessions."""
    for index in range(count):
        event = _event(
            kind="lesson.injected",
            lesson_id=lesson.lesson_id,
            session=f"hit-{index % session_count}",
            payload={"solution_rev": lesson.solution_rev, "state_at_injection": "confirmed"},
            sequence=offset + index,
        )
        assert append_event(plane, event)


async def _record_lesson(service: ExperienceService, *, solution: str = "Use the supported command.") -> Lesson:
    """Record and materialize one candidate lesson."""
    lesson_id = await service.record(
        LessonDraft(
            trigger=LessonTrigger(executable="gh", subcommand="pr edit", error_signature="project cards unsupported"),
            symptom="The command rejects project-card fields.",
            solution=solution,
            fix_example="gh api graphql",
            scope_paths=["src/release.py"],
        ),
        session="recording",
        source="authored",
    )
    assert lesson_id
    await service.refresh()
    lesson = await service.get_lesson(lesson_id)
    assert lesson is not None
    return lesson


async def _qualifying_lesson(service: ExperienceService, primary: Path, plane: Path) -> Lesson:
    """Create one confirmed lesson exactly at both graduation thresholds."""
    lesson = await _record_lesson(service)
    _append_shared_confirmation(primary, lesson, sequence=1)
    _append_injections(plane, lesson, count=service.config.graduate_hits)
    await service.refresh()
    qualified = await service.get_lesson(lesson.lesson_id)
    assert qualified is not None
    assert qualified.state == "confirmed"
    assert qualified.hits == service.config.graduate_hits
    assert qualified.sessions >= service.config.graduate_sessions
    return qualified


@pytest.mark.asyncio
async def test_graduate_opens_one_issue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Open one deterministic issue only after both threshold boundaries."""
    service, ledger, primary, plane = _services(tmp_path, monkeypatch)
    lesson = await _record_lesson(service)
    _append_shared_confirmation(primary, lesson, sequence=1)
    _append_injections(plane, lesson, count=service.config.graduate_hits - 1)
    await service.refresh()

    assert await graduate(service, ledger, ledger_name=primary.name) == []
    assert await ledger.get_issue(graduation_issue_id(lesson)) is None

    _append_injections(plane, lesson, count=1, offset=30)
    await service.refresh()
    current = await service.get_lesson(lesson.lesson_id)
    assert current is not None
    assert await graduate(service, ledger, ledger_name=primary.name) == [lesson.lesson_id]
    issue_id = graduation_issue_id(current)
    issue = await ledger.get_issue(issue_id)
    assert issue is not None
    assert issue["kind"] == "tech_debt"
    assert issue["severity"] == "low"
    assert issue["discovered_from"] == f"experience:{lesson.lesson_id}"

    await service.refresh()
    assert await graduate(service, ledger, ledger_name=primary.name) == []
    assert [item["kind"] for item in await ledger.issue_history(issue_id)] == ["issue.opened"]


@pytest.mark.asyncio
async def test_graduate_recovers_after_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repair an issue-open/event-write crash without opening another issue."""
    service, ledger, primary, plane = _services(tmp_path, monkeypatch)
    lesson = await _qualifying_lesson(service, primary, plane)
    trigger = lesson.draft.trigger
    title = f"Recurring pitfall {lesson.lesson_id}: {trigger.executable} {trigger.subcommand}"
    issue_id = await ledger.open_issue(
        title,
        "Opened immediately before a simulated process crash.",
        kind="tech_debt",
        severity="low",
        discovered_from=f"experience:{lesson.lesson_id}",
        actor="agent:experience",
    )
    assert issue_id == graduation_issue_id(lesson)

    assert await graduate(service, ledger, ledger_name=primary.name) == [lesson.lesson_id]
    assert [item["kind"] for item in await ledger.issue_history(issue_id)] == ["issue.opened"]
    await service.refresh()
    repaired = await service.get_lesson(lesson.lesson_id)
    assert repaired is not None
    assert repaired.issue_id == issue_id
    assert repaired.issue_ledger == primary.name


@pytest.mark.asyncio
async def test_graduate_foreign_ledger_not_retired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never retire a lesson whose graduation event names another ledger."""
    service, ledger, primary, plane = _services(tmp_path, monkeypatch)
    lesson = await _qualifying_lesson(service, primary, plane)
    trigger = lesson.draft.trigger
    issue_id = await ledger.open_issue(
        f"Recurring pitfall {lesson.lesson_id}: {trigger.executable} {trigger.subcommand}",
        "Foreign-owned issue with a colliding deterministic identity.",
        kind="tech_debt",
        severity="low",
        discovered_from=f"experience:{lesson.lesson_id}",
        actor="agent:experience",
    )
    graduated = _event(
        kind="lesson.graduated",
        lesson_id=lesson.lesson_id,
        session="foreign-graduation",
        payload={"solution_rev": lesson.solution_rev, "issue_id": issue_id, "ledger": "other-repository"},
        sequence=40,
    )
    assert append_event(plane, graduated)
    await service.refresh()
    assert await ledger.close_issue(issue_id, "fixed", "agent:test", force=True)

    assert await graduate(service, ledger, ledger_name=primary.name) == []
    await service.refresh()
    current = await service.get_lesson(lesson.lesson_id)
    assert current is not None
    assert current.state == "confirmed"
    assert current.issue_ledger == "other-repository"


@pytest.mark.asyncio
async def test_closed_issue_retires_lesson(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retire a local lesson when its owning graduation issue is closed."""
    service, ledger, primary, plane = _services(tmp_path, monkeypatch)
    lesson = await _qualifying_lesson(service, primary, plane)
    assert await graduate(service, ledger, ledger_name=primary.name) == [lesson.lesson_id]
    await service.refresh()
    graduated = await service.get_lesson(lesson.lesson_id)
    assert graduated is not None
    assert await ledger.close_issue(graduated.issue_id, "fixed upstream", "agent:test", force=True)

    assert await graduate(service, ledger, ledger_name=primary.name) == [lesson.lesson_id]
    await service.refresh()
    retired = await service.get_lesson(lesson.lesson_id)
    assert retired is not None
    assert retired.state == "retired"
    assert await service.match_failure("gh pr edit 1", "project cards unsupported", session="later") is None


@pytest.mark.asyncio
async def test_graduate_counts_only_current_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not inherit a prior solution revision's graduation hits."""
    service, ledger, primary, plane = _services(tmp_path, monkeypatch)
    old = await _record_lesson(service, solution="Use the legacy workaround.")
    _append_shared_confirmation(primary, old, sequence=1)
    _append_injections(plane, old, count=service.config.graduate_hits)

    new_draft = old.draft.model_copy(deep=True)
    new_draft.solution = "Use the current supported command."
    for session in ("new-recording", "new-validation"):
        assert await service.record(new_draft, session=session, source="authored") == old.lesson_id
    await service.refresh()
    current = await service.get_lesson(old.lesson_id)
    assert current is not None
    assert current.solution_rev != old.solution_rev
    _append_shared_confirmation(primary, current, sequence=50)
    await service.refresh()
    current = await service.get_lesson(old.lesson_id)
    assert current is not None
    assert current.state == "confirmed"
    assert current.hits == 0

    assert await graduate(service, ledger, ledger_name=primary.name) == []
    assert await ledger.get_issue(graduation_issue_id(current)) is None

    _append_injections(plane, current, count=service.config.graduate_hits, offset=51)
    await service.refresh()
    assert await graduate(service, ledger, ledger_name=primary.name) == [current.lesson_id]


@pytest.mark.asyncio
async def test_graduate_requires_injection_session_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Count distinct current-revision injection sessions, not unrelated evidence sessions."""
    service, ledger, primary, plane = _services(tmp_path, monkeypatch)
    lesson = await _record_lesson(service)
    _append_shared_confirmation(primary, lesson, sequence=1)
    _append_injections(plane, lesson, count=service.config.graduate_hits, session_count=1)
    unrelated_evidence = _event(
        kind="lesson.validated",
        lesson_id=lesson.lesson_id,
        session="validation-only",
        payload={"solution_rev": lesson.solution_rev, "via": "trigger_family"},
        sequence=60,
    )
    assert append_event(plane, unrelated_evidence)
    await service.refresh()
    current = await service.get_lesson(lesson.lesson_id)
    assert current is not None
    assert current.sessions >= service.config.graduate_sessions

    assert await graduate(service, ledger, ledger_name=primary.name) == []

    for sequence, session in enumerate(("hit-extra-1", "hit-extra-2"), start=70):
        event = _event(
            kind="lesson.injected",
            lesson_id=current.lesson_id,
            session=session,
            payload={"solution_rev": current.solution_rev, "state_at_injection": "confirmed"},
            sequence=sequence,
        )
        assert append_event(plane, event)
    await service.refresh()
    assert await graduate(service, ledger, ledger_name=primary.name) == [current.lesson_id]
