"""Contracts graph publication tests (TASK-3038)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest

from parrot.knowledge.contracts.datasource import ContractCardDataSource
from parrot.knowledge.contracts.graph_loader import (
    FEATURE_EDGE_COLLECTIONS,
    ContractGraphLoader,
    ContractsDomainNotLoaded,
    EdgeSpec,
)
from parrot.knowledge.contracts.models import (
    ContractCard,
    Obligation,
    Party,
    Signatory,
    TermSpec,
)

from .test_catalog_contract import InMemoryContractCatalog

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


class UpsertResult:
    """Mimics ``OntologyGraphStore.upsert_nodes``'s return value."""

    def __init__(self, inserted: int = 0, updated: int = 0) -> None:
        self.inserted = inserted
        self.updated = updated
        self.unchanged = 0


class FakeGraphStore:
    """In-memory ``OntologyGraphStore`` with the semantics that matter.

    Faithfully reproduces the two behaviours the loader must work around:
    ``create_edges`` inserts by endpoints and **never** updates properties,
    and ``get_all_nodes`` hides soft-deleted vertices.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges: dict[str, list[dict[str, Any]]] = {}
        self.fail_on: set[str] = set()
        self.swallow_writes: set[str] = set()

    async def upsert_nodes(self, ctx, collection, nodes, key_field):
        if collection in self.fail_on:
            raise RuntimeError(f"{collection} unavailable")
        bucket = self.nodes.setdefault(collection, {})
        inserted = updated = 0
        if collection in self.swallow_writes:
            return UpsertResult(0, 0)
        for node in nodes:
            key = node[key_field]
            if key in bucket:
                updated += 1
            else:
                inserted += 1
            bucket[key] = {**node, "_key": key, "_active": True}
        return UpsertResult(inserted, updated)

    async def get_all_nodes(self, ctx, collection):
        if collection in self.fail_on:
            raise RuntimeError(f"{collection} unavailable")
        return [node for node in self.nodes.get(collection, {}).values() if node.get("_active") is not False]

    async def soft_delete_nodes(self, ctx, collection, keys):
        bucket = self.nodes.setdefault(collection, {})
        for key in keys:
            if key in bucket:
                bucket[key]["_active"] = False

    async def create_edges(self, ctx, edge_collection, edges):
        bucket = self.edges.setdefault(edge_collection, [])
        created = 0
        for edge in edges:
            # Upsert on (_from, _to) — properties of an existing edge are
            # deliberately NOT updated, exactly like the real store.
            if any(item["_from"] == edge["_from"] and item["_to"] == edge["_to"] for item in bucket):
                continue
            bucket.append(dict(edge))
            created += 1
        return created

    async def get_all_edges(self, ctx, collection):
        if collection in self.fail_on:
            raise RuntimeError(f"{collection} unavailable")
        return list(self.edges.get(collection, []))

    async def edges_incident(self, ctx, collection, node_id):
        return [
            edge for edge in self.edges.get(collection, []) if node_id in (edge.get("source_id"), edge.get("target_id"))
        ]

    async def remove_edge_by_triple(self, ctx, collection, source_id, target_id, kind):
        bucket = self.edges.get(collection, [])
        before = len(bucket)
        self.edges[collection] = [
            edge
            for edge in bucket
            if not (
                (edge.get("source_id") or edge.get("_from")) == source_id
                and (edge.get("target_id") or edge.get("_to")) == target_id
            )
        ]
        return len(self.edges[collection]) < before

    # -- helpers for assertions -------------------------------------------

    def edge_pairs(self, collection: str) -> set[tuple[str, str]]:
        return {(edge["source_id"], edge["target_id"]) for edge in self.edges.get(collection, [])}

    def active_keys(self, collection: str) -> set[str]:
        return {key for key, node in self.nodes.get(collection, {}).items() if node.get("_active") is not False}


class FakeTenantManager:
    """Resolves a context whose ontology carries the contracts entities."""

    def __init__(self, entities: tuple[str, ...] = ("Contract", "Obligation", "Party")) -> None:
        self.entities = entities
        self.calls: list[tuple[str, str | None]] = []

    def resolve(self, tenant_id: str, domain: str | None = None):
        self.calls.append((tenant_id, domain))
        ontology = type("Ontology", (), {"entities": {name: object() for name in self.entities}})()
        return type(
            "Ctx",
            (),
            {
                "tenant_id": tenant_id,
                "arango_db": f"{tenant_id}_ontology",
                "pgvector_schema": tenant_id,
                "ontology": ontology,
            },
        )()


def card(contract_id: str = "acme-msa", **overrides) -> ContractCard:
    """A synthetic card with every edge-bearing field populated."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"sha-{contract_id}",
        "source_format": "pdf",
        "owner_employee_id": "emp-1",
        "department": "legal",
        "parties": [
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id="party-acme", name="ACME Inc.", role="customer"),
        ],
        "signatories": [
            Signatory(
                person_id=f"{contract_id}-person-jane",
                name="Jane Doe",
                party_id="party-acme",
                signed_on=date(2025, 12, 20),
                employee_id=None,
            )
        ],
        "term": TermSpec(effective_date=date(2026, 1, 1), expiration_date=date(2026, 12, 31)),
        "obligations": [
            Obligation(
                obligation_id=f"{contract_id}-ob-001",
                contract_id=contract_id,
                kind="compliance",
                text="Vendor shall maintain SOC 2.",
                node_id="0005",
                standard_id="soc2",
            )
        ],
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


