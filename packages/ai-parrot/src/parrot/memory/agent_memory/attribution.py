"""Admit only runtime-observed evidence for actually delivered memory versions."""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from parrot.memory.dynamics.models import MemoryCitation, MemoryExposure, ReviewSignal
from parrot.memory.episodic.visibility import visible_to_scope
from parrot.tools.abstract import ToolResult

from .models import ChatStorageEvidenceRef, MemoryEvent, MemoryRequestScope
from .runtime import current_memory_exposure

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolAttempt:
    """Describe one tool body that actually ran at the manager boundary."""

    tool_name: str
    call_id: str
    terminal: Literal["returned", "raised", "cancelled"]
    observed_at: datetime
    first_attempt: bool
    correction_count: int
    exception_class: str | None = None
    exception_message: str | None = None
    returned: Any = None


@dataclass
class _ToolEventCapture:
    """Hold one invocation's attempts until its provider response completes."""

    scope: MemoryRequestScope
    manager: Any | None
    attempts: list[ToolAttempt] = field(default_factory=list)
    events: list[MemoryEvent] = field(default_factory=list)
    event_ids: set[str] = field(default_factory=set)
    exposure_id: str | None = None
    completed: bool = False


_tool_capture: ContextVar[_ToolEventCapture | None] = ContextVar("agent_memory_tool_capture", default=None)


def bind_tool_event_capture(scope: MemoryRequestScope, manager: Any | None) -> Token:
    """Start an isolated tool-attempt buffer for one agent invocation."""
    return _tool_capture.set(_ToolEventCapture(scope=scope, manager=manager))


def reset_tool_event_capture(token: Token) -> None:
    """Drop invocation-local attempts and invalidate unfinished exposure manifests."""
    capture = _tool_capture.get()
    if capture is not None and not capture.completed and capture.exposure_id is not None:
        discard = getattr(capture.manager, "discard_memory_exposure", None)
        if callable(discard):
            discard(capture.exposure_id)
    try:
        _tool_capture.reset(token)
    except ValueError:
        # Token created in another Context: nothing is bound here, and cleanup must not abort the caller's finally.
        pass


def note_memory_exposure(exposure_id: str | None) -> None:
    """Associate the final packed manifest with the current invocation capture."""
    capture = _tool_capture.get()
    if capture is not None:
        capture.exposure_id = exposure_id


async def capture_tool_attempt(
    tool_name: str,
    *,
    terminal: Literal["returned", "raised", "cancelled"],
    returned: Any = None,
    exception: BaseException | None = None,
) -> None:
    """Build and buffer one record for a body that actually executed."""
    capture = _tool_capture.get()
    if capture is None:
        return

    prior_attempts = [attempt for attempt in capture.attempts if attempt.tool_name == tool_name]
    correction_count = sum(_attempt_is_failure(attempt) for attempt in prior_attempts)
    sequence = len(capture.attempts)
    digest = hashlib.sha256(f"{capture.scope.turn_id}\x00{sequence}\x00{tool_name}".encode("utf-8")).hexdigest()
    attempt = ToolAttempt(
        tool_name=tool_name,
        call_id=f"tool-{digest}",
        terminal=terminal,
        observed_at=datetime.now(UTC),
        first_attempt=not prior_attempts,
        correction_count=correction_count,
        exception_class=type(exception).__name__ if exception is not None else None,
        exception_message=str(exception) if exception is not None else None,
        returned=returned,
    )
    capture.attempts.append(attempt)

    evidence_refs: tuple[str, ...] = ()
    if capture.scope.user_id is not None and capture.scope.session_id is not None:
        evidence_refs = (
            ChatStorageEvidenceRef(
                tenant_id=capture.scope.tenant_id,
                agent_name=capture.scope.agent_id,
                user_id=capture.scope.user_id,
                session_id=capture.scope.session_id,
                turn_id=capture.scope.turn_id,
            ).to_reference(),
        )
    event = MemoryEvent(
        event_id=attempt.call_id,
        kind="tool",
        scope=capture.scope,
        observed_at=attempt.observed_at,
        evidence_refs=evidence_refs,
        payload={"attempt": attempt, "exposure_id": current_memory_exposure()},
    )
    await record_tool_event(event)


async def record_tool_event(event: MemoryEvent) -> None:
    """Record an actual execution attempt once for post-provider admission."""
    capture = _tool_capture.get()
    if capture is None or event.kind != "tool" or event.scope != capture.scope:
        return
    if event.event_id in capture.event_ids:
        return
    capture.event_ids.add(event.event_id)
    capture.events.append(event)


