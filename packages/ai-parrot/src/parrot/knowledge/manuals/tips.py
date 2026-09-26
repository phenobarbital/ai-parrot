"""Technician tips: add, retire and re-link across manual revisions (FEAT-601 M9).

Tips live in technician-owned collections the graph loader never reconciles.
Re-linking follows R1 strictly: source identity, then exact content-hash
equality; text similarity only ever yields curator candidates.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.ontology.schema import TenantContext

from .domain import TECHNICIAN_COLLECTIONS
from .models import Step, Tip

logger = logging.getLogger(__name__)

CANDIDATE_THRESHOLD = 0.85
TIP_COLLECTION, TIP_EDGE, TIP_AUTHOR_EDGE = TECHNICIAN_COLLECTIONS  # ("tech_tip", "tech_tip_on", "tech_tip_by")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RelinkOutcome(BaseModel):
    """What happened to one tip during a relink run."""

    tip_id: str
    previous_step_id: str | None
    new_step_id: str | None
    method: Literal["source_identity", "content_hash", "unchanged", "candidate", "orphaned"]
    candidates: list[tuple[str, float]] = Field(default_factory=list)


class RelinkReport(BaseModel):
    """Aggregate relink result for one manual; ``failed`` lists tip ids that could not be written."""

    manual_id: str
    relinked: list[RelinkOutcome] = Field(default_factory=list)
    orphaned: list[RelinkOutcome] = Field(default_factory=list)
    candidates: list[RelinkOutcome] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)


def _text_similarity(left: str, right: str) -> float:
    """rapidfuzz token_sort_ratio / 100 on step TEXT (never on hashes)."""
    if not (left or "").strip() or not (right or "").strip():
        return 0.0
    if left == right:
        return 1.0
    try:
        from rapidfuzz import fuzz  # noqa: PLC0415 - optional dependency
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RuntimeError(
            "Technician tip relink requires rapidfuzz. Install it with `pip install 'ai-parrot[graphindex]'`."
        ) from exc
    return float(fuzz.token_sort_ratio(left, right)) / 100.0


def _match(
    previous: Step, current: Sequence[Step], *, manual_id: str
) -> tuple[str, str | None, list[tuple[str, float]]]:
    """Return (method, new_step_id, candidates) following the fixed R1 order."""
    manual_prefix = f"{manual_id}:"
    scoped = [step for step in current if step.identity.step_id.startswith(manual_prefix)]
    previous_identity = previous.identity

    # (1) same non-null source_identity among current steps.
    if previous_identity.source_identity is not None:
        matches = [step for step in scoped if step.identity.source_identity == previous_identity.source_identity]
        if matches:
            step = min(matches, key=lambda candidate: candidate.order)
            method = "unchanged" if step.identity.step_id == previous_identity.step_id else "source_identity"
            return method, step.identity.step_id, []

    # (2) exact content_hash equality; ties broken by lowest order.
    hash_matches = [step for step in scoped if step.identity.content_hash == previous_identity.content_hash]
    if hash_matches:
        step = min(hash_matches, key=lambda candidate: candidate.order)
        method = "unchanged" if step.identity.step_id == previous_identity.step_id else "content_hash"
        return method, step.identity.step_id, []

    # (3) text similarity: curator candidate only, never an automatic relink.
    candidates: list[tuple[str, float]] = []
    for step in scoped:
        score = _text_similarity(previous.text.value or "", step.text.value or "")
        if score >= CANDIDATE_THRESHOLD:
            candidates.append((step.identity.step_id, score))
    if candidates:
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return "candidate", None, candidates

    # (4) nothing matched: orphaned, kept, never deleted.
    return "orphaned", None, []


async def relink_tips(
    graph_store: Any,
    ctx: TenantContext,
    *,
    manual_id: str,
    previous_steps: Sequence[Step],
    current_steps: Sequence[Step],
    linked_by: str = "manuals.relink",
    now: Callable[[], datetime] = _utcnow,
) -> RelinkReport:
    """Re-attach active tips of ``manual_id`` from previous to current steps. Idempotent; never raises per tip."""
    report = RelinkReport(manual_id=manual_id)
    manual_prefix = f"{manual_id}:"
    by_id = {step.identity.step_id: step for step in previous_steps if step.identity.step_id.startswith(manual_prefix)}
    current_by_id = {
        step.identity.step_id: step for step in current_steps if step.identity.step_id.startswith(manual_prefix)
    }
    current_list = list(current_by_id.values())

    tip_docs = await graph_store.query_documents(ctx, TIP_COLLECTION, filters={"active": True})
    relevant: list[tuple[dict[str, Any], Step]] = []
    for doc in tip_docs:
        attached = doc.get("attached_step_id")
        if not attached:
            continue
        previous_step = by_id.get(attached) or current_by_id.get(attached)
        if previous_step is None:
            # Either not this manual's tip, or a genuine older orphan we lack
            # step data for — leave it exactly as it is (never deleted).
            continue
        relevant.append((doc, previous_step))

    for doc, previous_step in relevant:
        tip_id = doc["tip_id"]
        outcome: RelinkOutcome | None = None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                outcome = await _apply_match(
                    graph_store,
                    ctx,
                    doc=doc,
                    previous_step=previous_step,
                    current_steps=current_list,
                    manual_id=manual_id,
                    linked_by=linked_by,
                    now=now,
                )
                break
            except Exception as exc:  # noqa: BLE001 - collected, never raised
                last_error = exc
                logger.warning("relink_tips %s: tip %s failed on attempt %d: %s", manual_id, tip_id, attempt + 1, exc)
        if outcome is None:
            report.failed.append(tip_id)
            logger.warning("relink_tips %s: tip %s failed after retry: %s", manual_id, tip_id, last_error)
            continue
        if outcome.method == "candidate":
            report.candidates.append(outcome)
        elif outcome.method == "orphaned":
            report.orphaned.append(outcome)
        else:
            report.relinked.append(outcome)

    logger.info(
        "relink_tips %s: %d relinked, %d orphaned, %d candidates, %d failed",
        manual_id,
        len(report.relinked),
        len(report.orphaned),
        len(report.candidates),
        len(report.failed),
    )
    return report


async def _apply_match(
    graph_store: Any,
    ctx: TenantContext,
    *,
    doc: dict[str, Any],
    previous_step: Step,
    current_steps: Sequence[Step],
    manual_id: str,
    linked_by: str,
    now: Callable[[], datetime],
) -> RelinkOutcome:
    """Resolve one tip's match and, when needed, write its edge/document change."""
    tip_id = doc["tip_id"]
    old_step_id = doc.get("attached_step_id")
    method, new_step_id, candidates = _match(previous_step, current_steps, manual_id=manual_id)
    outcome = RelinkOutcome(
        tip_id=tip_id,
        previous_step_id=old_step_id,
        new_step_id=new_step_id,
        method=method,
        candidates=candidates,
    )

    if method == "unchanged":
        return outcome

    if method in ("source_identity", "content_hash"):
        linked_at = now().isoformat()
        edge_doc = {
            "_from": f"{TIP_COLLECTION}/{tip_id}",
            "_to": f"step/{new_step_id}",
            "source_id": f"{TIP_COLLECTION}/{tip_id}",
            "target_id": f"step/{new_step_id}",
            "kind": TIP_EDGE,
            "origin": "technician",
            "linked_by": linked_by,
            "linked_at": linked_at,
        }
        # Create the new edge before removing the old one: a failed create
        # (retried once, then reported in RelinkReport.failed) must never
        # leave the tip disconnected from every step.
        await graph_store.create_edges(ctx, TIP_EDGE, [edge_doc])
        await graph_store.remove_edge_by_triple(
            ctx, TIP_EDGE, f"{TIP_COLLECTION}/{tip_id}", f"step/{old_step_id}", TIP_EDGE
        )
        history = [
            *doc.get("history", []),
            {"action": "relinked", "method": method, "from": old_step_id, "to": new_step_id, "at": linked_at},
        ]
        updated = {**doc, "attached_step_id": new_step_id, "orphaned": False, "history": history}
        await graph_store.upsert_document(ctx, TIP_COLLECTION, updated)
        return outcome

    # method in ("candidate", "orphaned"): keep attached_step_id + source_revision,
    # flip orphaned once and append history once (idempotent on repeated runs).
    if not doc.get("orphaned"):
        at = now().isoformat()
        entry: dict[str, Any] = {"action": method, "at": at}
        if method == "candidate":
            entry["candidates"] = candidates
        history = [*doc.get("history", []), entry]
        updated = {**doc, "orphaned": True, "history": history}
        await graph_store.upsert_document(ctx, TIP_COLLECTION, updated)
    return outcome


