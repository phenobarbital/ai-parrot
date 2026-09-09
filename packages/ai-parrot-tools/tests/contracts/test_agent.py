"""ReAct contracts agent tests (TASK-3048)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.knowledge.contracts.evidence import EvidenceArchive
from parrot_tools.contracts.agent import (
    CONTRACTS_SYSTEM_PROMPT,
    ContractsAgent,
    ContractsAgentProducer,
)
from parrot_tools.contracts.flow import ContractsAnswerFlow, ContractsDraftProducer
from parrot_tools.contracts.retrieval import Clarification, ContractRetrieval
from parrot_tools.contracts.service import (
    AnswerOutcome,
    ContractsAnswerService,
    ServiceUnavailable,
)
from parrot_tools.contracts.verifier import CitationVerifier

from .test_retrieval import TODAY, FakeCatalog, make_card, reader_context

CLAUSE = "Vendor shall maintain SOC 2 Type II certification."
INSURANCE = "Vendor shall carry cyber liability insurance."


class FakeReActAgent:
    """A ReAct agent double: replies with scripted text."""

    def __init__(self, reply: str = "", *, fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.prompts: list[str] = []

    async def ask(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider unavailable")
        return type("Reply", (), {"output": self.reply})()


async def build_service(tmp_path) -> ContractsAnswerService:
    """A service over one archived card."""
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
    return ContractsAnswerService(
        retrieval=ContractRetrieval(catalog=catalog, today=lambda: TODAY),
        verifier=CitationVerifier(catalog=catalog, evidence=archive),
    )


@pytest.fixture()
async def service(tmp_path) -> ContractsAnswerService:
    return await build_service(tmp_path)


@pytest.fixture()
def agent_producer(service) -> ContractsAgentProducer:
    producer = ContractsAgentProducer(FakeReActAgent(CLAUSE))
    service.producer = producer
    return producer


# --------------------------------------------------------------------------
# The agent drafts; the service releases
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_shared_service_is_what_releases_the_answer(service, agent_producer):
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )

    assert isinstance(outcome, AnswerOutcome)
    assert outcome.answer.answer_kind == "lookup"
    assert outcome.answer.citations
    assert agent_producer.calls == 1
    assert await service.catalog.get_answer(outcome.answer_id) is not None


@pytest.mark.asyncio
async def test_react_and_fixed_flow_agree_on_the_same_case(tmp_path):
    """Same question, same protected shape from both producers."""
    react_service = await build_service(tmp_path / "react")
    react_service.producer = ContractsAgentProducer(FakeReActAgent(CLAUSE))

    flow_service = await build_service(tmp_path / "flow")
    flow = ContractsAnswerFlow(
        service=flow_service, producer=ContractsDraftProducer(adapter=None)
    )

    question = "Which contracts require SOC 2?"
    react = await react_service.answer(question, request_context=reader_context())
    fixed = await flow.answer(question, request_context=reader_context())

    assert react.answer.answer_kind == fixed.answer.answer_kind == "lookup"
    assert react.answer.provenance == fixed.answer.provenance
    assert {citation.node_id for citation in react.answer.citations} <= {
        citation.node_id for citation in fixed.answer.citations
    }

    # And on an evaluative question, both hand off without judgment.
    evaluative = "Should we accept the redline on acme-msa?"
    react_handoff = await react_service.answer(evaluative, request_context=reader_context())
    fixed_handoff = await flow.answer(evaluative, request_context=reader_context())
    assert (
        react_handoff.answer.answer_kind
        == fixed_handoff.answer.answer_kind
        == "interpretation_required"
    )
    assert react_handoff.answer.answer is fixed_handoff.answer.answer is None


# --------------------------------------------------------------------------
# 2. Nothing adversarial escapes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_invented_model_answer_cannot_escape(service):
    service.producer = ContractsAgentProducer(
        FakeReActAgent("ACME agreed to unlimited liability and free ponies.")
    )
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )

    assert "ponies" not in (outcome.answer.answer or "")
    # Every released sentence is backed by an archived clause.
    assert outcome.answer.answer_kind in {"lookup", "not_found"}
    for citation in outcome.answer.citations:
        assert citation.quote in {CLAUSE, INSURANCE}


@pytest.mark.asyncio
async def test_a_provider_failure_degrades_to_a_refusal_not_raw_text(service):
    service.producer = ContractsAgentProducer(FakeReActAgent(CLAUSE, fail=True))
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )

    assert outcome.answer.answer_kind == "not_found"
    assert outcome.answer.answer is None
    assert service.producer.last_reply is None


@pytest.mark.asyncio
async def test_retired_citations_cannot_come_back_through_chat(service, agent_producer):
    first = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )
    owner = reader_context(roles=("contract_owner",), confirmed=True)
    await service.retire_answer(first.answer_id, request_context=owner, reason="wrong")

    second = await service.answer(
        "Which contracts require SOC 2?", request_context=reader_context()
    )
    assert second.answer.answer_kind == "not_found"


@pytest.mark.asyncio
async def test_a_forged_context_is_denied(service, agent_producer):
    forged = reader_context(roles=("contract_owner",), tenant_id="other-tenant")
    outcome = await service.answer(
        "Which contracts require SOC 2?", request_context=forged
    )
    assert outcome.answer.answer_kind == "denied"
    assert agent_producer.calls == 0, "a denied request never reaches the model"


@pytest.mark.asyncio
async def test_an_audit_failure_fails_the_chat_turn(service, agent_producer):
    service.catalog.audit_fails = True
    with pytest.raises(ServiceUnavailable):
        await service.answer(
            "Which contracts require SOC 2?", request_context=reader_context()
        )


@pytest.mark.asyncio
async def test_streaming_emits_only_verified_text(service):
    service.producer = ContractsAgentProducer(
        FakeReActAgent("ACME agreed to free ponies forever.")
    )
    chunks = [
        chunk
        async for chunk in service.stream_answer(
            "Which contracts require SOC 2?", request_context=reader_context()
        )
    ]
    assert not any("ponies" in chunk for chunk in chunks)


# --------------------------------------------------------------------------
# 3. Wiring: one policy, no new transport
# --------------------------------------------------------------------------


def test_the_agent_mounts_the_contracts_toolkit_and_delegates_release():
    source = Path(inspect.getfile(ContractsAgent)).read_text()
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    # The agent calls the shared service; it does not re-implement policy.
    assert "answer" in called
    assert "stream_answer" in called
    for forbidden in ("record_answer", "retired_citations", "resolve"):
        assert forbidden not in called, forbidden


def test_the_agent_defines_no_second_citation_policy():
    source = Path(inspect.getfile(ContractsAgent)).read_text()
    assert "class CitationVerifier" not in source
    assert "def verify(" not in source
    assert "AnswerRecord(" not in source


def test_the_agent_introduces_no_new_transport():
    source = Path(inspect.getfile(ContractsAgent)).read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for forbidden in ("aiohttp", "fastapi", "flask", "parrot.server", "parrot.scheduler"):
        assert not any(name.startswith(forbidden) for name in imported), forbidden


def test_the_system_prompt_forbids_advice_and_unsupported_statements():
    lowered = CONTRACTS_SYSTEM_PROMPT.lower()
    assert "never give legal advice" in lowered
    assert "untrusted data" in lowered
    assert "you do not release answers" in lowered


@pytest.mark.asyncio
async def test_the_producer_reads_only_the_authorized_dossier(service, agent_producer):
    await service.answer("Which contracts require SOC 2?", request_context=reader_context())
    prompt = agent_producer.agent.prompts[0]

    assert "acme-msa" in prompt
    assert "Authorized contracts for this request" in prompt
    assert "contracts_" in prompt, "the agent is told to use the toolkit"


@pytest.mark.asyncio
async def test_a_clarification_never_reaches_the_model(service, agent_producer):
    result = await service.answer(
        "what is the weather in madrid", request_context=reader_context()
    )
    assert isinstance(result, Clarification)
    assert agent_producer.calls == 0
