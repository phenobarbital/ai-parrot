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


def test_zone_appearance_rejects_free_text() -> None:
    """Reject values outside the closed appearance vocabulary."""
    with pytest.raises(ValidationError):
        ZoneAppearance(background_color="off-white")


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
