"""Experience domain schemas."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from parrot.knowledge.wiki.experience.fastpath import MAX_EVENT_BYTES, leading_command, normalize_error, redact

LessonCategory = Literal["pitfall"]
LessonState = Literal["candidate", "confirmed", "quarantined", "retired"]
LessonTier = Literal["repo", "global"]
LessonSource = Literal["paired", "authored", "mined"]

# A user home-directory prefix: /home/<user>, /var/home/<user>, /Users/<user> or
# <drive>:/Users/<user>. The drive-letter form cannot start right after "/" or ":",
# so a PATH-style list such as "/home/a/p:/home/a/q" keeps its separators.
_HOME_PATH_RE = re.compile(
    r"(?<![\w.~-])(?:/var)?/(?:home|Users)/[^/\s'\"`:;,)\]}>]+|(?<![\w.~/:-])[A-Za-z]:/Users/[^/\s'\"`:;,)\]}>]+"
)


class LessonTrigger(BaseModel):
    """Normalized command and error pattern that identifies a reusable lesson."""

    model_config = ConfigDict(extra="forbid")

    executable: str
    subcommand: str = ""
    error_signature: str = ""
    error_excerpt: str = ""
    command_example: str = ""


class LessonDraft(BaseModel):
    """Author-supplied candidate lesson accepted from an agent or pairing flow."""

    model_config = ConfigDict(extra="forbid")

    category: LessonCategory = "pitfall"
    trigger: LessonTrigger
    symptom: str = ""
    solution: str
    fix_example: str = ""
    scope_paths: list[str] = Field(default_factory=list)


class Lesson(BaseModel):
    """Reduced current lesson state derived from immutable experience events."""

    lesson_id: str
    draft: LessonDraft
    solution_rev: str
    revisions: list[str]
    tier: LessonTier
    state: LessonState
    hits: int
    validations: int
    refutations: int
    sessions: int
    issue_id: str = ""
    issue_ledger: str = ""
    recorded_by: str
    recorded_at: str


class CommandOutcome(BaseModel):
    """One command execution result, retaining an unknown outcome when needed."""

    model_config = ConfigDict(extra="forbid")

    command: str
    ok: bool | None
    error: str = ""
    observation_id: str = ""


class ExperienceConfig(BaseModel):
    """Validated runtime limits and lifecycle thresholds for experience memory."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    confirm_sessions: int = 2
    quarantine_refutations: int = 2
    graduate_hits: int = 5
    graduate_sessions: int = 3
    brief_max_entries: int = 5
    brief_token_budget: int = 400
    inject_min_score: float = 0.35
    advice_cooldown_seconds: int = 600
    max_triggers_bytes: int = 262144
    max_transcript_tail_bytes: int = 262144
    max_session_pending: int = 32
    pairing_excluded_executables: list[str] = Field(
        default_factory=lambda: [
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
        ]
    )


ExperienceEventKind = Literal[
    "lesson.recorded",
    "failure.observed",
    "lesson.injected",
    "lesson.validated",
    "lesson.refuted",
    "lesson.confirmed",
    "lesson.quarantined",
    "lesson.graduated",
    "lesson.retired",
]


class ExperienceEvent(BaseModel):
    """Canonical redacted event persisted in an append-only experience log."""

    model_config = ConfigDict(extra="forbid")

    _shared_attestation: bool = PrivateAttr(default=False)

    schema_version: int = 1
    event_id: str
    kind: ExperienceEventKind
    lesson_id: str = ""
    session: str
    observation_id: str = ""
    actor: str
    seat: str = ""
    ts: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RecordedPayload(BaseModel):
    """Payload defining the initial revision, tier, and provenance of a lesson."""

    model_config = ConfigDict(extra="forbid")

    draft: LessonDraft
    solution_rev: str
    tier: LessonTier
    source: LessonSource


class FailurePayload(BaseModel):
    """Payload describing the normalized command family and observed failure."""

    model_config = ConfigDict(extra="forbid")

    executable: str
    subcommand: str
    error_signature: str
    error_excerpt: str = ""


class InjectionPayload(BaseModel):
    """Payload recording that a lesson was surfaced for a matching failure."""

    model_config = ConfigDict(extra="forbid")

    solution_rev: str
    state_at_injection: LessonState


class EvidencePayload(BaseModel):
    """Payload linking validation or refutation evidence to a lesson revision."""

    model_config = ConfigDict(extra="forbid")

    solution_rev: str
    via: Literal["trigger_family", "fix_family", "rediscovery"]


class AttestationPayload(BaseModel):
    """Payload attesting to a reviewed lifecycle state for one lesson revision."""

    model_config = ConfigDict(extra="forbid")

    solution_rev: str


class GraduatedPayload(BaseModel):
    """Payload linking a graduated lesson revision to its owning ledger issue."""

    model_config = ConfigDict(extra="forbid")

    solution_rev: str
    issue_id: str
    ledger: str


