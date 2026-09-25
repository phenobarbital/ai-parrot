"""Tests for the blocking procedure verifier (FEAT-601 M10, R2)."""

from __future__ import annotations

from parrot.knowledge.manuals.models import ManualVersion, Prerequisites, ProcedureCitation, ProcedureView, StepView
from parrot_tools.procedures.assembly import AssembledProcedure
from parrot_tools.procedures.verifier import ProcedureVerifier


class FakeEvidence:
    """Stands in for ManualLibrary.load_section (TASK-3713)."""

    def __init__(self, sections: dict[str, str]) -> None:
        self.sections = sections

    async def load_section(self, manual_id, version_n, node_id):
        return self.sections.get(node_id)


def _revision(*, n: int = 1, revision: str = "A", source_sha256: str = "a" * 64) -> ManualVersion:
    """Build the archived revision citations must be pinned to."""
    return ManualVersion(n=n, revision=revision, source_sha256=source_sha256)


def _procedure_view() -> ProcedureView:
    """Build a minimal released procedure view."""
    return ProcedureView(procedure_id="proc-1", manual_id="manual-1", title="Assemble widget", kind="assembly")


def _step_view(order: int, *, torque: str | None = None, duration_minutes: int | None = None) -> StepView:
    """Build a minimal released step view."""
    return StepView(
        step_id=f"step-{order}",
        order=order,
        text=f"Do step {order}",
        torque=torque,
        duration_minutes=duration_minutes,
    )


def _citation(node_id: str, quote: str, *, version_n: int = 1, source_sha256: str = "") -> ProcedureCitation:
    """Build a released citation for one node."""
    return ProcedureCitation(
        manual_id="manual-1", node_id=node_id, quote=quote, version_n=version_n, source_sha256=source_sha256
    )


def _assembled(
    steps: list[StepView],
    citations: list[ProcedureCitation],
    *,
    missing_required: list[str] | None = None,
    unsupported_fields: list[str] | None = None,
    revision: ManualVersion | None = None,
) -> AssembledProcedure:
    """Build an assembled procedure without going through retrieval/assembly I/O."""
    return AssembledProcedure(
        procedure=_procedure_view(),
        steps=steps,
        prerequisites=Prerequisites(),
        citations=citations,
        revision=revision or _revision(),
        missing_required=missing_required or [],
        unsupported_fields=unsupported_fields or [],
    )


async def test_verifier_blocks_incomplete():
    """missing_required ⇒ answer_kind="incomplete", zero steps released (contrast with contracts drop semantics)."""
    step = _step_view(1)
    citation = _citation("node-1", "Tighten the bolt")
    assembled = _assembled([step], [citation], missing_required=["step:x:order"])
    evidence = FakeEvidence({"node-1": "Tighten the bolt to spec."})
    verifier = ProcedureVerifier(catalog=None, evidence=evidence, allowed_revision=_revision())

    outcome = await verifier.verify(assembled, draft_prose="", kind="procedure", pattern=None)

    assert outcome.answer.answer_kind == "incomplete"
    assert outcome.answer.steps == []
    assert "step:x:order" in outcome.blocked_reason


async def test_verifier_rejects_non_verbatim_quote():
    """A citation whose quote is absent from the archived section blocks release."""
    step = _step_view(1)
    citation = _citation("node-1", "Tighten the bolt")
    assembled = _assembled([step], [citation])
    evidence = FakeEvidence({"node-1": "This body never mentions the fastener at all."})
    verifier = ProcedureVerifier(catalog=None, evidence=evidence, allowed_revision=_revision())

    outcome = await verifier.verify(assembled, draft_prose="", kind="procedure", pattern=None)

    assert outcome.answer.answer_kind == "incomplete"
    assert len(outcome.rejected) == 1
    assert "verbatim" in outcome.rejected[0].reason


async def test_verifier_prose_cannot_add_steps():
    """Prose naming an unknown step/value is dropped."""
    steps = [_step_view(order, torque=f"{order * 10} N·m") for order in range(1, 6)]
    citations = [_citation(f"node-{order}", f"Step {order} text") for order in range(1, 6)]
    sections = {f"node-{order}": f"Step {order} text in the full body." for order in range(1, 6)}
    assembled = _assembled(steps, citations)
    evidence = FakeEvidence(sections)
    verifier = ProcedureVerifier(catalog=None, evidence=evidence, allowed_revision=_revision())

    outcome = await verifier.verify(assembled, draft_prose="Then do step 7 at 45 Nm", kind="procedure", pattern=None)

    assert outcome.answer.answer_kind == "procedure"
    assert outcome.answer.answer == ""
    assert outcome.dropped_claims


async def test_verifier_releases_complete_procedure():
    """All quotes verbatim ⇒ answer_kind "procedure", 5 steps, 5 citations."""
    steps = [_step_view(order, torque=f"{order * 10} N·m") for order in range(1, 6)]
    citations = [_citation(f"node-{order}", f"Step {order} text") for order in range(1, 6)]
    sections = {f"node-{order}": f"Step {order} text in the full body." for order in range(1, 6)}
    assembled = _assembled(steps, citations)
    evidence = FakeEvidence(sections)
    verifier = ProcedureVerifier(catalog=None, evidence=evidence, allowed_revision=_revision())

    outcome = await verifier.verify(assembled, draft_prose="Follow step 3 at 30 N·m.", kind="procedure", pattern=None)

    assert outcome.answer.answer_kind == "procedure"
    assert len(outcome.answer.steps) == 5
    assert len(outcome.answer.citations) == 5
    assert outcome.answer.answer == "Follow step 3 at 30 N·m."
    assert not outcome.dropped_claims
    assert not outcome.rejected
