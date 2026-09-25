"""Pure, deterministic assembly of one procedure answer (FEAT-601 M10).

No I/O and no model: traversal rows plus the selected card revision fully
determine the output. Gaps are recorded rather than filled.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.manuals.models import (
    HazardView,
    ManualVersion,
    MediaView,
    Prerequisites,
    Procedure,
    ProcedureAnswerKind,
    ProcedureCitation,
    ProcedureView,
    Step,
    StepView,
    TipView,
    applies,
)
from parrot_tools.procedures.retrieval import RequestContext, RetrievalResult

logger = logging.getLogger(__name__)


class AssembledProcedure(BaseModel):
    """Everything a procedure answer may release, plus recorded gaps."""

    procedure: ProcedureView
    steps: list[StepView] = Field(default_factory=list)
    prerequisites: Prerequisites
    hazards: list[HazardView] = Field(default_factory=list)
    media: list[MediaView] = Field(default_factory=list)
    tips: list[TipView] = Field(default_factory=list)
    citations: list[ProcedureCitation] = Field(default_factory=list)
    revision: ManualVersion
    missing_required: list[str] = Field(default_factory=list)
    unsupported_fields: list[str] = Field(default_factory=list)
    filtered_by_serial: list[str] = Field(default_factory=list)
    needs_serial: bool = False


def assemble_procedure(
    result: RetrievalResult,
    *,
    kind: ProcedureAnswerKind,
    step_order: int | None = None,
    include_tips: bool = True,
    context: Optional[RequestContext] = None,
) -> AssembledProcedure:
    """Assemble one revision's deterministic procedure representation.

    Args:
        result: Traversal output for exactly one selected card revision.
        kind: Requested answer kind.
        step_order: Requested order when assembling a single step.
        include_tips: Whether eligible technician tips are included.
        context: Trusted equipment model and serial, if available.

    Returns:
        The assembly and every detected release gap.

    Raises:
        ValueError: If no selected manual/revision or procedure is available.
    """
    if result.manual is None or result.revision is None:
        raise ValueError("assembly needs the selected manual revision")

    procedure = _select_procedure(result)
    model = context.equipment_model if context else None
    serial = context.equipment_serial if context else None
    kept, filtered, needs_serial = _apply_applicability(procedure.steps, model=model, serial=serial)
    missing: list[str] = []
    unsupported: list[str] = []
    ordered = _order_steps(kept, result.rows, missing=missing, unsupported=unsupported)

    if kind == "step" and step_order is not None:
        selected = [item for item in ordered if item[0].order == step_order]
        if not selected:
            missing.append(f"step_order:{step_order}")
        ordered = selected

    released_steps = [step for step, _ in ordered]
    step_views = [_step_view(step, verdict) for step, verdict in ordered]
    hazards = _hazards(released_steps)
    prerequisites = _prerequisites(released_steps)
    citations, citation_unsupported = _citations(
        released_steps, manual_id=result.manual.manual_id, revision=result.revision
    )
    unsupported.extend(citation_unsupported)
    released_ids = {step.identity.step_id for step in released_steps}

    return AssembledProcedure(
        procedure=_procedure_view(procedure, result.manual.manual_id),
        steps=step_views,
        prerequisites=prerequisites,
        hazards=hazards,
        media=_media(result.manual.figures, released_steps),
        tips=_tips(result.rows, released_ids) if include_tips else [],
        citations=citations,
        revision=result.revision,
        missing_required=_unique(missing),
        unsupported_fields=_unique(unsupported),
        filtered_by_serial=filtered,
        needs_serial=needs_serial,
    )


def _select_procedure(result: RetrievalResult) -> Procedure:
    """Return the card procedure identified by the traversal projection."""
    assert result.manual is not None
    procedure_ids = {
        value for row in result.rows if (value := _identifier(row.get("procedure"), "procedure_id")) is not None
    }
    if len(procedure_ids) > 1:
        raise ValueError("assembly requires rows for one procedure")
    if procedure_ids:
        procedure_id = procedure_ids.pop()
        for procedure in result.manual.procedures:
            if procedure.procedure_id == procedure_id:
                return procedure
        raise ValueError("traversal procedure is absent from the selected manual")
    if len(result.manual.procedures) == 1:
        return result.manual.procedures[0]
    raise ValueError("assembly requires one selected procedure")


def _apply_applicability(
    steps: list[Step], *, model: str | None, serial: str | None
) -> tuple[list[tuple[Step, str]], list[str], bool]:
    """Split steps by applicability without attempting to resolve uncertainty."""
    kept: list[tuple[Step, str]] = []
    filtered: list[str] = []
    needs_serial = False
    for step in steps:
        verdict = applies(step, model=model, serial=serial)
        if verdict == "no":
            filtered.append(step.identity.step_id)
            continue
        if verdict == "unknown" and serial is None:
            needs_serial = True
        kept.append((step, verdict))
    return kept, filtered, needs_serial


def _order_steps(
    kept: list[tuple[Step, str]],
    rows: list[dict[str, Any]],
    *,
    missing: list[str],
    unsupported: list[str],
) -> list[tuple[Step, str]]:
    """Order steps from graph rows and record projection/order inconsistencies."""
    card_ids = {step.identity.step_id for step, _ in kept}
    row_orders: dict[str, int] = {}
    precedes: list[tuple[str, str]] = []
    for row in rows:
        step_id = _identifier(row.get("step"), "step_id") or _string(row.get("step_id"))
        if step_id is None:
            continue
        if step_id not in card_ids:
            unsupported.append(f"row:{step_id}")
            continue
        order = row.get("order")
        if isinstance(order, int):
            row_orders[step_id] = order
        precedes.extend(_precedes(row, step_id))

    sortable: list[tuple[int, Step, str]] = []
    for step, verdict in kept:
        step_id = step.identity.step_id
        order = row_orders.get(step_id)
        if order is None:
            missing.append(f"step:{step_id}:order")
            order = step.order
        sortable.append((order, step, verdict))
    sortable.sort(key=lambda item: (item[0], item[1].identity.step_id))

    actual_orders = [order for order, _, _ in sortable]
    for expected, observed in enumerate(actual_orders, start=1):
        if observed != expected:
            missing.append(f"order_gap:{expected}")
            break
    orders_by_id = {step.identity.step_id: order for order, step, _ in sortable}
    for source, target in precedes:
        if source in orders_by_id and target in orders_by_id and orders_by_id[source] >= orders_by_id[target]:
            missing.append(f"precedes:{source}->{target}")
    return [(step, verdict) for _, step, verdict in sortable]


def _prerequisites(steps: list[Step]) -> Prerequisites:
    """Union parts/tools and inlined hazards across released steps."""
    parts: dict[str, Any] = {}
    tools: dict[str, Any] = {}
    for step in steps:
        for part in step.parts:
            existing = parts.get(part.part_id)
            if existing is None:
                parts[part.part_id] = part.model_copy(deep=True)
            elif existing.quantity is not None and part.quantity is not None:
                parts[part.part_id] = existing.model_copy(update={"quantity": existing.quantity + part.quantity})
        for tool in step.tools:
            tools.setdefault(tool.tool_id, tool)
    return Prerequisites(parts=list(parts.values()), tools=list(tools.values()), hazards=_hazards(steps))


def _tips(rows: list[dict[str, Any]], released_step_ids: set[str]) -> list[TipView]:
    """Return only active, non-orphaned tips for released steps."""
    tips: list[TipView] = []
    seen: set[str] = set()
    for row in rows:
        raw_tip = row.get("tip")
        if not isinstance(raw_tip, dict):
            continue
        step_id = _identifier(row.get("step"), "step_id") or _string(row.get("step_id"))
        tip_id = _identifier(raw_tip, "tip_id")
        if (
            step_id not in released_step_ids
            or tip_id is None
            or tip_id in seen
            or raw_tip.get("orphaned") is True
            or raw_tip.get("active") is False
        ):
            continue
        text = _string(raw_tip.get("text"))
        if not text:
            continue
        seen.add(tip_id)
        tips.append(
            TipView(
                tip_id=tip_id,
                step_id=step_id,
                text=text,
                author_employee_id=_string(raw_tip.get("author_employee_id")),
                created_at=raw_tip.get("created_at"),
            )
        )
    return tips


def _citations(
    steps: list[Step], *, manual_id: str, revision: ManualVersion
) -> tuple[list[ProcedureCitation], list[str]]:
    """Create one citation per step and report unsupported critical fields."""
    citations: list[ProcedureCitation] = []
    unsupported: list[str] = []
    for step in steps:
        step_id = step.identity.step_id
        evidence = step.text.evidence
        if evidence is None or not evidence.substantiates:
            unsupported.append(f"step:{step_id}:text.evidence")
        else:
            citations.append(
                ProcedureCitation(
                    manual_id=manual_id,
                    node_id=evidence.node_id,
                    quote=evidence.quote,
                    page=evidence.page,
                    version_n=revision.n,
                    source_sha256=revision.source_sha256,
                )
            )
        for field_name in ("torque", "duration_minutes"):
            field = getattr(step, field_name)
            if field is not None and not field.substantiated:
                unsupported.append(f"step:{step_id}:{field_name}")
    return citations, unsupported


def _procedure_view(procedure: Procedure, manual_id: str) -> ProcedureView:
    """Project a card procedure into its release view."""
    return ProcedureView(
        procedure_id=procedure.procedure_id,
        manual_id=manual_id,
        title=procedure.title.value or "",
        kind=procedure.kind,
        estimated_minutes=procedure.estimated_minutes,
        skill_level=procedure.skill_level,
        verification=procedure.verification,
    )


def _step_view(step: Step, verdict: str) -> StepView:
    """Project a released card step into its release view."""
    unknown = verdict == "unknown"
    return StepView(
        step_id=step.identity.step_id,
        order=step.order,
        text=step.text.value or "",
        torque=step.torque.value if step.torque else None,
        duration_minutes=step.duration_minutes.value if step.duration_minutes else None,
        applicability="unknown" if unknown else "yes",
        applicability_note="equipment serial is required" if unknown else None,
        part_ids=[part.part_id for part in step.parts],
        tool_ids=[tool.tool_id for tool in step.tools],
        hazard_ids=[hazard.hazard_id for hazard in step.hazards],
        media_ids=[media.media_id for media in step.media],
    )


def _hazards(steps: list[Step]) -> list[HazardView]:
    """Deduplicate hazards while retaining every released step association."""
    hazards: dict[str, HazardView] = {}
    for step in steps:
        for hazard in step.hazards:
            current = hazards.get(hazard.hazard_id)
            if current is None:
                hazards[hazard.hazard_id] = HazardView(
                    hazard_id=hazard.hazard_id,
                    severity=hazard.severity,
                    text=hazard.text.value or "",
                    step_ids=[step.identity.step_id],
                )
            elif step.identity.step_id not in current.step_ids:
                current.step_ids.append(step.identity.step_id)
    return list(hazards.values())


def _media(figures: list[Any], steps: list[Step]) -> list[MediaView]:
    """Project attached card media, placing overview media at procedure level."""
    figures_by_id = {figure.media_id: figure for figure in figures}
    media: list[MediaView] = []
    seen: set[tuple[str, str | None]] = set()
    for step in steps:
        for link in step.media:
            figure = figures_by_id.get(link.media_id)
            if figure is None:
                continue
            step_id = None if link.role == "overview" else step.identity.step_id
            key = (link.media_id, step_id)
            if key in seen:
                continue
            seen.add(key)
            media.append(
                MediaView(
                    media_id=figure.media_id,
                    kind=figure.kind,
                    role=link.role,
                    step_id=step_id,
                    caption=figure.caption,
                    label=figure.label,
                    page=figure.page,
                    t_start=figure.t_start,
                    t_end=figure.t_end,
                )
            )
    rank = {"primary": 0, "secondary": 1, "overview": 2}
    return sorted(media, key=lambda item: (rank[item.role], item.media_id, item.step_id or ""))


def _identifier(value: Any, key: str) -> str | None:
    """Read a graph identifier from an object projection or scalar value."""
    if isinstance(value, dict):
        return _string(value.get(key)) or _string(value.get("_key"))
    return _string(value)


def _string(value: Any) -> str | None:
    """Return nonempty string values without coercing graph data."""
    return value if isinstance(value, str) and value else None


def _precedes(row: dict[str, Any], source: str) -> list[tuple[str, str]]:
    """Read explicit precedes references when a traversal includes them."""
    values = row.get("precedes", [])
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        return []
    targets: list[tuple[str, str]] = []
    for value in values:
        target = _identifier(value, "step_id")
        if target:
            targets.append((source, target))
    return targets


def _unique(values: list[str]) -> list[str]:
    """Keep the first occurrence of each deterministic gap marker."""
    return list(dict.fromkeys(values))
