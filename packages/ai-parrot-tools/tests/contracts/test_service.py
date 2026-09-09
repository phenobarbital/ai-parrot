"""Shared answer service tests (TASK-3045)."""

from __future__ import annotations

from typing import Any, Optional, Sequence

import pytest

from parrot.knowledge.contracts.evidence import EvidenceArchive
from parrot.knowledge.contracts.models import Citation, ContractCard
from parrot_tools.contracts.retrieval import (
    AuthorizationDenied,
    Clarification,
    ContractRetrieval,
    RequestContext,
    RetrievalResult,
)
from parrot_tools.contracts.service import (
    MAX_DOSSIER_CARDS,
    AnswerOutcome,
    ConfirmationRequired,
    ContractsAnswerService,
    ServiceUnavailable,
)
from parrot_tools.contracts.verifier import AnswerDraft, CitationVerifier, Claim

from .test_retrieval import TODAY, FakeCatalog, make_card, reader_context

CLAUSE = "Vendor shall maintain SOC 2 Type II certification."
INSURANCE = "Vendor shall carry cyber liability insurance."


class ScriptedProducer:
    """Returns a scripted draft and records what it was given."""

    def __init__(self, draft: Optional[AnswerDraft] = None) -> None:
        self.draft_value = draft
        self.calls: list[tuple[str, int]] = []

    async def draft(
        self,
        question: str,
        result: RetrievalResult,
        dossier: Sequence[ContractCard],
    ) -> AnswerDraft:
        self.calls.append((question, len(dossier)))
        if self.draft_value is not None:
            return self.draft_value
        citations = [
            Citation(
                contract_id=card.contract_id,
                node_id="0005",
                quote=CLAUSE,
                page=12,
                version_n=1,
                source_sha256=card.source_sha256,
            )
            for card in dossier
        ]
        return AnswerDraft(
            claims=[Claim(text="ACME must hold SOC 2.", citations=citations)]
        )


@pytest.fixture()
async def service(tmp_path) -> ContractsAnswerService:
    catalog = FakeCatalog()
    card = make_card()
    await catalog.upsert(card)

    archive = EvidenceArchive(tmp_path / "evidence", tenant_id="troc")
    for version in card.versions:
        await archive.archive(
            archive.reference(
                card.contract_id,
                version_n=version.n,
                revision=version.revision,
                source_sha256=version.source_sha256,
            ),
            {"0005": f"4. Compliance. {CLAUSE}", "0008": f"7. Insurance. {INSURANCE}"},
            pages={"0005": 12},
        )

    retrieval = ContractRetrieval(catalog=catalog, today=lambda: TODAY)
    return ContractsAnswerService(
        retrieval=retrieval,
        verifier=CitationVerifier(catalog=catalog, evidence=archive),
        producer=ScriptedProducer(),
    )


# --------------------------------------------------------------------------
# 1. Answer shapes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_lookup_is_released_with_citations_and_audited(service):
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )

    assert isinstance(outcome, AnswerOutcome)
    assert outcome.answer.answer_kind == "lookup"
    assert outcome.answer.answer == "ACME must hold SOC 2."
    assert outcome.answer.citations[0].contract_id == "acme-msa"
    assert outcome.answer.pattern == "contracts_requiring_standard"

    record = await service.catalog.get_answer(outcome.answer_id)
    assert record is not None
    assert record.authorization.allowed is True
    assert record.user == "bob@troc"
    assert record.citations


@pytest.mark.asyncio
async def test_an_evaluative_question_returns_a_handoff_without_judgment(service):
    outcome = await service.answer(
        "Should we accept the redline on acme-msa?", request_context=reader_context()
    )

    assert outcome.answer.answer_kind == "interpretation_required"
    assert outcome.answer.answer is None, "no legal judgment text is ever produced"
    handoff = outcome.answer.handoff
    assert handoff.why_judgment
    assert "acme-msa" in handoff.related_contracts
    assert handoff.suggested_owner == "emp-1"
    # Clauses are LOCATED (not adjudicated) and each still passed the gate.
    assert [clause.node_id for clause in handoff.located_clauses] == ["0005", "0008"]
    assert handoff.located_clauses[0].quote == CLAUSE
    assert (await service.catalog.get_answer(outcome.answer_id)).answer_kind == (
        "interpretation_required"
    )


