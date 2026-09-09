"""Contracts toolkit tests (TASK-3046)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import pytest

from parrot.knowledge.contracts.evidence import EvidenceArchive
from parrot.knowledge.contracts.models import (
    AnswerRecord,
    AuthorizationOutcome,
    Citation,
)
from parrot_tools.contracts.retrieval import (
    AuthorizationDenied,
    ContractRetrieval,
    RequestContext,
)
from parrot_tools.contracts.service import (
    ConfirmationRequired,
    ContractsAnswerService,
    ServiceUnavailable,
)
from parrot_tools.contracts.toolkit import MAX_SECTION_CHARS, ContractsToolkit
from parrot_tools.contracts.verifier import CitationVerifier

from .test_retrieval import FROZEN_NOW, TODAY, FakeCatalog, make_card, reader_context

CLAUSE = "Vendor shall maintain SOC 2 Type II certification."


class FakeLibrary:
    """Serves published node bodies and records verification calls."""

    def __init__(self, bodies: dict[str, str]) -> None:
        self.bodies = bodies
        self.verify_calls: list[tuple[str, Any, str]] = []

    def published_loader(self, contract_id: str):
        def _loader(node_id: str) -> Optional[str]:
            return self.bodies.get(node_id)

        return _loader

    async def verify_card(self, contract_id, fields, *, user, expected_revision=None):
        self.verify_calls.append((contract_id, fields, user))
        return type(
            "Result",
            (),
            {
                "verified": ["title"],
                "corrected": list(fields or {}),
                "blockers": [],
                "card_verified": True,
            },
        )()


@pytest.fixture()
async def toolkit(tmp_path) -> ContractsToolkit:
    catalog = FakeCatalog()
    card = make_card()
    await catalog.upsert(card)
    await catalog.upsert(make_card("acme-sow-1", contract_type="sow", parent_contract_id="acme-msa"))

    archive = EvidenceArchive(tmp_path / "evidence", tenant_id="troc")
    await archive.archive(
        archive.reference("acme-msa", version_n=1, revision=1, source_sha256="sha-acme-msa"),
        {"0005": f"4. Compliance. {CLAUSE}"},
        pages={"0005": 12},
    )
    retrieval = ContractRetrieval(catalog=catalog, today=lambda: TODAY)
    library = FakeLibrary({"0005": f"4. Compliance. {CLAUSE}", "0009": "x" * 20_000})
    service = ContractsAnswerService(
        retrieval=retrieval,
        verifier=CitationVerifier(catalog=catalog, evidence=archive),
        library=library,
    )
    return ContractsToolkit(service=service, request_context=reader_context(), library=library)


def owner_toolkit(toolkit: ContractsToolkit, **overrides) -> ContractsToolkit:
    """A toolkit bound to an owner context."""
    context = reader_context(roles=("contract_owner",), confirmed=True, **overrides)
    return ContractsToolkit(service=toolkit.service, request_context=context, library=toolkit.library)


# --------------------------------------------------------------------------
# 1. Naming and confirmation metadata
# --------------------------------------------------------------------------


def test_tools_are_namespaced_with_the_contracts_prefix(toolkit):
    names = {tool.name for tool in toolkit.get_tools()}
    assert names == {
        "contracts_catalog_search",
        "contracts_get_card",
        "contracts_get_toc",
        "contracts_read_section",
        "contracts_obligations",
        "contracts_expiring",
        "contracts_verification_queue",
        "contracts_related_contracts",
        "contracts_verify_card",
        "contracts_retire_answer",
    }
    assert toolkit.name == "contracts"
    assert toolkit.tool_prefix == "contracts"


def test_write_tools_carry_requires_confirmation_metadata(toolkit):
    by_name = {tool.name: tool for tool in toolkit.get_tools()}
    for name in ("contracts_verify_card", "contracts_retire_answer"):
        assert (by_name[name].routing_meta or {}).get("requires_confirmation") is True
    for name in ("contracts_get_card", "contracts_catalog_search"):
        assert not (by_name[name].routing_meta or {}).get("requires_confirmation")
    assert toolkit.confirming_tools == frozenset({"verify_card", "retire_answer"})


def test_every_tool_is_documented(toolkit):
    for tool in toolkit.get_tools():
        assert tool.description and len(tool.description) > 20, tool.name


# --------------------------------------------------------------------------
# 2. Reads go through the gate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_tools_return_typed_bounded_data(toolkit):
    search = await toolkit.catalog_search("security")
    assert search["results"][0]["contract_id"] in {"acme-msa", "acme-sow-1"}
    assert "rank" in search["results"][0]

    card = await toolkit.get_card("acme-msa")
    assert card["contract_id"] == "acme-msa"
    assert "term" in card and "parties" in card
    assert "field_provenance" not in card, "provenance payloads stay out of tool output"

    obligations = await toolkit.obligations("acme-msa")
    assert len(obligations["obligations"]) == 2

    compliance = await toolkit.obligations("acme-msa", kind="compliance")
    assert [row["kind"] for row in compliance["obligations"]] == ["compliance"]

    expiring = await toolkit.expiring(days=200)
    assert expiring["contracts"]

    queue = await toolkit.verification_queue()
    assert "queue" in queue

    related = await toolkit.related_contracts("acme-msa")
    assert [row["contract_id"] for row in related["family"]] == ["acme-sow-1"]


@pytest.mark.asyncio
async def test_search_top_k_is_bounded(toolkit):
    result = await toolkit.catalog_search("security", top_k=10_000)
    assert len(result["results"]) <= 25


@pytest.mark.asyncio
async def test_section_bodies_are_bounded(toolkit):
    result = await toolkit.read_section("acme-msa", "0009")
    assert len(result["body"]) == MAX_SECTION_CHARS


@pytest.mark.asyncio
async def test_reads_are_denied_without_a_read_role(toolkit):
    stranger = ContractsToolkit(
        service=toolkit.service,
        request_context=reader_context(roles=()),
        library=toolkit.library,
    )
    for call in (
        stranger.catalog_search("security"),
        stranger.get_card("acme-msa"),
        stranger.get_toc("acme-msa"),
        stranger.read_section("acme-msa", "0005"),
        stranger.obligations("acme-msa"),
        stranger.expiring(),
        stranger.verification_queue(),
        stranger.related_contracts("acme-msa"),
    ):
        with pytest.raises(AuthorizationDenied):
            await call


@pytest.mark.asyncio
async def test_a_direct_call_cannot_bypass_my_contracts_narrowing(toolkit):
    """Someone else's contract is refused even when named explicitly."""
    self_service = ContractsToolkit(
        service=toolkit.service,
        request_context=RequestContext(
            user_id="carol@troc",
            roles=(),
            tenant_id="troc",
            employee_id="emp-9",
            employee_graph_id="employees/emp-9",
        ),
        library=toolkit.library,
    )
    with pytest.raises(AuthorizationDenied):
        await self_service.get_card("acme-msa")


