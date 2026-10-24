"""translate_jsonschema_to_a2ui — FEAT-650 TASK-4199."""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.a2ui_translate import translate_jsonschema_to_a2ui


async def test_missing_extra_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report the optional-extra requirement when no A2UI renderer is registered."""
    import parrot_formdesigner.api.render as render

    monkeypatch.setattr(render, "_RENDERERS", {})
    with pytest.raises(RuntimeError, match="ai-parrot"):
        await translate_jsonschema_to_a2ui({"type": "object", "properties": {}})


async def test_composition_preserves_sections_and_validates() -> None:
    """Preserve section ownership through JSON Schema and emit a valid A2UI surface."""
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot.outputs.a2ui.catalog import validate_envelope
    from parrot.outputs.a2ui.catalog.base import ProducerOrigin
    from parrot.outputs.a2ui.serialization import deserialize
    from parrot_formdesigner.core import FieldType, FormField, FormSchema, FormSection, FormSubsection
    from parrot_formdesigner.renderers import A2UIFormRenderer, JsonSchemaRenderer

    form = FormSchema(
        form_id="rt",
        title={"en": "RT"},
        tenant="document-tenant",
        sections=[
            FormSection(
                section_id="s1",
                title={"en": "One"},
                description={"en": "d1"},
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                        placeholder={"en": "ph"},
                        default="x",
                        description={"en": "fd"},
                    ),
                    FormField(
                        field_id="ro",
                        field_type=FieldType.NUMBER,
                        label={"en": "RO"},
                        read_only=True,
                    ),
                    FormSubsection(
                        subsection_id="s1a",
                        title={"en": "Sub"},
                        fields=[
                            FormField(
                                field_id="tags",
                                field_type=FieldType.MULTI_SELECT,
                                label={"en": "Tags"},
                                options=[
                                    {"value": "a", "label": "A"},
                                    {"value": "b", "label": "B", "disabled": True},
                                ],
                            )
                        ],
                    ),
                ],
            ),
            FormSection(
                section_id="s2",
                title={"en": "Two"},
                fields=[
                    FormField(
                        field_id="color",
                        field_type=FieldType.SELECT,
                        label={"en": "Color"},
                        options=[{"value": "r", "label": "Red"}],
                    )
                ],
            ),
        ],
    )
    json_schema = await JsonSchemaRenderer().render(form)

    rendered = await translate_jsonschema_to_a2ui(
        json_schema.content,
        form_id=form.form_id,
        tenant="acme",
        renderer=A2UIFormRenderer(),
    )
    message = deserialize(rendered.content)
    assert not isinstance(message, list)
    surface = message.create_surface
    assert surface is not None

    cards = [component for component in surface.components if component.component == "Card"]
    assert [card.id for card in cards] == ["sec-s1", "sec-s2"]

    field_sections = {
        component.metadata.extensions.root["parrot_field_id"]: component.metadata.extensions.root["parrot_section_id"]
        for component in surface.components
        if component.metadata is not None
        and component.metadata.extensions is not None
        and "parrot_field_id" in component.metadata.extensions.root
    }
    assert field_sections == {"name": "s1", "ro": "s1", "tags": "s1", "color": "s2"}

    root = next(component for component in surface.components if component.id == "root")
    assert root.metadata is not None
    assert root.metadata.extensions is not None
    assert root.metadata.extensions.root["parrot_tenant"] == "acme"
    validate_envelope(surface, origin=ProducerOrigin.TOOL)
