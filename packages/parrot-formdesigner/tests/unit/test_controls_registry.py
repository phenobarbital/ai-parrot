"""Unit tests for ``parrot_formdesigner.controls.registry``."""

from __future__ import annotations

import importlib
import sys

import pytest

from parrot_formdesigner.controls.registry import (
    FieldControlMetadata,
    _REGISTRY,
    get_controls,
    iter_controls,
    register_field_control,
)
from parrot_formdesigner.core.types import FieldType


@pytest.fixture(autouse=True)
def _clear_registry():
    """Reset the module-level registry between tests."""
    _REGISTRY.clear()
    yield
    _REGISTRY.clear()


def test_register_basic():
    register_field_control(
        FieldType.TEXT,
        label="Text",
        description="Single-line text",
        category="basic",
        icon="text",
        snippet={"type": "string"},
        render_hint="input",
        supports_constraints=True,
    )
    controls = get_controls()
    assert len(controls) == 1
    assert controls[0].type == "text"
    assert isinstance(controls[0], FieldControlMetadata)


def test_register_idempotent_overwrite(caplog):
    register_field_control(
        FieldType.TEXT,
        label="A",
        description="d",
        category="basic",
        icon="t",
        snippet={},
        render_hint="input",
        supports_constraints=True,
    )
    register_field_control(
        FieldType.TEXT,
        label="B",
        description="d",
        category="basic",
        icon="t",
        snippet={},
        render_hint="input",
        supports_constraints=True,
    )
    controls = get_controls()
    assert len(controls) == 1
    assert controls[0].label == "B"


def test_register_with_string_type():
    """Extension types use a string id rather than a FieldType enum."""
    register_field_control(
        "rich_text",
        label="Rich Text",
        description="Rich text editor",
        category="advanced",
        icon="rich-text",
        snippet={"type": "string", "format": "rich-text"},
        render_hint="rich",
        supports_constraints=True,
    )
    controls = get_controls()
    assert len(controls) == 1
    assert controls[0].type == "rich_text"


def test_iter_controls_yields_in_registration_order():
    register_field_control(
        FieldType.TEXT,
        label="t",
        description="d",
        category="basic",
        icon="t",
        snippet={},
        render_hint="input",
        supports_constraints=True,
    )
    register_field_control(
        FieldType.NUMBER,
        label="n",
        description="d",
        category="basic",
        icon="n",
        snippet={},
        render_hint="input",
        supports_constraints=True,
    )
    seq = [c.type for c in iter_controls()]
    assert seq == ["text", "number"]


def test_builtin_seeds_every_field_type():
    # Re-import builtin so it re-runs `_seed()` against our cleared registry.
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    controls = get_controls()
    types_seeded = {c.type for c in controls}
    assert types_seeded == {ft.value for ft in FieldType}
    assert len(controls) == len(FieldType)


def test_builtin_categories_known():
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    allowed = {"basic", "selection", "media", "layout", "advanced"}
    for c in get_controls():
        assert c.category in allowed


def test_builtin_container_flags():
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    by_type = {c.type: c for c in get_controls()}
    assert by_type["group"].is_container is True
    assert by_type["array"].is_container is True
    assert by_type["text"].is_container is False


def test_builtin_supports_constraints():
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    by_type = {c.type: c for c in get_controls()}
    assert by_type["text"].supports_constraints is True
    assert by_type["boolean"].supports_constraints is False
    assert by_type["group"].supports_constraints is False


def test_builtin_snippets_are_deep_copies():
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    by_type = {c.type: c for c in get_controls()}
    # Mutating a returned snippet must not corrupt subsequent calls.
    text_snip = by_type["text"].snippet
    text_snip["mutated"] = True

    from parrot_formdesigner.tools.field_helpers import (
        get_form_field_schema_snippets,
    )

    snippets = get_form_field_schema_snippets()
    assert "mutated" not in snippets["text"]
