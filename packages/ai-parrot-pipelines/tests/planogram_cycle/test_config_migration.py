"""Offline tests for the config migration utility."""

import copy
import json

import pytest

from parrot_pipelines.planogram.comparison.definition import load_slots_definition, validate_bindings
from parrot_pipelines.planogram.migration import (
    _PREFLIGHT_SQL,
    ConversionReport,
    PreflightRow,
    _main,
    check_row,
    convert_config,
)


@pytest.fixture
def legacy_config() -> dict:
    """header shelf (backlit promotional_graphic + illumination_required + endcap text reqs) and a
    middle shelf: product A quantity_range [2, 2], product B quantity_range [1, 3], one fact_tag."""
    return {
        "brand": "Acme",
        "category": "Printers",
        "aisle": {"name": "Tech"},
        "advertisement_endcap": {
            "enabled": True,
            "position": "header",
            "text_requirements": [{"required_text": "Hello Savings", "mandatory": True}],
        },
        "shelves": [
            {
                "level": "header",
                "compliance_threshold": 0.9,
                "products": [
                    {
                        "name": "Acme Backlit",
                        "product_type": "promotional_graphic",
                        "illumination_required": "on",
                        "illumination_penalty": 0.4,
                        "visual_features": ["illuminated logo"],
                    }
                ],
            },
            {
                "level": "middle",
                "product_weight": 0.7,
                "products": [
                    {"name": "ES-400", "product_type": "product", "quantity_range": [2, 2]},
                    {"name": "RR-60", "product_type": "product", "quantity_range": [1, 3]},
                    {"name": "Tag", "product_type": "fact_tag"},
                ],
            },
        ],
    }


def _convert(config) -> ConversionReport:
    return convert_config(config, planogram_type="product_on_shelves")


def test_convert_does_not_mutate_input(legacy_config):
    before = copy.deepcopy(legacy_config)
    _convert(legacy_config)
    assert legacy_config == before


def test_fixed_quantity_seeds_facings_and_range_is_unresolved(legacy_config):
    report = _convert(legacy_config)
    middle = report.candidate["shelves"][1]
    assert [(f["facing_id"], f["slot"], f["product"]) for f in middle["facings"]] == [
        ("shelf-2:1", 1, "ES-400"),
        ("shelf-2:2", 2, "ES-400"),
        ("shelf-2:3", 3, "RR-60"),
    ]
    assert len(report.unresolved) == 1 and "RR-60" in report.unresolved[0]
    assert any("slot order taken from list order" in w for w in report.warnings)
    assert all(f["descriptors"] == {} for f in middle["facings"])  # never invents descriptors / prices


def test_promotional_product_becomes_zone_with_zone_present_binding(legacy_config):
    report = _convert(legacy_config)
    header = report.candidate["shelves"][0]
    assert header["facings"] == []
    assert report.candidate["zones"] == [
        {"zone_id": "zone-header-1", "kind": "backlit", "shelf_id": "shelf-1", "required": True}
    ]
    zone_present = next(b for b in report.bindings if b["kind"] == "zone_present")
    assert zone_present["target_id"] == "zone-header-1" and zone_present["rule_id"] == "zone_present:zone-header-1"


def test_nested_illumination_and_text_become_bindings(legacy_config):
    report = _convert(legacy_config)
    by_id = {b["rule_id"]: b for b in report.bindings}
    assert by_id["illumination:zone-header-1"]["params"] == {"required": "on", "penalty": 0.4, "name": "Acme Backlit"}
    assert by_id["visual_features:zone-header-1"]["params"] == {"expected": ["illuminated logo"]}
    assert by_id["text_requirements:zone-header-1"]["params"]["requirements"] == [
        {"required_text": "Hello Savings", "mandatory": True}
    ]
    ids = {f["facing_id"] for s in report.candidate["shelves"] for f in s["facings"]}
    ids |= {z["zone_id"] for z in report.candidate["zones"]} | {s["shelf_id"] for s in report.candidate["shelves"]}
    assert all(b["target_id"] in ids for b in report.bindings)


