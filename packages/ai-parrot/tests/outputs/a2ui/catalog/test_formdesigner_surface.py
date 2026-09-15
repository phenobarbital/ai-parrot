"""Conformance test: a parrot-formdesigner FormSchema lowered by
``A2UIFormRenderer`` (FEAT-544) against the official A2UI v1.0 wire schema
and the SSR-HTML renderer.

Skipped entirely when ``parrot-formdesigner`` is not installed alongside
ai-parrot (the satellite dependency direction is the other way round —
parrot-formdesigner optionally depends on ai-parrot, not vice versa).
"""

from __future__ import annotations

import pytest

pytest.importorskip("parrot_formdesigner")

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer

from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope, validate_message
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.models import A2UIAgentMessage, CreateSurface


@pytest.fixture
def representative_form() -> FormSchema:
    """A form covering natively-lowered types plus one degraded type (FILE)."""
    return FormSchema(
        form_id="conformance",
        title="Conformance Form",
        tenant="acme",
        sections=[
            FormSection(
                section_id="main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                    FormField(
                        field_id="plan",
                        field_type=FieldType.SELECT,
                        label="Plan",
                        options=[{"value": "basic", "label": "Basic"}, {"value": "pro", "label": "Pro"}],
                    ),
                    FormField(field_id="subscribe", field_type=FieldType.BOOLEAN, label="Subscribe"),
                    FormField(field_id="start", field_type=FieldType.DATE, label="Start"),
                    FormField(field_id="nps", field_type=FieldType.NPS, label="How likely..."),
                    FormField(
                        field_id="tags",
                        field_type=FieldType.MULTI_SELECT,
                        label="Tags",
                        options=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
                    ),
                    FormField(field_id="hidden_ref", field_type=FieldType.HIDDEN, label="Ref", default="abc123"),
                    FormField(field_id="attachment", field_type=FieldType.FILE, label="Attachment"),
                ],
            )
        ],
    )


async def test_formdesigner_surface_validates_against_official_schema(representative_form: FormSchema) -> None:
    renderer = A2UIFormRenderer()
    rendered = await renderer.render(representative_form)

    assert rendered.content_type == "application/a2ui+json"
    surface_dict = rendered.content["createSurface"]
    surface_model = CreateSurface.model_validate(surface_dict)

    # Structural + catalog validation (spec §7, ProducerOrigin.TOOL).
    validate_envelope(surface_model, origin=ProducerOrigin.TOOL, surface_catalog_id=DEFAULT_CATALOG_ID)

    # Official jsonschema conformance (agent_to_renderer.json).
    agent_message = A2UIAgentMessage.model_validate(rendered.content)
    validate_message(agent_message)

    # HIDDEN and FILE both count as "no visible component" for FILE
    # (degraded notice) / dataModel-only (HIDDEN) — FILE is the one
    # expected degradation in this fixture.
    degraded_field_ids = {entry["field_id"] for entry in rendered.metadata["degraded"]}
    assert degraded_field_ids == {"attachment"}
    assert "hidden_ref" in rendered.content["createSurface"]["dataModel"]["answers"]


async def test_formdesigner_surface_renders_with_ssr_html(representative_form: FormSchema) -> None:
    ssr_html_module = pytest.importorskip("parrot.outputs.a2ui_renderers.ssr_html")
    SSRHTMLRenderer = ssr_html_module.SSRHTMLRenderer

    renderer = A2UIFormRenderer()
    rendered = await renderer.render(representative_form)
    surface_model = CreateSurface.model_validate(rendered.content["createSurface"])

    artifact = await SSRHTMLRenderer().render(surface_model)

    assert artifact.mime_type == "text/html"
    assert artifact.metadata.get("degraded", []) == []
