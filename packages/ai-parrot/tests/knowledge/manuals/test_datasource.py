"""ManualCardDataSource routing and projection tests (FEAT-601 M8)."""

from __future__ import annotations

from datetime import date

import pytest

pytest.importorskip("parrot_loaders")

from parrot.knowledge.common.provenance import Evidence, Extracted
from parrot.knowledge.manuals.datasource import (  # noqa: E402
    ENTITY_FIELDS,
    ENTITY_ROUTING_ORDER,
    SOURCE_NAME,
    ManualCardDataSource,
    UnknownFieldRequest,
)
from parrot.knowledge.manuals.models import (  # noqa: E402
    CalloutLink,
    EquipmentRef,
    Hazard,
    ManualCard,
    ManualVersion,
    MediaLink,
    MediaRef,
    PartRef,
    Procedure,
    Step,
    StepIdentity,
    ToolRef,
)

from .._support.catalog import InMemoryManualCatalog  # noqa: E402


def _extracted(value: str | int, node_id: str = "node-1") -> Extracted[str | int]:
    """Build one independently evidenced value for a manual fixture."""
    return Extracted(value=value, evidence=Evidence(node_id=node_id, quote=str(value), page=3), confidence=0.9)


def _card() -> ManualCard:
    """Build a complete, single-purpose card with all owned entity kinds."""
    part = PartRef(part_id="part-1", part_number="PN-1", name=_extracted("Bracket"), quantity=2)
    tool = ToolRef(tool_id="tool-1", name=_extracted("Wrench"), spec="10 mm")
    hazard = Hazard(hazard_id="hazard-1", severity="warning", text=_extracted("Wear gloves"))
    first = Step(
        identity=StepIdentity(step_id="step-1", source_identity="1", content_hash="a" * 64),
        order=1,
        text=_extracted("Attach bracket"),
        parts=[part],
        tools=[tool],
        hazards=[hazard],
        media=[MediaLink(media_id="media-1", role="primary", confidence=0.9)],
    )
    second = Step(
        identity=StepIdentity(step_id="step-2", source_identity="2", content_hash="b" * 64),
        order=2,
        text=_extracted("Tighten bolts", node_id="node-2"),
    )
    procedure = Procedure(
        procedure_id="manual-1:assemble",
        slug="assemble",
        kind="assembly",
        title=_extracted("Assemble"),
        steps=[first, second],
        estimated_minutes=5,
    )
    return ManualCard(
        manual_id="manual-1",
        revision="A",
        source_sha256="c" * 64,
        equipment=[EquipmentRef(equipment_id="equipment-1", model="Model 1", aliases=["M1"])],
        procedures=[procedure],
        global_parts=[part],
        global_tools=[tool],
        global_hazards=[hazard],
        figures=[
            MediaRef(
                media_id="media-1",
                kind="figure",
                storage_key="manual-1/media-1.png",
                page=3,
                label="Fig. 1",
                callouts=[CalloutLink(media_id="media-1", part_id="part-1", callout="1", confidence=0.95)],
            )
        ],
    )


@pytest.fixture()
async def source() -> ManualCardDataSource:
    """Return a tenant-bound source with one full card.

    ``ManualCatalogStore.upsert`` owns bitemporal version metadata and
    discards any ``versions`` pre-populated on the card itself (see its
    contract in ``catalog.py``) — the caller supplies version metadata via
    the ``version=`` kwarg instead.
    """
    catalog = InMemoryManualCatalog()
    await catalog.upsert(
        _card(),
        version=ManualVersion(n=1, revision="A", valid_from=date(2026, 1, 1), source_sha256="c" * 64),
    )
    return ManualCardDataSource(SOURCE_NAME, {"catalog": catalog})


def test_datasource_routing_order() -> None:
    """Most-specific step marker wins; invalid or mixed fields fail loudly."""
    source = ManualCardDataSource(SOURCE_NAME, {"catalog": InMemoryManualCatalog()})
    assert ENTITY_ROUTING_ORDER[0] == ("step_id", "Step")
    assert source.infer_entity(["step_id", "procedure_id"]) == "Step"
    assert source.infer_entity(None) == "Manual"
    with pytest.raises(UnknownFieldRequest):
        source.infer_entity(["step_id", "manual_id"])
    with pytest.raises(UnknownFieldRequest):
        source.infer_entity(["unknown"])


@pytest.mark.asyncio
async def test_snapshot_projects_all_entities_without_tips(source: ManualCardDataSource) -> None:
    """Eight owned entity projections are deterministic and flatten Extracted values."""
    snapshot = await source.snapshot()
    assert set(snapshot) == set(ENTITY_FIELDS)
    assert "Tip" not in snapshot
    assert snapshot["Equipment"] == sorted(snapshot["Equipment"], key=lambda record: record["equipment_id"])
    assert snapshot["Manual"][0]["versions"][0]["valid_from"] == "2026-01-01"
    assert snapshot["Procedure"][0]["title"] == "Assemble"
    assert snapshot["Part"][0]["name"] == "Bracket"
    assert snapshot["Tool"][0]["name"] == "Wrench"
    assert snapshot["Hazard"][0]["text"] == "Wear gloves"


@pytest.mark.asyncio
async def test_step_records_carry_edge_fields(source: ManualCardDataSource) -> None:
    """Step relationship fields preserve the exact loader input shapes."""
    steps = await source.records_for("Step")
    first = next(record for record in steps if record["step_id"] == "step-1")
    assert first["parts"] == [{"part_id": "part-1", "quantity": 2, "context": None}]
    assert first["tool_ids"] == ["tool-1"]
    assert first["hazard_ids"] == ["hazard-1"]
    assert first["media"] == [{"media_id": "media-1", "role": "primary", "confidence": 0.9, "origin": "manual"}]
    assert first["precedes"] == [{"step_id": "step-2", "kind": "order"}]
    assert first["node_id"] == "node-1"
    assert first["page"] == 3


def test_requires_manual_catalog() -> None:
    """The datasource requires an injected tenant-bound catalog instance."""
    with pytest.raises(ValueError, match="tenant-bound ManualCatalogStore"):
        ManualCardDataSource(SOURCE_NAME, {})


def test_registered_under_manualcard() -> None:
    """Import-time registration exposes this source through the loader factory."""
    from parrot_loaders.extractors.factory import DataSourceFactory

    assert DataSourceFactory._api_registry[SOURCE_NAME] is ManualCardDataSource
