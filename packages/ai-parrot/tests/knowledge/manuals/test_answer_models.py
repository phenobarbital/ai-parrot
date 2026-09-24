"""Tests for TASK-3700: ProcedureAnswer, citations, view models and kind invariants."""

import pytest

from parrot.knowledge.manuals.models import (
    HazardView,
    MediaView,
    ProcedureAnswer,
    ProcedureCitation,
    ProcedureView,
    StepView,
    TipView,
    derive_provenance,
)


def _cite(verified: bool = False) -> ProcedureCitation:
    return ProcedureCitation(
        manual_id="model-x-b",
        node_id="0003",
        quote="Torque to 12 Nm.",
        page=3,
        verification="verified" if verified else "extracted",
    )


def _procedure_view() -> ProcedureView:
    return ProcedureView(procedure_id="p1", manual_id="model-x-b", title="Assemble bracket", kind="assembly")


def _step(order: int = 1, step_id: str = "s1") -> StepView:
    return StepView(step_id=step_id, order=order, text="Remove bolts.")


def test_procedure_answer_kind_invariants():
    """procedure needs steps+citations; incomplete carries reason and no steps; denied carries nothing."""
    answer = ProcedureAnswer(
        answer_kind="procedure",
        procedure=_procedure_view(),
        steps=[_step(order=1, step_id="s1"), _step(order=2, step_id="s2")],
        citations=[_cite()],
    )
    assert answer.answer_kind == "procedure"
    assert len(answer.steps) == 2

    incomplete = ProcedureAnswer(answer_kind="incomplete", reason="step 3 missing")
    assert incomplete.reason == "step 3 missing"
    assert incomplete.steps == []

    denied = ProcedureAnswer(answer_kind="denied")
    assert denied.answer == ""
    assert denied.steps == []
    assert denied.citations == []


def test_procedure_answer_requires_steps_and_citations():
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="procedure", procedure=_procedure_view())
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="procedure", procedure=_procedure_view(), steps=[_step()])


def test_procedure_answer_requires_unique_and_increasing_orders():
    with pytest.raises(ValueError):
        ProcedureAnswer(
            answer_kind="procedure",
            procedure=_procedure_view(),
            steps=[_step(order=2, step_id="s1"), _step(order=1, step_id="s2")],
            citations=[_cite()],
        )
    with pytest.raises(ValueError):
        ProcedureAnswer(
            answer_kind="procedure",
            procedure=_procedure_view(),
            steps=[_step(order=1, step_id="s1"), _step(order=1, step_id="s2")],
            citations=[_cite()],
        )


def test_incomplete_releases_no_steps():
    with pytest.raises(ValueError):
        ProcedureAnswer(
            answer_kind="incomplete",
            reason="step 3 missing",
            steps=[StepView(step_id="s1", order=1, text="Remove bolts.")],
        )


def test_incomplete_requires_reason():
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="incomplete")


def test_denied_rejects_every_payload_field():
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="denied", answer="some text")
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="denied", citations=[_cite()])
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="denied", procedure=_procedure_view())


def test_provenance_is_derived_not_trusted():
    answer = ProcedureAnswer(
        answer_kind="lookup", answer="See page 3.", citations=[_cite(True)], provenance="extracted"
    )
    assert answer.provenance == "verified"


def test_derive_provenance_mixed():
    assert derive_provenance([_cite(True), _cite(False)]) == "mixed"


def test_derive_provenance_empty_and_all_verified():
    assert derive_provenance([]) == "extracted"
    assert derive_provenance([_cite(True)]) == "verified"
    assert derive_provenance([_cite(False)]) == "extracted"


def test_unknown_applicability_requires_note():
    with pytest.raises(ValueError):
        StepView(step_id="s1", order=1, text="Remove bolts.", applicability="unknown")
    view = StepView(
        step_id="s1", order=1, text="Remove bolts.", applicability="unknown", applicability_note="serial unknown"
    )
    assert view.applicability_note == "serial unknown"


def test_citation_rejects_blank_quote():
    with pytest.raises(ValueError):
        ProcedureCitation(manual_id="m1", node_id="n1", quote="   ")


def test_citation_key_is_manual_and_node_id():
    citation = _cite()
    assert citation.key == ("model-x-b", "0003")


def test_lookup_rejects_steps_and_procedure():
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="lookup", answer="text", citations=[_cite()], steps=[_step()])
    with pytest.raises(ValueError):
        ProcedureAnswer(answer_kind="lookup", answer="text", citations=[_cite()], procedure=_procedure_view())


def test_clarification_not_found_out_of_scope_carry_nothing():
    for kind in ("clarification", "not_found", "out_of_scope"):
        answer = ProcedureAnswer(answer_kind=kind)
        assert answer.steps == []
        assert answer.citations == []
        with pytest.raises(ValueError):
            ProcedureAnswer(answer_kind=kind, citations=[_cite()])


def test_hazard_and_media_and_tip_views_construct():
    hazard = HazardView(hazard_id="h1", severity="warning", text="Wear gloves.")
    media = MediaView(media_id="m1", kind="figure", role="primary")
    tip = TipView(tip_id="t1", step_id="s1", text="Reverse the clip on rev B.")
    assert hazard.severity == "warning"
    assert media.role == "primary"
    assert tip.step_id == "s1"
