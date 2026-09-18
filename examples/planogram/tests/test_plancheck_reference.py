"""Unit tests for plancheck.reference (FEAT-565, spec §4 — Module 2). Synthetic data only."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from plancheck.models import Catalog, CatalogItem, SlotReading
from plancheck.reference import (
    emit_catalog_template,
    load_catalog,
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


def test_load_catalog_reports_missing_skus(tmp_path, mini_planogram, mini_catalog):
    # Remove items for AC-11 and BO-35
    items = [item for item in mini_catalog.items if item.sku not in ("AC-11", "BO-35")]
    catalog = Catalog(items=items)
    path = _write(tmp_path, "catalog.json", catalog.model_dump(mode="json"))
    loaded_catalog, missing = load_catalog(path, mini_planogram)
    assert missing == ["AC-11", "BO-35"]
    # Duplicate SKU should raise
    items_with_dup = items + [items[0]]
    catalog_dup = Catalog(items=items_with_dup)
    path_dup = _write(tmp_path, "catalog_dup.json", catalog_dup.model_dump(mode="json"))
    with pytest.raises(ValueError, match="Duplicate SKU"):
        load_catalog(path_dup, mini_planogram)


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


def test_emit_catalog_template_refuses_overwrite(tmp_path, mini_planogram):
    path = tmp_path / "template.json"
    # First call should succeed
    emit_catalog_template(mini_planogram, path)
    # Load and verify
    loaded_catalog, missing = load_catalog(path, mini_planogram)
    assert missing == []
    assert len(loaded_catalog.items) == 17  # All identity-required SKUs except CLOSEOUT
    # Second call should raise FileExistsError
    with pytest.raises(FileExistsError):
        emit_catalog_template(mini_planogram, path)


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
