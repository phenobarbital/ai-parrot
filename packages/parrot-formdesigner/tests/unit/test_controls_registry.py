"""Unit tests for ``parrot_formdesigner.controls.registry``."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

from parrot_formdesigner.controls.registry import (
    FieldControlMetadata,
    _REGISTRY,
    get_controls,
    iter_controls,
    register_field_control,
)
from parrot_formdesigner.core.types import FieldType

# TASK-2337 (FEAT-448): the twelve types absorbed from the client catalog.
_TASK2337_TYPES = [
    "search",
    "masked",
    "color_picker",
    "emoji",
    "cron",
    "tree_select",
    "signature_pad",
    "credit_card",
    "image_dropzone",
    "multi_upload",
    "ai_capture",
    "place",
]


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
    """get_controls() returns 32 entries (20 existing + 10 FEAT-167 + 1 FEAT-170 REST + 1 FEAT-300 FORMULA)."""
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    controls = get_controls()
    assert len(controls) == 32, f"Expected 32 controls, got {len(controls)}"

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


# TASK-2338 (FEAT-448): the shared catalog fixture, and the ratchet that
# reads it. See spec §5.5/AC7.
#
# AC1/AC2 ("a test fails if a FieldType value is missing from / the catalog
# names a type not in FieldType") are already covered above by
# `test_builtin_seeds_every_field_type` (bidirectional set equality between
# `get_controls()` and `FieldType`) and, at the HTTP layer, by
# `tests/integration/test_form_controls_contract.py::test_endpoint_covers_every_field_type`.
# The tests below cover what TASK-2338 actually adds: the `value_shape`
# contract per type, and the committed-snapshot staleness ratchet (AC3/AC4).


def test_value_shape_present_for_every_field_type():
    """Every FieldType's control entry publishes a non-empty value_shape."""
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    for c in get_controls():
        assert c.value_shape, f"{c.type} has an empty value_shape"
        assert "type" in c.value_shape, f"{c.type}'s value_shape is missing 'type'"


@pytest.mark.parametrize("type_id", _TASK2337_TYPES)
def test_value_shape_matches_jsonschema_renderer(type_id: str):
    """The catalog's value_shape for each TASK-2337 type is EXACTLY what
    JsonSchemaRenderer.type_level_value_shape() computes — the anti-drift
    property the task exists to guarantee (spec §5.5): the catalog is not a
    second hand-maintained copy, it reads the JSON Schema renderer's own
    _TYPE_MAP/_FORMAT_MAP/_STRUCTURAL_EXTRAS.
    """
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.renderers.jsonschema import type_level_value_shape

    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    by_type = {c.type: c for c in get_controls()}

    ft = FieldType(type_id)
    assert by_type[type_id].value_shape == type_level_value_shape(ft)


def test_credit_card_value_shape_excludes_cvv_and_number():
    """credit_card's published contract never advertises cvv/number keys —
    the catalog must not invite a client to send what the validator
    rejects (spec §4, TASK-2334)."""
    sys.modules.pop("parrot_formdesigner.controls.builtin", None)
    importlib.import_module("parrot_formdesigner.controls.builtin")
    by_type = {c.type: c for c in get_controls()}
    cc_shape = by_type["credit_card"].value_shape
    assert set(cc_shape["properties"].keys()) == {"brand", "last4", "name", "expiry"}
    assert "cvv" not in cc_shape["properties"]
    assert "number" not in cc_shape["properties"]


def _load_snapshot_script():
    """Load scripts/generate_form_controls_snapshot.py via its file path.

    ``scripts/`` is a plain directory of standalone scripts, not a Python
    package (mirrors the pattern in tests/unit/test_migrations_form_uid.py
    for migrations/003_migrate_form_data.py).
    """
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "generate_form_controls_snapshot.py"
    spec = importlib.util.spec_from_file_location("generate_form_controls_snapshot", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_form_controls_snapshot"] = module
    spec.loader.exec_module(module)
    return module


def test_form_controls_snapshot_is_fresh():
    """The committed snapshot matches the live catalog exactly (AC3/AC4).

    If this fails, the catalog changed (a FieldType was added/removed, or a
    control's metadata/value_shape changed) without regenerating the
    snapshot. Run `python scripts/generate_form_controls_snapshot.py` and
    commit the result.
    """
    gen = _load_snapshot_script()
    fresh_text = gen.render_snapshot_text(gen.compute_snapshot())
    assert gen.SNAPSHOT_PATH.exists(), (
        f"{gen.SNAPSHOT_PATH} does not exist — run "
        "`python scripts/generate_form_controls_snapshot.py` once to create it."
    )
    committed_text = gen.SNAPSHOT_PATH.read_text()
    assert committed_text == fresh_text, (
        f"{gen.SNAPSHOT_PATH} is stale. Run " "`python scripts/generate_form_controls_snapshot.py` to regenerate it."
    )


def test_form_controls_snapshot_covers_every_field_type():
    """The committed snapshot itself satisfies AC1/AC2 — no live server
    needed to check it (spec §5.5: "a committed snapshot ... in CI without
    a running server")."""
    gen = _load_snapshot_script()
    snapshot = gen.compute_snapshot()
    types_in_snapshot = {c["type"] for c in snapshot["controls"]}
    assert types_in_snapshot == {ft.value for ft in FieldType}
