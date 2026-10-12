"""products_found for shelf-based, non-ink-wall planogram types (FEAT-648)."""

from __future__ import annotations

from typing import Any

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    FixtureMembership,
    Identification,
    IdentificationResult,
    PerceptionResult,
    ReferenceImage,
    Shape,
    ShapeKind,
    Slot,
    SlotPresence,
)
from parrot_pipelines.planogram.layout import resolve_layout_profile
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import (
    EndcapBacklitMultitier,
    EndcapNoShelvesPromotional,
    GraphicPanelDisplay,
    InkWall,
    ProductCounter,
    ProductOnShelves,
)

_SHELF_TYPES = [EndcapBacklitMultitier, ProductOnShelves, ProductCounter, GraphicPanelDisplay]


class _InlineExecutor:
    """Run CPU helpers inline."""

    async def run(self, fn: Any, *args: Any) -> Any:
        """Call the helper synchronously."""
        return fn(*args)


class _NoOcr:
    """Offline OCR marker."""

    available = False


@pytest.mark.parametrize("composable", _SHELF_TYPES)
def test_shelf_types_opt_in_to_slot_presence(composable: type[Any]) -> None:
    """The four shelf-based profiles report slot presence with display-name labels (G1, G3, G4)."""
    assert composable.default_layout_profile().reporting == ReportingPolicy(slot_presence=True)


def test_zone_and_ink_wall_profiles_unchanged() -> None:
    """Zone-only and ink-wall profiles keep their FEAT-645 reporting policies."""
    assert EndcapNoShelvesPromotional.default_layout_profile().reporting == ReportingPolicy()
    assert InkWall.default_layout_profile().reporting == ReportingPolicy(product_label="product", slot_presence=True)
    assert ReportingPolicy().slot_presence is False


