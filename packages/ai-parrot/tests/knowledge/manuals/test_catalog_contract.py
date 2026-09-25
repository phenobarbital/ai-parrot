"""Contract tests for the M4 manual catalog protocol."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from parrot.knowledge.common.provenance import Evidence, Extracted, FieldProvenance
from parrot.knowledge.manuals.catalog import (
    AnswerRecord,
    CatalogConflictError,
    DuplicateSourceError,
    ManualCatalogStore,
    queue_entries_for,
)
from parrot.knowledge.manuals.models import EquipmentRef, ManualCard, MediaRef, Procedure, Step, StepIdentity

from .._support.catalog import InMemoryManualCatalog


def make_card(manual_id: str = "model-x", **overrides: object) -> ManualCard:
    """Build a valid minimal manual card for catalog testing."""
    step = Step(
        identity=StepIdentity(step_id=f"{manual_id}:install:one", content_hash="a" * 64),
        order=1,
        text=Extracted(
            value="Install the filter.", evidence=Evidence(node_id="n1", quote="Install the filter."), confidence=0.9
        ),
    )
    payload: dict[str, object] = {
        "manual_id": manual_id,
        "revision": "rev-a",
        "source_uri": f"manual://{manual_id}.pdf",
        "source_sha256": f"{manual_id}-sha",
        "equipment": [EquipmentRef(equipment_id=f"{manual_id}-eq", model="Model X", aliases=["MX-100"])],
        "procedures": [
            Procedure(
                procedure_id=f"{manual_id}:install",
                slug="install",
                kind="assembly",
                title=Extracted(value="Filter installation", confidence=0.9),
                steps=[step],
            )
        ],
        "figures": [
            MediaRef(
                media_id=f"{manual_id}:fig-1",
                kind="figure",
                storage_key="figures/one.png",
                label="Fig 1",
                caption="Filter view",
            )
        ],
    }
    payload.update(overrides)
    return ManualCard(**payload)


@pytest.fixture()
def catalog() -> InMemoryManualCatalog:
    """Return a fresh tenant-bound catalog double."""
    return InMemoryManualCatalog(tenant_id="t1")


def test_protocol_is_fully_implemented_and_async() -> None:
    """The double implements every abstract async operation."""
    assert not getattr(InMemoryManualCatalog, "__abstractmethods__", set())
    for name in ManualCatalogStore.__abstractmethods__:
        assert inspect.iscoroutinefunction(getattr(ManualCatalogStore, name))
        assert inspect.iscoroutinefunction(getattr(InMemoryManualCatalog, name))


def test_cannot_instantiate_the_protocol_directly() -> None:
    """The protocol remains abstract."""
    with pytest.raises(TypeError):
        ManualCatalogStore(tenant_id="t1")  # type: ignore[abstract]


@pytest.mark.parametrize("value", ["Bad-Name", "1abc", "drop table;"])
def test_invalid_identifiers_rejected(value: str) -> None:
    """Schema and configured text-search identifiers reject unsafe input."""
    with pytest.raises(ValueError):
        InMemoryManualCatalog(schema=value)
    with pytest.raises(ValueError):
        InMemoryManualCatalog(search_regconfig=value)


@pytest.mark.asyncio
async def test_catalog_contract_inmemory(catalog: InMemoryManualCatalog) -> None:
    """Upsert writes history/outbox and detects stale writes and source clashes."""
    card = make_card()
    created = await catalog.upsert(card)
    assert created.created and created.revision == 1 and len(created.queued) == 1
    assert await catalog.find_by_sha(card.source_sha256) == await catalog.get(card.manual_id)
    assert await catalog.find_by_source_uri(card.source_uri or "") == await catalog.get(card.manual_id)
    assert len(await catalog.versions(card.manual_id)) == 1
    assert (await catalog.search("filter"))[0].matched == "procedure"

    await catalog.upsert(card.model_copy(update={"revision": "rev-b"}), expected_revision=1)
    assert [version.n for version in await catalog.versions(card.manual_id)] == [1, 2]
    with pytest.raises(CatalogConflictError):
        await catalog.upsert(card, expected_revision=1)
    with pytest.raises(DuplicateSourceError, match="already belongs"):
        await catalog.upsert(make_card("other", source_sha256=card.source_sha256))


@pytest.mark.asyncio
async def test_queue_ordering(catalog: InMemoryManualCatalog) -> None:
    """Derived queue entries follow reason priority and manual-id ties."""
    missing = make_card("b-missing", field_provenance={"revision": FieldProvenance(origin="llm", quote="")})
    low_step = Step(
        identity=StepIdentity(step_id="a-low:install:one", content_hash="b" * 64),
        order=1,
        text=Extracted(value="Install", evidence=Evidence(node_id="n2", quote="Install"), confidence=0.5),
    )
    low = make_card("a-low", procedures=[make_card().procedures[0].model_copy(update={"steps": [low_step]})])
    unpaired = make_card(
        "c-figure",
        procedures=[
            make_card()
            .procedures[0]
            .model_copy(update={"steps": [low_step.model_copy(update={"figure_refs": ["Missing"]})]})
        ],
    )
    stale = make_card("d-stale", verification="stale")
    for card in (missing, low, unpaired, stale):
        await catalog.upsert(card)
    entries = await catalog.verification_queue()
    assert [entry.reason for entry in entries] == [
        "missing_evidence",
        "low_confidence_step",
        "unpaired_figure",
        "stale",
    ]
    assert entries[0].items == ["revision"]
    assert queue_entries_for(stale)[0].reason == "stale"


@pytest.mark.asyncio
async def test_resolve_equipment_deterministic(catalog: InMemoryManualCatalog) -> None:
    """Exact equipment matches are ordered by equipment id."""
    first = make_card("a", equipment=[EquipmentRef(equipment_id="z", model="Model X")])
    second = make_card("b", equipment=[EquipmentRef(equipment_id="a", model="Model X")])
    await catalog.upsert(first)
    await catalog.upsert(second)
    assert [item.equipment_id for item in await catalog.resolve_equipment("model x")] == ["a", "z"]


@pytest.mark.asyncio
async def test_record_answer_failure_propagates(catalog: InMemoryManualCatalog) -> None:
    """An unavailable audit store prevents an answer record from being written."""
    catalog.fail_record_answer = True
    record = AnswerRecord(
        answer_id="answer-1",
        asked_at=datetime(2026, 9, 25, tzinfo=timezone.utc),
        user="tech@example.test",
        question="How do I install it?",
        answer_kind="procedure",
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await catalog.record_answer(record)
