"""Reporting defaults and configuration overrides for FEAT-645."""

import copy

import pytest

from parrot_pipelines.planogram.layout import resolve_layout_profile
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types.ink_wall import InkWall


def test_ink_wall_default_reporting() -> None:
    """Ink-wall enables model labels and independent presence defaults."""
    first = InkWall.default_layout_profile()
    second = InkWall.default_layout_profile()

    assert first.reporting.product_label == "product"
    assert first.reporting.slot_presence is True
    assert first.reporting.misplaced_min_confidence == 0.9
    assert first.reporting is not second.reporting

    first.reporting.product_label = "display_name"
    assert second.reporting.product_label == "product"


@pytest.mark.parametrize("kind", sorted(PlanogramCompliance._PLANOGRAM_TYPES))
def test_other_types_default_reporting(kind: str) -> None:
    """All registered types except ink-wall retain legacy reporting."""
    profile = PlanogramCompliance._PLANOGRAM_TYPES[kind].default_layout_profile()

    if kind == "ink_wall":
        assert profile.reporting.product_label == "product"
        assert profile.reporting.slot_presence is True
    else:
        assert profile.reporting.product_label == "display_name"
        assert profile.reporting.slot_presence is False
    assert profile.reporting.misplaced_min_confidence == 0.9


def test_layout_profile_reporting_override() -> None:
    """A partial override disables presence while preserving model labels."""
    defaults = InkWall.default_layout_profile()
    config = {"layout_profile": {"reporting": {"slot_presence": False}}}
    before_defaults = defaults.model_copy(deep=True)
    before_config = copy.deepcopy(config)

    resolved = resolve_layout_profile(defaults, config, config_name="ink-wall")

    assert resolved.reporting.product_label == "product"
    assert resolved.reporting.slot_presence is False
    assert resolved.reporting.misplaced_min_confidence == 0.9
    assert defaults == before_defaults
    assert config == before_config
