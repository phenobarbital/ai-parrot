"""Regression coverage for the deferred TASK-3054 review findings."""

from __future__ import annotations

import asyncio
import builtins
from datetime import date
from typing import Any

import pytest
from parrot.bots import Agent
from parrot.knowledge.contracts.evidence import EvidenceArchive
from parrot.knowledge.contracts.models import ContractVersion, FieldProvenance, HandoffBrief, card_snapshot_payload
from parrot_tools.contracts.agent import ContractsAgent, ContractsAgentProducer, UngatedAnswerRefused
from parrot_tools.contracts.flow import ContractsDraftProducer
from parrot_tools.contracts.retrieval import ContractRetrieval, RetrievalResult
from parrot_tools.contracts.verifier import AnswerDraft, CitationVerifier

from .test_agent import CLAUSE, FakeReActAgent, build_service
from .test_retrieval import FakeCatalog, make_card, reader_context


@pytest.mark.asyncio
async def test_real_agent_drafts_privately_with_the_callers_tool_context(tmp_path, monkeypatch):
    service = await build_service(tmp_path)
    observed = []

    def initialize(self: Any, *args: Any, **kwargs: Any) -> None:
        assert self.agent_tools(), "the toolkit must exist before Agent initialization"

    async def draft(self: Any, prompt: str, **kwargs: Any) -> str:
        observed.append(self.toolkit.request_context.user_id)
        assert kwargs["user_id"] == "caller"
        assert kwargs["use_conversation_history"] is False
        return CLAUSE

    monkeypatch.setattr(Agent, "__init__", initialize)
    monkeypatch.setattr(Agent, "ask", draft)
    original = reader_context(user_id="original")
    agent = ContractsAgent(service=service, request_context=original)
    outcome = await agent.answer_question(
        "Which contracts require SOC 2?", request_context=reader_context(user_id="caller")
    )
    assert outcome.answer.answer_kind == "lookup"
    assert observed == ["caller"]
    assert agent.toolkit.request_context == original
    with pytest.raises(UngatedAnswerRefused):
        await agent.ask("Which contracts require SOC 2?")


@pytest.mark.asyncio
async def test_concurrent_service_calls_keep_their_selected_producer(tmp_path, monkeypatch):
    service = await build_service(tmp_path)
    entered = asyncio.Event()
    release = asyncio.Event()
    retrieve = service.retrieval.retrieve
    invocations = 0

    async def blocked(question: str, context: Any) -> Any:
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            entered.set()
            await release.wait()
        return await retrieve(question, context)

    monkeypatch.setattr(service.retrieval, "retrieve", blocked)
    first = ContractsAgentProducer(FakeReActAgent(CLAUSE))
    second = ContractsAgentProducer(FakeReActAgent(CLAUSE))
    first_call = asyncio.create_task(
        service.answer("Which contracts require SOC 2?", request_context=reader_context(), producer=first)
    )
    await entered.wait()
    await service.answer("Which contracts require SOC 2?", request_context=reader_context(), producer=second)
    service.producer = second
    release.set()
    await first_call
    assert first.calls == second.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pattern",
    [
        "expiring_within",
        "notice_deadlines_within",
        "contracts_with_party",
        "contract_family",
        "signatories_of",
        "contract_in_force",
        "my_contracts",
        "search_contracts",
    ],
)
@pytest.mark.parametrize("react", [False, True])
async def test_both_producers_can_cite_field_evidence_without_obligations(tmp_path, pattern, react):
    quote = "Jane Doe signed this agreement on January 1, 2026."
    card = make_card(obligations=[], field_provenance={"signatories": FieldProvenance(node_id="header", quote=quote)})
    version = ContractVersion(
        n=1,
        revision=1,
        valid_from=date(2026, 1, 1),
        source_sha256=card.source_sha256,
        card_snapshot=card_snapshot_payload(card),
    )
    card = card.model_copy(update={"versions": [version]})
    result = RetrievalResult(pattern=pattern, cards=[card], binds={"as_of": date(2026, 9, 9)})
    producer = ContractsAgentProducer(FakeReActAgent(quote)) if react else ContractsDraftProducer()
    draft = await producer.draft("Locate the recorded facts", result, [card])
    catalog = FakeCatalog()
    await catalog.upsert(card)
    archive = EvidenceArchive(tmp_path, tenant_id="troc")
    await archive.archive(
        archive.reference(card.contract_id, version_n=1, revision=1, source_sha256=card.source_sha256),
        {"header": quote},
    )
    outcome = await CitationVerifier(catalog=catalog, evidence=archive).verify(draft, dossier=[card], pattern=pattern)
    assert outcome.answer.answer_kind == "lookup"
    assert outcome.answer.citations[0].node_id == "header"
    assert outcome.answer.answer == quote