@pytest.mark.asyncio
async def test_the_actor_is_never_taken_from_a_tool_argument(toolkit):
    import inspect

    for method in (
        toolkit.catalog_search,
        toolkit.get_card,
        toolkit.read_section,
        toolkit.verify_card,
        toolkit.retire_answer,
    ):
        parameters = set(inspect.signature(method).parameters)
        assert not parameters & {"user", "actor", "roles", "tenant_id", "request_context"}


# --------------------------------------------------------------------------
# 3. Retired evidence and confirming writes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_retired_section_becomes_unavailable(toolkit):
    available = await toolkit.read_section("acme-msa", "0005")
    assert CLAUSE in available["body"]

    await toolkit.catalog.record_answer(
        AnswerRecord(
            answer_id="ans-1",
            asked_at=FROZEN_NOW,
            user="bob@troc",
            question="q",
            answer_kind="lookup",
            answer="a",
            citations=[
                Citation(
                    contract_id="acme-msa",
                    node_id="0005",
                    quote=CLAUSE,
                    version_n=1,
                    source_sha256="sha-acme-msa",
                )
            ],
            authorization=AuthorizationOutcome(allowed=True),
        )
    )
    await toolkit.catalog.retire_answer("ans-1", user="bob@troc", reason="wrong clause")

    retired = await toolkit.read_section("acme-msa", "0005")
    assert retired["body"] is None
    assert "retired" in retired["reason"]


