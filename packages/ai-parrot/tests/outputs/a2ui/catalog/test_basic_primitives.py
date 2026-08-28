"""Anti-drift tests for the 18 Basic Catalog primitives (FEAT-470 TASK-2536)."""

from __future__ import annotations

import pytest
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.basic import (
    BASIC_CATALOG_ID,
    basic_components,
    load_spec,
)
from parrot.outputs.a2ui.catalog.basic.inputs import (
    Button,
    CheckBox,
    ChoicePicker,
    DateTimeInput,
    Slider,
    TextField,
)
from parrot.outputs.a2ui.catalog.basic.layout import (
    Card,
    Column,
    Divider,
    List,
    Modal,
    Row,
    Tabs,
)
from parrot.outputs.a2ui.catalog.basic.media import (
    AudioPlayer,
    Icon,
    Image,
    Text,
    Video,
)
from pydantic import ValidationError

_ALL_PRIMITIVE_CLASSES = {
    "Text": Text,
    "Image": Image,
    "Icon": Icon,
    "Video": Video,
    "AudioPlayer": AudioPlayer,
    "Row": Row,
    "Column": Column,
    "List": List,
    "Card": Card,
    "Tabs": Tabs,
    "Modal": Modal,
    "Divider": Divider,
    "Button": Button,
    "TextField": TextField,
    "CheckBox": CheckBox,
    "ChoicePicker": ChoicePicker,
    "Slider": Slider,
    "DateTimeInput": DateTimeInput,
}


class TestBasicComponentEnums:
    def test_len_basic_components_is_18(self):
        assert len(basic_components()) == 18
        assert set(_ALL_PRIMITIVE_CLASSES) == {d.name for d in basic_components()}

    @pytest.mark.parametrize("name", sorted(_ALL_PRIMITIVE_CLASSES))
    def test_basic_component_enums(self, name):
        """Every enum-typed field's literal values match the vendored JSON."""
        official = load_spec("catalog")["components"][name]
        cls = _ALL_PRIMITIVE_CLASSES[name]
        schema = cls.model_json_schema()
        props = _flatten_properties(official)
        for prop_name, prop_schema in props.items():
            enum_values = prop_schema.get("enum")
            if enum_values is None:
                continue
            model_prop = schema.get("properties", {}).get(prop_name)
            assert model_prop is not None, f"{name}.{prop_name} missing from model schema"
            model_enum = _extract_enum(model_prop, schema.get("$defs", {}))
            assert model_enum is not None, f"{name}.{prop_name} has no enum in model"
            assert set(model_enum) == set(enum_values), (
                f"{name}.{prop_name} enum drift: model={model_enum} json={enum_values}"
            )


def _flatten_properties(component_schema: dict) -> dict:
    """Merge top-level ``properties`` with any ``allOf``-nested ``properties``."""
    props = dict(component_schema.get("properties", {}))
    for sub in component_schema.get("allOf", []):
        props.update(sub.get("properties", {}))
    return props


def _extract_enum(model_prop: dict, defs: dict) -> list | None:
    """Best-effort enum extraction from a pydantic-generated JSON schema property."""
    if "enum" in model_prop:
        return model_prop["enum"]
    ref = model_prop.get("allOf", [{}])[0].get("$ref") if "allOf" in model_prop else model_prop.get("$ref")
    if ref:
        def_name = ref.rsplit("/", 1)[-1]
        return defs.get(def_name, {}).get("enum")
    for key in ("anyOf", "oneOf"):
        for option in model_prop.get(key, []):
            enum = _extract_enum(option, defs)
            if enum is not None:
                return enum
    return None


class TestBasicRequiredFields:
    def test_slider_requires_max(self):
        with pytest.raises(ValidationError):
            Slider(id="s", value=1)

    def test_checkbox_requires_label_and_value(self):
        with pytest.raises(ValidationError):
            CheckBox(id="c")
        CheckBox(id="c", label="Agree", value=False)

    def test_button_requires_child_and_action(self):
        with pytest.raises(ValidationError):
            Button(id="b")
        Button(id="b", child="lbl", action={"event": {"name": "go"}})

    def test_row_column_list_require_children(self):
        with pytest.raises(ValidationError):
            Row(id="r")
        with pytest.raises(ValidationError):
            Column(id="c")
        with pytest.raises(ValidationError):
            List(id="l")

    def test_card_requires_child(self):
        with pytest.raises(ValidationError):
            Card(id="c")

    def test_tabs_requires_nonempty_tabs(self):
        with pytest.raises(ValidationError):
            Tabs(id="t", tabs=[])

    def test_modal_requires_trigger_and_content(self):
        with pytest.raises(ValidationError):
            Modal(id="m")
        Modal(id="m", trigger="btn", content="body")

    def test_datetime_input_requires_value(self):
        with pytest.raises(ValidationError):
            DateTimeInput(id="d")
        DateTimeInput(id="d", value="")

    def test_choicepicker_requires_options_and_value(self):
        with pytest.raises(ValidationError):
            ChoicePicker(id="c")
        ChoicePicker(id="c", options=[{"label": "A", "value": "a"}], value=["a"])


class TestBasicRegisteredWithBasicCatalogId:
    @pytest.mark.parametrize("name", sorted(_ALL_PRIMITIVE_CLASSES))
    def test_basic_registered_with_basic_catalog_id(self, name):
        basic_components()  # ensure registration has happened
        entry = get_component(name)
        assert entry.definition.catalog_id == BASIC_CATALOG_ID
        assert entry.definition.is_primitive is True
        assert entry.definition.instructions
