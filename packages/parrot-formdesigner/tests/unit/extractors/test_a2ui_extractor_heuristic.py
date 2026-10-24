"""A2UIExtractor heuristic mode — FEAT-650 TASK-4202."""

from __future__ import annotations

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.extractors import A2UIExtractor, ExtractionMode  # noqa: E402


def _c(component_id: str, component: str, **props: object) -> dict[str, object]:
    return {"id": component_id, "component": component, **props}


def _surface(components: list[dict[str, object]], data_model: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "version": "v1.0",
        "createSurface": {
            "surfaceId": "s",
            "catalogId": "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json",
            "sendDataModel": True,
            "components": components,
            "dataModel": data_model or {"answers": {}},
        },
    }


GENERIC = _surface(
    [
        _c("root", "Column", children=["card1", "img", "actions"]),
        _c("card1", "Card", child="body1"),
        _c("body1", "Column", children=["t1", "name", "lbl_age", "age", "tags", "when"]),
        _c("t1", "Text", text="Personal"),
        _c(
            "name",
            "TextField",
            label="Name",
            value={"path": "/answers/name"},
            checks=[{"condition": {"call": "required", "args": {"value": {"path": "/answers/name"}}}}],
        ),
        _c("lbl_age", "Text", text="Age"),
        _c("age", "Slider", min=0, max=120, steps=12, value={"path": "/answers/age"}),
        _c(
            "tags",
            "ChoicePicker",
            label="Tags",
            variant="multipleSelection",
            options=[{"label": "A", "value": "a"}],
            value={"path": "/answers/tags"},
        ),
        _c("when", "DateTimeInput", enableDate=True, enableTime=True, value={"path": "/answers/when"}),
        _c("img", "Image", url="x.png"),
        _c("actions", "Row", children=["cancel"]),
        _c("cancel", "Button", child="cancel_t", action={"event": {"name": "form.cancel"}}),
        _c("cancel_t", "Text", text="Cancel"),
    ],
    {"answers": {"name": "Ana"}},
)


def test_generic_surface_maps_fields_sections_and_drops() -> None:
    out = A2UIExtractor().extract(GENERIC)
    assert out.mode is ExtractionMode.HEURISTIC
    section = out.form.sections[0]
    assert section.section_id == "card1"
    back = {field.field_id: field for field in out.form.iter_fields_recursive()}
    assert back["name"].field_type is FieldType.TEXT
    assert back["name"].required and back["name"].default == "Ana"
    assert back["age"].field_type is FieldType.NUMBER and back["age"].constraints.max_value == 120
    assert back["tags"].field_type is FieldType.MULTI_SELECT and back["tags"].options[0].value == "a"
    assert back["when"].field_type is FieldType.DATETIME
    assert out.form.cancel_allowed is True
    assert {d.component_id for d in out.dropped} >= {"img"}
    assert "Age" in str(back["age"].label)
    assert "label_inferred_from_text:age" in out.warnings


def test_tabs_flatten_to_sections_and_collisions_suffix() -> None:
    surface = _surface(
        [
            _c("root", "Column", children=["tabs"]),
            _c("tabs", "Tabs", tabs=[{"title": "First", "child": "tab1_body"}, {"title": "Second", "child": "tab2_body"}]),
            _c("tab1_body", "Column", children=["tab1_title", "first"]),
            _c("tab1_title", "Text", text="First"),
            _c("first", "TextField", label="First", value={"path": "/answers/x"}),
            _c("tab2_body", "Column", children=["tab2_title", "second"]),
            _c("tab2_title", "Text", text="Second"),
            _c("second", "TextField", label="Second", value={"path": "/answers/x"}),
        ]
    )
    out = A2UIExtractor().extract(surface)
    assert [section.section_id for section in out.form.sections] == ["tab1_body", "tab2_body"]
    assert [field.field_id for field in out.form.iter_all_fields()] == ["x", "x_2"]
    assert "tabs_flattened" in out.warnings
    assert "field_id_collision:x" in out.warnings


def test_text_variants_and_checks() -> None:
    surface = _surface(
        [
            _c("root", "Column", children=["long", "number", "secret", "email"]),
            _c("long", "TextField", variant="longText", label="Long", value="text", checks=[]),
            _c("number", "TextField", variant="number", label="Number", value="1", checks=[]),
            _c("secret", "TextField", variant="obscured", label="Secret", value="x", checks=[]),
            _c(
                "email",
                "TextField",
                label="Email",
                value={"path": "/answers/email"},
                checks=[
                    {"condition": {"call": "email"}},
                    {"condition": {"call": "regex", "args": {"pattern": "^[a-z]+$"}}},
                    {"condition": {"call": "length", "args": {"min": 2, "max": 12}}},
                    {"condition": {"call": "numeric", "args": {"min": 1, "max": 9}}},
                ],
            ),
        ]
    )
    out = A2UIExtractor().extract(surface)
    fields = {field.field_id: field for field in out.form.iter_all_fields()}
    assert fields["long"].field_type is FieldType.TEXT_AREA
    assert fields["number"].field_type is FieldType.NUMBER
    assert fields["secret"].field_type is FieldType.PASSWORD
    assert fields["email"].field_type is FieldType.EMAIL
    assert fields["email"].constraints.pattern == "^[a-z]+$"
    assert fields["email"].constraints.min_length == 2 and fields["email"].constraints.max_length == 12
    assert fields["email"].constraints.min_value == 1 and fields["email"].constraints.max_value == 9


def test_never_raises_on_content() -> None:
    out = A2UIExtractor().extract(_surface([_c("root", "Column", children=["v"]), _c("v", "Video", url="v.mp4")]))
    assert out.form.sections and not list(out.form.iter_all_fields()) and out.dropped[0].reason == "unsupported_component"