@pytest.mark.asyncio
async def test_write_tools_require_the_owner_role(toolkit):
    with pytest.raises(AuthorizationDenied):
        await toolkit.verify_card("acme-msa", {"title": None})
    with pytest.raises(AuthorizationDenied):
        await toolkit.retire_answer("ans-1", reason="x")


@pytest.mark.asyncio
async def test_write_tools_require_a_trusted_confirmation(toolkit):
    unconfirmed = ContractsToolkit(
        service=toolkit.service,
        request_context=reader_context(roles=("contract_owner",), confirmed=False),
        library=toolkit.library,
    )
    with pytest.raises(ConfirmationRequired):
        await unconfirmed.verify_card("acme-msa", {"title": None})
    with pytest.raises(ConfirmationRequired):
        await unconfirmed.retire_answer("ans-1", reason="x")


@pytest.mark.asyncio
async def test_metadata_alone_does_not_authorise_a_write(toolkit):
    """The tool is marked confirming, but the service enforces it."""
    by_name = {tool.name: tool for tool in toolkit.get_tools()}
    assert (by_name["contracts_verify_card"].routing_meta or {})["requires_confirmation"]

    # A transport that ignored the metadata still cannot write.
    with pytest.raises(AuthorizationDenied):
        await toolkit.verify_card("acme-msa", {"title": "hijacked"})


@pytest.mark.asyncio
async def test_an_owner_can_verify_correct_and_override_ownership(toolkit):
    owner = owner_toolkit(toolkit)
    result = await owner.verify_card("acme-msa", {"title": "ACME MSA"}, owner_employee_id="emp-2")
    assert result["card_verified"] is True
    contract_id, fields, user = toolkit.library.verify_calls[-1]
    assert contract_id == "acme-msa"
    assert fields == {"title": "ACME MSA", "owner_employee_id": "emp-2"}
    assert user == "bob@troc", "the actor comes from the trusted context"


@pytest.mark.asyncio
async def test_an_owner_can_merge_parties(toolkit):
    merged: list[tuple[str, str, str]] = []

    async def merge_parties(keep_party_id, merge_party_id, *, user):
        merged.append((keep_party_id, merge_party_id, user))
        return type("Result", (), {"model_dump": lambda self, mode=None: {"ok": True}})()

    toolkit.catalog.merge_parties = merge_parties  # type: ignore[method-assign]
    owner = owner_toolkit(toolkit)
    result = await owner.verify_card("acme-msa", merge_party_id="party-old", keep_party_id="party-acme")

    assert result["merged"] == {"ok": True}
    assert merged == [("party-acme", "party-old", "bob@troc")]


@pytest.mark.asyncio
async def test_an_owner_can_retire_an_answer(toolkit):
    await toolkit.catalog.record_answer(
        AnswerRecord(
            answer_id="ans-2",
            asked_at=FROZEN_NOW,
            user="bob@troc",
            question="q",
            answer_kind="lookup",
            answer="a",
            citations=[
                Citation(
                    contract_id="acme-msa",
                    node_id="0005",
                    quote=CLAUSE,
                    version_n=1,
                    source_sha256="sha-acme-msa",
                )
            ],
            authorization=AuthorizationOutcome(allowed=True),
        )
    )
    owner = owner_toolkit(toolkit)
    result = await owner.retire_answer("ans-2", reason="superseded clause")

    assert result["answer_id"] == "ans-2"
    assert result["retired_by"] == "bob@troc"
    assert result["reason"] == "superseded clause"
    assert "acme-msa:0005" in result["suppressed"]
