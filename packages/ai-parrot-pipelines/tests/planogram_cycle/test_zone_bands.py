"""Fixture-relative band selectors: several observed fragments, one configured zone."""

import pytest
from pydantic import ValidationError

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition, ZoneDefinition
from parrot_pipelines.planogram.comparison.rules import evaluate_rules
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.layout import LayoutProfile, ZoneSelector
from parrot_pipelines.planogram.migration import convert_config
from parrot_pipelines.planogram.perception.bands import (
    OUTSIDE_FIXTURE_EVIDENCE,
    assign_bands,
    band_box,
    banded_zones,
    fixture_box,
)
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.stages.perceive import _match_zone_selectors

SIZE = (1500, 1125)
#: A stacked promotional endcap as a detector returns it: text fragments, one box spanning two panels,
#: and a sign of the neighbouring fixture.
FRAGMENTS = {
    "logo": (425, 77, 514, 108),
    "headline": (428, 132, 883, 181),
    "side_card": (933, 79, 1105, 210),
    "tagline": (553, 258, 735, 283),
    "panel": (409, 229, 1117, 778),
    "table_title": (640, 423, 907, 441),
    "base": (511, 671, 1074, 972),
    "neighbour": (1395, 547, 1476, 574),
}
SELECTORS = [
    ZoneSelector(zone_id="header", kind="zone", band=(0.0, 0.35)),
    ZoneSelector(zone_id="middle", kind="zone", band=(0.37, 0.54)),
    ZoneSelector(zone_id="bottom", kind="zone", band=(0.54, 0.95)),
]
EXPECTED = {
    "logo": "header",
    "headline": "header",
    "side_card": "header",
    "tagline": "header",
    "panel": "middle",
    "table_title": "middle",
    "base": "bottom",
}


def _zone(shape_id: str, box) -> Shape:
    return Shape(
        shape_id=shape_id,
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=box[0], y1=box[1], x2=box[2], y2=box[3], confidence=0.9),
        source=ObservationSource.LLM,
    )


def _zones(names=None) -> list:
    return [_zone(name, box) for name, box in FRAGMENTS.items() if names is None or name in names]


def test_fragments_are_assigned_to_the_band_holding_their_centre():
    assigned, outside = assign_bands(_zones(), SELECTORS)
    assert assigned == EXPECTED
    assert outside == {"neighbour"}
    assert fixture_box(_zones()) == (409, 77, 1117, 972)


def test_without_band_selectors_nothing_is_assigned():
    assert assign_bands(_zones(), [ZoneSelector(zone_id="header", kind="zone", ordinal=0)]) == ({}, set())
    assert assign_bands([], SELECTORS) == ({}, set())
    assert fixture_box([]) is None


def test_band_box_is_a_slice_of_the_fixture():
    assert band_box((100, 200, 300, 1200), (0.5, 0.75)) == (100, 700, 300, 950)
    assert band_box((100, 200, 100, 1200), (0.5, 0.75)) is None


@pytest.mark.parametrize(
    "fields",
    [
        {"band": (0.4, 0.4)},
        {"band": (0.6, 0.2)},
        {"band": (0.0, 1.2)},
        {"band": (0.0, 0.5), "ordinal": 0},
        {"band": (0.0, 0.5), "region": (0.0, 0.0, 1.0, 1.0)},
    ],
)
def test_invalid_bands_are_rejected(fields):
    with pytest.raises(ValidationError, match="band"):
        ZoneSelector(zone_id="header", **fields)


def test_perception_marks_band_members_and_drops_the_neighbour():
    zones = {zone.shape_id: zone for zone in _match_zone_selectors(_zones(), SELECTORS, SIZE)}
    assert zones["neighbour"].membership == FixtureMembership.OFF_FIXTURE
    assert OUTSIDE_FIXTURE_EVIDENCE in zones["neighbour"].membership_evidence
    for shape_id, zone_id in EXPECTED.items():
        assert zones[shape_id].membership == FixtureMembership.ON_FIXTURE
        assert zones[shape_id].membership_evidence == [f"zone_selector:{zone_id}"]
    assert [zone.shape_id for zone in banded_zones(list(zones.values()), "middle")] == ["panel", "table_title"]


def _run_rules(zones, texts, illumination, bindings, features=None):
    perception = PerceptionResult(image_id="img0", image_size=SIZE, zones=_match_zone_selectors(zones, SELECTORS, SIZE))
    identification = IdentificationResult(
        image_id="img0",
        identifications=[
            Identification(shape_id=shape_id, image_id="img0", text=text, source=ObservationSource.LLM)
            for shape_id, text in texts.items()
        ],
        rule_observations=[
            RuleObservation(
                image_id="img0",
                target_id=shape_id,
                kind="illumination",
                value=state,
                assessed=True,
                source=ObservationSource.LLM,
            )
            for shape_id, state in illumination.items()
        ]
        + [
            RuleObservation(
                image_id="img0",
                target_id=shape_id,
                kind="visual_features",
                value=phrases,
                assessed=True,
                source=ObservationSource.LLM,
            )
            for shape_id, phrases in (features or {}).items()
        ],
    )
    ctx = CycleContext(
        definition=SlotsDefinition(
            zones=[ZoneDefinition(zone_id=zone_id, kind="graphic") for zone_id in ("header", "middle", "bottom")]
        ),
        bindings=bindings,
        layout=LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], zone_selectors=SELECTORS),
    )
    return evaluate_rules([perception], [identification], [], ctx)


