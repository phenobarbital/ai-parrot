"""Pure reduction and deterministic matching for experience lessons."""

from __future__ import annotations

from collections.abc import Iterable

from parrot.knowledge.wiki.experience.fastpath import normalize_error
from parrot.knowledge.wiki.experience.models import ExperienceConfig, ExperienceEvent, Lesson


def reduce_events(events: Iterable[ExperienceEvent], config: ExperienceConfig) -> dict[str, Lesson]:
    """Derive lessons from a set of events.

    Events are de-duplicated by their immutable event identity before their
    evidence is grouped by lesson and solution revision.  The returned mapping
    is deterministic for every ordering of the same event set.

    Args:
        events: Validated events from the repository, global, and shared logs.
        config: Thresholds used for confirmation and quarantine.

    Returns:
        The derived lesson for every lesson that has a valid recording event.
    """
    unique_events = _deduplicate_events(events)
    by_lesson: dict[str, list[ExperienceEvent]] = {}
    for event in unique_events.values():
        if event.lesson_id:
            by_lesson.setdefault(event.lesson_id, []).append(event)

    lessons: dict[str, Lesson] = {}
    for lesson_id in sorted(by_lesson):
        lesson = _reduce_lesson(lesson_id, by_lesson[lesson_id], config)
        if lesson is not None:
            lessons[lesson_id] = lesson
    return lessons


def match_score(lesson: Lesson, executable: str, subcommand: str, error: str) -> float:
    """Return the deterministic trigger-family similarity for a failure.

    Args:
        lesson: The reduced lesson to compare.
        executable: The failure's executable basename.
        subcommand: The failure's command family.
        error: The failure's error text.

    Returns:
        Zero for another command family, one for an exact normalized error,
        otherwise the Jaccard similarity of normalized error tokens.
    """
    trigger = lesson.draft.trigger
    if (trigger.executable, trigger.subcommand) != (executable, subcommand):
        return 0.0

    expected = normalize_error(trigger.error_signature)
    observed = normalize_error(error)
    if expected == observed:
        return 1.0

    expected_tokens = set(expected.split())
    observed_tokens = set(observed.split())
    union = expected_tokens | observed_tokens
    if not union:
        return 0.0
    return len(expected_tokens & observed_tokens) / len(union)


def _deduplicate_events(events: Iterable[ExperienceEvent]) -> dict[str, ExperienceEvent]:
    """Return event identities once, preserving trusted provenance across copies."""
    unique: dict[str, ExperienceEvent] = {}
    for event in events:
        existing = unique.get(event.event_id)
        if existing is None:
            unique[event.event_id] = event.model_copy(deep=True)
        elif event._shared_attestation:
            existing._shared_attestation = True
    return unique


def _reduce_lesson(lesson_id: str, events: list[ExperienceEvent], config: ExperienceConfig) -> Lesson | None:
    """Reduce all valid revisions belonging to one lesson identity."""
    recordings: dict[str, list[ExperienceEvent]] = {}
    for event in events:
        if event.kind != "lesson.recorded":
            continue
        solution_rev = _solution_rev(event)
        if solution_rev and _is_recording(event):
            recordings.setdefault(solution_rev, []).append(event)

    if not recordings:
        return None

    revision_data: dict[str, dict[str, object]] = {}
    for solution_rev, record_events in recordings.items():
        ordered_records = sorted(record_events, key=_event_order)
        recording = ordered_records[0]
        recording_session = recording.session
        validations = {event.session for event in ordered_records[1:] if event.session != recording_session}
        refutations: set[str] = set()
        sessions = {event.session for event in ordered_records}
        injections = 0
        issue_id = ""
        issue_ledger = ""
        shared_confirmed = False
        shared_quarantined = False

        for event in events:
            if _solution_rev(event) != solution_rev:
                continue
            if event.kind == "lesson.validated" and event.session != recording_session:
                validations.add(event.session)
                sessions.add(event.session)
            elif event.kind == "lesson.refuted":
                refutations.add(event.session)
                sessions.add(event.session)
            elif event.kind == "lesson.injected":
                injections += 1
                sessions.add(event.session)
            elif event.kind == "lesson.graduated":
                sessions.add(event.session)
                payload = event.payload
                if isinstance(payload.get("issue_id"), str) and isinstance(payload.get("ledger"), str):
                    issue_id = payload["issue_id"]
                    issue_ledger = payload["ledger"]
            elif event.kind == "lesson.confirmed" and event._shared_attestation:
                shared_confirmed = True
            elif event.kind == "lesson.quarantined" and event._shared_attestation:
                shared_quarantined = True

        revision_data[solution_rev] = {
            "recording": recording,
            "validations": validations,
            "refutations": refutations,
            "sessions": sessions,
            "hits": injections,
            "issue_id": issue_id,
            "issue_ledger": issue_ledger,
            "shared_confirmed": shared_confirmed,
            "shared_quarantined": shared_quarantined,
        }

    revisions = sorted(
        revision_data,
        key=lambda revision: (
            -len(revision_data[revision]["validations"]),
            revision_data[revision]["recording"].ts,
            revision,
        ),
    )
    current_rev = revisions[0]
    current = revision_data[current_rev]
    recording = current["recording"]
    retired = any(event.kind == "lesson.retired" for event in events)
    validations = current["validations"]
    refutations = current["refutations"]

    if retired:
        state = "retired"
    elif current["shared_quarantined"] or len(refutations) >= config.quarantine_refutations:
        state = "quarantined"
    elif current["shared_confirmed"] or (
        len(validations) >= config.confirm_sessions and len(validations) > len(refutations)
    ):
        state = "confirmed"
    else:
        state = "candidate"

    payload = recording.payload
    try:
        return Lesson(
            lesson_id=lesson_id,
            draft=payload["draft"],
            solution_rev=current_rev,
            revisions=revisions,
            tier=payload["tier"],
            state=state,
            hits=current["hits"],
            validations=len(validations),
            refutations=len(refutations),
            sessions=len(current["sessions"]),
            issue_id=current["issue_id"],
            issue_ledger=current["issue_ledger"],
            recorded_by=recording.actor,
            recorded_at=recording.ts,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _solution_rev(event: ExperienceEvent) -> str:
    """Return the event solution revision when its payload has one."""
    solution_rev = event.payload.get("solution_rev")
    return solution_rev if isinstance(solution_rev, str) else ""


def _is_recording(event: ExperienceEvent) -> bool:
    """Return whether a recorded event has the minimum reducer payload."""
    payload = event.payload
    return isinstance(payload.get("draft"), dict) and payload.get("tier") in {"repo", "global"}


def _event_order(event: ExperienceEvent) -> tuple[str, str]:
    """Return a stable ordering for otherwise unordered event collections."""
    return event.ts, event.event_id