@pytest.mark.asyncio
async def test_pre_triage_runs_before_retrieval(service):
    """An evaluative question never reaches the retrieval layer."""
    probes: list[str] = []
    original = service.retrieval.retrieve

    async def spy(question, context):
        probes.append(question)
        return await original(question, context)

    service.retrieval.retrieve = spy  # type: ignore[method-assign]
    await service.answer("Can we terminate acme-msa early?", request_context=reader_context())
    assert probes == []


@pytest.mark.asyncio
async def test_an_unsupported_question_returns_a_typed_clarification(service):
    result = await service.answer(
        "what is the weather in madrid", request_context=reader_context()
    )
    assert isinstance(result, Clarification)
    assert result.reason
    assert not hasattr(result, "answer_kind"), "no invented answer kind"


@pytest.mark.asyncio
async def test_an_ambiguous_entity_returns_a_clarification(service):
    await service.catalog.upsert(make_card("alpha", title="master agreement with globex"))
    await service.catalog.upsert(make_card("beta", title="master agreement with globex"))

    result = await service.answer(
        "Who signed the master agreement with globex?", request_context=reader_context()
    )
    assert isinstance(result, Clarification)
    assert result.candidates == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_an_unverifiable_draft_becomes_not_found(service):
    service.producer = ScriptedProducer(
        AnswerDraft(
            claims=[
                Claim(
                    text="ACME must give us a pony.",
                    citations=[
                        Citation(
                            contract_id="acme-msa",
                            node_id="0005",
                            quote="Vendor shall provide one pony.",
                            version_n=1,
                            source_sha256="sha-acme-msa",
                        )
                    ],
                )
            ]
        )
    )
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )

    assert outcome.answer.answer_kind == "not_found"
    assert outcome.answer.answer is None
    assert outcome.rejected
    assert (await service.catalog.get_answer(outcome.answer_id)).answer_kind == "not_found"


# --------------------------------------------------------------------------
# 2. Failing closed
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_denied_request_is_released_as_denied_and_audited(service):
    stranger = reader_context(roles=())
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=stranger
    )

    assert outcome.answer.answer_kind == "denied"
    assert outcome.answer.answer is None
    assert outcome.answer.citations == []
    record = await service.catalog.get_answer(outcome.answer_id)
    assert record.authorization.allowed is False
    assert record.authorization.reason


@pytest.mark.asyncio
async def test_a_forged_tenant_or_missing_principal_is_denied(service):
    for context in (
        reader_context(tenant_id="other-tenant"),
        RequestContext(roles=("contract_reader",)),
    ):
        outcome = await service.answer(
            "Which contracts require SOC 2?", request_context=context
        )
        assert outcome.answer.answer_kind == "denied"


@pytest.mark.asyncio
async def test_an_audit_outage_fails_the_request_instead_of_answering(service):
    service.catalog.audit_fails = True
    with pytest.raises(ServiceUnavailable, match="could not be audited"):
        await service.answer(
            "Which contracts require SOC 2?", request_context=reader_context()
        )


@pytest.mark.asyncio
async def test_even_a_denial_is_not_released_without_an_audit(service):
    service.catalog.audit_fails = True
    with pytest.raises(ServiceUnavailable):
        await service.answer(
            "Which contracts require SOC 2?", request_context=reader_context(roles=())
        )


@pytest.mark.asyncio
async def test_owner_operations_require_the_owner_role_and_a_confirmation(service):
    reader = reader_context(roles=("contract_reader",), confirmed=True)
    with pytest.raises(AuthorizationDenied):
        await service.retire_answer("ans-1", request_context=reader, reason="x")

    unconfirmed = reader_context(roles=("contract_owner",), confirmed=False)
    with pytest.raises(ConfirmationRequired, match="explicit confirmation"):
        await service.retire_answer("ans-1", request_context=unconfirmed, reason="x")


