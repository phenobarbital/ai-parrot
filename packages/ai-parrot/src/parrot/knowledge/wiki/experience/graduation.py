"""Host-only graduation with deterministic ledger identity."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from parrot.knowledge.wiki.experience.fastpath import append_event
from parrot.knowledge.wiki.experience.models import ExperienceEvent, Lesson, validate_event
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.ledger.events import compute_issue_id
from parrot.knowledge.wiki.ledger.service import LedgerService

logger = logging.getLogger(__name__)


def _graduation_title(lesson: Lesson) -> str:
    """Return the canonical recurring-pitfall issue title."""
    trigger = lesson.draft.trigger
    return f"Recurring pitfall {lesson.lesson_id}: {trigger.executable} {trigger.subcommand}"


def graduation_issue_id(lesson: Lesson) -> str:
    """Return the deterministic recurring-pitfall issue ID."""
    return compute_issue_id("tech_debt", _graduation_title(lesson), f"experience:{lesson.lesson_id}")


def _graduation_body(lesson: Lesson) -> str:
    """Render the current lesson revision into a stable ledger body."""
    trigger = lesson.draft.trigger
    command = " ".join(part for part in (trigger.executable, trigger.subcommand) if part)
    return "\n".join(
        (
            "A confirmed experience-memory lesson has crossed its graduation threshold.",
            "",
            f"Lesson: {lesson.lesson_id}",
            f"Solution revision: {lesson.solution_rev}",
            f"Trigger: {command}",
            f"Symptom: {lesson.draft.symptom}",
            f"Solution: {lesson.draft.solution}",
            f"Hits: {lesson.hits}",
            f"Sessions: {lesson.sessions}",
        )
    )


def _append_lifecycle_event(
    service: ExperienceService,
    lesson: Lesson,
    *,
    kind: str,
    payload: dict[str, str],
) -> bool:
    """Validate and durably append one host-owned lifecycle event."""
    if service.plane_dir is None:
        return False
    event = validate_event(
        {
            "schema_version": 1,
            "event_id": "",
            "kind": kind,
            "lesson_id": lesson.lesson_id,
            "session": f"experience-{kind.removeprefix('lesson.')}",
            "actor": "agent:experience",
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": payload,
        }
    )
    return event is not None and append_event(service.plane_dir, event.model_dump(mode="json"))


def _injection_sessions(events: list[ExperienceEvent]) -> dict[tuple[str, str], set[str]]:
    """Group injection sessions by lesson and solution revision."""
    sessions: dict[tuple[str, str], set[str]] = {}
    for event in events:
        if event.kind != "lesson.injected":
            continue
        solution_rev = event.payload.get("solution_rev")
        if not isinstance(solution_rev, str):
            continue
        sessions.setdefault((event.lesson_id, solution_rev), set()).add(event.session)
    return sessions


def _qualifies(
    lesson: Lesson,
    service: ExperienceService,
    injection_sessions: dict[tuple[str, str], set[str]],
) -> bool:
    """Return whether the confirmed current revision crosses both thresholds."""
    return (
        lesson.state == "confirmed"
        and not lesson.issue_id
        and lesson.hits >= service.config.graduate_hits
        and len(injection_sessions.get((lesson.lesson_id, lesson.solution_rev), set()))
        >= service.config.graduate_sessions
    )


async def graduate(service: ExperienceService, ledger: LedgerService, *, ledger_name: str) -> list[str]:
    """Open qualifying issues and retire closed issues owned by this ledger."""
    if service.index is None or service.plane_dir is None or not service.config.enabled:
        return []

    try:
        lock_descriptor = await service.index._acquire_lock()
    except Exception:
        logger.debug("experience graduation lock failed", exc_info=True)
        return []
    if lock_descriptor is None:
        return []

    affected: list[str] = []
    try:
        lessons = await service.list_lessons()
        snapshot = service.index._snapshot()
        if snapshot is None:
            return []
        injection_sessions = _injection_sessions(snapshot[0])

        # Retire from the unchanged snapshot before graduation appends make the
        # published generation stale.  Foreign ledger ownership is terminal for
        # this pass even when the same deterministic issue exists locally.
        for lesson in lessons:
            if not lesson.issue_id or lesson.issue_ledger != ledger_name or lesson.state == "retired":
                continue
            try:
                issue = await ledger.get_issue(lesson.issue_id)
            except Exception:
                logger.debug("experience graduation issue lookup failed", exc_info=True)
                continue
            if issue is None or issue.get("status") != "closed":
                continue
            if _append_lifecycle_event(
                service,
                lesson,
                kind="lesson.retired",
                payload={"reason": f"Graduation issue {lesson.issue_id} closed."},
            ):
                affected.append(lesson.lesson_id)

        for lesson in lessons:
            if not _qualifies(lesson, service, injection_sessions):
                continue
            issue_id = graduation_issue_id(lesson)
            try:
                issue = await ledger.get_issue(issue_id)
                if issue is None:
                    opened_id = await ledger.open_issue(
                        title=_graduation_title(lesson),
                        body=_graduation_body(lesson),
                        kind="tech_debt",
                        severity="low",
                        discovered_from=f"experience:{lesson.lesson_id}",
                        actor="agent:experience",
                    )
                    if opened_id != issue_id:
                        logger.warning(
                            "experience graduation opened unexpected issue %s instead of %s",
                            opened_id,
                            issue_id,
                        )
                        continue
            except Exception:
                logger.debug("experience graduation issue open failed", exc_info=True)
                continue

            if not _append_lifecycle_event(
                service,
                lesson,
                kind="lesson.graduated",
                payload={"solution_rev": lesson.solution_rev, "issue_id": issue_id, "ledger": ledger_name},
            ):
                continue
            if lesson.lesson_id not in affected:
                affected.append(lesson.lesson_id)

            # A crash-repaired issue may already be closed.  Record ownership
            # before retirement so the reducer observes the normal lifecycle.
            if issue is not None and issue.get("status") == "closed":
                if _append_lifecycle_event(
                    service,
                    lesson,
                    kind="lesson.retired",
                    payload={"reason": f"Graduation issue {issue_id} closed."},
                ):
                    continue

        return affected
    except Exception:
        logger.debug("experience graduation failed", exc_info=True)
        return affected
    finally:
        service.index._release_lock(lock_descriptor)
