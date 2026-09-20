"""Offline tests for the slots definition loader, coverage and rule bindings (FEAT-574, Module 9)."""

import copy
import json

import pytest

from parrot_pipelines.planogram.comparison import (
    RuleBinding,
    SlotsDefinition,
    SlotsDefinitionError,
    definition_coverage,
    load_slots_definition,
    validate_bindings,
)


def _facing(facing_id: str, shelf_id: str, slot: int, product: str, display_name=None, **extra) -> dict:
    """A native facing dict."""
    descriptors = {"display_name": display_name} if display_name else {}
    return {
        "facing_id": facing_id,
        "shelf_id": shelf_id,
        "slot": slot,
        "product": product,
        "descriptors": descriptors,
        **extra,
    }


@pytest.fixture
def native_definition() -> dict:
    """2 shelves x 3 facings (2 described, 1 undescribed per shelf) + one required header zone on its own shelf."""
    return {
        "version": "1",
        "meta": {"planogram": "synthetic"},
        "shelves": [
            {
                "shelf_id": "shelf_2",
                "shelf_number": 2,
                "level": "bottom",
                "facings": [
                    _facing("f21", "shelf_2", 3, "SKU-UNDESC-2"),
                    _facing("f22", "shelf_2", 1, "SKU-C", "Scanner C"),
                    _facing("f23", "shelf_2", 2, "SKU-D", "Scanner D"),
                ],
            },
            {
                "shelf_id": "shelf_1",
                "shelf_number": 1,
                "level": "top",
                "facings": [
                    _facing("f11", "shelf_1", 1, "SKU-A", "Scanner A"),
                    _facing("f12", "shelf_1", 2, "SKU-B", "Scanner B"),
                    _facing("f13", "shelf_1", 3, "SKU-UNDESC-1"),
                ],
            },
            {"shelf_id": "shelf_header", "shelf_number": 0, "level": "header", "facings": []},
        ],
        "zones": [{"zone_id": "zone_header", "kind": "header", "shelf_id": "shelf_header"}],
    }


@pytest.fixture
def page1_definition() -> dict:
    """Synthetic file in the planogram_page1.json layout: 1 shelf, 3 positions, one with facings=2."""

    def position(pos: int, slot: int, product: str, facings: int = 1, display_name=None) -> dict:
        return {
            "position": pos,
            "segment": "A",
            "segment_number": 1,
            "slot": slot,
            "segment_slot": slot,
            "product": product,
            "brand": "TestBrand",
            "shelf": 1,
            "facings": facings,
            "confidence": "high",
            "read_method": "manual",
            "notes": None,
            "display_name": display_name,
            "family": None,
            "xl": None,
            "colors": None,
            "pack": None,
            "identifiers": None,
            "aliases": None,
            "price": None,
        }

    return {
        "planogram": {"planogram": "Synthetic", "fixture": "F1"},
        "shelves": [
            {
                "shelf": 1,
                "shelf_number": 1,
                "product_count": 3,
                "facing_count": 4,
                "products": {
                    "pos 1:1": position(1, 1, "ES-400", display_name="ES-400 scanner"),
                    "pos 1:2": position(2, 2, "RR-60", facings=2, display_name="RR-60 scanner"),
                    "pos 1:3": position(3, 3, "DS-770"),
                },
            }
        ],
    }


def test_loads_dict_and_path_equally(native_definition, tmp_path):
    """A dict and a JSON file with the same content give equal definitions, ordered."""
    path = tmp_path / "definition.json"
    path.write_text(json.dumps(native_definition))
    from_dict = load_slots_definition(copy.deepcopy(native_definition))
    assert isinstance(from_dict, SlotsDefinition)
    assert from_dict == load_slots_definition(path) == load_slots_definition(str(path))
    assert [s.shelf_id for s in from_dict.shelves] == ["shelf_header", "shelf_1", "shelf_2"]
    assert [f.facing_id for f in from_dict.shelves[2].facings] == ["f22", "f23", "f21"]


def test_unreadable_source_is_rejected(tmp_path):
    """Missing file and non-JSON content raise SlotsDefinitionError."""
    with pytest.raises(SlotsDefinitionError):
        load_slots_definition(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SlotsDefinitionError):
        load_slots_definition(bad)


def test_slots_definition_accepts_page1_layout(page1_definition):
    """Stable ids p<position:03d>_f<index> / shelf_<n>; facings=2 expands to two facings."""
    definition = load_slots_definition(page1_definition)
    shelf = definition.shelves[0]
    assert shelf.shelf_id == "shelf_1"
    assert [f.facing_id for f in shelf.facings] == ["p001_f1", "p002_f1", "p002_f2", "p003_f1"]
    rr = [f for f in shelf.facings if f.product == "RR-60"]
    assert [(f.facings, f.facing_index, f.slot) for f in rr] == [(2, 1, 2), (2, 2, 2)]
    assert definition.meta == {"planogram": "Synthetic", "fixture": "F1"}
    assert shelf.facings[0].descriptors.display_name == "ES-400 scanner"


def _dup_facing(d):
    d["shelves"][1]["facings"][1]["facing_id"] = "f11"


def _dup_zone(d):
    d["zones"].append({"zone_id": "zone_header", "kind": "backlit", "shelf_id": "shelf_header"})


