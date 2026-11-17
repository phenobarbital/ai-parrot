"""overrides_to_envelopes — FEAT-650 TASK-4193 (requires the ai-parrot extra)."""

from __future__ import annotations

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot.outputs.a2ui.catalog import validate_message  # noqa: E402
from parrot.outputs.a2ui.serialization import deserialize  # noqa: E402
from parrot_formdesigner.api import dialect as d  # noqa: E402
from parrot_formdesigner.api.render import _RENDERERS, register_renderer  # noqa: E402
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection  # noqa: E402
from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.renderers import A2UIFormRenderer  # noqa: E402


@pytest.fixture(autouse=True)
def _a2ui() -> None:
    """Register a real A2UI renderer while preserving global renderer state."""
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    register_renderer("a2ui", A2UIFormRenderer())
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


@pytest.fixture
def form() -> FormSchema:
    """Build a form covering text and choice field lowering."""
    return FormSchema(
        form_id="f",
        title={"en": "F"},
        description={"en": "D"},
        tenant="navigator",
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"}),
                    FormField(
                        field_id="color",
                        field_type=FieldType.SELECT,
                        label={"en": "Color"},
                        options=[{"value": "r", "label": "Red"}],
                    ),
                ],
            )
        ],
    )


async def _apply(form: FormSchema, overrides: dict[str, object]) -> tuple[list[dict[str, object]], list[str]]:
    """Render and validate each translated update envelope."""
    envelopes, _rendered, warnings = await d.render_a2ui_schema(form, overrides=overrides)
    for envelope in envelopes:
        validate_message(deserialize(envelope))
    return envelopes, warnings


async def test_title_replaces_root_title(form: FormSchema) -> None:
    """Translate a form title override into its root Text update."""
    envelopes, warnings = await _apply(form, {"title": "New"})

    component = envelopes[1]["updateComponents"]["components"][0]
    assert component["id"] == "root-title"
    assert component["text"] == "New"
    assert warnings == []


async def test_property_title_relowers_field(form: FormSchema) -> None:
    """Re-lower a field when its JSON-Schema title changes."""
    envelopes, warnings = await _apply(form, {"properties": {"name": {"title": "Full name"}}})

    component = envelopes[1]["updateComponents"]["components"][0]
    assert component["id"] == "f-name"
    assert component["label"] == "Full name"
    assert warnings == []


async def test_property_default_emits_update_data_model(form: FormSchema) -> None:
    """Emit a data-model update for a field default override."""
    envelopes, warnings = await _apply(form, {"properties": {"name": {"default": "Ana"}}})

    update = envelopes[1]["updateDataModel"]
    assert update["path"] == "/answers/name"
    assert update["value"] == "Ana"
    assert warnings == []


async def test_property_options_and_required(form: FormSchema) -> None:
    """Re-lower choice options and required checks in table order."""
    envelopes, warnings = await _apply(
        form,
        {
            "properties": {"color": {"x-options": [{"value": "b", "label": "Blue"}]}},
            "required": ["name"],
        },
    )

    option_component = envelopes[1]["updateComponents"]["components"][0]
    required_component = envelopes[2]["updateComponents"]["components"][0]
    assert option_component["options"] == [{"label": "Blue", "value": "b"}]
    assert required_component["id"] == "f-name"
    assert required_component["checks"][0]["condition"]["call"] == "required"
    assert warnings == []


async def test_unknown_field_and_untranslatable_key_warn(form: FormSchema) -> None:
    """Keep unknown fields and top-level schema keys as warnings only."""
    envelopes, warnings = await _apply(form, {"properties": {"nope": {"title": "x"}}, "$schema": "x"})

    assert len(envelopes) == 1
    assert warnings == ["override_unknown_field:nope", "override_not_translatable:$schema"]
