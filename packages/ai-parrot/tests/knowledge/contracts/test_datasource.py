"""Catalog-backed ontology datasource tests (TASK-3037)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from parrot.knowledge.contracts.datasource import (
    ENTITY_FIELDS,
    SOURCE_NAME,
    ContractCardDataSource,
    UnknownFieldRequest,
)
from parrot.knowledge.contracts.models import (
    ContractCard,
    ContractVersion,
    Obligation,
    Party,
    Signatory,
    TermSpec,
)
from parrot.knowledge.contracts.standards import STANDARD_IDS

from .test_catalog_contract import InMemoryContractCatalog

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def card(contract_id: str = "acme-msa", **overrides) -> ContractCard:
    """A synthetic card with parties, signatories and obligations."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "contract_type": "msa",
        "status": "active",
        "summary": "Security obligations for ACME.",
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
                title="CFO",
                signed_on=date(2025, 12, 20),
            )
        ],
        "term": TermSpec(
            effective_date=date(2026, 1, 1),
            expiration_date=date(2026, 12, 31),
            notice_days=60,
            notice_deadline=date(2026, 11, 1),
            auto_renew=True,
            next_renewal_date=date(2026, 12, 31),
        ),
        "obligations": [
            Obligation(
                obligation_id=f"{contract_id}-ob-001",
                contract_id=contract_id,
                kind="compliance",
                obligor="counterparty",
                text="Vendor shall maintain SOC 2.",
                node_id="0005",
                page=12,
                standard_id="soc2",
                due_date=date(2026, 10, 1),
            )
        ],
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


@pytest.fixture()
async def source() -> ContractCardDataSource:
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card())
    await catalog.add_party_alias("acme incorporated", "party-acme", user="bob@troc")
    return ContractCardDataSource(SOURCE_NAME, {"catalog": catalog})


# --------------------------------------------------------------------------
# Registration and configuration
# --------------------------------------------------------------------------


def test_the_source_is_registered_as_contractcard():
    from parrot_loaders.extractors.factory import DataSourceFactory

    catalog = InMemoryContractCatalog()
    built = DataSourceFactory().get(SOURCE_NAME, {"catalog": catalog})
    assert isinstance(built, ContractCardDataSource)
    assert built.catalog is catalog


def test_a_tenant_bound_catalog_is_mandatory():
    with pytest.raises(ValueError, match="tenant-bound ContractCatalogStore"):
        ContractCardDataSource(SOURCE_NAME, {})
    with pytest.raises(ValueError):
        ContractCardDataSource(SOURCE_NAME, {"catalog": "troc"})


# --------------------------------------------------------------------------
# 1. Overlapping field-set routing
# --------------------------------------------------------------------------


@pytest.mark.parametrize("entity", sorted(ENTITY_FIELDS))
def test_each_entity_field_set_routes_to_itself(entity):
    assert ContractCardDataSource.infer_entity(sorted(ENTITY_FIELDS[entity])) == entity


def test_routing_order_resolves_the_documented_overlaps():
    # Person and Party overlap on party_id/name; Obligation overlaps
    # Contract on contract_id. The marker order settles both.
    assert ContractCardDataSource.infer_entity(["party_id", "name"]) == "Party"
    assert ContractCardDataSource.infer_entity(["person_id", "party_id", "name"]) == "Person"
    assert ContractCardDataSource.infer_entity(["obligation_id", "contract_id", "kind"]) == "Obligation"
    assert ContractCardDataSource.infer_entity(["contract_id", "title"]) == "Contract"
    assert ContractCardDataSource.infer_entity(None) == "Contract"


def test_ambiguous_and_unknown_field_requests_are_rejected():
    with pytest.raises(UnknownFieldRequest, match="ambiguous"):
        ContractCardDataSource.infer_entity(["party_id", "person_id_typo", "name"])
    with pytest.raises(UnknownFieldRequest, match="ambiguous"):
        ContractCardDataSource.infer_entity(["obligation_id", "person_id"])
    with pytest.raises(UnknownFieldRequest, match="no contracts entity"):
        ContractCardDataSource.infer_entity(["employee_id", "job_title"])
    with pytest.raises(UnknownFieldRequest):
        ContractCardDataSource.infer_entity(["contract_id", "salary"])


@pytest.mark.asyncio
async def test_extract_rejects_a_malformed_request_instead_of_returning_empty(source):
    with pytest.raises(UnknownFieldRequest):
        await source.extract(fields=["nonexistent_field"])


# --------------------------------------------------------------------------
# 2. Projections
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contract_projection_uses_iso_dates_and_plain_versions(source):
    await source.catalog.upsert(
        await source.catalog.get("acme-msa"),
        expected_revision=1,
        version=ContractVersion(
            n=1,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 7, 1),
            source_sha256="sha-acme-msa",
            recorded_at=FROZEN_NOW,
        ),
    )
    result = await source.extract(fields=sorted(ENTITY_FIELDS["Contract"]))
    record = result.records[0].data

    assert record["effective_date"] == "2026-01-01"
    assert record["expiration_date"] == "2026-12-31"
    assert record["notice_deadline"] == "2026-11-01"
    assert record["counterparty_names"] == ["ACME Inc."]
    assert record["card_revision"] == 2
    assert record["active"] is True
    assert isinstance(record["versions"], list)
    assert len(record["versions"]) == 2
    assert record["versions"][0]["valid_from"] is None, "unknown dates stay unresolved"
    version = record["versions"][-1]
    assert isinstance(version, dict)
    assert version["valid_from"] == "2026-01-01"
    assert version["valid_to"] == "2026-07-01"
    assert version["revision"] == 2
    assert "card_snapshot" not in version, "snapshots never reach the graph payload"