def _text_rule(zone_id, *required) -> RuleBinding:
    return RuleBinding(
        rule_id=f"text_requirements:{zone_id}",
        kind="text_requirements",
        target_id=zone_id,
        params={"requirements": [{"required_text": text, "match_type": "contains"} for text in required]},
    )


def test_text_of_every_fragment_counts_for_its_zone_only():
    texts = {"logo": "EPSON", "headline": "EcoTank Printers", "tagline": "Goodbye Cartridges.", "base": "Special Offer"}
    outcomes = _run_rules(
        _zones(),
        texts,
        {},
        [
            RuleBinding(rule_id="zone_present:header", kind="zone_present", target_id="header"),
            _text_rule("header", "EPSON", "EcoTank Printers", "Goodbye Cartridges"),
            _text_rule("bottom", "EcoTank Printers"),
        ],
    )
    assert outcomes["zone_present:header"].passed is True
    assert outcomes["text_requirements:header"].passed is True
    assert {ref.shape_id for ref in outcomes["text_requirements:header"].observations} >= {
        "logo",
        "headline",
        "tagline",
    }
    assert (
        outcomes["text_requirements:bottom"].assessed is True and outcomes["text_requirements:bottom"].passed is False
    )


def test_phrases_read_off_a_zone_crop_are_text_evidence_for_that_zone_only():
    bindings = [_text_rule("bottom", "Special Offer"), _text_rule("header", "Special Offer")]
    outcomes = _run_rules(
        _zones(), {"base": "Why print?"}, {}, bindings, {"base": ["EPSON logo", "Special Offer insert"]}
    )
    assert outcomes["text_requirements:bottom"].passed is True
    assert outcomes["text_requirements:header"].passed is False


def test_a_band_without_fragments_is_not_observed_not_ambiguous():
    outcomes = _run_rules(
        _zones({"logo", "headline", "base"}),
        {},
        {},
        [RuleBinding(rule_id="zone_present:middle", kind="zone_present", target_id="middle")],
    )
    assert outcomes["zone_present:middle"].assessed is False
    assert outcomes["zone_present:middle"].detail == "zone visibility unknown"


def test_illumination_of_a_zone_follows_the_larger_fragments():
    binding = RuleBinding(
        rule_id="illumination:header", kind="illumination", target_id="header", params={"required": "off"}
    )
    states = {"logo": "on", "headline": "off", "side_card": "off", "tagline": "off"}
    assert _run_rules(_zones(), {}, states, [binding])["illumination:header"].passed is True
    lit = {"logo": "off", "headline": "on", "side_card": "on", "tagline": "on"}
    outcome = _run_rules(_zones(), {}, lit, [binding])["illumination:header"]
    assert outcome.assessed is True and outcome.passed is False


def _stacked(with_heights: bool) -> dict:
    shelves = [
        {"level": "bottom", "y_start_ratio": 0.54, "height_ratio": 0.41, "name": "Base"},
        {"level": "header", "y_start_ratio": 0.0, "height_ratio": 0.35, "name": "Top"},
        {"level": "middle", "y_start_ratio": 0.37, "height_ratio": 0.17, "name": "Table"},
    ]
    return {
        "shelves": [
            {
                "level": shelf["level"],
                "y_start_ratio": shelf["y_start_ratio"],
                **({"height_ratio": shelf["height_ratio"]} if with_heights else {}),
                "products": [{"name": shelf["name"], "product_type": "promotional_graphic"}],
            }
            for shelf in shelves
        ]
    }


def test_converter_emits_bands_for_a_zone_only_fixture_with_geometry():
    report = convert_config(_stacked(with_heights=True), planogram_type="endcap_no_shelves_promotional")
    bands = {selector["zone_id"]: selector["band"] for selector in report.layout_profile["zone_selectors"]}
    assert bands == {"zone-header-1": [0.0, 0.35], "zone-middle-1": [0.37, 0.54], "zone-bottom-1": [0.54, 0.95]}
    assert all("ordinal" not in selector for selector in report.layout_profile["zone_selectors"])
    assert any("fixture bands" in item for item in report.warnings) and report.unresolved == []
    LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], zone_selectors=report.layout_profile["zone_selectors"])


def test_converter_keeps_ordinals_without_heights():
    report = convert_config(_stacked(with_heights=False), planogram_type="endcap_no_shelves_promotional")
    assert [selector.get("ordinal") for selector in report.layout_profile["zone_selectors"]] == [0, 1, 2]
