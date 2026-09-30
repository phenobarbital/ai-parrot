"""LayoutProfile validation, merge and compatibility alias (FEAT-612, Module 1)."""

import copy

import pytest

from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import IdentifyStrategy
from parrot_pipelines.planogram.layout import (
    LayoutProfile,
    ZoneSelector,
    resolve_layout_profile,
    validate_zone_selectors,
)
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.perception.slots import AnchorRule


@pytest.fixture
def defaults() -> LayoutProfile:
    """Return generic synthetic defaults without retailer data."""
    return LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], anchor_rule=AnchorRule.TAG_BELOW_PRODUCT)


def test_empty_config_returns_equal_copy(defaults: LayoutProfile) -> None:
    """An empty configuration returns an equal, distinct profile."""
    resolved = resolve_layout_profile(defaults, {}, config_name="cfg")
    assert resolved == defaults and resolved is not defaults


def test_overrides_reach_fields_and_lists_replace(defaults: LayoutProfile) -> None:
    """Overrides reach scalar fields and replace lists atomically."""
    resolved = resolve_layout_profile(
        defaults,
        {
            "layout_profile": {
                "identify_strategy": "slots",
                "min_row_items": 4,
                "ocr_targets": ["tag"],
                "fill_gaps": True,
            }
        },
        config_name="cfg",
    )
    assert resolved.identify_strategy is IdentifyStrategy.SLOTS
    assert resolved.min_row_items == 4
    assert resolved.ocr_targets == ["tag"]
    assert resolved.fill_gaps is True


def test_nested_references_merge_recursively(defaults: LayoutProfile) -> None:
    """Nested reference-policy values retain unspecified defaults."""
    resolved = resolve_layout_profile(
        defaults,
        {"layout_profile": {"references": {"max_per_call": 2}}},
        config_name="cfg",
    )
    assert resolved.references.max_per_call == 2
    assert resolved.references.enabled is True and resolved.references.selection == "all"


def test_no_mutation_of_config_or_defaults(defaults: LayoutProfile) -> None:
    """Resolving retains caller configuration and source defaults exactly."""
    config = {"layout_profile": {"references": {"max_per_call": 2}, "ocr_targets": ["slot"]}}
    before_config, before_defaults = copy.deepcopy(config), defaults.model_copy(deep=True)
    resolve_layout_profile(defaults, config, config_name="cfg")
    assert config == before_config and defaults == before_defaults


@pytest.mark.parametrize(
    ("override", "path"),
    [
        ({"bogus": 1}, "layout_profile.bogus"),
        ({"shape_profiles": [{**PRICE_TAG_PROFILE.model_dump(), "min_widht": 0.1}]}, "shape_profiles.0.min_widht"),
        ({"shape_profiles": [{**PRICE_TAG_PROFILE.model_dump(), "kind": "robot"}]}, "shape_profiles.0.kind"),
        ({"identify_strategy": "tiles"}, "identify_strategy"),
        ({"ocr_batch_size": 0}, "ocr_batch_size"),
        ({"references": {"max_per_call": 0}}, "references.max_per_call"),
        ({"zone_selectors": [{"zone_id": "z", "region": [0.8, 0.1, 0.2, 0.9]}]}, "region"),
        ({"descriptor_fields": ["family"], "required_descriptor_fields": ["xl"]}, "required_descriptor_fields"),
        ({"perception_mode": "cv", "shape_profiles": []}, "shape_profiles"),
    ],
)
def test_invalid_fields_name_config_and_path(defaults: LayoutProfile, override: dict, path: str) -> None:
    """Invalid overrides name both their configuration and field path."""
    with pytest.raises(ValueError) as info:
        resolve_layout_profile(defaults, {"layout_profile": override}, config_name="store-cfg")
    assert "store-cfg" in str(info.value) and path in str(info.value)


def test_duplicate_selector_and_profile_names_rejected(defaults: LayoutProfile) -> None:
    """Duplicate selector ids and profile names are invalid."""
    with pytest.raises(ValueError, match="zone_selectors"):
        resolve_layout_profile(
            defaults,
            {"layout_profile": {"zone_selectors": [{"zone_id": "z1"}, {"zone_id": "z1"}]}},
            config_name="cfg",
        )
    with pytest.raises(ValueError, match="shape_profiles"):
        resolve_layout_profile(
            defaults,
            {"layout_profile": {"shape_profiles": [PRICE_TAG_PROFILE.model_dump(), PRICE_TAG_PROFILE.model_dump()]}},
            config_name="cfg",
        )


def test_top_level_perception_mode_alias(defaults: LayoutProfile) -> None:
    """The legacy mode alias is accepted only when it agrees with the profile."""
    assert (
        resolve_layout_profile(defaults, {"perception_mode": "llm_detector"}, config_name="c").perception_mode
        == "llm_detector"
    )
    assert (
        resolve_layout_profile(
            defaults,
            {"perception_mode": "cv", "layout_profile": {"perception_mode": "cv"}},
            config_name="c",
        ).perception_mode
        == "cv"
    )
    with pytest.raises(ValueError, match="perception_mode"):
        resolve_layout_profile(
            defaults,
            {"perception_mode": "cv", "layout_profile": {"perception_mode": "llm_detector"}},
            config_name="c",
        )


def test_explicit_null_only_for_optional(defaults: LayoutProfile) -> None:
    """Null remains valid only for optional selector fields."""
    ok = resolve_layout_profile(
        defaults,
        {"layout_profile": {"zone_selectors": [{"zone_id": "z", "kind": None}]}},
        config_name="c",
    )
    assert ok.zone_selectors[0].kind is None
    with pytest.raises(ValueError, match="work_width"):
        resolve_layout_profile(defaults, {"layout_profile": {"work_width": None}}, config_name="c")


def test_validate_zone_selectors_against_definition(defaults: LayoutProfile) -> None:
    """Selectors must resolve every repeated zone kind in the loaded definition."""
    definition = load_slots_definition(
        {
            "shelves": [
                {
                    "shelf_id": "s1",
                    "shelf_number": 1,
                    "facings": [
                        {
                            "facing_id": "f1",
                            "shelf_id": "s1",
                            "slot": 1,
                            "product": "P-1",
                            "descriptors": {"display_name": "P 1"},
                        }
                    ],
                }
            ],
            "zones": [
                {"zone_id": "za", "kind": "poster", "shelf_id": "s1"},
                {"zone_id": "zb", "kind": "poster", "shelf_id": "s1"},
            ],
        }
    )
    with pytest.raises(ValueError, match="za.*zb"):
        validate_zone_selectors(defaults, definition, config_name="cfg")
    dangling = defaults.model_copy(update={"zone_selectors": [ZoneSelector(zone_id="nowhere")]})
    with pytest.raises(ValueError, match="zone_selectors.0.zone_id"):
        validate_zone_selectors(dangling, definition, config_name="cfg")
    configured = defaults.model_copy(
        update={
            "zone_selectors": [
                ZoneSelector(zone_id="za", ordinal=0),
                ZoneSelector(zone_id="zb", ordinal=1),
            ]
        }
    )
    assert validate_zone_selectors(configured, definition, config_name="cfg") is None