@pytest.mark.asyncio
async def test_party_projection_unions_catalog_wide_aliases(source):
    await source.catalog.upsert(
        card(
            "zeta-sow",
            contract_type="sow",
            parties=[Party(party_id="party-acme", name="ACME, Incorporated", role="customer")],
            signatories=[],
            obligations=[],
        )
    )
    await source.catalog.add_party_alias("acme corp", "party-acme", user="bob@troc")

    records = await source.records_for("Party")
    acme = next(record for record in records if record["party_id"] == "party-acme")

    assert acme["aliases"] == ["ACME, Incorporated", "acme corp", "acme incorporated"]
    assert acme["kind"] == "customer"
    assert acme["is_us"] is False
    assert [record["party_id"] for record in records] == ["party-acme", "party-us"]


@pytest.mark.asyncio
async def test_person_and_obligation_projections(source):
    people = await source.records_for("Person")
    assert people == [
        {
            "person_id": "acme-msa-person-jane",
            "name": "Jane Doe",
            "title": "CFO",
            "party_id": "party-acme",
            "employee_id": None,
        }
    ]

    obligations = await source.records_for("Obligation")
    assert obligations[0]["obligation_id"] == "acme-msa-ob-001"
    assert obligations[0]["standard_id"] == "soc2"
    assert obligations[0]["due_date"] == "2026-10-01"
    assert obligations[0]["active"] is True


@pytest.mark.asyncio
async def test_standard_seeds_are_static_and_deterministic(source):
    records = await source.records_for("ComplianceStandard")
    assert [record["standard_id"] for record in records] == list(STANDARD_IDS)
    assert len(records) == 8
    assert records == await source.records_for("ComplianceStandard")
    assert "soc 2" in records[0]["aliases"]

    # Seeds do not depend on any card being present.
    empty = ContractCardDataSource(SOURCE_NAME, {"catalog": InMemoryContractCatalog()})
    assert len(await empty.records_for("ComplianceStandard")) == 8


@pytest.mark.asyncio
async def test_retracted_contracts_are_excluded_unless_requested(source):
    await source.catalog.remove("acme-msa")
    assert await source.records_for("Contract") == []

    inclusive = ContractCardDataSource(SOURCE_NAME, {"catalog": source.catalog, "include_inactive": True})
    records = await inclusive.records_for("Contract")
    assert records[0]["active"] is False
    assert (await inclusive.records_for("Obligation"))[0]["active"] is False


@pytest.mark.asyncio
async def test_extract_returns_only_the_requested_fields(source):
    result = await source.extract(fields=["contract_id", "title", "status"])
    assert result.total == 1
    assert set(result.records[0].data) == {"contract_id", "title", "status"}
    assert result.records[0].metadata["entity"] == "Contract"
    assert result.source_name == SOURCE_NAME


@pytest.mark.asyncio
async def test_list_fields_covers_every_entity(source):
    fields = await source.list_fields()
    for entity_fields in ENTITY_FIELDS.values():
        assert entity_fields <= set(fields)


# --------------------------------------------------------------------------
# Standalone filters and the prevalidated snapshot
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standalone_filters_narrow_a_projection(source):
    await source.catalog.upsert(card("zeta-nda", contract_type="nda", status="expired"))

    assert len(await source.records_for("Contract")) == 2
    assert [record["contract_id"] for record in await source.records_for("Contract", filters={"status": "active"})] == [
        "acme-msa"
    ]
    assert [
        record["contract_id"] for record in await source.records_for("Contract", filters={"contract_id": "zeta-nda"})
    ] == ["zeta-nda"]
    assert len(await source.records_for("Obligation", filters={"contract_id": "acme-msa"})) == 1


@pytest.mark.asyncio
async def test_unsupported_filters_are_rejected(source):
    with pytest.raises(UnknownFieldRequest, match="unsupported filters"):
        await source.records_for("Contract", filters={"salary": 1})


@pytest.mark.asyncio
async def test_snapshot_returns_all_five_entities_prevalidated(source):
    snapshot = await source.snapshot()
    assert set(snapshot) == {
        "Contract",
        "Party",
        "Person",
        "Obligation",
        "ComplianceStandard",
    }
    assert len(snapshot["Contract"]) == 1
    assert len(snapshot["ComplianceStandard"]) == 8
    assert snapshot["Obligation"][0]["contract_id"] == "acme-msa"


# --------------------------------------------------------------------------
# 3. Failures are never empty successes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_catalog_failure_propagates_instead_of_emptying_the_snapshot(source):
    async def boom(**kwargs):
        raise RuntimeError("catalog unavailable")

    source.catalog.list_cards = boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="catalog unavailable"):
        await source.extract(fields=sorted(ENTITY_FIELDS["Contract"]))
    with pytest.raises(RuntimeError):
        await source.snapshot()


@pytest.mark.asyncio
async def test_an_empty_catalog_is_an_honest_empty_projection():
    empty = ContractCardDataSource(SOURCE_NAME, {"catalog": InMemoryContractCatalog()})
    result = await empty.extract(fields=["contract_id", "title"])
    assert result.total == 0
    assert result.errors == []
