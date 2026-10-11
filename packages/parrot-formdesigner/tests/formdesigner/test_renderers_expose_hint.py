"""FEAT-649 / TASK-4231 — every visual renderer exposes ``FormField.hint``."""

from __future__ import annotations

from io import BytesIO

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.renderers.pdf import PdfRenderer


def _form(hint=None) -> FormSchema:
    field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name", hint=hint)
    return FormSchema(
        form_id="demo", title="Demo", tenant="acme", sections=[FormSection(section_id="s", fields=[field])]
    )


async def test_html5_hint_small_escaped():
    out = await HTML5Renderer().render(_form("Say <b>first</b> name"))
    assert '<small class="hint' in out.content
    assert "&lt;b&gt;" in out.content


async def test_html5_no_hint_unchanged():
    out = await HTML5Renderer().render(_form())
    assert 'class="hint' not in out.content


async def test_jsonschema_x_hint_localized():
    out = await JsonSchemaRenderer().render(_form({"en": "First name", "es": "Nombre"}), locale="es")
    assert out.content["properties"]["name"]["x-hint"] == "Nombre"


async def test_jsonschema_no_hint():
    out = await JsonSchemaRenderer().render(_form())
    assert "x-hint" not in out.content["properties"]["name"]


async def test_adaptive_card_subtle_hint():
    pytest.importorskip("parrot.outputs.cards.spec")
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    out = await AdaptiveCardRenderer().render(_form("First name"))
    assert "First name" in str(out.content)

    def walk(node):
        if isinstance(node, dict):
            yield node
            for v in node.values():
                yield from walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from walk(v)

    assert any(
        n.get("type") == "TextBlock" and n.get("isSubtle") is True and n.get("text") == "First name"
        for n in walk(out.content)
    )


async def test_a2ui_hint_text_component():
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer

    out = await A2UIFormRenderer().render(_form("First name"))
    ids = [c["id"] for c in out.content["createSurface"]["components"]]
    assert "f-name-hint" in ids
    assert ids.index("f-name") < ids.index("f-name-hint")
    hint = next(c for c in out.content["createSurface"]["components"] if c["id"] == "f-name-hint")
    assert hint["text"] == "First name"


async def test_pdf_hint_line():
    from pypdf import PdfReader

    out = await PdfRenderer().render(_form("Use capitals"))
    text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(out.content)).pages)
    assert "Use capitals" in text