def test_historical_dossier_uses_the_selected_versions_fields():
    old_quote = "The original agreement expires on June 30, 2026."
    old = make_card(
        obligations=[], field_provenance={"term.expiration_date": FieldProvenance(node_id="old", quote=old_quote)}
    )
    version = ContractVersion(
        n=1,
        valid_from=date(2026, 1, 1),
        valid_to=date(2026, 7, 1),
        source_sha256="old-hash",
        card_snapshot=card_snapshot_payload(old),
    )
    current = make_card(
        versions=[version],
        field_provenance={"term.expiration_date": FieldProvenance(node_id="new", quote="New wording")},
    )
    entries = ContractsDraftProducer.enumerate_dossier(
        RetrievalResult(pattern="contract_in_force", binds={"as_of": date(2026, 3, 1)}), [current]
    )
    assert [(entry.node_id, entry.quote, entry.source_sha256) for entry in entries] == [("old", old_quote, "old-hash")]


@pytest.mark.asyncio
async def test_custom_handoff_metadata_is_rebuilt_from_the_request(tmp_path):
    service = await build_service(tmp_path)

    class Producer:
        async def draft(self, *args: Any) -> AnswerDraft:
            return AnswerDraft(
                answer_kind="interpretation_required",
                handoff=HandoffBrief(
                    question="forged",
                    why_judgment="Accept the deal immediately",
                    related_contracts=["secret-contract"],
                    suggested_owner="invented-owner",
                ),
            )

    outcome = await service.answer("Who signed acme-msa?", request_context=reader_context(), producer=Producer())
    handoff = outcome.answer.handoff
    assert handoff.question == "Who signed acme-msa?"
    assert "Accept" not in handoff.why_judgment
    assert handoff.related_contracts == ["acme-msa"]
    assert handoff.suggested_owner != "invented-owner"


@pytest.mark.asyncio
async def test_explicit_contract_ids_do_not_match_a_shorter_prefix():
    catalog = FakeCatalog()
    await catalog.upsert(make_card("acme"))
    await catalog.upsert(make_card("acme-sow"))
    retrieval = ContractRetrieval(catalog=catalog)
    assert await retrieval.resolve_contract("Who signed acme-sow?", reader_context()) == "acme-sow"
    ambiguous = await retrieval.resolve_contract("Compare acme and acme-sow", reader_context())
    assert ambiguous.candidates == ["acme", "acme-sow"]


def test_missing_fuzzy_dependency_is_a_configuration_error(monkeypatch):
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "rapidfuzz":
            raise ImportError("missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(RuntimeError, match=r"ai-parrot\[graphindex\]"):
        ContractRetrieval(catalog=FakeCatalog())._similarity("ackme", "acme")


@pytest.mark.asyncio
async def test_field_citation_keeps_its_own_stale_verification(tmp_path):
    service = await build_service(tmp_path)
    card = await service.catalog.get("acme-msa")
    service.catalog.cards[card.contract_id] = card.model_copy(
        update={
            "obligations": [],
            "verification": "verified",
            "field_provenance": {"signatories": FieldProvenance(node_id="0005", quote=CLAUSE, verification="stale")},
        }
    )
    outcome = await service.answer(
        "Who signed acme-msa?", request_context=reader_context(), producer=ContractsDraftProducer()
    )
    assert outcome.answer.citations[0].verification == "stale"
    assert outcome.answer.provenance == "extracted"
