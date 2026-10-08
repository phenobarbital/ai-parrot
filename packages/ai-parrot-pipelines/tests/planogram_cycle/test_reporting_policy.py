"""Reporting policy validation and precedence for FEAT-645."""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from parrot_pipelines.planogram.comparison.definition import (
    ReportingPolicy,
    SlotsDefinition,
    SlotsDefinitionError,
    effective_reporting,
    load_slots_definition,
)


def _native_definition(reporting: Any) -> dict[str, Any]:
    """Build the smallest native definition accepted by the public loader."""
    return {
        "meta": {"reporting": reporting},
        "shelves": [
            {
                "shelf_id": "shelf_1",
                "shelf_number": 1,
                "facings": [
                    {
                        "facing_id": "facing_1",
                        "shelf_id": "shelf_1",
                        "slot": 1,
                        "product": "MODEL-1",
                        "descriptors": {"display_name": "Model 1"},
                    }
                ],
            }
        ],
    }


def _page1_definition(reporting: Any) -> dict[str, Any]:
    """Build the smallest page1 definition accepted by the public loader."""
    return {
        "planogram": {"reporting": reporting},
        "shelves": [
            {
                "shelf_number": 1,
                "products": {
                    "position_1": {
                        "slot": 1,
                        "position": 1,
                        "product": "MODEL-1",
                        "display_name": "Model 1",
                    }
                },
            }
        ],
    }


@pytest.mark.parametrize(
    "reporting",
    [
        {"unknown": True},
        {"product_label": "x"},
        {"misplaced_min_confidence": 1.5},
        {"misplaced_min_confidence": -0.1},
        None,
        [],
    ],
)
def test_reporting_meta_override_validated(reporting: Any) -> None:
    """Direct validation uses ValidationError; the loader exposes SlotsDefinitionError."""
    native = _native_definition(reporting)
    with pytest.raises(ValidationError):
        SlotsDefinition(meta={"reporting": reporting})
    with pytest.raises(ValidationError):
        SlotsDefinition.model_validate(native)
    with pytest.raises(SlotsDefinitionError):
        load_slots_definition(native)
    with pytest.raises(SlotsDefinitionError):
        load_slots_definition(_page1_definition(reporting))


def test_effective_reporting_precedence() -> None:
    """Only explicit meta keys override a profile; no source object is mutated."""
    defaults = ReportingPolicy()
    assert effective_reporting(None, None) == defaults

    profile = ReportingPolicy(product_label="product", slot_presence=True, misplaced_min_confidence=0.7)
    layout = SimpleNamespace(reporting=profile)
    empty_meta = SlotsDefinition(meta={})
    empty_reporting = SlotsDefinition(meta={"reporting": {}})
    assert effective_reporting(layout, empty_meta) == profile
    assert effective_reporting(layout, empty_reporting) == profile

    definition = SlotsDefinition(
        meta={
            "reporting": {
                "product_label": "display_name",
                "slot_presence": False,
                "misplaced_min_confidence": 0.4,
            }
        }
    )
    assert effective_reporting(layout, definition) == ReportingPolicy(misplaced_min_confidence=0.4)
    assert layout.reporting is profile
    assert definition.meta == {
        "reporting": {
            "product_label": "display_name",
            "slot_presence": False,
            "misplaced_min_confidence": 0.4,
        }
    }

    assert effective_reporting(layout, SlotsDefinition(meta={"reporting": {"product_label": "display_name"}})) == (
        ReportingPolicy(product_label="display_name", slot_presence=True, misplaced_min_confidence=0.7)
    )
    assert effective_reporting(
        layout, SlotsDefinition(meta={"reporting": {"slot_presence": False}})
    ) == ReportingPolicy(product_label="product", misplaced_min_confidence=0.7)
    assert effective_reporting(
        layout,
        SlotsDefinition(meta={"reporting": {"misplaced_min_confidence": 0.2}}),
    ) == ReportingPolicy(product_label="product", slot_presence=True, misplaced_min_confidence=0.2)


def test_reporting_policy_defaults_and_bounds() -> None:
    """Default labels/presence remain legacy and threshold endpoints are accepted."""
    assert ReportingPolicy() == ReportingPolicy(
        product_label="display_name",
        slot_presence=False,
        misplaced_min_confidence=0.9,
    )
    assert ReportingPolicy(misplaced_min_confidence=0.0).misplaced_min_confidence == 0.0
    assert ReportingPolicy(misplaced_min_confidence=1.0).misplaced_min_confidence == 1.0
    with pytest.raises(ValidationError):
        ReportingPolicy(unknown=True)
    with pytest.raises(ValidationError):
        ReportingPolicy(product_label="unknown")
