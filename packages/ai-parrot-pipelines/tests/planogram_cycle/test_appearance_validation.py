"""FEAT-683: appearance bindings are validated at preflight."""

import pytest

from parrot_pipelines.planogram.comparison.definition import (
    SlotsDefinitionError,
    load_slots_definition,
    validate_bindings,
)
from parrot_pipelines.planogram.migration import check_row

SLOTS = {
    "version": "1",
    "meta": {"planogram_type": "endcap_no_shelves_promotional"},
    "shelves": [],
    "zones": [{"zone_id": "zone-base-1", "kind": "graphic", "shelf_id": None, "required": True}],
}


def _config(params):
    return {
        "rule_bindings": [
            {"rule_id": "zone_present:zone-base-1", "kind": "zone_present", "target_id": "zone-base-1"},
            {"rule_id": "appearance:zone-base-1", "kind": "appearance", "target_id": "zone-base-1", "params": params},
        ]
    }


@pytest.mark.parametrize(
    "params", [{"background_color": "white"}, {"border_color": ["blue", "none"], "finish": ["matte"]}]
)
def test_valid_appearance_binding(params):
    bindings = validate_bindings(load_slots_definition(SLOTS), _config(params))
    assert bindings[1].kind == "appearance"


@pytest.mark.parametrize(
    "params, message",
    [
        ({}, "at least one attribute"),
        ({"colour": ["white"]}, "colour"),
        ({"background_color": ["off-white"]}, "off-white"),
        ({"background_color": ["unknown"]}, "unknown"),
        ({"base_surface_color": "not_visible"}, "not_visible"),
        ({"background_color": []}, "background_color"),
    ],
)
def test_invalid_appearance_binding(params, message):
    with pytest.raises(SlotsDefinitionError, match=message):
        validate_bindings(load_slots_definition(SLOTS), _config(params))


def test_appearance_cannot_target_a_facing():
    slots = {
        "version": "1",
        "shelves": [
            {
                "shelf_id": "shelf-1",
                "shelf_number": 1,
                "facings": [
                    {
                        "facing_id": "facing-1",
                        "shelf_id": "shelf-1",
                        "slot": 1,
                        "product": "SKU-1",
                        "descriptors": {"display_name": "Sku One"},
                    }
                ],
            }
        ],
        "zones": [],
    }
    config = {
        "rule_bindings": [
            {
                "rule_id": "appearance:facing-1",
                "kind": "appearance",
                "target_id": "facing-1",
                "params": {"background_color": "white"},
            }
        ]
    }

    with pytest.raises(SlotsDefinitionError, match="must target a zone or shelf"):
        validate_bindings(load_slots_definition(slots), config)


def test_check_row_reports_invalid_appearance():
    valid = check_row(
        {
            "config_name": "t",
            "planogram_type": "endcap_no_shelves_promotional",
            "slots_definition": SLOTS,
            "planogram_config": _config({"background_color": "white"}),
        }
    )
    invalid = check_row(
        {
            "config_name": "t",
            "planogram_type": "endcap_no_shelves_promotional",
            "slots_definition": SLOTS,
            "planogram_config": _config({"background_color": ["off-white"]}),
        }
    )

    assert valid.ok
    assert not invalid.ok
    assert any("invalid rule_bindings" in problem for problem in invalid.problems)
