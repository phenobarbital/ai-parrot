"""Offline tests for the config migration utility."""

import copy
import json
import sys
import types

import pytest

from parrot_pipelines.planogram.comparison.definition import load_slots_definition, validate_bindings
from parrot_pipelines.planogram.migration import (
    MIGRATED_TYPES,
    _PREFLIGHT_SQL,
    ConversionReport,
    PreflightRow,
    _main,
    check_row,
    convert_config,
    preflight,
)
from parrot_pipelines.planogram.plan import PlanogramCompliance


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


@pytest.fixture
def ink_page1() -> dict:
    """Minimal page-1 ink layout with no source descriptors."""
    return {
        "planogram": {"planogram": "Ink"},
        "shelves": [
            {"shelf_number": 1, "products": {"p1": {"position": 1, "slot": 1, "product": "INK-1"}}}
        ],
    }


@pytest.fixture
def promo_config() -> dict:
    """Promotional zones, including one optional zone."""
    return {
        "shelves": [
            {
                "level": "header",
                "products": [
                    {"name": "Backlit", "product_type": "backlit_panel"},
                    {"name": "Poster", "product_type": "lower_poster", "mandatory": False},
                ],
            }
        ]
    }


@pytest.fixture
def panel_config() -> dict:
    """Two same-kind graphics require explicit selector review."""
    return {
        "shelves": [
            {"level": "top", "products": [{"name": "Graphic A", "product_type": "graphic"}]},
            {"level": "bottom", "products": [{"name": "Graphic B", "product_type": "graphic"}]},
        ]
    }


@pytest.fixture
def counter_config() -> dict:
    """Product plus background and information-label zones."""
    return {
        "shelves": [
            {
                "products": [
                    {
                        "name": "P-100",
                        "product_type": "product",
                        "quantity_range": [1, 1],
                        "descriptors": {"display_name": "Product 100"},
                    },
                    {"name": "Backdrop", "product_type": "promotional_background"},
                    {"name": "Details", "product_type": "information_label"},
                ]
            }
        ],
        "scoring_weights": {"product": 0.5},
    }


