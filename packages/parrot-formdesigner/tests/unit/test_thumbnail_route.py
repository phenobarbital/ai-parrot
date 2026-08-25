"""Unit tests for handle_get_thumbnail (FEAT-460, TASK-2469)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.file_upload import handle_get_thumbnail
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry

_TEST_TENANT = "test-tenant"


def _field_uid(form: FormSchema, field_id: str) -> uuid.UUID:
    for field in form.iter_fields_recursive():
        if field.field_id == field_id:
            return field.field_uid
    raise AssertionError(f"field_id {field_id!r} not found in form {form.form_id!r}")


def _make_form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="thumb-demo",
        title={"en": "Thumb Demo"},
        sections=[FormSection(section_id="s1", fields=list(fields))],
        tenant=_TEST_TENANT,
    )


async def _tenant_wrapped_thumbnail(request: web.Request) -> web.Response:
    request["tenant"] = request.match_info["tenant"]
    return await handle_get_thumbnail(request)


async def _make_client(aiohttp_client, form: FormSchema, blob_storage):
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = blob_storage
    app.router.add_get(
        "/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/thumbnail",
        _tenant_wrapped_thumbnail,
    )
    return await aiohttp_client(app)


class TestHandleGetThumbnail:
    @pytest.mark.asyncio
    async def test_returns_bytes_with_webp_content_type(self, aiohttp_client):
        field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
        form = _make_form(field)

        async def _stream():
            yield b"thumb-bytes"

        storage = MagicMock()
        storage.get = AsyncMock(return_value=_stream())
        client = await _make_client(aiohttp_client, form, storage)

        resp = await client.get(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'photo')}/thumbnail"
            "?ref=temp%3A%2F%2Fsome%2Fref",
        )
        assert resp.status == 200
        assert resp.content_type == "image/webp"
        assert await resp.read() == b"thumb-bytes"
        storage.get.assert_called_once_with("temp://some/ref")

    @pytest.mark.asyncio
    async def test_missing_ref_returns_404(self, aiohttp_client):
        field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
        form = _make_form(field)
        storage = MagicMock()
        client = await _make_client(aiohttp_client, form, storage)

        resp = await client.get(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'photo')}/thumbnail",
        )
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_storage_miss_returns_404_not_500(self, aiohttp_client):
        field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
        form = _make_form(field)
        storage = MagicMock()
        storage.get = AsyncMock(side_effect=FileNotFoundError("gone"))
        client = await _make_client(aiohttp_client, form, storage)

        resp = await client.get(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'photo')}/thumbnail"
            "?ref=temp%3A%2F%2Fmissing",
        )
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_non_upload_field_returns_404(self, aiohttp_client):
        field = FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"})
        form = _make_form(field)
        storage = MagicMock()
        client = await _make_client(aiohttp_client, form, storage)

        resp = await client.get(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'name')}/thumbnail"
            "?ref=temp%3A%2F%2Fanything",
        )
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_unknown_form_returns_404(self, aiohttp_client):
        field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
        form = _make_form(field)
        storage = MagicMock()
        client = await _make_client(aiohttp_client, form, storage)

        resp = await client.get(
            f"/api/v1/{_TEST_TENANT}/forms/{uuid.uuid4()}/fields/{_field_uid(form, 'photo')}/thumbnail"
            "?ref=temp%3A%2F%2Fanything",
        )
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_unknown_field_returns_404(self, aiohttp_client):
        field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
        form = _make_form(field)
        storage = MagicMock()
        client = await _make_client(aiohttp_client, form, storage)

        resp = await client.get(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{uuid.uuid4()}/thumbnail"
            "?ref=temp%3A%2F%2Fanything",
        )
        assert resp.status == 404
