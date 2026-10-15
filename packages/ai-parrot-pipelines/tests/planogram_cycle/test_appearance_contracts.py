"""FEAT-683: closed appearance vocabulary shared by evidence, validation and evaluation."""

import pytest
from pydantic import ValidationError

from parrot_pipelines.planogram.contracts import (
    APPEARANCE_UNDETERMINED,
    APPEARANCE_VALUES,
    ObservationSource,
    RuleObservation,
    ZoneAppearance,
)
from parrot_pipelines.planogram.identification.evidence import ZoneEvidenceAnswer


def test_zone_appearance_defaults_unknown() -> None:
    """Default all appearance attributes to an undetermined value."""
    appearance = ZoneAppearance()
    assert appearance.model_dump() == {
        "background_color": "unknown",
        "border_color": "unknown",
        "finish": "unknown",
        "base_surface_color": "unknown",
    }


def test_appearance_values_exclude_undetermined() -> None:
    """Only determinate closed-vocabulary values may be configured."""
    assert all(not values.intersection(APPEARANCE_UNDETERMINED) for values in APPEARANCE_VALUES.values())
    assert set(APPEARANCE_VALUES) == set(ZoneAppearance.model_fields)


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("border_color", "beige"),
        ("border_color", "cream"),
        ("background_color", "off-white"),
        ("finish", "satin"),
        ("base_surface_color", "teal"),
        ("background_color", None),
        ("background_color", 3),
    ],
)
def test_zone_appearance_coerces_out_of_vocabulary_to_unknown(field: str, raw: object) -> None:
    """A model answer outside the closed vocabulary becomes ``unknown`` instead of failing validation."""
    assert getattr(ZoneAppearance.model_validate({field: raw}), field) == "unknown"


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("background_color", "Blue", "blue"),
        ("background_color", " WHITE ", "white"),
        ("border_color", "gray", "grey"),
        ("background_color", "multi-color", "multicolor"),
        ("background_color", "Multicolour", "multicolor"),
        ("base_surface_color", "not visible", "not_visible"),
        ("border_color", "None", "none"),
    ],
)
def test_zone_appearance_normalises_case_spacing_and_spellings(field: str, raw: str, expected: str) -> None:
    """Case, surrounding spaces, hyphens/spaces and well-known spellings normalise into the vocabulary."""
    assert getattr(ZoneAppearance.model_validate({field: raw}), field) == expected


def test_zone_appearance_keeps_field_specific_values() -> None:
    """``none`` stays a border answer and ``not_visible`` a base-surface answer; elsewhere they are unknown."""
    appearance = ZoneAppearance.model_validate(
        {
            "background_color": "none",
            "border_color": "none",
            "finish": "not_visible",
            "base_surface_color": "not_visible",
        }
    )
    assert appearance.model_dump() == {
        "background_color": "unknown",
        "border_color": "none",
        "finish": "unknown",
        "base_surface_color": "not_visible",
    }


def test_evidence_answer_with_out_of_vocabulary_colour_keeps_the_zone_evidence() -> None:
    """One unexpected colour must not invalidate the illumination and visual evidence of the same answer."""
    answer = ZoneEvidenceAnswer.model_validate(
        {
            "illumination": "off",
            "visual_features": ["EPSON logo"],
            "appearance": {"background_color": "white", "border_color": "beige", "base_surface_color": "blue"},
        }
    )
    assert answer.illumination == "off"
    assert answer.visual_features == ["EPSON logo"]
    assert answer.appearance.model_dump() == {
        "background_color": "white",
        "border_color": "unknown",
        "finish": "unknown",
        "base_surface_color": "blue",
    }


def test_zone_appearance_still_rejects_a_non_object() -> None:
    """Coercion is per attribute: an answer whose appearance is not an object still fails validation."""
    with pytest.raises(ValidationError):
        ZoneAppearance.model_validate([])


def test_rule_observation_accepts_appearance_dict() -> None:
    """Preserve the evidence-stage appearance dictionary on an observation."""
    value = ZoneAppearance(background_color="blue", finish="matte").model_dump()
    observation = RuleObservation(
        image_id="img0",
        target_id="img0:zone-region:z1",
        kind="appearance",
        value=value,
        source=ObservationSource.LLM,
    )
    assert observation.value == value