@pytest.fixture
def backlit_config() -> dict:
    """Backlit product shelf with a source section requiring spatial review."""
    return {
        "shelves": [
            {
                "level": "middle",
                "sections": [{"id": "section-1"}],
                "products": [
                    {
                        "name": "P-1",
                        "product_type": "product",
                        "quantity_range": [1, 1],
                        "descriptors": {"display_name": "Product 1"},
                    }
                ],
            }
        ]
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
    assert any("RR-60" in item for item in report.unresolved)
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


def test_candidate_validation_failure_is_unresolved(legacy_config):
    """Missing descriptors are a blocking unresolved item, never merely a warning."""
    report = _convert(legacy_config)
    assert any("zero described positions" in item for item in report.unresolved)
    for shelf in report.candidate["shelves"]:
        for facing in shelf["facings"]:
            facing["descriptors"] = {"display_name": facing["product"]}
    definition = load_slots_definition(report.candidate)
    assert len(validate_bindings(definition, {"rule_bindings": report.bindings})) == len(report.bindings)


def test_unknown_type_rejected():
    with pytest.raises(ValueError):
        convert_config({}, planogram_type="tv_wall")


def test_check_row_counter_without_definition_is_not_ready():
    assert not check_row({"config_name": "x", "planogram_type": "product_counter"}).ok


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
    for shelf in legacy_config["shelves"]:
        for product in shelf["products"]:
            if product.get("product_type") == "product":
                product["descriptors"] = {"display_name": product["name"]}
    source = tmp_path / "config.json"
    source.write_text(json.dumps(legacy_config))
    assert _main(["convert", str(source), "--out", str(tmp_path / "c.json")]) == 0


def test_migrated_types_match_registry():
    assert MIGRATED_TYPES == set(PlanogramCompliance._PLANOGRAM_TYPES)


@pytest.mark.parametrize(
    ("ptype", "fixture_name"),
    [
        ("product_on_shelves", "legacy_config"),
        ("ink_wall", "ink_page1"),
        ("endcap_backlit_multitier", "backlit_config"),
        ("endcap_no_shelves_promotional", "promo_config"),
        ("graphic_panel_display", "panel_config"),
        ("product_counter", "counter_config"),
    ],
)
def test_every_type_converts_without_mutation(ptype, fixture_name, request):
    config = request.getfixturevalue(fixture_name)
    before = copy.deepcopy(config)
    report = convert_config(config, planogram_type=ptype)
    assert config == before
    assert report.candidate["shelves"] or report.candidate["zones"]


def test_conversion_is_deterministic(promo_config):
    assert convert_config(promo_config, planogram_type="endcap_no_shelves_promotional").model_dump() == convert_config(
        promo_config, planogram_type="endcap_no_shelves_promotional"
    ).model_dump()


def test_zone_only_candidate_has_zones_and_mandatory_presence(promo_config):
    report = convert_config(promo_config, planogram_type="endcap_no_shelves_promotional")
    assert report.candidate["shelves"] == [] and report.candidate["zones"]
    assert any(binding["kind"] == "zone_present" and binding["mandatory"] for binding in report.bindings)


def test_optional_zone_stays_optional(promo_config):
    report = convert_config(promo_config, planogram_type="endcap_no_shelves_promotional")
    optional = next(zone for zone in report.candidate["zones"] if zone["required"] is False)
    binding = next(binding for binding in report.bindings if binding["target_id"] == optional["zone_id"])
    assert binding["mandatory"] is False


def test_repeated_same_kind_zones_need_selector(panel_config):
    report = convert_config(panel_config, planogram_type="graphic_panel_display")
    assert any("selector" in item for item in report.unresolved)


def test_backlit_sections_are_unresolved(backlit_config):
    report = convert_config(backlit_config, planogram_type="endcap_backlit_multitier")
    assert any("section-1" in item for item in report.unresolved)


def test_counter_products_become_facings_and_labels_zones(counter_config):
    report = convert_config(counter_config, planogram_type="product_counter")
    assert report.candidate["shelves"][0]["facings"][0]["product"] == "P-100"
    assert any(zone["kind"] == "information_label" for zone in report.candidate["zones"])


def test_counter_scoring_weights_are_unresolved(counter_config):
    report = convert_config(counter_config, planogram_type="product_counter")
    assert any("scoring_weights" in item for item in report.unresolved)


def test_ink_page1_never_invents_descriptors(ink_page1):
    report = convert_config(ink_page1, planogram_type="ink_wall")
    facing = report.candidate["shelves"][0]["facings"][0]
    assert facing["facing_id"] == "p001_f1" and facing["descriptors"] == {}
    assert any("descriptors" in item for item in report.unresolved)


def test_top_level_perception_mode_moves_to_layout_profile(promo_config):
    promo_config["perception_mode"] = "cv"
    report = convert_config(promo_config, planogram_type="endcap_no_shelves_promotional")
    assert report.layout_profile["perception_mode"] == "cv"


def test_check_row_unknown_type_not_ready():
    verdict = check_row({"config_name": "x", "planogram_type": "tv_wall"})
    assert not verdict.ok and "tv_wall" in verdict.problems[0]


def test_check_row_invalid_layout_not_ready():
    verdict = check_row(
        {
            "config_name": "x",
            "planogram_type": "product_on_shelves",
            "slots_definition": {"shelves": [], "zones": [{"zone_id": "z", "kind": "header"}]},
            "planogram_config": {"layout_profile": {"no_such_key": 1}, "rule_bindings": []},
        }
    )
    assert not verdict.ok and any("invalid layout_profile" in problem for problem in verdict.problems)


@pytest.mark.asyncio
async def test_preflight_issues_single_select(monkeypatch):
    calls = []

    class Connection:
        async def fetch_all(self, sql):
            calls.append(sql)
            return []

    class Context:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class AsyncDB:
        def __init__(self, *_args, **_kwargs):
            pass

        async def connection(self):
            return Context()

    monkeypatch.setitem(sys.modules, "asyncdb", types.SimpleNamespace(AsyncDB=AsyncDB))
    assert await preflight("postgresql://example") == []
    assert calls == [_PREFLIGHT_SQL]
