"""Unit tests for plancheck.reference (FEAT-565, spec §4 — Module 2). Synthetic data only."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from plancheck.models import Catalog, CatalogItem, SlotReading
from plancheck.reference import (
    DESCRIPTOR_FIELDS,
    init_descriptor_fields,
    load_descriptors,
    load_planogram,
    load_prices,
    normalize_brand,
    resolve_identity,
)


def _write(tmp_path: Path, name: str, payload: object) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _reading(**kwargs: object) -> SlotReading:
    base = {"slot_id": "img_r01_s01", "occupancy": "occupied", "visibility": "full"}
    return SlotReading(**{**base, **kwargs})


def test_load_planogram_expands_facings(tmp_path, mini_planogram_data):
    data = copy.deepcopy(mini_planogram_data)
    # Set CLOSEOUT facings to 3
    for shelf in data["shelves"]:
        for product in shelf["products"].values():
            if product["product"] == "CLOSEOUT":
                product["facings"] = 3
    path = _write(tmp_path, "planogram.json", data)
    ref = load_planogram(path)
    assert len(ref.facings) == 20
    closeout_facings = [f for f in ref.facings if f.sku == "CLOSEOUT"]
    assert len(closeout_facings) == 3
    assert all(not f.identity_required for f in closeout_facings)
    assert {f.facing_id for f in closeout_facings} == {"p018_f1", "p018_f2", "p018_f3"}


def test_load_planogram_orders_by_slot_not_position(tmp_path, mini_planogram_data):
    data = copy.deepcopy(mini_planogram_data)
    # Reverse dict order for shelf 1
    shelf1 = data["shelves"][0]
    products = list(shelf1["products"].values())
    products.reverse()
    shelf1["products"] = {f"pos 1:{i+1}": p for i, p in enumerate(products)}
    path = _write(tmp_path, "planogram.json", data)
    ref = load_planogram(path)
    shelf1_facings = ref.shelf(1)
    assert [f.slot for f in shelf1_facings] == [1, 2, 3, 4, 5, 6]
    assert [f.position for f in shelf1_facings] == [1, 2, 5, 3, 4, 6]
    # Shelf 2 facings should have reference_read_method == "inferred"
    shelf2_facings = ref.shelf(2)
    assert all(f.reference_read_method == "inferred" for f in shelf2_facings)


def test_load_planogram_rejects_noncontiguous_slots(tmp_path, mini_planogram_data):
    data = copy.deepcopy(mini_planogram_data)
    # Delete slot 3 of shelf 2
    shelf2 = data["shelves"][1]
    del shelf2["products"]["pos 2:3"]
    path = _write(tmp_path, "planogram.json", data)
    with pytest.raises(ValueError, match="1..n"):
        load_planogram(path)


def test_load_descriptors_builds_catalog_and_reports_undescribed(tmp_path, mini_planogram_data, mini_catalog):
    data = copy.deepcopy(mini_planogram_data)
    data["shelves"][0]["products"]["pos 1:1"]["display_name"] = None  # AC-11
    data["shelves"][2]["products"]["pos 3:5"]["display_name"] = "  "  # BO-35 (blank = undescribed)
    data["shelves"][0]["products"]["pos 1:2"]["price"] = "29.99"  # AC-12
    data["shelves"][0]["products"]["pos 1:2"]["identifiers"] = ["AC12", "AC-12"]
    path = _write(tmp_path, "planogram.json", data)
    catalog, undescribed, prices = load_descriptors(path, load_planogram(path))
    assert undescribed == ["AC-11", "BO-35"]
    assert {i.sku for i in catalog.items} == {i.sku for i in mini_catalog.items} - {"AC-11", "BO-35"}
    assert catalog.by_sku("BO-25") == mini_catalog.by_sku("BO-25")
    assert catalog.by_sku("AC-12").identifiers == ["AC-12", "AC12"]  # SKU first, no repeats
    assert prices == {"AC-12": Decimal("29.99")}


def test_load_descriptors_rejects_bad_input(tmp_path, mini_planogram_data):
    base = copy.deepcopy(mini_planogram_data)
    no_brand = copy.deepcopy(base)
    no_brand["shelves"][0]["products"]["pos 1:1"]["brand"] = None
    bad_price = copy.deepcopy(base)
    bad_price["shelves"][0]["products"]["pos 1:1"]["price"] = "n/a"
    conflict = copy.deepcopy(base)  # same SKU in two positions, described differently
    conflict["shelves"][1]["products"]["pos 2:1"].update(product="AC-11", display_name="Acme 10 Other")
    for name, data, match in (
        ("no_brand", no_brand, "no brand"),
        ("bad_price", bad_price, "non-numeric price"),
        ("conflict", conflict, "described differently"),
    ):
        path = _write(tmp_path, f"{name}.json", data)
        with pytest.raises(ValueError, match=match):
            load_descriptors(path, load_planogram(path))


def test_resolve_identifier_signature_alias(mini_catalog):
    # Identifier rule
    reading = _reading(brand="acme", visible_text=["AC-12"])
    sku, candidates, res = resolve_identity(reading, mini_catalog)
    assert sku == "AC-12" and candidates == ["AC-12"] and res == "direct"
    # Signature rule
    reading = _reading(brand="Bolt", family="21", xl=True, colors=["Black"])
    sku, candidates, res = resolve_identity(reading, mini_catalog)
    assert sku == "BO-25" and candidates == ["BO-25"] and res == "direct"
    # Alias rule with a local catalog
    local_catalog = Catalog(
        items=[
            CatalogItem(
                sku="ZETA-77",
                brand="Zeta",
                display_name="Zeta 77 Photo Gloss",
                identifiers=["ZETA-77"],
                aliases=["Zeta 77 Photo Gloss Paper"],
            ),
            CatalogItem(
                sku="ACME-10",
                brand="Acme",
                display_name="Acme 10 Black",
                identifiers=["ACME-10"],
                aliases=["Acme 10 Black Ink"],
            ),
        ]
    )
    reading = _reading(brand="Zeta", visible_text=["zeta 77 photo gloss paper"])
    sku, candidates, res = resolve_identity(reading, local_catalog)
    assert sku == "ZETA-77" and candidates == ["ZETA-77"] and res == "direct"


def test_resolve_never_merges_xl(mini_catalog):
    # xl=None with XL + standard items -> ambiguous
    reading = _reading(brand="Acme", family="10", colors=["black"], xl=None)
    sku, candidates, res = resolve_identity(reading, mini_catalog)
    assert sku is None and set(candidates) == {"AC-11", "AC-12"} and res == "ambiguous"
    # xl=False -> AC-11 direct
    reading = _reading(brand="Acme", family="10", colors=["black"], xl=False)
    sku, candidates, res = resolve_identity(reading, mini_catalog)
    assert sku == "AC-11" and candidates == ["AC-11"] and res == "direct"
    # Unknown brand -> unresolved
    reading = _reading(brand="UnknownBrand")
    sku, candidates, res = resolve_identity(reading, mini_catalog)
    assert sku is None and candidates == [] and res == "unresolved"


def test_resolve_signature_single_match_null_xl_is_ambiguous(mini_catalog):
    """Spec §2: rule 2 with reading.xl is None can only produce candidates -- ambiguous
    even with exactly one signature match, never direct."""
    # family "10" + colors=["tri-color"] matches exactly one catalog item (AC-13); with
    # xl left unset the resolution must still be ambiguous, not direct.
    reading = _reading(brand="Acme", family="10", colors=["tri-color"], xl=None)
    sku, candidates, res = resolve_identity(reading, mini_catalog)
    assert sku is None and candidates == ["AC-13"] and res == "ambiguous"
    # Same signature with xl explicitly set -> direct, as before.
    reading = _reading(brand="Acme", family="10", colors=["tri-color"], xl=False)
    sku, candidates, res = resolve_identity(reading, mini_catalog)
    assert sku == "AC-13" and candidates == ["AC-13"] and res == "direct"


def test_init_descriptor_fields_adds_nulls_and_keeps_values(tmp_path, mini_planogram_data):
    data = copy.deepcopy(mini_planogram_data)
    for shelf in data["shelves"]:
        for product in shelf["products"].values():
            for name in DESCRIPTOR_FIELDS:
                product.pop(name, None)
    data["shelves"][0]["products"]["pos 1:1"]["display_name"] = "Keep me"
    path = _write(tmp_path, "planogram.json", data)
    assert init_descriptor_fields(path) == 18
    written = json.loads(path.read_text(encoding="utf-8"))
    pos = written["shelves"][0]["products"]["pos 1:1"]
    assert pos["display_name"] == "Keep me" and all(name in pos for name in DESCRIPTOR_FIELDS)
    assert written["shelves"][1]["products"]["pos 2:1"]["xl"] is None
    assert init_descriptor_fields(path) == 0  # idempotent
    ref = load_planogram(path)
    catalog, undescribed, _ = load_descriptors(path, ref)
    assert [i.sku for i in catalog.items] == ["AC-11"] and len(undescribed) == 16


def test_load_prices_decimal_and_errors(tmp_path):
    # Valid prices
    prices_data = {"AC-11": "29.99", "BO-14": 45.5}
    path = _write(tmp_path, "prices.json", prices_data)
    prices = load_prices(path)
    assert prices["AC-11"] == Decimal("29.99")
    assert prices["BO-14"] == Decimal("45.5")
    # Non-numeric value
    prices_data_bad = {"AC-11": "n/a"}
    path_bad = _write(tmp_path, "prices_bad.json", prices_data_bad)
    with pytest.raises(ValueError, match="Non-numeric price"):
        load_prices(path_bad)
    # Non-object JSON
    path_list = tmp_path / "prices_list.json"
    path_list.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        load_prices(path_list)


def test_resolve_signature_skips_items_without_family():
    """A described position may leave ``family`` null: rule 2 must skip it, not crash on ``None.casefold()``."""
    catalog = Catalog(
        items=[
            CatalogItem(sku="ZX-1", brand="Zeta", display_name="Zeta Plain", identifiers=["ZX-1"]),
            CatalogItem(sku="ZX-2", brand="Zeta", display_name="Zeta 5 Black", family="5", colors=["black"]),
        ]
    )
    reading = _reading(brand="Zeta", family="5", xl=False, colors=["black"])
    assert resolve_identity(reading, catalog) == ("ZX-2", ["ZX-2"], "direct")
    reading = _reading(brand="Zeta", family="9", xl=False, visible_text=["ZX-1"])
    assert resolve_identity(reading, catalog) == ("ZX-1", ["ZX-1"], "direct")
