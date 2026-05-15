"""Tests for FieldType.REST entries across all renderers (FEAT-170)."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.renderers.pdf import PdfRenderer
from parrot_formdesigner.renderers.xforms import XFormsRenderer


def _form_with(field: FormField) -> FormSchema:
    return FormSchema(
        form_id="test",
        title={"en": "Test"},
        sections=[FormSection(section_id="s", fields=[field])],
    )


@pytest.fixture
def rest_callback_field() -> FormField:
    return FormField(
        field_id="upload",
        field_type=FieldType.REST,
        label={"en": "Upload"},
        required=True,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "planogram_compliance",
                "response_path": "$.compliance_score",
                "display_template": "Score: {{ answer }}",
            }
        },
    )


# ---------------------------------------------------------------------------
# HTML5 — native
# ---------------------------------------------------------------------------

async def test_html5_native_rest(rest_callback_field: FormField) -> None:
    out = await HTML5Renderer().render(_form_with(rest_callback_field))
    assert '<input type="file"' in out.content
    assert "blob_ref" in out.content
    assert "parrot-rest-uploader" in out.content
    assert out.warnings == []


# ---------------------------------------------------------------------------
# JSON Schema — native
# ---------------------------------------------------------------------------

async def test_jsonschema_native_rest(rest_callback_field: FormField) -> None:
    out = await JsonSchemaRenderer().render(_form_with(rest_callback_field))
    schema = out.content  # already a dict
    props = schema["properties"]["upload"]
    assert props["type"] == "object"
    assert "answer" in props["properties"]
    assert "blob_ref" in props["properties"]
    x = props["x-parrot-rest"]
    assert x["mode"] == "callback"
    assert x["upload_url_template"].endswith("/upload")
    assert out.warnings == []


# ---------------------------------------------------------------------------
# Adaptive Card — fallback + warning
# ---------------------------------------------------------------------------

async def test_adaptive_card_fallback_warns(rest_callback_field: FormField) -> None:
    out = await AdaptiveCardRenderer().render(_form_with(rest_callback_field))
    assert out.warnings, "Expected at least one RenderWarning"
    w = out.warnings[0]
    assert w.field_type == "rest"
    assert w.renderer == "adaptive_card"


# ---------------------------------------------------------------------------
# PDF — fallback + warning
# ---------------------------------------------------------------------------

async def test_pdf_fallback_warns(rest_callback_field: FormField) -> None:
    out = await PdfRenderer().render(_form_with(rest_callback_field))
    assert out.warnings, "Expected at least one RenderWarning"
    w = out.warnings[0]
    assert w.field_type == "rest"
    assert w.renderer == "pdf"


# ---------------------------------------------------------------------------
# XForms — fallback (plain input, no crash)
# ---------------------------------------------------------------------------

async def test_xforms_fallback_no_crash(rest_callback_field: FormField) -> None:
    out = await XFormsRenderer().render(_form_with(rest_callback_field))
    assert out.content  # non-empty XML
    content = out.content if isinstance(out.content, str) else out.content.decode()
    assert "upload" in content  # field_id present


# ---------------------------------------------------------------------------
# Telegram — WebApp redirect (no crash, REST in WebApp set)
# ---------------------------------------------------------------------------

async def test_telegram_webapp_redirect(rest_callback_field: FormField) -> None:
    from parrot_formdesigner.renderers.telegram.renderer import (
        TelegramRenderer,
        _WEBAPP_FIELD_TYPES,
    )

    assert FieldType.REST in _WEBAPP_FIELD_TYPES
    out = await TelegramRenderer().render(_form_with(rest_callback_field))
    payload = out.content  # TelegramFormPayload Pydantic model
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload
    assert data.get("mode") == "webapp"
