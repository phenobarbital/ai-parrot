"""SKU preservation and normalization for FEAT-645."""

from typing import Any

import pytest

from parrot_pipelines.planogram.comparison.definition import Descriptors, SlotsDefinitionError, load_slots_definition


@pytest.mark.parametrize(
    "value, expected",
    [(6347569, "6347569"), (0, "0"), (" 00123 ", "00123"), (" ", None), (None, None)],
)
def test_descriptor_sku_normalization(value: Any, expected: str | None) -> None:
    """Retain identifiers without losing zeroes or representing absence as text."""
    assert Descriptors(sku=value).sku == expected
    assert Descriptors().sku is None
    with pytest.raises(ValueError, match="sku must be an integer or string"):
        Descriptors(sku=["invalid"])


@pytest.mark.parametrize("layout", ["native", "page1"])
def test_descriptor_sku_kept_native_and_page1(layout: str) -> None:
    """Both supported definition shapes preserve numeric and string SKUs."""
    if layout == "native":
        source = {
            "shelves": [
                {
                    "shelf_id": "shelf_1",
                    "shelf_number": 1,
                    "facings": [
                        {
                            "facing_id": "f1",
                            "shelf_id": "shelf_1",
                            "slot": 1,
                            "product": "MODEL-1",
                            "descriptors": {"display_name": "Model One", "sku": 6347569},
                        }
                    ],
                }
            ]
        }
        expected_sku = "6347569"
        source_sku = source["shelves"][0]["facings"][0]["descriptors"]["sku"]
    else:
        source = {
            "planogram": {"planogram": "Synthetic"},
            "shelves": [
                {
                    "shelf_number": 1,
                    "products": {
                        "position-1": {
                            "position": 1,
                            "slot": 1,
                            "product": "MODEL-1",
                            "facings": 2,
                            "display_name": "Model One",
                            "sku": " 00123 ",
                        }
                    },
                }
            ],
        }
        expected_sku = "00123"
        source_sku = source["shelves"][0]["products"]["position-1"]["sku"]

    definition = load_slots_definition(source)

    assert [facing.descriptors.sku for facing in definition.all_facings()] == [expected_sku] * len(
        definition.all_facings()
    )
    assert [facing.descriptors.model_dump()["sku"] for facing in definition.all_facings()] == [expected_sku] * len(
        definition.all_facings()
    )
    if layout == "native":
        assert source["shelves"][0]["facings"][0]["descriptors"]["sku"] == source_sku
    else:
        assert source["shelves"][0]["products"]["position-1"]["sku"] == source_sku


def test_descriptor_sku_attribute_collision() -> None:
    """The new typed field cannot be shadowed in custom attributes."""
    source = {
        "shelves": [
            {
                "shelf_id": "shelf_1",
                "shelf_number": 1,
                "facings": [
                    {
                        "facing_id": "f1",
                        "shelf_id": "shelf_1",
                        "slot": 1,
                        "product": "MODEL-1",
                        "descriptors": {"display_name": "Model One", "attributes": {"sku": "shadow"}},
                    }
                ],
            }
        ]
    }

    with pytest.raises(SlotsDefinitionError, match="attributes collide with typed fields: sku"):
        load_slots_definition(source)


def test_integral_float_sku_becomes_string() -> None:
    """Spreadsheet-read float SKUs normalize to their integer string; fractional ones are rejected."""
    assert Descriptors(sku=12.0).sku == "12"
    with pytest.raises(ValueError):
        Descriptors(sku=12.5)
