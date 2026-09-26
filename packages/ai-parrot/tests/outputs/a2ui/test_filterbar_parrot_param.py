"""FilterBar parrot_param pass-through (FEAT-598 M10)."""

import json
from pathlib import Path

import jsonschema
import pytest

from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import filterbar
from parrot.outputs.a2ui.models import Component

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2).encode() + b"\n"


def _filterbar() -> Component:
    return Component(
        id="fb",
        component="FilterBar",
        filters=[
            {
                "column": "program",
                "label": "Program",
                "options": [{"label": "Epson", "value": "epson"}],
                "param": {"source": "activity", "name": "program"},
            },
            {"column": "store", "label": "Store", "options": []},
        ],
    )


def test_filterbar_param_passthrough() -> None:
    tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
    with_param = tree.children[0].metadata.extensions.root
    without_param = tree.children[1].metadata.extensions.root
    assert with_param["parrot_param"] == {"source": "activity", "name": "program"}
    assert "parrot_param" not in without_param


def test_filterbar_param_golden() -> None:
    one = _dump(filterbar.FilterBarComponent().lower(_filterbar(), {}))
    two = _dump(filterbar.FilterBarComponent().lower(_filterbar(), {}))
    assert one == two == (GOLDEN_DIR / "filterbar_param_lowered.json").read_bytes()


def test_filterbar_param_schema_valid() -> None:
    props = {
        "filters": [
            {
                "column": "program",
                "label": "Program",
                "options": [{"label": "Epson", "value": "epson"}],
                "param": {"source": "activity", "name": "program"},
            }
        ]
    }
    jsonschema.validate(props, filterbar.FILTERBAR_SCHEMA)


def test_filterbar_param_schema_rejects_extra_key() -> None:
    props = {
        "filters": [
            {
                "column": "program",
                "label": "Program",
                "options": [{"label": "Epson", "value": "epson"}],
                "param": {"source": "activity", "name": "program", "url": "https://example.com"},
            }
        ]
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(props, filterbar.FILTERBAR_SCHEMA)


def test_filterbar_param_lowered_is_v1_valid() -> None:
    tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
    to_components(tree)
