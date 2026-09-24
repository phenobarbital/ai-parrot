"""Attributed, revision-checked review transforms (FEAT-578 Module 5).

Pure: takes a record plus a request and returns the next revision. The CAS
write belongs to ``DecisionRepository.save``.

The invariant this module exists to protect (Q3 / AC11): accepting an
inferred candidate changes ``review_status`` and NOTHING else about its
provenance. It stays ``origin='inferred'`` with
``source_status='unknown'`` forever.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from parrot.knowledge.wiki.decisions.codec import render_markdown, review_fingerprint
from parrot.knowledge.wiki.decisions.models import (
    ADR_INVALID_ARGUMENT,
    ADR_REVISION_CONFLICT,
    CandidateEdit,
    DecisionError,
    DecisionLink,
    DecisionRecord,
    ReviewEvent,
    ReviewRequest,
)

logger = logging.getLogger(__name__)

#: Fields no review action may ever change (spec §2). Asserted after every
#: transform, so a future action cannot quietly widen the surface.
IMMUTABLE_FIELDS = (
    "decision_id",
    "origin",
    "source_status",
    "source_status_raw",
    "source_path",
    "evidence",
    "generation",
    "schema_version",
)


def check_revision(record: DecisionRecord, expected_revision: int) -> None:
    """Refuse a review built against a superseded revision.

    Raises:
        DecisionError: ``ADR_REVISION_CONFLICT``. There is no automatic
            re-read or retry — the reviewer must look at what changed
            (spec §2 "no automatic review overwrite/retry").
    """
    if record.revision != expected_revision:
        raise DecisionError(
            ADR_REVISION_CONFLICT,
            f"{record.decision_id} is at revision {record.revision}, review expected {expected_revision}",
            decision_id=record.decision_id,
        )


def _apply_edit(record: DecisionRecord, edit: CandidateEdit) -> dict[str, Any]:
    """Field updates for a ``revise``, from the six editable fields only."""
    updates: dict[str, Any] = {}
    for field in ("title", "context", "decision", "consequences", "observations", "hypotheses"):
        value = getattr(edit, field)
        if value is not None:
            updates[field] = value
    # A revision invalidates the previous review (spec §2: "Revision ...
    # resets review status to unreviewed").
    updates["review_status"] = "unreviewed"
    return updates


def _apply_link(record: DecisionRecord, documented_decision_id: str) -> dict[str, Any]:
    """Field updates for a ``link`` to an existing documented record."""
    new_link = DecisionLink(
        target_id=documented_decision_id,
        relation="supersedes",
        provenance="asserted",
        evidence_indexes=[],
    )
    return {"links": [*record.links, new_link]}


def apply_review(record: DecisionRecord, request: ReviewRequest) -> DecisionRecord:
    """Validate and apply one attributed review action.

    Args:
        record: The record as just read, at ``request.expected_revision``.
        request: The maintainer's action. ``actor`` is mandatory —
            attribution is not optional (spec §2 ``ReviewEvent``).

    Returns:
        The next revision, with one appended :class:`ReviewEvent`. Existing
        history is never edited or dropped (AC6).

    Raises:
        DecisionError: ``ADR_REVISION_CONFLICT`` when stale,
            ``ADR_INVALID_ARGUMENT`` for a malformed action payload or a
            ``link`` whose target is not a documented record.
    """
    check_revision(record, request.expected_revision)
    before = review_fingerprint(record)

    if request.action == "accept":
        updates: dict[str, Any] = {"review_status": "accepted"}
    elif request.action == "reject":
        updates = {"review_status": "rejected"}
    elif request.action == "revise":
        if request.replacement is None:
            raise DecisionError(
                ADR_INVALID_ARGUMENT, "action='revise' requires a replacement", decision_id=record.decision_id
            )
        updates = _apply_edit(record, request.replacement)
        if "decision" in updates and not updates["decision"].strip():
            raise DecisionError(
                ADR_INVALID_ARGUMENT,
                "action='revise' would leave decision empty",
                decision_id=record.decision_id,
            )
    elif request.action == "link":
        if request.documented_decision_id is None:
            raise DecisionError(
                ADR_INVALID_ARGUMENT, "action='link' requires documented_decision_id", decision_id=record.decision_id
            )
        updates = _apply_link(record, request.documented_decision_id)
    else:  # pragma: no cover — ReviewRequest.action is a closed Literal
        raise DecisionError(
            ADR_INVALID_ARGUMENT, f"unknown review action {request.action!r}", decision_id=record.decision_id
        )

    updated = record.model_copy(update={**updates, "revision": record.revision + 1})

    for field in IMMUTABLE_FIELDS:
        if getattr(updated, field) != getattr(record, field):
            raise DecisionError(
                ADR_INVALID_ARGUMENT,
                f"review action {request.action!r} attempted to change immutable field {field!r}",
                decision_id=record.decision_id,
            )

    after = review_fingerprint(updated)
    event = ReviewEvent(
        revision=updated.revision,
        action=request.action,
        actor=request.actor,
        timestamp=datetime.now(tz=UTC).isoformat(),
        reason=request.reason,
        before_sha1=before,
        after_sha1=after,
    )
    return updated.model_copy(update={"review_history": [*record.review_history, event]})


def validate_link_target(target: DecisionRecord | None, target_id: str) -> None:
    """Ensure a ``link`` action names an existing DOCUMENTED record.

    Raises:
        DecisionError: ``ADR_INVALID_ARGUMENT`` when the target is missing
            or is itself inferred — spec §2: "Linking requires an existing
            documented ADR record."
    """
    if target is None:
        raise DecisionError(ADR_INVALID_ARGUMENT, f"link target {target_id!r} does not exist", decision_id=target_id)
    if target.origin != "documented":
        raise DecisionError(
            ADR_INVALID_ARGUMENT, f"link target {target_id!r} is not a documented record", decision_id=target_id
        )


def render_export(record: DecisionRecord) -> str:
    """Render a record as Markdown for ``adr export``.

    Writing or committing this output is explicitly outside the feature
    (spec §2); the command prints to stdout. The origin/status labels are
    part of the rendering, so an exported candidate is still unmistakably a
    candidate.
    """
    return render_markdown(record)
