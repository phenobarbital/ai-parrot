"""Unit/integration tests for handle_file_upload (FEAT-460)."""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web
from parrot_formdesigner.api.file_upload import handle_file_upload
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


def _field_uid(form: FormSchema, field_id: str) -> uuid.UUID:
    for field in form.iter_fields_recursive():
        if field.field_id == field_id:
            return field.field_uid
    raise AssertionError(f"field_id {field_id!r} not found in form {form.form_id!r}")


def _make_form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="upload-demo",
        title={"en": "Upload Demo"},
        sections=[FormSection(section_id="s1", fields=list(fields))],
        tenant="navigator",
    )


@pytest.fixture
def mock_blob_storage() -> MagicMock:
    storage = MagicMock()
    storage.put = AsyncMock(return_value="temp://bucket/test-blob")
    storage.delete = AsyncMock(return_value=None)
    return storage


async def _tenant_wrapped_upload(request: web.Request) -> web.Response:
    request["tenant"] = request.match_info["tenant"]
    return await handle_file_upload(request)


async def _make_client(aiohttp_client, form: FormSchema, mock_storage, thumbnail_service=None):
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = mock_storage
    if thumbnail_service is not None:
        app["thumbnail_service"] = thumbnail_service
    app.router.add_post(
        "/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload",
        _tenant_wrapped_upload,
    )
    return await aiohttp_client(app)


def _file_data(filename="report.pdf", content_type="application/pdf", content=b"hello world"):
    data = FormData()
    data.add_field("file", io.BytesIO(content), filename=filename, content_type=content_type)
    return data


class TestFileUploadHandler:
    @pytest.mark.asyncio
    async def test_upload_single_file_returns_envelope(self, aiohttp_client, mock_blob_storage):
        field = FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"})
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=_file_data(),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["filename"] == "report.pdf"
        assert body["content_type"] == "application/pdf"
        assert body["size"] == len(b"hello world")
        assert body["blob_ref"] == "temp://bucket/test-blob"
        assert body["checksum"].startswith("sha256:")

    @pytest.mark.asyncio
    async def test_upload_multiple_files_multi_upload(self, aiohttp_client, mock_blob_storage):
        field = FormField(field_id="gallery", field_type=FieldType.MULTI_UPLOAD, label={"en": "Gallery"})
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        data = FormData()
        data.add_field("file", io.BytesIO(b"one"), filename="a.txt", content_type="text/plain")
        data.add_field("file", io.BytesIO(b"two"), filename="b.txt", content_type="text/plain")

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/" f"{_field_uid(form, 'gallery')}/file-upload",
            data=data,
        )
        assert resp.status == 200
        body = await resp.json()
        assert isinstance(body, list)
        assert len(body) == 2

    @pytest.mark.asyncio
    async def test_single_cardinality_rejects_multi(self, aiohttp_client, mock_blob_storage):
        field = FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"})
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        data = FormData()
        data.add_field("file", io.BytesIO(b"one"), filename="a.txt", content_type="text/plain")
        data.add_field("file", io.BytesIO(b"two"), filename="b.txt", content_type="text/plain")

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=data,
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_mime_rejected(self, aiohttp_client, mock_blob_storage):
        field = FormField(
            field_id="photo",
            field_type=FieldType.IMAGE,
            label={"en": "Photo"},
            constraints=FieldConstraints(allowed_mime_types=["image/png"]),
        )
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'photo')}/file-upload",
            data=_file_data(filename="photo.jpg", content_type="image/jpeg", content=b"jpegbytes"),
        )
        assert resp.status == 415

    @pytest.mark.asyncio
    async def test_size_exceeded(self, aiohttp_client, mock_blob_storage):
        field = FormField(
            field_id="doc",
            field_type=FieldType.FILE,
            label={"en": "Doc"},
            constraints=FieldConstraints(max_file_size_bytes=5),
        )
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=_file_data(content=b"this content is way over five bytes"),
        )
        assert resp.status == 413

    @pytest.mark.asyncio
    async def test_non_upload_field_type(self, aiohttp_client, mock_blob_storage):
        field = FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"})
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'name')}/file-upload",
            data=_file_data(),
        )
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_data_url_under_threshold(self, aiohttp_client, mock_blob_storage):
        field = FormField(
            field_id="doc",
            field_type=FieldType.FILE,
            label={"en": "Doc"},
            constraints=FieldConstraints(max_inline_size_bytes=1024),
        )
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=_file_data(content=b"short"),
        )
        body = await resp.json()
        assert body["data_url"] is not None
        assert body["data_url"].startswith("data:application/pdf;base64,")

    @pytest.mark.asyncio
    async def test_data_url_over_threshold(self, aiohttp_client, mock_blob_storage):
        field = FormField(
            field_id="doc",
            field_type=FieldType.FILE,
            label={"en": "Doc"},
            constraints=FieldConstraints(max_inline_size_bytes=2),
        )
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=_file_data(content=b"this is longer than two bytes"),
        )
        body = await resp.json()
        assert body["data_url"] is None

    @pytest.mark.asyncio
    async def test_checksum_computed(self, aiohttp_client, mock_blob_storage):
        field = FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"})
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=_file_data(),
        )
        body = await resp.json()
        assert body["checksum"].startswith("sha256:")

    @pytest.mark.asyncio
    async def test_thumbnail_for_image(self, aiohttp_client, mock_blob_storage):
        thumbnail_service = MagicMock()
        thumbnail_service.generate = AsyncMock(return_value="temp://thumb-ref")

        field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage, thumbnail_service)

        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'photo')}/file-upload",
            data=_file_data(filename="photo.jpg", content_type="image/jpeg", content=b"jpegbytes"),
        )
        body = await resp.json()
        # thumbnail_url is a fetchable path under handle_get_thumbnail
        # (TASK-2469), not the raw blob_ref — the ref is URL-encoded in
        # the 'ref' query parameter.
        assert body["thumbnail_url"] == (
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'photo')}"
            "/thumbnail?ref=temp%3A%2F%2Fthumb-ref"
        )
        thumbnail_service.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_prior_blob_cleanup(self, aiohttp_client, mock_blob_storage):
        field = FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"})
        form = _make_form(field)
        client = await _make_client(aiohttp_client, form, mock_blob_storage)

        await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=_file_data(),
            headers={"X-Parrot-Prior-Blob-Ref": "temp://bucket/old-blob"},
        )
        mock_blob_storage.delete.assert_called_once_with("temp://bucket/old-blob")
