"""ManualGraphLoader reconciliation (FEAT-601 M9, AC5, AC11)."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

import pytest

pytest.importorskip("parrot_loaders")

from parrot.knowledge.common.provenance import Evidence, Extracted  # noqa: E402
from parrot.knowledge.manuals.graph_loader import ManualGraphLoader  # noqa: E402
from parrot.knowledge.manuals.models import (  # noqa: E402
    EquipmentRef,
    ManualCard,
    ManualVersion,
    MediaLink,
    MediaRef,
    PartRef,
    Procedure,
    Step,
    StepIdentity,
)
from parrot.knowledge.manuals.models import manual_snapshot_payload  # noqa: E402
from parrot.knowledge.manuals.tips import RelinkReport  # noqa: E402

from .._support.catalog import InMemoryManualCatalog  # noqa: E402
from .._support.graph import FakeGraphStore, FakeTenantManager  # noqa: E402


def _extracted(value: str) -> Extracted[str]:
    """Create a minimally substantiated text value."""
    return Extracted(value=value, evidence=Evidence(node_id="node-1", quote=value, page=1), confidence=1.0)


def _card(revision: str = "A") -> ManualCard:
    """Create one manual with duplicate media links for merge coverage."""
    part = PartRef(part_id="part-1", part_number="P-1", name=_extracted("Bracket"), quantity=1)
    step = Step(
        identity=StepIdentity(step_id="manual-1:step-1", source_identity="1", content_hash="a" * 64),
        order=1,
        text=_extracted("Fit bracket"),
        parts=[part],
        media=[
            MediaLink(media_id="media-1", role="primary", confidence=0.8),
            MediaLink(media_id="media-1", role="secondary", confidence=0.9),
        ],
    )
    return ManualCard(
        manual_id="manual-1",
        revision=revision,
        source_sha256=f"{revision.lower()}" * 64,
        equipment=[EquipmentRef(equipment_id="equipment-1", model="Model 1")],
        procedures=[
            Procedure(procedure_id="manual-1:fit", slug="fit", kind="assembly", title=_extracted("Fit"), steps=[step])
        ],
        global_parts=[part],
        figures=[MediaRef(media_id="media-1", kind="figure", storage_key="manual-1/figure.png")],
    )


async def _catalog(card: ManualCard) -> InMemoryManualCatalog:
    """Store a card with store-owned version metadata supplied through ``version=``."""
    catalog = InMemoryManualCatalog()
    await catalog.upsert(
        card,
        version=ManualVersion(
            n=1,
            revision=card.revision,
            valid_from=date(2026, 1, 1),
            source_sha256=card.source_sha256,
            card_snapshot=manual_snapshot_payload(card),
        ),
    )
    return catalog


def test_desired_edges_merges_duplicate_pairs() -> None:
    """Two step/media roles collapse into one edge with a sorted role list."""
    snapshot: dict[str, list[dict[str, Any]]] = {
        "Step": [
            {
                "step_id": "step-1",
                "media": [
                    {"media_id": "media-1", "role": "secondary", "confidence": 0.8},
                    {"media_id": "media-1", "role": "primary", "confidence": 0.9},
                ],
            }
        ],
        "Media": [{"media_id": "media-1", "callouts": []}],
    }
    edges = ManualGraphLoader.desired_edges(snapshot)
    assert len(edges) == 1
    assert edges[0].properties == {"roles": ["primary", "secondary"], "confidence": 0.9}


@pytest.mark.asyncio
async def test_publish_all_never_touches_technician_collections() -> None:
    """Pre-seeded technician data is unchanged by publication and retraction."""
    catalog = await _catalog(_card())
    graph = FakeGraphStore()
    graph.nodes["tech_tip"] = {"tip-1": {"_key": "tip-1", "tip_id": "tip-1", "_active": True}}
    graph.edges["tech_tip_on"] = [{"_from": "tech_tip/tip-1", "_to": "step/manual-1:step-1"}]
    graph.edges["tech_tip_by"] = [{"_from": "tech_tip/tip-1", "_to": "employee/e-1"}]
    original = (
        deepcopy(graph.nodes["tech_tip"]),
        deepcopy(graph.edges["tech_tip_on"]),
        deepcopy(graph.edges["tech_tip_by"]),
    )
    loader = ManualGraphLoader(catalog=catalog, graph_store=graph, tenant_manager=FakeTenantManager())
    await loader.publish_all()
    await loader.retract("manual-1")
    assert (graph.nodes["tech_tip"], graph.edges["tech_tip_on"], graph.edges["tech_tip_by"]) == original


@pytest.mark.asyncio
async def test_edges_carry_origin_and_triple() -> None:
    """Every owned edge document carries the generic triple and manual origin."""
    catalog = await _catalog(_card())
    graph = FakeGraphStore()
    loader = ManualGraphLoader(catalog=catalog, graph_store=graph, tenant_manager=FakeTenantManager())
    report = await loader.publish_all()
    assert report.published
    for edges in graph.edges.values():
        for edge in edges:
            assert {"source_id", "target_id", "kind", "origin"} <= edge.keys()
            assert edge["origin"] == "manual"


@pytest.mark.asyncio
async def test_startup_check_foreign_manager_raises() -> None:
    """A manager lacking the procedures entities fails the domain check."""
    catalog = await _catalog(_card())
    loader = ManualGraphLoader(
        catalog=catalog, graph_store=FakeGraphStore(), tenant_manager=FakeTenantManager(("Contract",))
    )
    from parrot.knowledge.manuals.domain import ProceduresDomainNotLoaded

    with pytest.raises(ProceduresDomainNotLoaded):
        await loader.startup_check()


@pytest.mark.asyncio
async def test_relink_failure_makes_report_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """A relink report with failures prevents the publication from claiming success."""
    first = _card("A")
    catalog = await _catalog(first)
    second = _card("B")
    await catalog.upsert(
        second,
        version=ManualVersion(
            n=2,
            revision="B",
            valid_from=date(2026, 2, 1),
            source_sha256=second.source_sha256,
            card_snapshot=manual_snapshot_payload(second),
        ),
    )
    graph = FakeGraphStore()
    graph.nodes["manual"] = {
        "manual-1": {"_key": "manual-1", "manual_id": "manual-1", "revision": "A", "_active": True}
    }

    async def failed_relink(*args: Any, **kwargs: Any) -> RelinkReport:
        """Return a deterministic relink failure without writing technician collections."""
        return RelinkReport(manual_id="manual-1", failed=["tip-1"])

    monkeypatch.setattr("parrot.knowledge.manuals.graph_loader.relink_tips", failed_relink)
    loader = ManualGraphLoader(catalog=catalog, graph_store=graph, tenant_manager=FakeTenantManager())
    report = await loader.publish_all()
    assert report.tip_relink is not None
    assert report.tip_relink.failed == ["tip-1"]
    assert not report.complete()
    assert not report.published
