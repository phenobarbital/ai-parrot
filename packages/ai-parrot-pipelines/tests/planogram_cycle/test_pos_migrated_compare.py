"""Offline tests for ProductOnShelves.compare evidence and fact-tag corroboration (FEAT-612)."""

import logging
from unittest.mock import MagicMock

import pytest
from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


def _definition(with_header: bool = True):
    """Build a compact slots definition with two products and an optional backlit zone."""
    shelves = []
    zones = []
    if with_header:
        shelves.append({"shelf_id": "header", "shelf_number": 0, "level": "header", "facings": []})
        zones.append({"zone_id": "zone_backlit", "kind": "backlit", "shelf_id": "header", "required": True})
    shelves.append(
        {
            "shelf_id": "top",
            "shelf_number": 1,
            "level": "top",
            "facings": [
                {
                    "facing_id": f"top_f{i}",
                    "shelf_id": "top",
                    "slot": i,
                    "product": f"ES-{i}00",
                    "brand": "Acme",
                    "descriptors": {"display_name": f"ES-{i}00", "identifiers": [f"ES-{i}00"]},
                }
                for i in (1, 2)
            ],
        }
    )
    return load_slots_definition({"shelves": shelves, "zones": zones})


@pytest.fixture
def handler() -> ProductOnShelves:
    """Build ProductOnShelves with a minimal migrated configuration."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.compare")
    pipeline.reference_images = {}
    config = MagicMock()
    config.planogram_config = {"brand": "Acme"}
    config.slots_definition = {"shelves": []}
    config.get_planogram_description.side_effect = ValueError("no legacy shelves")
    return ProductOnShelves(pipeline=pipeline, config=config)


def _ctx(definition, bindings=()) -> CycleContext:
    """Build a comparison context."""
    return CycleContext(
        definition=definition,
        bindings=list(bindings),
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def _zone(membership=FixtureMembership.ON_FIXTURE) -> Shape:
    """Build the single observed header zone used by rule tests."""
    return Shape(
        shape_id="img0:zone",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=10, y1=10, x2=390, y2=80, confidence=0.9),
        membership=membership,
    )


def _perception(zone=None, products=("ES-100", "ES-200"), tag=None) -> PerceptionResult:
    """Build product slots and optional fact-tag evidence."""
    shapes, slots = [], []
    for n, _product in enumerate(products, start=1):
        shape_id = f"img0:p{n}"
        box = DetectionBox(x1=20 + 150 * (n - 1), y1=150, x2=150 + 150 * (n - 1), y2=300, confidence=0.9)
        shapes.append(
            Shape(
                shape_id=shape_id,
                image_id="img0",
                kind=ShapeKind.PRODUCT,
                box=box,
                row_index=0,
                slot_index=n,
                membership=FixtureMembership.ON_FIXTURE,
            )
        )
        slots.append(
            Slot(
                slot_id=f"img0:r0:s{n}",
                image_id="img0",
                row_index=0,
                slot_index=n,
                box=box,
                anchor_shape_id=shape_id,
            )
        )
    if zone is not None:
        shapes.append(zone)
    if tag is not None:
        shapes.append(tag)
    return PerceptionResult(
        image_id="img0", image_size=(400, 400), shapes=shapes, slots=slots, zones=[zone] if zone else [], row_count=1
    )


def _identifications(products=("ES-100", "ES-200"), occupancy="occupied") -> IdentificationResult:
    """Build one identification per product slot."""
    return IdentificationResult(
        image_id="img0",
        identifications=[
            Identification(
                shape_id=f"img0:r0:s{n}",
                image_id="img0",
                product=product,
                brand="Acme",
                occupancy=occupancy,
                evidence=[f"reads {product}"],
            )
            for n, product in enumerate(products, start=1)
        ],
    )


async def test_compare_header_illumination_from_evidence_penalty_once(handler):
    """Illumination comes from rule observations and compare never touches vision."""
    definition = _definition()
    binding = RuleBinding(
        rule_id="ill", kind="illumination", target_id="zone_backlit", params={"required": "on", "penalty": 0.5}
    )
    zone_binding = RuleBinding(rule_id="zone", kind="zone_present", target_id="zone_backlit")
    ctx = _ctx(definition, [zone_binding, binding])
    ctx.vision = MagicMock()
    identifications = _identifications().model_copy(
        update={
            "rule_observations": [
                RuleObservation(
                    image_id="img0",
                    target_id="img0:zone",
                    kind="illumination",
                    value="off",
                    assessed=True,
                    source=ObservationSource.LLM,
                )
            ]
        }
    )
    result = await handler.compare([_perception(_zone())], [identifications], ctx)
    header = next(score for score in result.shelf_scores if score.shelf_id == "header")
    assert header.lenient_score == pytest.approx(0.5)
    assert result.compliance_results[0].compliance_status.value == "non_compliant"
    assert result.overall_compliant is False


async def test_compare_unknown_illumination_is_inconclusive(handler):
    """Unassessed illumination does not become a false failure."""
    definition = _definition()
    binding = RuleBinding(rule_id="ill", kind="illumination", target_id="zone_backlit", params={"required": "on"})
    observations = [
        RuleObservation(
            image_id="img0",
            target_id="img0:zone",
            kind="illumination",
            value=None,
            assessed=False,
            source=ObservationSource.LLM,
        )
    ]
    result = await handler.compare(
        [_perception(_zone())],
        [_identifications().model_copy(update={"rule_observations": observations})],
        _ctx(definition, [binding]),
    )
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
    assert result.overall_compliant is False


async def test_fact_tag_corroborates_occupied_unresolved_slot(handler):
    """A tag supports an observed uncatalogued product without changing confidence or occupancy."""
    tag = Shape(
        shape_id="img0:tag1",
        image_id="img0",
        kind=ShapeKind.FACT_TAG,
        box=DetectionBox(x1=35, y1=300, x2=130, y2=320, confidence=0.9),
        ocr_text="ES-100",
        membership=FixtureMembership.ON_FIXTURE,
    )
    perception = _perception(products=("scanner", "ES-200"), tag=tag)
    identifications = _identifications(products=("scanner", "ES-200"))
    original = identifications.identifications[0]
    corroborated = handler._corroborate_with_fact_tags(perception, identifications, _definition(with_header=False))
    assert corroborated.identifications[0].evidence[-1] == "fact_tag | ES-100"
    assert corroborated.identifications[0].raw_confidence == original.raw_confidence
    assert corroborated.identifications[0].occupancy == original.occupancy
    result = await handler.compare([perception], [identifications], _ctx(_definition(with_header=False)))
    status = {position.facing_id: position.status for position in result.position_results}
    assert status["top_f1"] == FacingStatus.MATCH


async def test_fact_tag_never_creates_unseen_product(handler):
    """A tag below an absent slot cannot create an occupied facing."""
    tag = Shape(
        shape_id="img0:tag2",
        image_id="img0",
        kind=ShapeKind.FACT_TAG,
        box=DetectionBox(x1=185, y1=300, x2=280, y2=320, confidence=0.9),
        ocr_text="ES-200",
        membership=FixtureMembership.ON_FIXTURE,
    )
    perception = _perception(tag=tag)
    identifications = _identifications(products=("ES-100",), occupancy="occupied")
    result = await handler.compare([perception], [identifications], _ctx(_definition(with_header=False)))
    status = {position.facing_id: position.status for position in result.position_results}
    assert status["top_f2"] != FacingStatus.MATCH
    assert not any(
        position.facing_id == "top_f2" and position.status == FacingStatus.INFERRED_PRESENT
        for position in result.position_results
    )


async def test_compare_inconclusive_is_not_compliant(handler):
    """Missing identification evidence keeps the assessment inconclusive."""
    definition = _definition(with_header=False)
    result = await handler.compare([_perception()], [_identifications(products=("ES-100",))], _ctx(definition))
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
    assert result.overall_compliant is False


async def test_compare_complete_and_compliant(handler):
    """Complete matching observations are compliant."""
    definition = _definition(with_header=False)
    result = await handler.compare([_perception()], [_identifications()], _ctx(definition))
    assert result.assessment_status == AssessmentStatus.COMPLETE
    assert result.overall_compliant is True
    assert [item.compliance_status.value for item in result.compliance_results] == ["compliant"]


async def test_compare_ignores_off_fixture_observations(handler):
    """Off-fixture shapes do not satisfy expected facings."""
    definition = _definition(with_header=False)
    perception = _perception()
    perception.shapes[1] = perception.shapes[1].model_copy(update={"membership": FixtureMembership.OFF_FIXTURE})
    result = await handler.compare([perception], [_identifications()], _ctx(definition))
    statuses = {position.facing_id: position.status for position in result.position_results}
    assert statuses["top_f1"] == FacingStatus.MATCH
    assert statuses["top_f2"] == FacingStatus.NOT_VISIBLE


def test_handler_is_a_full_cycle_type(handler):
    """The type implements every shared cycle hook."""
    assert all(handler._implements(name) for name in ("perceive", "identify", "compare"))
