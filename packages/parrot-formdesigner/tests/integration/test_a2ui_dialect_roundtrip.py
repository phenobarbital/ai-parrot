"""FEAT-650 end-to-end round-trips (TASK-4205, spec §4 Integration Tests)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.api.handlers import FormAPIHandler  # noqa: E402
from parrot_formdesigner.api.render import _RENDERERS, register_renderer  # noqa: E402
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection  # noqa: E402
from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.extractors import A2UIExtractor  # noqa: E402
from parrot_formdesigner.renderers import A2UIFormRenderer, JsonSchemaRenderer  # noqa: E402
from parrot_formdesigner.services.a2ui_export import A2UIExportService  # noqa: E402
from parrot_formdesigner.services.a2ui_translate import translate_jsonschema_to_a2ui  # noqa: E402
from parrot_formdesigner.services.registry import FormRegistry  # noqa: E402

GOLDEN = Path(__file__).parents[1] / "unit" / "api" / "fixtures" / "golden_schema_legacy.json"
TENANT = "navigator"


def _form(fid="rt", tenant=TENANT) -> FormSchema:
    return FormSchema(
        form_id=fid,
        title={"en": "RT"},
        tenant=tenant,
        is_public=True,
        sections=[
            FormSection(
                section_id="s1",
                title={"en": "One"},
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"}, required=True),
                    FormField(field_id="nps", field_type=FieldType.NPS, label={"en": "NPS"}),
                ],
            ),
            FormSection(
                section_id="s2",
                title={"en": "Two"},
                fields=[
                    FormSubsection(
                        subsection_id="s2a",
                        title={"en": "A"},
                        fields=[
                            FormField(
                                field_id="color",
                                field_type=FieldType.SELECT,
                                label={"en": "Color"},
                                options=[{"value": "r", "label": "Red"}],
                            )
                        ],
                    )
                ],
            ),
        ],
    )


def _golden_form() -> FormSchema:
    """The stable form captured in the legacy golden (same as tests/unit/api/test_get_schema_dialect.py)."""
    return FormSchema(
        form_id="golden-form",
        title={"en": "Golden Form"},
        description={"en": "Golden description"},
        tenant=TENANT,
        is_public=True,
        sections=[
            FormSection(
                section_id="identity",
                title={"en": "Identity"},
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"}, required=True),
                    FormField(
                        field_id="choice",
                        field_type=FieldType.SELECT,
                        label={"en": "Choice"},
                        options=[{"value": "one", "label": "One"}, {"value": "two", "label": "Two"}],
                    ),
                ],
            ),
            FormSection(
                section_id="details",
                fields=[
                    FormField(field_id="quantity", field_type=FieldType.NUMBER, label={"en": "Quantity"}),
                    FormField(field_id="confirmed", field_type=FieldType.BOOLEAN, label={"en": "Confirmed"}),
                ],
            ),
        ],
    )


def _request(form_uid=None, *, query=None, body=None, content_type="application/json") -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": str(form_uid)} if form_uid else {}
    req.query = query or {}
    req.headers = {}
    req.get = MagicMock(side_effect=lambda key, default=None: TENANT if key == "tenant" else default)
    req.__contains__ = MagicMock(return_value=False)
    req.content_type = content_type
    req.content_length = len(json.dumps(body)) if body is not None else 0
    req.json = AsyncMock(return_value=body)
    req.app = {}
    req.session = {"session": {"programs": [TENANT]}}
    return req


@pytest.fixture(autouse=True)
def _a2ui_renderer():
    """Register the real A2UI renderer and restore the global registry afterwards."""
    snapshot = dict(_RENDERERS)
    register_renderer("a2ui", A2UIFormRenderer())
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


@pytest.fixture
async def handler():
    registry = FormRegistry()
    return FormAPIHandler(registry=registry)


def _projection(form: FormSchema) -> list:
    """Strict projection (AC9): structure, ids, types, required, options — never descriptions/dependencies."""

    def fields(items):
        out = []
        for item in items:
            if isinstance(item, FormSubsection):
                out.append(("sub", item.subsection_id, fields(item.fields)))
            else:
                out.append(
                    (
                        item.field_id,
                        item.field_type.value,
                        bool(item.required),
                        [o["value"] if isinstance(o, dict) else getattr(o, "value", o) for o in (item.options or [])],
                    )
                )
        return out

    return [(s.section_id, fields(s.fields)) for s in form.sections]


async def test_form_to_a2ui_to_form(handler):
    form = _form()
    await handler.registry.register(form, tenant=TENANT)

    resp = await handler.get_schema(_request(form.form_uid, query={"dialect": "a2ui"}))
    assert resp.status == 200
    envelope = json.loads(resp.body)

    resp = await handler.create_form(
        _request(query={"overwrite": "true"}, body=envelope, content_type="application/a2ui+json")
    )
    assert resp.status == 201, resp.body

    got = await handler.registry.get(form.form_uid, tenant=TENANT)
    assert got is not None
    assert _projection(got) == _projection(form)

    identity = await handler.get_form(_request(form.form_uid))
    assert json.loads(identity.body)["form_uid"] == str(form.form_uid)


async def test_jsonschema_to_a2ui_preserves_sections():
    rendered = await JsonSchemaRenderer().render(_form())
    surface = await translate_jsonschema_to_a2ui(rendered.content, tenant="navigator", renderer=A2UIFormRenderer())
    cards = [c for c in surface.content["createSurface"]["components"] if c["component"] == "Card"]
    assert [c["id"] for c in cards] == ["sec-s1", "sec-s2"]


async def test_export_then_import_tenant():
    src = FormRegistry(storage=None, default_tenant="a")
    for fid in ("x", "y"):
        await src.register(_form(fid, tenant="a"), tenant="a")
    rows = [r async for r in A2UIExportService(src, renderer=A2UIFormRenderer()).export_tenant("a")]
    dst = FormRegistry(storage=None, default_tenant="b")
    for r in rows:
        await dst.register(
            A2UIExtractor().extract(r.envelope, tenant="b").form.model_copy(update={"tenant": "b"}), tenant="b"
        )
    assert (
        sorted(f.form_id for f in await dst.list_forms(tenant="b")) == ["x", "y"]
        and await src.list_forms(tenant="b") == []
    )


async def test_fieldsync_golden_unchanged(handler):
    form = _golden_form()
    await handler.registry.register(form, tenant=TENANT)
    resp = await handler.get_schema(_request(form.form_uid))
    assert resp.status == 200
    assert json.loads(resp.body) == json.loads(GOLDEN.read_text())
