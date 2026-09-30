"""Tests for evidence-only planogram rule helpers and shared comparison plumbing."""

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import ZoneDefinition
from parrot_pipelines.planogram.comparison.rules import match_zone, normalize_text, visual_feature_match
from parrot_pipelines.planogram.comparison.definition import SlotsDefinition
from parrot_pipelines.planogram.contracts import FixtureMembership, PerceptionResult, Shape, ShapeKind


def _zone(shape_id: str, y1: int) -> Shape:
    return Shape(
        shape_id=shape_id,
        image_id="img0",
        kind=ShapeKind.ZONE,
        profile="header",
        box=DetectionBox(x1=10, y1=y1, x2=100, y2=y1 + 20, confidence=1.0),
        membership=FixtureMembership.ON_FIXTURE,
    )


def test_text_and_visual_helpers_keep_product_on_shelves_semantics() -> None:
    """The copied helpers preserve normalization and semantic feature matching."""
    assert normalize_text("Café — DISPLAY/logo") == "cafe display logo"
    assert visual_feature_match([], ["anything"]) == 1.0
    assert visual_feature_match(["logo"], []) == 0.0
    assert visual_feature_match(["illuminated logo"], ["backlit branding"]) == 1.0


def test_selector_ordinal_matches_sorted_zone() -> None:
    """An ordinal selector chooses the corresponding sorted observed zone."""
    definition = SlotsDefinition(
        zones=[ZoneDefinition(zone_id="header-0", kind="header"), ZoneDefinition(zone_id="header-1", kind="header")]
    )
    selectors = [
        type("Selector", (), {"zone_id": "header-0", "profile": "header", "kind": "zone", "ordinal": 0, "region": None})(),
        type("Selector", (), {"zone_id": "header-1", "profile": "header", "kind": "zone", "ordinal": 1, "region": None})(),
    ]
    perception = PerceptionResult(
        image_id="img0",
        image_size=(200, 200),
        zones=[_zone("z1", 20), _zone("z2", 80)],
    )
    shape, status = match_zone(definition.zones[1], perception, definition, selectors)
    assert status == "matched"
    assert shape is not None and shape.shape_id == "z2"


def test_multiple_unselected_zones_are_ambiguous() -> None:
    """Without a selector, multiple candidates cannot be assigned by definition rank."""
    definition = SlotsDefinition(zones=[ZoneDefinition(zone_id="header", kind="header")])
    perception = PerceptionResult(
        image_id="img0",
        image_size=(200, 200),
        zones=[_zone("z1", 20), _zone("z2", 80)],
    )
    shape, status = match_zone(definition.zones[0], perception, definition, [])
    assert shape is None
    assert status == "ambiguous"