@pytest.fixture()
async def loader():
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card())
    store = FakeGraphStore()
    return ContractGraphLoader(
        catalog=catalog,
        graph_store=store,
        tenant_manager=FakeTenantManager(),
        datasource=ContractCardDataSource("contractcard", {"catalog": catalog}),
    )


# --------------------------------------------------------------------------
# Startup and tenancy
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_startup_resolves_the_contracts_domain_explicitly(loader):
    await loader.startup_check()
    assert loader._tenant_manager.calls == [("troc", "contracts")]


@pytest.mark.asyncio
async def test_startup_fails_when_the_contracts_domain_is_not_loaded():
    catalog = InMemoryContractCatalog()
    loader = ContractGraphLoader(
        catalog=catalog,
        graph_store=FakeGraphStore(),
        tenant_manager=FakeTenantManager(entities=("Employee", "Department")),
    )
    with pytest.raises(ContractsDomainNotLoaded, match="dedicated TenantOntologyManager"):
        await loader.startup_check()

    report = await loader.publish_all()
    assert report.published is False
    assert any("Contract" in error for error in report.errors)


# --------------------------------------------------------------------------
# 1. First publish and single-card safety
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_publish_creates_every_scalar_and_property_edge(loader):
    report = await loader.publish_all()
    store = loader.graph_store

    assert report.published is True
    assert report.complete is True
    assert report.contracts == 1

    assert store.edge_pairs("party_to") == {
        ("contract/acme-msa", "party/party-us"),
        ("contract/acme-msa", "party/party-acme"),
    }
    assert store.edge_pairs("signed_by") == {("contract/acme-msa", "person/acme-msa-person-jane")}
    assert store.edge_pairs("represents") == {("person/acme-msa-person-jane", "party/party-acme")}
    assert store.edge_pairs("imposed_by") == {("obligation/acme-msa-ob-001", "contract/acme-msa")}
    assert store.edge_pairs("requires") == {("obligation/acme-msa-ob-001", "compliance_standard/soc2")}
    assert store.edge_pairs("owned_by") == {("contract/acme-msa", "employees/emp-1")}
    assert store.edge_pairs("managed_by") == {("contract/acme-msa", "departments/legal")}

    role_edge = store.edges["party_to"][0]
    assert role_edge["kind"] == "party_to"
    assert role_edge["source_id"] and role_edge["target_id"]
    assert {edge["_to"] for edge in store.edges["party_to"]}


