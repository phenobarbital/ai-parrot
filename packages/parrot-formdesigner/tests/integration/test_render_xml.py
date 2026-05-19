"""End-to-end test for ``GET /api/v1/forms/{id}/render/xml``.

Boots an aiohttp app via ``setup_form_api``, registers a sample form, and
verifies the XForms 1.1 dispatcher returns a valid XML doc.
"""

from __future__ import annotations

import pytest
from aiohttp import web
from lxml import etree

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
        form_id="e2e-xml",
        title={"en": "E2E XML"},
        tenant="navigator",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                        required=True,
                    ),
                ],
            )
        ],
    )


async def test_e2e_xml_render(aiohttp_client, sample_form):
    registry = FormRegistry()
    await registry.register(sample_form)

    app = web.Application()
    app["form_registry"] = registry
    app.router.add_get(
        "/api/v1/forms/{form_id}/render/{format}", handle_render
    )

    client = await aiohttp_client(app)
    resp = await client.get(
        f"/api/v1/forms/{sample_form.form_id}/render/xml"
    )
    assert resp.status == 200
    assert resp.content_type == "application/xml"
    body = await resp.read()
    parsed = etree.fromstring(body)
    assert parsed.nsmap.get("xf") == "http://www.w3.org/2002/xforms"
