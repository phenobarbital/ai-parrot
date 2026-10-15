"""Text requirements see text prepared for their match type: case and punctuation survive where needed (FEAT-687)."""

import pytest

from parrot.models.compliance import TextMatcher
from parrot.models.detections import DetectionBox, TextRequirement
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition, ZoneDefinition
from parrot_pipelines.planogram.comparison.rules import _requirement_features, evaluate_rules, normalize_text
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    Identification,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.layout import LayoutProfile, ZoneSelector
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.stages.perceive import _match_zone_selectors

SIZE = (1500, 1125)
SELECTORS = [ZoneSelector(zone_id="header", kind="zone", ordinal=0)]


def _found(required_text: str, texts, **options) -> bool:
    """Run one requirement the way ``_rule_text`` does, over raw features (as ``_entity_texts`` returns them)."""
    requirement = TextRequirement(required_text=required_text, **options)
    raw = [feature for text in texts for feature in (f"ocr:{text}", text)]
    return TextMatcher.check_text_match(
        required_text=requirement.required_text,
        visual_features=_requirement_features(requirement, raw),
        match_type=requirement.match_type,
        case_sensitive=requirement.case_sensitive,
        confidence_threshold=requirement.confidence_threshold,
    ).found


def test_case_sensitive_regex_matches_raw_text():
    assert _found(r"Scan\s*&\s*Done", ["Scan & Done. Leave the work to Epson"], match_type="regex", case_sensitive=True)


def test_case_sensitive_regex_rejects_lowercase():
    assert not _found(r"Scan\s*&\s*Done", ["scan & done"], match_type="regex", case_sensitive=True)


def test_case_sensitive_regex_brand():
    assert _found("EPSON", ["EPSON Goodbye Cartridges."], match_type="regex", case_sensitive=True)
    assert not _found("EPSON", ["Epson EcoTank"], match_type="regex", case_sensitive=True)


def test_contains_case_sensitive_ignores_punctuation_keeps_case():
    assert _found("Scan & Done", ["Scan & Done."], match_type="contains", case_sensitive=True)
    assert not _found("Scan & Done", ["SCAN & DONE."], match_type="contains", case_sensitive=True)


def test_contains_default_unchanged():
    assert _found("hello savings", ["Hello Savings."])
    assert _found("Scan & Done", ["scan & done"])
    assert not _found("Hello Savings", ["Goodbye Cartridges."])


def test_exact_case_sensitive():
    assert _found("Hello Savings", ["Goodbye Cartridges. Hello Savings."], match_type="exact", case_sensitive=True)
    assert not _found("Hello Savings", ["HELLO SAVINGS"], match_type="exact", case_sensitive=True)


@pytest.mark.parametrize(
    ("requirement", "passed"),
    [
        ({"required_text": "EPSON", "match_type": "regex", "case_sensitive": True}, True),
        ({"required_text": "Epson", "match_type": "regex", "case_sensitive": True}, False),
        ({"required_text": "Hello Savings", "match_type": "contains"}, True),
    ],
)
def test_rule_text_end_to_end(requirement, passed):
    zone = Shape(
        shape_id="poster",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=400, y1=60, x2=1100, y2=500, confidence=0.9),
        source=ObservationSource.LLM,
    )
    perception = PerceptionResult(
        image_id="img0", image_size=SIZE, zones=_match_zone_selectors([zone], SELECTORS, SIZE)
    )
    identification = IdentificationResult(
        image_id="img0",
        identifications=[
            Identification(
                shape_id="poster",
                image_id="img0",
                text="EPSON Goodbye Cartridges. Hello Savings.",
                source=ObservationSource.LLM,
            )
        ],
    )
    binding = RuleBinding(
        rule_id="text_requirements:header",
        kind="text_requirements",
        target_id="header",
        params={"requirements": [requirement]},
    )
    ctx = CycleContext(
        definition=SlotsDefinition(zones=[ZoneDefinition(zone_id="header", kind="header")]),
        bindings=[binding],
        layout=LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], zone_selectors=SELECTORS),
    )
    outcome = evaluate_rules([perception], [identification], [], ctx)["text_requirements:header"]
    assert outcome.assessed is True
    assert outcome.passed is passed


def test_normalize_text_unchanged():
    assert normalize_text("Café — DISPLAY/logo") == "cafe display logo"
    assert normalize_text("ocr:Scan & Done.") == "ocr scan done"
    assert normalize_text("") == ""