@pytest.mark.asyncio
async def test_a_forged_actor_cannot_grant_itself_the_owner_role(service):
    forged = RequestContext(
        user_id="mallory@example", roles=("contract_owner",), tenant_id="other-tenant",
        confirmed=True,
    )
    with pytest.raises(AuthorizationDenied, match="does not match this catalog"):
        await service.retire_answer("ans-1", request_context=forged, reason="x")


@pytest.mark.asyncio
async def test_write_operations_need_a_configured_library(service):
    owner = reader_context(roles=("contract_owner",), confirmed=True)
    with pytest.raises(ServiceUnavailable, match="no contract library"):
        await service.verify_card("acme-msa", {"title": None}, request_context=owner)


# --------------------------------------------------------------------------
# 3. Retirement, streaming and the dossier bound
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retirement_suppresses_evidence_from_later_answers(service):
    first = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )
    assert first.answer.answer_kind == "lookup"

    owner = reader_context(roles=("contract_owner",), confirmed=True)
    retired = await service.retire_answer(
        first.answer_id, request_context=owner, reason="wrong clause"
    )
    assert retired.retired is True
    assert first.answer_id in service.invalidated

    second = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )
    assert second.answer.answer_kind == "not_found", "retired evidence cannot come back"


@pytest.mark.asyncio
async def test_retired_evidence_cannot_reach_a_handoff_either(service):
    first = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )
    owner = reader_context(roles=("contract_owner",), confirmed=True)
    await service.retire_answer(first.answer_id, request_context=owner, reason="wrong")

    handoff_outcome = await service.answer(
        "Should we accept the redline on acme-msa?", request_context=reader_context()
    )
    quotes = [
        citation.quote
        for citation in handoff_outcome.answer.handoff.located_clauses
    ]
    assert quotes, "the handoff still locates other clauses"
    assert CLAUSE not in quotes, "the retired clause is suppressed"


@pytest.mark.asyncio
async def test_streaming_buffers_until_the_whole_gate_has_passed(service):
    chunks = [chunk async for chunk in service.stream_answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )]
    assert chunks == ["ACME must hold SOC 2."]

    # A denied request streams no substantive text.
    denied = [chunk async for chunk in service.stream_answer(
        "Which contracts require SOC 2?", request_context=reader_context(roles=())
    )]
    assert denied == []


@pytest.mark.asyncio
async def test_streaming_never_emits_a_raw_draft(service):
    service.producer = ScriptedProducer(
        AnswerDraft(
            claims=[
                Claim(
                    text="RAW MODEL TEXT that never passed verification",
                    citations=[
                        Citation(
                            contract_id="acme-msa",
                            node_id="0005",
                            quote="not in the document",
                            version_n=1,
                            source_sha256="sha-acme-msa",
                        )
                    ],
                )
            ]
        )
    )
    chunks = [chunk async for chunk in service.stream_answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )]
    assert chunks == [], "an unverified draft is never streamed"


@pytest.mark.asyncio
async def test_the_dossier_handed_to_a_producer_is_bounded(service):
    for index in range(MAX_DOSSIER_CARDS + 5):
        await service.catalog.upsert(make_card(f"bulk-{index:03d}"))

    producer = ScriptedProducer(AnswerDraft(claims=[]))
    service.producer = producer
    await service.answer("Which contracts require SOC 2?", request_context=reader_context())

    assert producer.calls[0][1] <= MAX_DOSSIER_CARDS


@pytest.mark.asyncio
async def test_a_missing_producer_is_a_service_failure(service):
    service.producer = None
    with pytest.raises(ServiceUnavailable, match="no answer producer"):
        await service.answer(
            "Which contracts require SOC 2?", request_context=reader_context()
        )


@pytest.mark.asyncio
async def test_an_optional_triage_adapter_sees_only_the_question(service):
    seen: list[Any] = []

    class Triage:
        async def classify(self, question):
            seen.append(question)
            return type("Verdict", (), {"interpretation_required": True})()

    service.triage = Triage()
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )

    assert seen == ["Which contracts require SOC 2?"], "no dossier, no roles, no AQL"
    assert outcome.answer.answer_kind == "interpretation_required"
