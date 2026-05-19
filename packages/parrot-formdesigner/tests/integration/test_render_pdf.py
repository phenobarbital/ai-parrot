"""End-to-end test for ``GET /api/v1/forms/{id}/render/pdf``."""

from __future__ import annotations

from io import BytesIO

import pytest
from aiohttp import web
from pypdf import PdfReader

from parrot_formdesigner.api.render import _RENDERERS, _seed_default_renderers, handle_render
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


@pytest.fixture(autouse=True)
def _seed():
    _RENDERERS.clear()
    _seed_default_renderers()
    yield
    _RENDERERS.clear()


@pytest.fixture
def sample_form() -> FormSchema:
    return FormSchema(
        form_id="e2e-pdf",
        title={"en": "E2E PDF"},
        tenant="navigator",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                    ),
                ],
            )
        ],
    )


async def test_e2e_pdf_render(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/forms/{form_id}/render/{format}", handle_render
    )

    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/v1/forms/{sample_form.form_id}/render/pdf"
    )
    assert resp.status == 200
    assert resp.content_type == "application/pdf"
    body = await resp.read()
    reader = PdfReader(BytesIO(body))
    assert len(reader.pages) >= 1
    assert "/AcroForm" in reader.trailer["/Root"]
