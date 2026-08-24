"""End-to-end integration tests for the raw upload field types (FEAT-460).

Exercises the complete `/file-upload` pipeline (multipart -> MIME/size
check -> real TempBlobStorage -> FileEnvelope JSON) and the legacy
regression path (existing `submit_data` submission endpoint accepting
legacy string/dropzone/multi-upload shapes via the validator's dual-read
coercer).
"""

from __future__ import annotations

import io
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web
from parrot_formdesigner.api.file_upload import handle_file_upload
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.file_envelope import FileEnvelope
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.blob_storage import TempBlobStorage
from parrot_formdesigner.services.registry import FormRegistry
from PIL import Image

_TEST_TENANT = "test-tenant"


# ---------------------------------------------------------------------------
# Fixtures (spec §4)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_file_envelope():
    return {
        "filename": "report.pdf",
        "content_type": "application/pdf",
        "size": 183204,
        "blob_ref": "temp://form-uid/field-uid/blob-uuid",
        "data_url": None,
        "thumbnail_url": None,
        "checksum": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }


@pytest.fixture
def sample_image_envelope():
    return {
        "filename": "photo.jpg",
        "content_type": "image/jpeg",
        "size": 45000,
        "blob_ref": "temp://form-uid/field-uid/blob-uuid",
        "data_url": "data:image/jpeg;base64,/9j/4AAQ...",
        "thumbnail_url": "/api/v1/test-tenant/forms/form-uid/fields/field-uid/thumbnail/thumb-uuid",
        "checksum": "sha256:abc123...",
    }


@pytest.fixture
def legacy_dropzone_value():
    """Legacy IMAGE_DROPZONE shape that must still be accepted."""
    return {"name": "photo.jpg", "type": "image/jpeg", "size": 45000, "dataUrl": "data:image/jpeg;base64,AA=="}


@pytest.fixture
def legacy_multi_upload_value():
    """Legacy MULTI_UPLOAD shape that must still be accepted."""
    return [{"answer": "result", "blob_ref": "s3://bucket/key", "display": "photo.jpg"}]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _field_uid(form: FormSchema, field_id: str) -> uuid.UUID:
    for field in form.iter_fields_recursive():
        if field.field_id == field_id:
            return field.field_uid
    raise AssertionError(f"field_id {field_id!r} not found in form {form.form_id!r}")


def _make_form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="upload-e2e",
        title={"en": "Upload E2E"},
        sections=[FormSection(section_id="s1", fields=list(fields))],
        tenant=_TEST_TENANT,
    )


async def _tenant_wrapped_upload(request: web.Request) -> web.Response:
    request["tenant"] = request.match_info["tenant"]
    return await handle_file_upload(request)


async def _make_upload_client(aiohttp_client, form: FormSchema, blob_storage):
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = blob_storage
    app.router.add_post(
        "/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload",
        _tenant_wrapped_upload,
    )
    return await aiohttp_client(app)


def _jpeg_bytes(size=(800, 600), color="blue") -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TestFileUploadEndToEnd
# ---------------------------------------------------------------------------