class RetiredPayload(BaseModel):
    """Payload preserving the authored reason that a lesson was retired."""

    model_config = ConfigDict(extra="forbid")

    reason: str


EVENT_PAYLOADS: dict[str, type[BaseModel]] = {
    "lesson.recorded": RecordedPayload,
    "failure.observed": FailurePayload,
    "lesson.injected": InjectionPayload,
    "lesson.validated": EvidencePayload,
    "lesson.refuted": EvidencePayload,
    "lesson.confirmed": AttestationPayload,
    "lesson.quarantined": AttestationPayload,
    "lesson.graduated": GraduatedPayload,
    "lesson.retired": RetiredPayload,
}


def validate_event(line: Mapping[str, Any]) -> ExperienceEvent | None:
    """Return a canonical event or ``None`` when a log record is invalid.

    Every text value is redacted before the event identity is recomputed.  The
    private shared-attestation flag deliberately cannot be supplied by JSON.

    Args:
        line: One decoded experience-log line.

    Returns:
        The validated event, or ``None`` when the envelope, payload, or byte
        budget is invalid.
    """
    if not isinstance(line, Mapping) or type(line.get("schema_version")) is not int or line["schema_version"] != 1:
        return None

    try:
        envelope = ExperienceEvent.model_validate(line)
    except ValidationError:
        return None

    payload_type = EVENT_PAYLOADS.get(envelope.kind)
    if payload_type is None or not isinstance(envelope.payload, Mapping):
        return None
    try:
        payload = payload_type.model_validate(envelope.payload).model_dump(mode="json")
    except ValidationError:
        return None

    canonical_payload = _strip_home(_normalize_payload(envelope.kind, payload))
    canonical_envelope = _strip_home(_redact_text(envelope.model_dump(mode="json")))
    canonical_envelope["payload"] = canonical_payload
    canonical_envelope["event_id"] = _event_id_for(canonical_envelope)

    try:
        event = ExperienceEvent.model_validate(canonical_envelope)
        serialized = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (TypeError, UnicodeEncodeError, ValidationError):
        return None
    if len(serialized) + 1 > MAX_EVENT_BYTES:
        return None
    return event


def solution_rev_for(draft: LessonDraft) -> str:
    """Return the eight-character revision id for a redacted solution and fix family.

    Args:
        draft: The lesson draft whose solution revision is being identified.

    Returns:
        A stable SHA-1 prefix for the normalized solution and parsed fix family.
    """
    solution = " ".join(redact(draft.solution).split())
    executable, subcommand = leading_command(redact(draft.fix_example))
    identity = f"{solution}|{executable}|{subcommand}"
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8]  # noqa: S324 - stable identity, not security


def _event_id_for(event: Mapping[str, Any]) -> str:
    """Return the deterministic identity for an already-normalized event."""
    observation_id = event["observation_id"]
    if observation_id:
        identity = "|".join((event["kind"], event["lesson_id"], event["session"], observation_id))
    else:
        payload = json.dumps(event["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        identity = "|".join((event["kind"], event["lesson_id"], event["session"], event["ts"], payload))
    return hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]  # noqa: S324 - stable identity, not security


def _normalize_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Redact and bound payload text before event identity is derived."""
    normalized = _redact_text(payload)
    if kind == "lesson.recorded":
        draft = normalized["draft"]
        trigger = draft["trigger"]
        trigger["error_signature"] = normalize_error(trigger["error_signature"])
        trigger["error_excerpt"] = trigger["error_excerpt"][:400]
        trigger["command_example"] = trigger["command_example"][:300]
        draft["symptom"] = draft["symptom"][:400]
        draft["solution"] = draft["solution"][:600]
        draft["fix_example"] = draft["fix_example"][:300]
    elif kind == "failure.observed":
        normalized["error_signature"] = normalize_error(normalized["error_signature"])
        normalized["error_excerpt"] = normalized["error_excerpt"][:400]
    elif kind == "lesson.retired":
        normalized["reason"] = normalized["reason"][:200]
    return normalized


def _redact_text(value: Any) -> Any:
    """Recursively redact text in an already schema-validated JSON value."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_text(item) for key, item in value.items()}
    return value


def _strip_home(value: Any) -> Any:
    """Recursively replace user home-directory prefixes with ``~``.

    Runs after redaction and error normalization, so failure signatures keep
    their inputs; the stored text and the event identity see ``~``. Only
    values are rewritten: dict keys are schema names.

    Args:
        value: An already schema-validated JSON value.

    Returns:
        The value with every home-directory prefix replaced by ``~``.
    """
    if isinstance(value, str):
        return _HOME_PATH_RE.sub("~", value)
    if isinstance(value, list):
        return [_strip_home(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_home(item) for key, item in value.items()}
    return value
