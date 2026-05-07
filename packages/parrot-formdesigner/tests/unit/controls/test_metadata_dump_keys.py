"""Stability test for ``FieldControlMetadata.model_dump`` keys.

Guards against accidental field additions / renames in future PRs without
a contract bump. The expected key set MUST stay stable across the
``parrot-formdesigner`` 0.x series.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.controls import (
    FieldControlMetadata,
    get_controls,
    register_field_control,
)
from parrot_formdesigner.controls.registry import _REGISTRY


EXPECTED_KEYS = {
    "type",
    "label",
    "description",
    "category",
    "icon",
    "snippet",
    "render_hint",
    "supports_constraints",
    "is_container",
}


@pytest.fixture(autouse=True)
def _clear_registry():
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()


def test_dump_has_exact_keys():
    register_field_control(
        "x",
        label="X",
        description="d",
        category="basic",
        icon="x",
        snippet={},
        render_hint="input",
        supports_constraints=True,
    )
    dump = get_controls()[0].model_dump()
    assert set(dump.keys()) == EXPECTED_KEYS


def test_metadata_model_fields_match_expected():
    """Direct check on the Pydantic model's declared fields."""
    fields = set(FieldControlMetadata.model_fields.keys())
    assert fields == EXPECTED_KEYS


def test_extra_keys_are_rejected():
    """The model is configured with ``extra='forbid'``."""
    with pytest.raises(Exception):
        FieldControlMetadata.model_validate({
            "type": "x",
            "label": "X",
            "description": "d",
            "category": "basic",
            "icon": "x",
            "snippet": {},
            "render_hint": "input",
            "supports_constraints": True,
            "is_container": False,
            "extra_field": "should fail",
        })