class TestFileUploadEndToEnd:
    @pytest.mark.asyncio
    async def test_file_upload_returns_envelope(self, aiohttp_client):
        """Upload a PDF -> FileEnvelope with filename, content_type, size, blob_ref, checksum."""
        field = FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"})
        form = _make_form(field)
        blob_storage = TempBlobStorage()
        client = await _make_upload_client(aiohttp_client, form, blob_storage)

        data = FormData()
        content = b"%PDF-1.4 fake pdf content"
        data.add_field("file", io.BytesIO(content), filename="report.pdf", content_type="application/pdf")

        resp = await client.post(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload",
            data=data,
        )
        assert resp.status == 200
        body = await resp.json()

        # Validates against the real FileEnvelope model.
        envelope = FileEnvelope.model_validate(body)
        assert envelope.filename == "report.pdf"
        assert envelope.content_type == "application/pdf"
        assert envelope.size == len(content)
        assert envelope.blob_ref is not None
        assert envelope.checksum is not None and envelope.checksum.startswith("sha256:")

        # blob_ref is retrievable from the real blob storage.
        chunks = [chunk async for chunk in await blob_storage.get(envelope.blob_ref)]
        assert b"".join(chunks) == content

    @pytest.mark.asyncio
    async def test_image_upload_with_thumbnail(self, aiohttp_client):
        """Upload a JPEG -> FileEnvelope with thumbnail_url populated and retrievable."""
        field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
        form = _make_form(field)
        blob_storage = TempBlobStorage()
        client = await _make_upload_client(aiohttp_client, form, blob_storage)

        data = FormData()
        content = _jpeg_bytes()
        data.add_field("file", io.BytesIO(content), filename="photo.jpg", content_type="image/jpeg")

        resp = await client.post(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'photo')}/file-upload",
            data=data,
        )
        assert resp.status == 200
        body = await resp.json()
        envelope = FileEnvelope.model_validate(body)

        assert envelope.thumbnail_url is not None
        thumb_chunks = [chunk async for chunk in await blob_storage.get(envelope.thumbnail_url)]
        thumb_bytes = b"".join(thumb_chunks)
        thumb_img = Image.open(BytesIO(thumb_bytes))
        assert thumb_img.width <= 150
        assert thumb_img.height <= 150

    @pytest.mark.asyncio
    async def test_multi_file_upload(self, aiohttp_client):
        """Upload 3 files to MULTI_UPLOAD -> list of 3 FileEnvelopes."""
        field = FormField(field_id="gallery", field_type=FieldType.MULTI_UPLOAD, label={"en": "Gallery"})
        form = _make_form(field)
        blob_storage = TempBlobStorage()
        client = await _make_upload_client(aiohttp_client, form, blob_storage)

        data = FormData()
        for i in range(3):
            data.add_field(
                "file", io.BytesIO(f"content-{i}".encode()), filename=f"f{i}.txt", content_type="text/plain"
            )

        resp = await client.post(
            f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'gallery')}/file-upload",
            data=data,
        )
        assert resp.status == 200
        body = await resp.json()
        assert isinstance(body, list)
        assert len(body) == 3
        for item in body:
            FileEnvelope.model_validate(item)

    @pytest.mark.asyncio
    async def test_chunked_upload(self, aiohttp_client):
        """Upload in 2 chunks -> assembled file -> FileEnvelope."""
        field = FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"})
        form = _make_form(field)
        blob_storage = TempBlobStorage()
        client = await _make_upload_client(aiohttp_client, form, blob_storage)

        full_content = b"A" * 40 + b"B" * 40
        chunk1, chunk2 = full_content[:40], full_content[40:]
        url = f"/api/v1/{_TEST_TENANT}/forms/{form.form_uid}/fields/{_field_uid(form, 'doc')}/file-upload"

        resp1 = await client.post(
            url,
            data=chunk1,
            headers={
                "X-Parrot-Upload-Offset": "0",
                "X-Parrot-Upload-Length": str(len(full_content)),
                "Content-Type": "application/octet-stream",
            },
        )
        assert resp1.status == 202

        resp2 = await client.post(
            url,
            data=chunk2,
            headers={
                "X-Parrot-Upload-Offset": "40",
                "X-Parrot-Upload-Length": str(len(full_content)),
                "X-Parrot-Upload-Content-Type": "text/plain",
                "Content-Type": "application/octet-stream",
            },
        )
        assert resp2.status == 200
        body = await resp2.json()
        envelope = FileEnvelope.model_validate(body)
        assert envelope.size == len(full_content)

        chunks = [chunk async for chunk in await blob_storage.get(envelope.blob_ref)]
        assert b"".join(chunks) == full_content


# ---------------------------------------------------------------------------
# TestLegacyRegression — via the EXISTING submission endpoint (submit_data),
# not the new /file-upload endpoint.
# ---------------------------------------------------------------------------


def _make_submit_request(form_uid: uuid.UUID, body: dict) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": str(form_uid)}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body)
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    return req


def _make_submit_handler(form: FormSchema) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    # Real FormValidator (unmocked) — this is exactly what's under test:
    # the dual-read coercer's backward compatibility.
    return FormAPIHandler(registry=registry)


class TestLegacyRegression:
    @pytest.mark.asyncio
    async def test_legacy_string_file_accepted(self):
        """Submit form with legacy string FILE value -> no validation errors."""
        field = FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"})
        form = _make_form(field)
        handler = _make_submit_handler(form)

        request = _make_submit_request(form.form_uid, {"doc": "https://example.com/legacy-file.pdf"})
        resp = await handler.submit_data(request)
        assert resp.status != 422, f"legacy string FILE value was rejected: {resp.body}"

    @pytest.mark.asyncio
    async def test_legacy_dropzone_shape_accepted(self, legacy_dropzone_value):
        """Submit form with legacy {name,type,size,dataUrl} -> accepted."""
        field = FormField(field_id="photo", field_type=FieldType.IMAGE_DROPZONE, label={"en": "Photo"})
        form = _make_form(field)
        handler = _make_submit_handler(form)

        request = _make_submit_request(form.form_uid, {"photo": legacy_dropzone_value})
        resp = await handler.submit_data(request)
        assert resp.status != 422, f"legacy dropzone value was rejected: {resp.body}"

    @pytest.mark.asyncio
    async def test_legacy_multi_upload_shape_accepted(self, legacy_multi_upload_value):
        """Submit form with legacy [{answer,blob_ref,display}] -> accepted."""
        field = FormField(field_id="gallery", field_type=FieldType.MULTI_UPLOAD, label={"en": "Gallery"})
        form = _make_form(field)
        handler = _make_submit_handler(form)

        request = _make_submit_request(form.form_uid, {"gallery": legacy_multi_upload_value})
        resp = await handler.submit_data(request)
        assert resp.status != 422, f"legacy multi-upload value was rejected: {resp.body}"