async def flush_tool_events() -> None:
    """Admit buffered attempts only after the provider produced a completed response."""
    capture = _tool_capture.get()
    if capture is None or capture.completed:
        return
    capture.completed = True
    manager = capture.manager
    if manager is None:
        return

    if capture.exposure_id is not None:
        activate = getattr(manager, "activate_memory_exposure", None)
        if callable(activate) and not activate(capture.exposure_id, capture.scope):
            return

    record_event = getattr(manager, "record_event", None)
    if not callable(record_event):
        return
    try:
        for event in capture.events:
            try:
                await record_event(event)
            except Exception as exc:  # noqa: BLE001 - memory capture cannot change tool/provider results
                logger.warning("tool memory capture failed: %s", type(exc).__name__)
    finally:
        if capture.exposure_id is not None:
            deactivate = getattr(manager, "deactivate_memory_exposure", None)
            if callable(deactivate):
                deactivate(capture.exposure_id)


def validate_citation(
    citation: MemoryCitation,
    exposure: MemoryExposure,
    *,
    scope: MemoryRequestScope,
) -> MemoryCitation:
    """Reject cross-scope and non-delivered references before outcome admission."""
    unavailable = "citation scope or delivered exposure is unavailable"
    if citation.exposure_id != exposure.exposure_id or exposure.scope != scope:
        raise ValueError(unavailable)
    delivered = {ref.canonical_key: ref for ref in exposure.refs}
    if not citation.refs or any(delivered.get(ref.canonical_key) != ref for ref in citation.refs):
        raise ValueError(unavailable)
    if any(
        not (
            visible_to_scope(ref.namespace, scope)
            if ref.kind == "episode"
            else _namespace_matches_scope(ref.namespace, scope)
        )
        for ref in citation.refs
    ):
        raise ValueError(unavailable)
    return citation


def build_tool_signal(
    attempt: ToolAttempt,
    *,
    scope: MemoryRequestScope,
    evidence_ref: str,
) -> ReviewSignal | None:
    """Translate one runtime-observed attempt into the accepted evidence schema."""
    if attempt.terminal == "raised":
        outcome: Literal["failure", "cancelled", "incomplete"] = "failure"
        error_signature = _normalize_signature(attempt.exception_message)
        if error_signature is None:
            error_signature = _normalize_signature(attempt.exception_class) or "exception"
    elif attempt.terminal == "cancelled":
        outcome = "cancelled"
        error_signature = None
    elif _returned_explicit_failure(attempt.returned):
        outcome = "failure"
        result = attempt.returned
        error_signature = _normalize_signature(result.error)
        if error_signature is None:
            error_signature = _normalize_signature(result.status) or "failed"
    else:
        outcome = "incomplete"
        error_signature = None

    return ReviewSignal(
        outcome_id=attempt.call_id,
        outcome_revision=0,
        observed_at=attempt.observed_at,
        scope=scope,
        evidence_ref=evidence_ref,
        source="tool_runtime",
        outcome=outcome,
        first_attempt=attempt.first_attempt,
        correction_count=attempt.correction_count,
        error_signature=error_signature,
        recovery_refs=(),
        passed_check_ids=(),
    )


def _returned_explicit_failure(value: Any) -> bool:
    """Return whether a real ToolResult explicitly set a failure field."""
    if not isinstance(value, ToolResult):
        return False
    fields = value.model_fields_set
    return ("success" in fields and value.success is False) or (
        "status" in fields and value.status in {"error", "failed"}
    )


def _attempt_is_failure(attempt: ToolAttempt) -> bool:
    """Return whether an earlier attempt counts as a correction-producing failure."""
    return attempt.terminal == "raised" or (
        attempt.terminal == "returned" and _returned_explicit_failure(attempt.returned)
    )


def _normalize_signature(value: str | None) -> str | None:
    """Normalize and bound runtime failure text exactly as ReviewSignal requires."""
    if value is None:
        return None
    normalized = " ".join(unicodedata.normalize("NFKC", value).lower().split())
    return normalized[:200] or None


def _namespace_matches_scope(namespace: Any, scope: MemoryRequestScope) -> bool:
    """Compare every request-scoped namespace dimension without leaking which one failed."""
    return (
        namespace.tenant_id,
        namespace.agent_id,
        namespace.user_id,
        namespace.session_id,
        namespace.room_id,
        namespace.crew_id,
        namespace.model_id,
    ) == (
        scope.tenant_id,
        scope.agent_id,
        scope.user_id,
        scope.session_id,
        scope.room_id,
        scope.crew_id,
        scope.model_id,
    )
