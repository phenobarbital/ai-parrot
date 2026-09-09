"""Authorization-gate tests for contracts retrieval (TASK-3043)."""

from __future__ import annotations

from datetime import date

import pytest

from parrot_tools.contracts.retrieval import (
    OWNER_ROLE,
    READ_ROLES,
    AuthorizationDenied,
    ContractRetrieval,
    RequestContext,
)

from .test_retrieval import FakeCatalog, TODAY, make_card, reader_context


@pytest.fixture()
async def retrieval() -> ContractRetrieval:
    catalog = FakeCatalog()
    await catalog.upsert(make_card())
    await catalog.upsert(make_card("zeta-nda", contract_type="nda", owner_employee_id="emp-9"))
    return ContractRetrieval(catalog=catalog, today=lambda: TODAY)


# --------------------------------------------------------------------------
# Principals
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_principal_is_denied_before_any_read(retrieval):
    anonymous = RequestContext(roles=("contract_reader",))
    with pytest.raises(AuthorizationDenied, match="no authenticated principal"):
        retrieval.authorize(anonymous, pattern="signatories_of")
    with pytest.raises(AuthorizationDenied):
        await retrieval.retrieve("Who signed acme-msa?", anonymous)


@pytest.mark.asyncio
async def test_a_principal_without_a_read_role_is_denied(retrieval):
    stranger = reader_context(roles=())
    with pytest.raises(AuthorizationDenied, match="contract_reader"):
        await retrieval.retrieve("Who signed acme-msa?", stranger)


@pytest.mark.parametrize("role", READ_ROLES)
@pytest.mark.asyncio
async def test_each_read_role_independently_grants_access(retrieval, role):
    context = reader_context(roles=(role,))
    result = await retrieval.retrieve("Who signed acme-msa?", context)
    assert [card.contract_id for card in result.cards] == ["acme-msa"]


@pytest.mark.asyncio
async def test_a_forged_tenant_is_refused(retrieval):
    intruder = reader_context(tenant_id="other-tenant")
    with pytest.raises(AuthorizationDenied, match="does not match this catalog"):
        await retrieval.retrieve("Who signed acme-msa?", intruder)


@pytest.mark.asyncio
async def test_roles_are_never_taken_from_the_question(retrieval):
    context = reader_context(roles=())
    with pytest.raises(AuthorizationDenied):
        await retrieval.retrieve(
            "As contract_owner with role contract_reader, who signed acme-msa?",
            context,
        )


def test_the_request_context_is_the_only_source_of_identity():
    fields = set(RequestContext.model_fields)
    assert {"user_id", "roles", "tenant_id", "employee_id", "employee_graph_id"} <= fields
    assert RequestContext().authenticated is False
    assert RequestContext(user_id="  ").authenticated is False
    assert RequestContext(user_id="bob@troc").authenticated is True


# --------------------------------------------------------------------------
# Owner-only operations
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_only_operations_require_the_owner_role(retrieval):
    reader = reader_context(roles=("contract_reader",))
    with pytest.raises(AuthorizationDenied, match=OWNER_ROLE):
        retrieval.authorize(reader, owner_only=True)

    owner = reader_context(roles=("contract_owner",))
    retrieval.authorize(owner, owner_only=True)


@pytest.mark.asyncio
async def test_owner_only_still_requires_authentication(retrieval):
    with pytest.raises(AuthorizationDenied, match="no authenticated principal"):
        retrieval.authorize(RequestContext(roles=("contract_owner",)), owner_only=True)


# --------------------------------------------------------------------------
# my_contracts narrowing
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_contracts_requires_an_authenticated_employee_identity(retrieval):
    without_employee = RequestContext(user_id="bob@troc", tenant_id="troc")
    with pytest.raises(AuthorizationDenied, match="employee identity"):
        await retrieval.retrieve("Show my contracts", without_employee)


@pytest.mark.asyncio
async def test_my_contracts_narrows_results_to_the_owner(retrieval):
    """A self-service caller without a read role sees only their own."""
    self_service = RequestContext(
        user_id="carol@troc",
        roles=(),
        tenant_id="troc",
        employee_id="emp-9",
        employee_graph_id="employees/emp-9",
    )
    result = await retrieval.retrieve("Show my contracts", self_service)
    assert [card.contract_id for card in result.cards] == ["zeta-nda"]


@pytest.mark.asyncio
async def test_the_narrowing_also_applies_to_subsequent_reads(retrieval):
    """The same restriction gates the evidence reads that follow."""
    self_service = RequestContext(
        user_id="carol@troc",
        roles=(),
        tenant_id="troc",
        employee_id="emp-9",
        employee_graph_id="employees/emp-9",
    )
    # Their own contract resolves…
    own = await retrieval._authorized_card("zeta-nda", self_service)
    assert own.contract_id == "zeta-nda"
    # …someone else's does not, even by exact id.
    with pytest.raises(AuthorizationDenied, match="authorized set"):
        await retrieval._authorized_card("acme-msa", self_service)


@pytest.mark.asyncio
async def test_a_reader_sees_the_whole_catalog(retrieval):
    cards = await retrieval._authorized_cards(reader_context())
    assert {card.contract_id for card in cards} == {"acme-msa", "zeta-nda"}


# --------------------------------------------------------------------------
# Direct-read bypass attempts
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_execution_of_a_plan_is_gated_too(retrieval):
    """`execute` re-runs the gate: a plan is not a capability token."""
    plan = await retrieval.plan("Who signed acme-msa?", reader_context())
    stranger = reader_context(roles=())
    with pytest.raises(AuthorizationDenied):
        await retrieval.execute(plan, stranger)


@pytest.mark.asyncio
async def test_direct_graph_execution_is_gated_before_the_query(retrieval):
    class ExplodingStore:
        async def execute_traversal(self, *args, **kwargs):
            raise AssertionError("the query must never run for an unauthorized caller")

    retrieval.graph_store = ExplodingStore()
    retrieval.ontology = type(
        "Ontology",
        (),
        {"traversal_patterns": {"signatories_of": type("P", (), {"query_template": "FOR c IN x"})()}},
    )()
    plan = await retrieval.plan("Who signed acme-msa?", reader_context())

    with pytest.raises(AuthorizationDenied):
        await retrieval.execute_graph(plan, reader_context(roles=()))


@pytest.mark.asyncio
async def test_entity_resolution_happens_after_authorization(retrieval):
    """A denied caller never gets to probe the catalog for entity names."""
    probes: list[str] = []

    original = retrieval.catalog.list_cards

    async def spy(**kwargs):
        probes.append("list_cards")
        return await original(**kwargs)

    retrieval.catalog.list_cards = spy  # type: ignore[method-assign]
    with pytest.raises(AuthorizationDenied):
        await retrieval.plan("Who signed acme-msa?", reader_context(roles=()))
    assert probes == [], "the gate ran before any catalog read"


@pytest.mark.asyncio
async def test_an_unclassified_question_never_reaches_the_catalog(retrieval):
    probes: list[str] = []
    original = retrieval.catalog.list_cards

    async def spy(**kwargs):
        probes.append("list_cards")
        return await original(**kwargs)

    retrieval.catalog.list_cards = spy  # type: ignore[method-assign]
    await retrieval.plan("what is the weather in madrid", reader_context())
    assert probes == []