@pytest.mark.asyncio
async def test_standards_are_seeded_before_requires_is_linked(loader):
    await loader.publish_all()
    store = loader.graph_store
    assert "soc2" in store.active_keys("compliance_standard")
    assert len(store.active_keys("compliance_standard")) == 8
    assert store.edge_pairs("requires")


@pytest.mark.asyncio
async def test_parent_links_resolve_on_the_first_publish(loader):
    await loader.catalog.upsert(
        card(
            "acme-sow-1",
            contract_type="sow",
            parent_contract_id="acme-msa",
            obligations=[],
            signatories=[],
        )
    )
    await loader.catalog.upsert(
        card(
            "acme-amd-1",
            contract_type="amendment",
            parent_contract_id="acme-msa",
            obligations=[],
            signatories=[],
        )
    )
    await loader.publish_all()
    store = loader.graph_store

    assert store.edge_pairs("governed_by") == {("contract/acme-sow-1", "contract/acme-msa")}
    assert store.edge_pairs("amends") == {("contract/acme-amd-1", "contract/acme-msa")}
    amends = store.edges["amends"][0]
    assert amends["effective_date"] == "2026-01-01"


@pytest.mark.asyncio
async def test_publishing_one_card_never_deactivates_the_others(loader):
    await loader.catalog.upsert(card("zeta-nda", contract_type="nda", obligations=[], signatories=[]))
    await loader.publish_all()
    store = loader.graph_store
    assert store.active_keys("contract") == {"acme-msa", "zeta-nda"}

    report = await loader.publish(await loader.catalog.get("acme-msa"))

    assert report.published is True
    assert store.active_keys("contract") == {"acme-msa", "zeta-nda"}
    assert report.deactivated == {}


@pytest.mark.asyncio
async def test_a_removed_contract_is_deactivated_by_a_full_publish(loader):
    await loader.catalog.upsert(card("zeta-nda", contract_type="nda", obligations=[], signatories=[]))
    await loader.publish_all()

    await loader.catalog.remove("zeta-nda")
    report = await loader.publish_all()

    assert report.deactivated["contract"] == ["zeta-nda"]
    assert loader.graph_store.active_keys("contract") == {"acme-msa"}


# --------------------------------------------------------------------------
# 2. Edge reconciliation and retraction
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_change_removes_the_old_edge_before_creating_the_new_one(loader):
    await loader.publish_all()
    store = loader.graph_store
    assert store.edge_pairs("owned_by") == {("contract/acme-msa", "employees/emp-1")}

    stored = await loader.catalog.get("acme-msa")
    await loader.catalog.upsert(stored.model_copy(update={"owner_employee_id": "emp-2"}), expected_revision=1)
    report = await loader.publish_all()

    assert store.edge_pairs("owned_by") == {("contract/acme-msa", "employees/emp-2")}
    assert report.edges_removed.get("owned_by") == 1
    assert report.published is True


@pytest.mark.asyncio
async def test_changed_edge_properties_are_rewritten_not_left_stale(loader):
    await loader.publish_all()
    store = loader.graph_store
    assert store.edges["party_to"][0]["role"] in {"us", "customer"}

    stored = await loader.catalog.get("acme-msa")
    await loader.catalog.upsert(
        stored.model_copy(
            update={
                "parties": [
                    Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
                    Party(party_id="party-acme", name="ACME Inc.", role="vendor"),
                ]
            }
        ),
        expected_revision=1,
    )
    await loader.publish_all()

    roles = {edge["target_id"]: edge["role"] for edge in store.edges["party_to"]}
    assert roles["party/party-acme"] == "vendor", "create_edges never updates properties"