def _definition(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one shelf with a two-facing CLOSEOUT position."""
    definition: dict[str, Any] = {
        "version": "1",
        "shelves": [
            {
                "shelf_id": "s1",
                "shelf_number": 1,
                "level": "1",
                "facings": [
                    {
                        "facing_id": "s1_f1",
                        "shelf_id": "s1",
                        "slot": 1,
                        "position": 1,
                        "product": "ET-2850",
                        "brand": "Epson",
                        "descriptors": {"sku": "SKU-ET-2850", "display_name": "EcoTank ET-2850"},
                    },
                    {
                        "facing_id": "s1_f2a",
                        "shelf_id": "s1",
                        "slot": 2,
                        "position": 2,
                        "product": "CLOSEOUT",
                        "brand": "Epson",
                        "facings": 2,
                        "facing_index": 1,
                        "descriptors": {"sku": "SKU-CLOSEOUT", "display_name": "Closeout printer"},
                    },
                    {
                        "facing_id": "s1_f2b",
                        "shelf_id": "s1",
                        "slot": 2,
                        "position": 2,
                        "product": "CLOSEOUT",
                        "brand": "Epson",
                        "facings": 2,
                        "facing_index": 2,
                        "descriptors": {"sku": "SKU-CLOSEOUT", "display_name": "Closeout printer"},
                    },
                    {
                        "facing_id": "s1_f3",
                        "shelf_id": "s1",
                        "slot": 3,
                        "position": 3,
                        "product": "ET-4850",
                        "brand": "Epson",
                        "descriptors": {"sku": "SKU-ET-4850", "display_name": "EcoTank ET-4850"},
                    },
                ],
            }
        ],
    }
    if meta is not None:
        definition["meta"] = meta
    return definition


def _ctx(definition: dict[str, Any], *, layout: Any = None, bank: list[ReferenceImage] | None = None) -> CycleContext:
    """Build offline context; ``layout=None`` lets supported types resolve their own profile."""
    return CycleContext(
        vision=None,
        executor=_InlineExecutor(),
        ocr=_NoOcr(),
        definition=load_slots_definition(definition),
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
        layout=layout,
        reference_bank=bank or [],
    )


def _perception(slots: list[int]) -> PerceptionResult:
    """Build ON_FIXTURE product shapes and one slot per index on row zero."""
    box = DetectionBox(x1=10, y1=10, x2=80, y2=80, confidence=0.9)
    shapes = [
        Shape(
            shape_id=f"img0:product:{slot}",
            image_id="img0",
            kind=ShapeKind.PRODUCT,
            box=box,
            row_index=0,
            slot_index=slot,
            membership=FixtureMembership.ON_FIXTURE,
        )
        for slot in slots
    ]
    return PerceptionResult(
        image_id="img0",
        image_size=(100, 100),
        shapes=shapes,
        slots=[
            Slot(
                slot_id=f"img0:r0:s{slot}",
                image_id="img0",
                row_index=0,
                slot_index=slot,
                box=box,
                anchor_shape_id=f"img0:product:{slot}",
            )
            for slot in slots
        ],
        row_count=1,
    )


def _identifications(by_slot: dict[int, dict[str, Any]]) -> IdentificationResult:
    """Build one occupied identification per supplied slot index."""
    return IdentificationResult(
        image_id="img0",
        identifications=[
            Identification(
                shape_id=f"img0:r0:s{slot}",
                image_id="img0",
                occupancy="occupied",
                evidence=["read"],
                **fields,
            )
            for slot, fields in by_slot.items()
        ],
    )


def _pipeline(type_name: str, definition: dict[str, Any], fake_vision_client: Any) -> PlanogramCompliance:
    """Build the type handler without making a provider request."""
    return PlanogramCompliance(
        planogram_config=PlanogramConfig(
            planogram_type=type_name,
            planogram_config={"brand": "Epson"},
            slots_definition=definition,
        ),
        llm=fake_vision_client,
    )


@pytest.mark.asyncio
async def test_product_on_shelves_products_found_tri_state(fake_vision_client: Any) -> None:
    """Presence distinguishes match, mismatch, and an unseen two-facing position (AC-3, AC-5)."""
    definition = _definition()
    pipe = _pipeline("product_on_shelves", definition, fake_vision_client)
    comparison = await pipe._type_handler.compare(
        [_perception([1, 3])],
        [_identifications({1: {"product": "ET-2850", "brand": "Epson"}, 3: {"product": "ET-9999", "brand": "Epson"}})],
        _ctx(definition),
    )

    assert len(comparison.products_found) == 3
    by_position = {presence.position: presence for presence in comparison.products_found}
    assert (by_position[1].found, by_position[1].status) == (True, FacingStatus.MATCH)
    assert (by_position[3].found, by_position[3].status) == (False, FacingStatus.MISMATCH)
    assert (by_position[2].found, by_position[2].status, by_position[2].facings, by_position[2].facings_found) == (
        None,
        FacingStatus.NOT_VISIBLE,
        2,
        0,
    )
    assert [presence.display_name for presence in comparison.products_found] == [
        "EcoTank ET-2850",
        "Closeout printer",
        "EcoTank ET-4850",
    ]


@pytest.mark.asyncio
async def test_reference_matched_printer_is_found(fake_vision_client: Any) -> None:
    """A reference-only identity produces a matched, observed catalogue product (AC-4)."""
    definition = _definition()
    pipe = _pipeline("product_on_shelves", definition, fake_vision_client)
    context = _ctx(
        definition,
        bank=[ReferenceImage(label="ref-0001", image=b"png", catalog_key="ET-2850")],
    )
    comparison = await pipe._type_handler.compare(
        [_perception([1])],
        [_identifications({1: {"product": None, "brand": "Epson", "reference_id": "ref-0001"}})],
        context,
    )

    presence = next(item for item in comparison.products_found if item.position == 1)
    assert presence.found is True
    assert presence.observed == "ET-2850"


@pytest.mark.asyncio
async def test_endcap_backlit_multitier_products_found(fake_vision_client: Any) -> None:
    """The backlit shelf type produces the same tri-state presence report (AC-3)."""
    definition = _definition()
    pipe = _pipeline("endcap_backlit_multitier", definition, fake_vision_client)
    comparison = await pipe._type_handler.compare(
        [_perception([1, 3])],
        [_identifications({1: {"product": "ET-2850", "brand": "Epson"}, 3: {"product": "ET-9999", "brand": "Epson"}})],
        _ctx(definition),
    )

    assert [(item.found, item.status) for item in comparison.products_found] == [
        (True, FacingStatus.MATCH),
        (None, FacingStatus.NOT_VISIBLE),
        (False, FacingStatus.MISMATCH),
    ]


@pytest.mark.asyncio
async def test_layout_profile_reporting_override_disables_presence(fake_vision_client: Any) -> None:
    """The planogram config reporting override disables slot-presence output (AC-6)."""
    definition = _definition()
    pipe = _pipeline(
        "product_on_shelves",
        definition,
        fake_vision_client,
    )
    pipe.config.planogram_config = {"layout_profile": {"reporting": {"slot_presence": False}}}
    comparison = await pipe._type_handler.compare(
        [_perception([1])],
        [_identifications({1: {"product": "ET-2850", "brand": "Epson"}})],
        _ctx(definition),
    )

    assert comparison.products_found == []


@pytest.mark.asyncio
async def test_definition_meta_reporting_override_disables_presence(fake_vision_client: Any) -> None:
    """Definition reporting metadata wins over the type's profile policy (AC-6)."""
    definition = _definition(meta={"reporting": {"slot_presence": False}})
    pipe = _pipeline("product_on_shelves", definition, fake_vision_client)
    comparison = await pipe._type_handler.compare(
        [_perception([1])],
        [_identifications({1: {"product": "ET-2850", "brand": "Epson"}})],
        _ctx(definition),
    )

    assert comparison.products_found == []


@pytest.mark.asyncio
async def test_assemble_and_handler_shape_for_non_ink_wall(fake_vision_client: Any) -> None:
    """Assembly preserves typed slot-presence records with JSON round-trip support."""
    definition = _definition()
    pipe = _pipeline("product_on_shelves", definition, fake_vision_client)
    context = _ctx(definition)
    comparison = await pipe._type_handler.compare(
        [_perception([1])],
        [_identifications({1: {"product": "ET-2850", "brand": "Epson"}})],
        context,
    )
    assembled = pipe._assemble([], [], comparison, [], context)

    assert assembled["products_found"] == comparison.products_found
    assert all(isinstance(presence, SlotPresence) for presence in assembled["products_found"])
    assert all(SlotPresence.model_validate(presence.model_dump(mode="json")) == presence for presence in assembled["products_found"])
