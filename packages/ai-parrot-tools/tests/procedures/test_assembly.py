"""Tests for pure procedure assembly."""

from __future__ import annotations

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.models import Applicability, ManualVersion, MediaLink, PartRef, SerialRange, ToolRef
from parrot_tools.procedures.assembly import assemble_procedure
from parrot_tools.procedures.retrieval import RetrievalResult

from ._doubles import make_card, make_context


def _result(card, rows):
    """Build retrieval output pinned to the card's selected revision."""
    revision = ManualVersion(n=1, revision=card.revision, source_sha256="source-sha")
    return RetrievalResult(pattern="procedure_steps", rows=rows, manual=card, revision=revision)


def _rows(card):
    """Build graph-shaped procedure-step rows for a card."""
    procedure = card.procedures[0]
    return [
        {
            "procedure": {"procedure_id": procedure.procedure_id},
            "step": {"step_id": step.identity.step_id},
            "order": step.order,
        }
        for step in procedure.steps
    ]


def test_assemble_procedure_complete_and_gaps():
    """Assembly orders steps, deduplicates prerequisites, and excludes orphaned tips."""
    card = make_card()
    first = card.procedures[0].steps[0]
    second = card.procedures[0].steps[1]
    part_evidence = Evidence(node_id="parts", quote="Use the bolt", page=1)
    shared_part = PartRef(
        part_id="bolt", name=Extracted[str](value="Bolt", evidence=part_evidence, confidence=1.0), quantity=1
    )
    shared_tool = ToolRef(tool_id="wrench", name=Extracted[str](value="Wrench", evidence=part_evidence, confidence=1.0))
    card.procedures[0].steps[0] = first.model_copy(update={"parts": [shared_part], "tools": [shared_tool]})
    card.procedures[0].steps[1] = second.model_copy(update={"parts": [shared_part], "tools": [shared_tool]})
    rows = _rows(card)
    rows.append(
        {
            "step": {"step_id": card.procedures[0].steps[0].identity.step_id},
            "tip": {"tip_id": "orphan", "text": "Ignore me", "orphaned": True},
        }
    )

    assembled = assemble_procedure(_result(card, rows), kind="procedure")

    assert [step.order for step in assembled.steps] == [1, 2, 3, 4, 5]
    assert assembled.prerequisites.parts[0].quantity == 2
    assert [tool.tool_id for tool in assembled.prerequisites.tools] == ["wrench"]
    assert assembled.tips == []
    assert len(assembled.citations) == 5
    assert assembled.missing_required == []

    rows[2].pop("order")
    with_gap = assemble_procedure(_result(card, rows), kind="procedure")
    step_id = card.procedures[0].steps[2].identity.step_id
    assert f"step:{step_id}:order" in with_gap.missing_required


def test_assemble_filters_by_serial_and_flags_unknown():
    """Out-of-range serials drop a step and absent serials preserve uncertainty."""
    card = make_card()
    step = card.procedures[0].steps[3]
    evidence = Evidence(node_id="serial", quote="A100 to A250", page=4)
    applicability = Applicability(serial_ranges=[SerialRange(start="A100", end="A250", format="A000")], evidence=evidence)
    card.procedures[0].steps[3] = step.model_copy(update={"applicability": applicability})
    rows = _rows(card)

    excluded = assemble_procedure(_result(card, rows), kind="procedure", context=make_context(equipment_serial="A300"))
    assert step.identity.step_id in excluded.filtered_by_serial
    assert len(excluded.steps) == 4

    unknown = assemble_procedure(_result(card, rows), kind="procedure", context=make_context(equipment_serial=None))
    unknown_step = next(item for item in unknown.steps if item.step_id == step.identity.step_id)
    assert unknown_step.applicability == "unknown"
    assert unknown.needs_serial is True


def test_single_step_keeps_prerequisites_and_hazards():
    """A step answer retains the selected step's local safety checklist."""
    card = make_card()
    step = card.procedures[0].steps[1]
    evidence = Evidence(node_id="part", quote="Use a wrench", page=2)
    card.procedures[0].steps[1] = step.model_copy(
        update={
            "parts": [PartRef(part_id="nut", name=Extracted[str](value="Nut", evidence=evidence, confidence=1.0))],
            "tools": [ToolRef(tool_id="wrench", name=Extracted[str](value="Wrench", evidence=evidence, confidence=1.0))],
            "media": [MediaLink(media_id="figure-1", role="primary", confidence=1.0)],
        }
    )

    assembled = assemble_procedure(_result(card, _rows(card)), kind="step", step_order=2)

    assert [item.order for item in assembled.steps] == [2]
    assert [part.part_id for part in assembled.prerequisites.parts] == ["nut"]
    assert [tool.tool_id for tool in assembled.prerequisites.tools] == ["wrench"]
    assert [hazard.hazard_id for hazard in assembled.hazards] == ["hazard-2"]