@pytest.mark.asyncio
async def test_bare_discovery_edges_are_normalized_on_reconciliation(loader):
    store = loader.graph_store
    # A discovery pass writes edges with only _from/_to.
    store.edges["owned_by"] = [{"_from": "contract/acme-msa", "_to": "employees/emp-1"}]
    await loader.publish_all()

    edge = store.edges["owned_by"][0]
    assert edge["source_id"] == "contract/acme-msa"
    assert edge["target_id"] == "employees/emp-1"
    assert edge["kind"] == "owned_by"


@pytest.mark.asyncio
async def test_cleanup_touches_only_feature_owned_collections(loader):
    store = loader.graph_store
    store.edges["reports_to"] = [
        {
            "_from": "employees/emp-1",
            "_to": "employees/emp-boss",
            "source_id": "employees/emp-1",
            "target_id": "employees/emp-boss",
            "kind": "reports_to",
        }
    ]
    await loader.publish_all()
    assert len(store.edges["reports_to"]) == 1
    assert set(store.edges) - {"reports_to"} <= set(FEATURE_EDGE_COLLECTIONS)


@pytest.mark.asyncio
async def test_retraction_preserves_shared_nodes_and_history(loader):
    await loader.catalog.upsert(
        card(
            "zeta-sow",
            contract_type="sow",
            parties=[Party(party_id="party-acme", name="ACME Inc.", role="customer")],
            signatories=[],
            obligations=[],
        )
    )
    await loader.publish_all()
    store = loader.graph_store

    await loader.catalog.remove("acme-msa")
    report = await loader.retract("acme-msa")

    assert report.published is True
    assert report.retracted == ["acme-msa"]
    assert store.active_keys("contract") == {"zeta-sow"}
    assert store.active_keys("obligation") == set()
    # Shared identity survives: another contract still references the party.
    assert "party-acme" in store.active_keys("party")
    assert "acme-msa-person-jane" in store.nodes["person"]
    # Only the retracted contract's edges are gone.
    assert store.edge_pairs("party_to") == {("contract/zeta-sow", "party/party-acme")}
    assert store.edge_pairs("requires") == set()
    # Catalog history and audit are untouched.
    assert await loader.catalog.versions("acme-msa")


@pytest.mark.asyncio
async def test_retraction_reports_a_domain_failure_instead_of_claiming_success():
    catalog = InMemoryContractCatalog()
    loader = ContractGraphLoader(
        catalog=catalog,
        graph_store=FakeGraphStore(),
        tenant_manager=FakeTenantManager(entities=("Employee",)),
    )
    report = await loader.retract("acme-msa")
    assert report.published is False
    assert report.errors


# --------------------------------------------------------------------------
# 3. Failures never look like success
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_failure_is_reported_and_nothing_is_deactivated(loader):
    await loader.publish_all()
    store = loader.graph_store

    async def boom(**kwargs):
        raise RuntimeError("catalog unavailable")

    loader.catalog.list_cards = boom  # type: ignore[method-assign]
    report = await loader.publish_all()

    assert report.published is False
    assert any("extraction failed" in error for error in report.errors)
    assert report.deactivated == {}
    assert store.active_keys("contract") == {"acme-msa"}


@pytest.mark.asyncio
async def test_a_partial_write_keeps_the_revision_unpublished(loader):
    loader.graph_store.fail_on.add("obligation")
    report = await loader.publish_all()

    assert report.published is False
    assert any("obligation" in error for error in report.errors)


@pytest.mark.asyncio
async def test_a_false_success_is_caught_by_the_read_back(loader):
    # The store accepts the write and reports no error, but stores nothing.
    loader.graph_store.swallow_writes.add("contract")
    report = await loader.publish_all()

    assert report.errors == []
    assert report.missing_nodes == ["contract/acme-msa"]
    assert report.published is False, "an empty errors list is not evidence"


