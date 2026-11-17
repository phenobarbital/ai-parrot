"""Per-seat reasoning-effort resolution for sdd-coder attempts (pure, leaf module)."""

from __future__ import annotations

import logging
from typing import Dict, Literal, Optional, Sequence, Tuple, Union, get_args, get_origin

from pydantic import BaseModel

from parrot.flows.dev_loop.sdd_coder.complexity_models import StrongModelIdentity
from parrot.flows.dev_loop.sdd_coder.models import RosterSeat

EFFORT_FIELD_BY_BACKEND: Dict[str, str] = {
    "zai": "reasoning_effort",
    "moonshot": "reasoning_effort",
    "google-compat": "reasoning_effort",
    "google_coding": "effort",
    "codex": "reasoning_effort",
}

#: Values the Claude Code `Agent` tool accepts for its `effort` parameter (native seats).
NATIVE_AGENT_EFFORTS: Tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

EffortSource = Literal["strong_model", "seat"]


def resolve_seat_effort_with_source(
    seat: RosterSeat,
    classification: Optional[str],
    strong_models: Sequence[StrongModelIdentity],
) -> Tuple[Optional[str], Optional[EffortSource]]:
    """Resolve the effort for one attempt and where it came from.

    Args:
        seat: The roster seat running the attempt.
        classification: Complexity classification of the task, if assessed.
        strong_models: Strong-model identities of the complexity policy.

    Returns:
        ``(effort, source)``; ``(None, None)`` when nothing is configured.
    """
    if classification in ("complex", "unknown"):
        # Native seats have no backend; strong_models names them `native` (same key as roster.eligible_seats).
        backend = "native" if seat.kind == "native" else seat.backend
        for ident in strong_models:
            if (ident.backend, ident.model) == (backend, seat.model or "") and ident.effort:
                return ident.effort, "strong_model"
    if seat.effort:
        return seat.effort, "seat"
    return None, None


def resolve_seat_effort(
    seat: RosterSeat,
    classification: Optional[str],
    strong_models: Sequence[StrongModelIdentity],
) -> Optional[str]:
    """Resolve the effort for one attempt.

    Precedence: a matching strong model's effort (complex/unknown tasks only), then the
    seat's own effort, then ``None``.

    Args:
        seat: The roster seat running the attempt.
        classification: Complexity classification of the task, if assessed.
        strong_models: Strong-model identities of the complexity policy.

    Returns:
        The effort value or ``None``.
    """
    return resolve_seat_effort_with_source(seat, classification, strong_models)[0]


def resolve_native_effort(
    seat: RosterSeat,
    classification: Optional[str],
    strong_models: Sequence[StrongModelIdentity],
    *,
    logger: logging.Logger,
) -> Optional[str]:
    """Resolve the `Agent` tool effort for a native seat's attempt.

    Same precedence as :func:`resolve_seat_effort`; a value the `Agent` tool does not accept
    (``none``, ``minimal``) is skipped with a WARNING instead of being handed to the orchestrator.

    Args:
        seat: The native roster seat running the attempt.
        classification: Complexity classification of the task, if assessed.
        strong_models: Strong-model identities of the complexity policy.
        logger: Logger used for the skip warning.

    Returns:
        The effort to pass to the `Agent` tool, or ``None`` to leave the session default.
    """
    effort = resolve_seat_effort(seat, classification, strong_models)
    if effort is not None and effort not in NATIVE_AGENT_EFFORTS:
        logger.warning(
            "native seat %r: effort=%r not supported by the Agent tool (accepted: %s); ignored",
            seat.label,
            effort,
            ", ".join(NATIVE_AGENT_EFFORTS),
        )
        return None
    return effort


def _accepted_values(annotation: object) -> Optional[Tuple[str, ...]]:
    """Return the allowed literals of a field annotation, or ``None`` when any str is allowed."""
    if get_origin(annotation) is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            annotation = args[0]
    if get_origin(annotation) is Literal:
        return tuple(str(v) for v in get_args(annotation))
    return None


def apply_effort_to_profile(
    profile: BaseModel,
    backend: str,
    effort: Optional[str],
    *,
    seat_label: str,
    logger: logging.Logger,
) -> BaseModel:
    """Write ``effort`` into the backend-specific field of a dispatch profile.

    ``model_copy`` does not validate, so the value is checked against the field annotation here.

    Args:
        profile: The dispatch profile built for the backend.
        backend: The seat backend name.
        effort: Effort to apply, or ``None`` for no change.
        seat_label: Seat label, for log messages.
        logger: Logger used for skip warnings.

    Returns:
        The same profile when nothing is applied, otherwise an updated copy.
    """
    if effort is None:
        return profile
    field = EFFORT_FIELD_BY_BACKEND.get(backend)
    if field is None or field not in type(profile).model_fields:
        logger.warning(
            "seat %r: backend %r has no reasoning-effort setting; effort=%r ignored", seat_label, backend, effort
        )
        return profile
    accepted = _accepted_values(type(profile).model_fields[field].annotation)
    if accepted is not None and effort not in accepted:
        logger.warning(
            "seat %r: effort=%r not supported by backend %r (accepted: %s); ignored",
            seat_label,
            effort,
            backend,
            ", ".join(accepted),
        )
        return profile
    return profile.model_copy(update={field: effort})