async def add_tip(
    graph_store: Any,
    ctx: TenantContext,
    *,
    step_id: str,
    text: str,
    author_employee_id: str,
    source_revision: str,
    now: Callable[[], datetime] = _utcnow,
) -> Tip:
    """Write a technician tip + its ``tech_tip_on`` edge; author comes from the trusted context, never the model."""
    tip = Tip(
        tip_id=f"tip-{uuid.uuid4().hex[:16]}",
        text=text,
        origin="technician",
        author_employee_id=author_employee_id,
        created_at=now(),
        source_revision=source_revision,
        attached_step_id=step_id,
        history=[],
    )
    await graph_store.upsert_document(ctx, TIP_COLLECTION, {"_key": tip.tip_id, **tip.model_dump(mode="json")})
    linked_at = now().isoformat()
    edge_doc = {
        "_from": f"{TIP_COLLECTION}/{tip.tip_id}",
        "_to": f"step/{step_id}",
        "source_id": f"{TIP_COLLECTION}/{tip.tip_id}",
        "target_id": f"step/{step_id}",
        "kind": TIP_EDGE,
        "origin": "technician",
        "linked_by": "technician",
        "linked_at": linked_at,
    }
    await graph_store.create_edges(ctx, TIP_EDGE, [edge_doc])
    return tip


async def retire_tip(graph_store: Any, ctx: TenantContext, *, tip_id: str, by: str) -> None:
    """Deactivate a tip (curator action) and append an audit entry to its history."""
    doc = await graph_store.get_document(ctx, TIP_COLLECTION, tip_id)
    if doc is None:
        raise ValueError(f"tip {tip_id!r} not found")
    history = [*doc.get("history", []), {"action": "retired", "by": by, "at": _utcnow().isoformat()}]
    updated = {**doc, "active": False, "history": history}
    await graph_store.upsert_document(ctx, TIP_COLLECTION, updated)