@pytest.mark.asyncio
async def test_a_read_back_failure_keeps_the_revision_unpublished(loader):
    await loader.publish_all()

    class Failing(FakeGraphStore):
        async def get_all_edges(self, ctx, collection):
            if collection == "requires":
                raise RuntimeError("read-back unavailable")
            return await super().get_all_edges(ctx, collection)

    failing = Failing()
    failing.nodes = loader.graph_store.nodes
    failing.edges = loader.graph_store.edges
    loader.graph_store = failing

    report = await loader.publish_all()
    assert report.published is False
    assert any("requires" in error for error in report.errors)


@pytest.mark.asyncio
async def test_an_empty_catalog_publishes_nothing_and_deactivates_everything(loader):
    await loader.publish_all()
    await loader.catalog.remove("acme-msa")
    report = await loader.publish_all()

    assert report.contracts == 0
    assert report.deactivated["contract"] == ["acme-msa"]
    assert report.published is True, "an honestly empty catalog is a valid state"


# --------------------------------------------------------------------------
# Pure edge derivation
# --------------------------------------------------------------------------


def test_edges_are_derived_deterministically_and_carry_the_generic_triple():
    snapshot = {
        "Contract": [
            {
                "contract_id": "acme-msa",
                "contract_type": "msa",
                "active": True,
                "owner_employee_id": "emp-1",
                "department": "legal",
                "_party_roles": [("party-acme", "customer")],
                "_signatories": [("p1", "2025-12-20", "party-acme")],
            }
        ],
        "Party": [{"party_id": "party-acme"}],
        "Person": [{"person_id": "p1", "party_id": "party-acme", "employee_id": "emp-9"}],
        "Obligation": [
            {
                "obligation_id": "ob-1",
                "contract_id": "acme-msa",
                "standard_id": "soc2",
                "active": True,
            }
        ],
        "ComplianceStandard": [{"standard_id": "soc2"}],
    }
    edges = ContractGraphLoader.desired_edges(snapshot)
    assert edges == ContractGraphLoader.desired_edges(snapshot)
    kinds = [edge.collection for edge in edges]
    assert kinds == sorted(kinds)
    assert {edge.collection for edge in edges} == {
        "imposed_by",
        "is_employee",
        "managed_by",
        "owned_by",
        "party_to",
        "represents",
        "requires",
        "signed_by",
    }
    document = edges[0].document()
    assert set(document) >= {"_from", "_to", "source_id", "target_id", "kind"}


def test_edges_to_unknown_targets_are_not_written():
    snapshot = {
        "Contract": [
            {
                "contract_id": "acme-sow",
                "contract_type": "sow",
                "active": True,
                "parent_contract_id": "missing-msa",
                "_party_roles": [("ghost-party", "customer")],
                "_signatories": [],
            }
        ],
        "Party": [],
        "Person": [],
        "Obligation": [
            {
                "obligation_id": "ob-1",
                "contract_id": "acme-sow",
                "standard_id": "unknown_standard",
                "active": True,
            }
        ],
        "ComplianceStandard": [],
    }
    edges = ContractGraphLoader.desired_edges(snapshot)
    assert {edge.collection for edge in edges} == {"imposed_by"}


def test_inactive_records_produce_no_edges():
    snapshot = {
        "Contract": [
            {
                "contract_id": "acme-msa",
                "contract_type": "msa",
                "active": False,
                "owner_employee_id": "emp-1",
                "_party_roles": [("party-acme", "customer")],
                "_signatories": [],
            }
        ],
        "Party": [{"party_id": "party-acme"}],
        "Person": [],
        "Obligation": [{"obligation_id": "ob-1", "contract_id": "acme-msa", "active": False}],
        "ComplianceStandard": [],
    }
    assert ContractGraphLoader.desired_edges(snapshot) == []


def test_edge_spec_ids_and_triple():
    edge = EdgeSpec(
        collection="owned_by",
        source_collection="contract",
        source_key="acme-msa",
        target_collection="employees",
        target_key="emp-1",
    )
    assert edge.source_id == "contract/acme-msa"
    assert edge.target_id == "employees/emp-1"
    assert edge.triple == ("owned_by", "contract/acme-msa", "employees/emp-1", "owned_by")
