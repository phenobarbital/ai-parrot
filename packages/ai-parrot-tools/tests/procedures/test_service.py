"""Tests for the procedures release-path service (FEAT-601 M10)."""

from __future__ import annotations

from datetime import date

import pytest

from parrot.knowledge.common.provenance import Evidence
from parrot.knowledge.manuals.models import Applicability, ManualVersion, SerialRange
from parrot_tools.procedures.assembly import AssembledProcedure
from parrot_tools.procedures.retrieval import Clarification, ProcedureRetrieval
from parrot_tools.procedures.service import AnswerOutcome, ProceduresAnswerService, ServiceUnavailable
from parrot_tools.procedures.verifier import ProcedureVerifier

from ._doubles import FakeCatalog, FakeGraphStore, FakeOntology, FakePattern, make_card, make_context

QUESTION = "How do I assemble Model X?"
_AQL = "FOR s IN step RETURN s"


class FakeEvidence:
    """Stands in for ``ManualLibrary.load_section`` (TASK-3713, mirrors test_verifier.py)."""

    def __init__(self, sections: dict[str, str]) -> None:
        self.sections = sections

    async def load_section(self, manual_id: str, version_n: int, node_id: str) -> str | None:
        """Return the scripted archived body for ``node_id``."""
        return self.sections.get(node_id)


class RecordingFileManager:
    """A ``FileManagerInterface``-shaped double that records every presign call."""

    def __init__(self, url: str = "https://fake/figure.png") -> None:
        self.url = url
        self.calls: list[tuple[str, int]] = []

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Record the call and return the scripted url."""
        self.calls.append((path, expiry))
        return self.url


class FlagProducer:
    """A producer whose ``draft`` records that it ran and returns clean prose."""

    def __init__(self, prose: str = "Follow the printed instructions carefully.") -> None:
        self.prose = prose
        self.called = False

    async def draft(self, question: str, assembled: AssembledProcedure, *, context: object) -> str:
        """Flip the flag and return prose that carries no unverifiable claims."""
        self.called = True
        return self.prose


def _card_with_versions() -> object:
    """Build the five-step assembly card with one in-force revision."""
    card = make_card()
    revision = ManualVersion(n=1, revision=card.revision, valid_from=date(2000, 1, 1), source_sha256="")
    return card.model_copy(update={"versions": [revision]})


def _rows(card) -> list[dict]:
    """Build graph-shaped procedure-step rows for ``card`` (mirrors test_assembly.py)."""
    procedure = card.procedures[0]
    return [
        {
            "procedure": {"procedure_id": procedure.procedure_id},
            "step": {"step_id": step.identity.step_id},
            "order": step.order,
        }
        for step in procedure.steps
    ]


def _evidence(card) -> FakeEvidence:
    """Build a verbatim evidence store for every step of ``card``'s procedure."""
    sections = {}
    for step in card.procedures[0].steps:
        evidence: Evidence = step.text.evidence
        sections[evidence.node_id] = evidence.quote
    return FakeEvidence(sections)


def _service(*, card, catalog: FakeCatalog, file_manager, producer=None) -> ProceduresAnswerService:
    """Assemble a fully-wired service over a scripted graph/ontology/catalog."""
    graph = FakeGraphStore(rows_by_aql={_AQL: _rows(card)})
    ontology = FakeOntology({"procedure_steps": FakePattern(_AQL)})
    retrieval = ProcedureRetrieval(
        catalog=catalog, graph_store=graph, tenant_context=None, ontology=ontology, authorization=None
    )
    evidence = _evidence(card)

    def verifier_factory(revision: ManualVersion) -> ProcedureVerifier:
        return ProcedureVerifier(catalog=catalog, evidence=evidence, allowed_revision=revision)

    return ProceduresAnswerService(
        retrieval=retrieval,
        verifier_factory=verifier_factory,
        catalog=catalog,
        file_manager=file_manager,
        producer=producer,
    )


async def test_service_audit_before_release():
    """Failing record_answer => no AnswerOutcome, no presign call."""
    card = _card_with_versions()
    catalog = FakeCatalog(cards=[card], fail_audit=True)
    fm = RecordingFileManager()
    service = _service(card=card, catalog=catalog, file_manager=fm)

    with pytest.raises(ServiceUnavailable):
        await service.answer(QUESTION, request_context=make_context())

    assert fm.calls == []


async def test_stream_answer_buffers():
    """Nothing yielded before release."""
    card = _card_with_versions()
    catalog = FakeCatalog(cards=[card])
    fm = RecordingFileManager()
    producer = FlagProducer()
    service = _service(card=card, catalog=catalog, file_manager=fm, producer=producer)

    agen = service.stream_answer(QUESTION, request_context=make_context())
    assert catalog.answers == []

    first = await agen.__anext__()

    assert producer.called is True
    assert len(catalog.answers) == 1
    assert first == producer.prose


async def test_presign_skips_non_http():
    """A non-http(s) storage backend never leaks a URL into image_urls."""
    card = _card_with_versions()
    catalog = FakeCatalog(cards=[card])
    fm = RecordingFileManager("file:///tmp/x.png")
    service = _service(card=card, catalog=catalog, file_manager=fm)

    outcome = await service.answer(QUESTION, request_context=make_context())

    assert isinstance(outcome, AnswerOutcome)
    assert outcome.image_urls == []


async def test_needs_serial_returns_clarification():
    """A serial-qualified step with no equipment_serial in context asks for one."""
    card = _card_with_versions()
    procedure = card.procedures[0]
    step = procedure.steps[3]
    evidence = Evidence(node_id="serial", quote="A100 to A250", page=4)
    applicability = Applicability(
        serial_ranges=[SerialRange(start="A100", end="A250", format="A000")], evidence=evidence
    )
    procedure.steps[3] = step.model_copy(update={"applicability": applicability})
    catalog = FakeCatalog(cards=[card])
    fm = RecordingFileManager()
    service = _service(card=card, catalog=catalog, file_manager=fm)

    outcome = await service.answer(QUESTION, request_context=make_context())

    assert isinstance(outcome, Clarification)
    assert outcome.reason == "equipment_serial_required"
    assert catalog.answers == []