def test_thresholds_and_weights_stay_in_planogram_config(legacy_config):
    report = _convert(legacy_config)
    candidate_text = json.dumps(report.candidate)
    assert "compliance_threshold" not in candidate_text and "product_weight" not in candidate_text
    assert "advertisement_endcap" not in candidate_text


def test_fact_tags_are_not_facings(legacy_config):
    report = _convert(legacy_config)
    products = [f["product"] for s in report.candidate["shelves"] for f in s["facings"]]
    assert "Tag" not in products


def test_candidate_validates_once_described(legacy_config):
    """The only validation warning is the missing descriptors; once described it loads and binds."""
    report = _convert(legacy_config)
    assert any("zero described positions" in w for w in report.warnings)
    for shelf in report.candidate["shelves"]:
        for facing in shelf["facings"]:
            facing["descriptors"] = {"display_name": facing["product"]}
    definition = load_slots_definition(report.candidate)
    assert len(validate_bindings(definition, {"rule_bindings": report.bindings})) == len(report.bindings)


def test_non_pos_type_rejected():
    with pytest.raises(ValueError):
        convert_config({}, planogram_type="graphic_panel_display")


def test_check_row_legacy_type_is_ok():
    assert check_row({"config_name": "x", "planogram_type": "product_counter"}).ok


def test_check_row_flags_missing_and_invalid_definition(legacy_config):
    missing = check_row({"config_name": "a", "planogram_type": "product_on_shelves"})
    assert isinstance(missing, PreflightRow) and not missing.ok and "missing" in missing.problems[0]
    not_json = check_row({"config_name": "b", "planogram_type": "ink_wall", "slots_definition": "{oops"})
    assert not not_json.ok and "not valid JSON" in not_json.problems[0]
    invalid = check_row({"config_name": "c", "planogram_type": "ink_wall", "slots_definition": {"shelves": []}})
    assert not invalid.ok and "invalid slots_definition" in invalid.problems[0]

    report = _convert(legacy_config)
    for shelf in report.candidate["shelves"]:
        for facing in shelf["facings"]:
            facing["descriptors"] = {"display_name": facing["product"]}
    dangling = {"rule_bindings": [{"rule_id": "r", "kind": "zone_present", "target_id": "nowhere"}]}
    bad_bindings = check_row(
        {
            "config_name": "d",
            "slots_definition": json.dumps(report.candidate),
            "planogram_config": json.dumps(dangling),
        }
    )
    assert not bad_bindings.ok and "invalid rule_bindings" in bad_bindings.problems[0]
    good = check_row(
        {
            "config_name": "e",
            "slots_definition": report.candidate,
            "planogram_config": {**legacy_config, "rule_bindings": report.bindings},
        }
    )
    assert good.ok and good.problems == []


def test_preflight_sql_is_select_only():
    assert _PREFLIGHT_SQL.lstrip().upper().startswith("SELECT")
    assert not any(w in _PREFLIGHT_SQL.upper() for w in ("UPDATE", "INSERT", "DELETE", "ALTER"))


def test_cli_convert_exit_code_two_when_unresolved(tmp_path, legacy_config):
    source = tmp_path / "config.json"
    source.write_text(json.dumps({"planogram_config": legacy_config, "planogram_type": "product_on_shelves"}))
    out = tmp_path / "candidate.json"
    assert _main(["convert", str(source), "--out", str(out)]) == 2
    written = json.loads(out.read_text())
    assert written["unresolved"] and written["candidate"]["shelves"]
    assert json.loads(source.read_text())["planogram_config"] == legacy_config  # input untouched


def test_cli_convert_refuses_to_overwrite_input(tmp_path, legacy_config):
    source = tmp_path / "config.json"
    source.write_text(json.dumps(legacy_config))
    assert _main(["convert", str(source), "--out", str(source)]) == 1


def test_cli_convert_exit_zero_when_fully_resolved(tmp_path, legacy_config):
    legacy_config["shelves"][1]["products"][1]["quantity_range"] = [1, 1]
    source = tmp_path / "config.json"
    source.write_text(json.dumps(legacy_config))
    assert _main(["convert", str(source), "--out", str(tmp_path / "c.json")]) == 0
