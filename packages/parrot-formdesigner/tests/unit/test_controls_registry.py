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


def test_controls_registry_has_all_new_types():
    """get_controls() returns 30 entries (20 existing + 10 new) after import."""
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    controls = get_controls()
    assert len(controls) == 30, f"Expected 30 controls, got {len(controls)}"

    # Spot-check new types are present
    control_types = {c.type for c in controls}
    assert "signature" in control_types
    assert "nps" in control_types
    assert "likert" in control_types
    assert "ranking" in control_types
    assert "dynamic_select" in control_types
    assert "transfer_list" in control_types
    assert "remote_response" in control_types
    assert "availability" in control_types
    assert "location" in control_types
    assert "tags" in control_types


def test_controls_new_type_categories():
    """New types have correct categories per TASK-1153 spec."""
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    controls = {c.type: c for c in get_controls()}
    # media category
    assert controls["signature"].category == "media"
    # selection category
    assert controls["dynamic_select"].category == "selection"
    assert controls["transfer_list"].category == "selection"
    assert controls["location"].category == "selection"
    assert controls["tags"].category == "selection"
    # advanced category
    assert controls["remote_response"].category == "advanced"
    assert controls["availability"].category == "advanced"
    assert controls["nps"].category == "advanced"
    assert controls["likert"].category == "advanced"
    assert controls["ranking"].category == "advanced"


def test_controls_new_type_render_hints():
    """New types have correct render_hint values."""
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    controls = {c.type: c for c in get_controls()}
    assert controls["signature"].render_hint == "signature"
    assert controls["dynamic_select"].render_hint == "select"
    assert controls["transfer_list"].render_hint == "transfer-list"
    assert controls["nps"].render_hint == "rating"
    assert controls["likert"].render_hint == "rating"
    assert controls["ranking"].render_hint == "rating"