def _dup_shelf(d):
    d["shelves"][0]["shelf_id"] = "shelf_1"
    for f in d["shelves"][0]["facings"]:
        f["shelf_id"] = "shelf_1"


def _bad_slots(d):
    d["shelves"][1]["facings"][2]["slot"] = 5


def _conflict(d):
    d["shelves"][0]["facings"][1]["product"] = "SKU-A"  # "Scanner C" vs "Scanner A" for SKU-A


def _zero_described(d):
    for shelf in d["shelves"]:
        for f in shelf["facings"]:
            f["descriptors"] = {}


def _empty_shelf(d):
    d["zones"] = []


@pytest.mark.parametrize(
    "mutate, message",
    [
        (_dup_facing, "duplicate facing_id"),
        (_dup_zone, "duplicate zone_id"),
        (_dup_shelf, "duplicate shelf_id"),
        (_bad_slots, "1..n"),
        (_conflict, "conflicting descriptors"),
        (_zero_described, "zero described"),
        (_empty_shelf, "neither facings nor zones"),
    ],
)
def test_slots_definition_validation_errors(native_definition, mutate, message):
    """Every structural failure mode raises SlotsDefinitionError naming the problem."""
    mutate(native_definition)
    with pytest.raises(SlotsDefinitionError, match=message):
        load_slots_definition(native_definition)


def test_schema_error_is_wrapped(native_definition):
    """A Pydantic schema error surfaces as SlotsDefinitionError."""
    native_definition["shelves"][0]["facings"][0]["slot"] = 0
    with pytest.raises(SlotsDefinitionError):
        load_slots_definition(native_definition)


def test_undescribed_facings_are_legal_and_listed(native_definition):
    """Undescribed facings load; coverage lists them without raising."""
    definition = load_slots_definition(native_definition)
    fraction, undescribed = definition_coverage(definition)
    assert fraction == pytest.approx(4 / 6)
    assert undescribed == ["f13", "f21"]


def test_described_elsewhere_counts_for_same_product(native_definition):
    """An undescribed facing of a product described elsewhere counts as covered; identifiers suffice too."""
    native_definition["shelves"][0]["facings"][0]["product"] = "SKU-A"  # f21 now shares SKU-A (described in f11)
    native_definition["shelves"][1]["facings"][2]["descriptors"] = {"identifiers": ["UPC 123"]}  # f13
    fraction, undescribed = definition_coverage(load_slots_definition(native_definition))
    assert fraction == pytest.approx(1.0)
    assert undescribed == []


def _config(*bindings) -> dict:
    return {"rule_bindings": list(bindings)}


def _binding(rule_id: str, target_id: str, kind: str = "zone_present") -> dict:
    return {"rule_id": rule_id, "kind": kind, "target_id": target_id}


def test_rule_bindings_reject_dangling_and_ambiguous(native_definition):
    """Dangling, ambiguous and duplicate bindings are rejected; valid ones are returned."""
    definition = load_slots_definition(native_definition)
    ok = validate_bindings(definition, _config(_binding("r1", "zone_header"), _binding("r2", "f11", "illumination")))
    assert [b.rule_id for b in ok] == ["r1", "r2"] and all(isinstance(b, RuleBinding) for b in ok)

    with pytest.raises(SlotsDefinitionError, match="dangling"):
        validate_bindings(definition, _config(_binding("r1", "zone_header"), _binding("r2", "nowhere")))
    with pytest.raises(SlotsDefinitionError, match="duplicate rule_id"):
        validate_bindings(definition, _config(_binding("r1", "zone_header"), _binding("r1", "f11")))
    with pytest.raises(SlotsDefinitionError, match="malformed"):
        validate_bindings(definition, _config({"rule_id": "r1", "kind": "nope", "target_id": "f11"}))

    native_definition["zones"].append({"zone_id": "f11", "kind": "poster", "shelf_id": "shelf_1"})
    ambiguous = load_slots_definition(native_definition)
    with pytest.raises(SlotsDefinitionError, match="ambiguous"):
        validate_bindings(ambiguous, _config(_binding("r1", "zone_header"), _binding("r2", "f11")))


def test_zone_only_shelf_without_binding_is_rejected(native_definition):
    """A shelf without facings needs a rule bound to it (or to one of its zones)."""
    definition = load_slots_definition(native_definition)
    with pytest.raises(SlotsDefinitionError, match="zone-only shelf"):
        validate_bindings(definition, _config(_binding("r2", "f11", "illumination")))
    assert validate_bindings(definition, _config(_binding("r1", "shelf_header")))


def test_missing_rule_bindings_key_returns_empty(native_definition):
    """No rule_bindings key ⇒ [] (the loader-level zone check is the only guard then)."""
    definition = load_slots_definition(native_definition)
    native_definition_without_zone_shelf = copy.deepcopy(native_definition)
    del native_definition_without_zone_shelf["shelves"][2]
    del native_definition_without_zone_shelf["zones"][0]
    plain = load_slots_definition(native_definition_without_zone_shelf)
    assert validate_bindings(plain, {}) == []
    assert validate_bindings(plain, {"brand": "X"}) == []
    with pytest.raises(SlotsDefinitionError, match="zone-only shelf"):
        validate_bindings(definition, {})
