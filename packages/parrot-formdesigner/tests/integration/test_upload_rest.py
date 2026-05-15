"""Integration tests for POST /forms/{form_id}/fields/{field_id}/upload (FEAT-170)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

from parrot_formdesigner.api.uploads import handle_rest_upload
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.blob_storage import BlobRejectedError
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.rest_field_resolver import RestFieldResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rest_field(
    field_id: str = "doc",
    rest_meta: dict | None = None,
    constraints: FieldConstraints | None = None,
) -> FormField:
    return FormField(
        field_id=field_id,
        field_type=FieldType.REST,
        label="Document",
        meta={"rest": rest_meta or {"mode": "callback", "callback_ref": "my_cb"}},
        constraints=constraints,
    )


def _make_form(field: FormField, form_id: str = "f1") -> FormSchema:
    return FormSchema(
        form_id=form_id,
        title="Test",
        sections=[FormSection(section_id="s1", fields=[field])],
    )


@asynccontextmanager
async def _client(form: FormSchema, *, blob_storage=None, rest_resolver=None):
    registry = FormRegistry()
    await registry.register(form)
    app = web.Application()
    app["form_registry"] = registry
    if blob_storage is not None:
        app["blob_storage"] = blob_storage
    if rest_resolver is not None:
        app["rest_resolver"] = rest_resolver
    app.router.add_post(
        "/api/v1/forms/{form_id}/fields/{field_id}/upload",
        handle_rest_upload,
    )
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def _ok_result(**kwargs) -> RestFieldResult:
    return RestFieldResult(success=True, raw_value="ok", **kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_upload_happy_path_callback():
    """Callback mode: resolver invoked, envelope returned with blob_ref."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result(answer="processed"))

    blob_storage = AsyncMock()
    blob_storage.put = AsyncMock(return_value="s3://bucket/key")
    blob_storage.delete = AsyncMock()

    field = _rest_field(rest_meta={"mode": "callback", "callback_ref": "cb"})
    async with _client(_make_form(field), blob_storage=blob_storage, rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"hello"), filename="test.bin", content_type="application/octet-stream"
        )
        resp = await c.post("/api/v1/forms/f1/fields/doc/upload", data=data)
        assert resp.status == 200
        body = await resp.json()
        assert body["success"] is True
        assert body["answer"] == "processed"
        assert body["blob_ref"] == "s3://bucket/key"
        resolver.resolve.assert_called_once()


async def test_upload_413_too_large():
    """Upload exceeding max_file_size_bytes → 413."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result())
    field = _rest_field(
        constraints=FieldConstraints(max_file_size_bytes=5),
        rest_meta={"mode": "callback", "callback_ref": "cb"},
    )
    async with _client(_make_form(field), rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"x" * 100), filename="big.bin", content_type="application/octet-stream"
        )
        resp = await c.post("/api/v1/forms/f1/fields/doc/upload", data=data)
        assert resp.status == 413


async def test_upload_415_wrong_mime():
    """MIME not in allowed list → 415."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result())
    field = _rest_field(
        constraints=FieldConstraints(allowed_mime_types=["image/png"]),
        rest_meta={"mode": "callback", "callback_ref": "cb"},
    )
    async with _client(_make_form(field), rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"pdf bytes"), filename="doc.pdf", content_type="application/pdf"
        )
        resp = await c.post("/api/v1/forms/f1/fields/doc/upload", data=data)
        assert resp.status == 415


async def test_upload_prior_blob_deleted():
    """X-Parrot-Prior-Blob-Ref triggers delete on blob_storage."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result())

    blob_storage = AsyncMock()
    blob_storage.put = AsyncMock(return_value="s3://bucket/new-key")
    blob_storage.delete = AsyncMock()

    field = _rest_field(rest_meta={"mode": "callback", "callback_ref": "cb"})
    async with _client(_make_form(field), blob_storage=blob_storage, rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"data"), filename="f.bin", content_type="application/octet-stream"
        )
        resp = await c.post(
            "/api/v1/forms/f1/fields/doc/upload",
            data=data,
            headers={"X-Parrot-Prior-Blob-Ref": "s3://bucket/old-key"},
        )
        assert resp.status == 200
        blob_storage.delete.assert_called_once_with("s3://bucket/old-key")


async def test_upload_prior_blob_delete_failure_becomes_warning():
    """Failed prior-blob delete → 200 with warning in envelope."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result())

    blob_storage = AsyncMock()
    blob_storage.put = AsyncMock(return_value="s3://bucket/new-key")
    blob_storage.delete = AsyncMock(side_effect=Exception("S3 error"))

    field = _rest_field(rest_meta={"mode": "callback", "callback_ref": "cb"})
    async with _client(_make_form(field), blob_storage=blob_storage, rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"data"), filename="f.bin", content_type="application/octet-stream"
        )
        resp = await c.post(
            "/api/v1/forms/f1/fields/doc/upload",
            data=data,
            headers={"X-Parrot-Prior-Blob-Ref": "s3://bucket/old"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert any("prior_blob_delete_failed" in w for w in body["warnings"])


async def test_upload_404_form_not_found():
    """Unknown form_id → 404."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result())
    field = _rest_field()
    async with _client(_make_form(field), rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"x"), filename="x.bin", content_type="application/octet-stream"
        )
        resp = await c.post("/api/v1/forms/MISSING/fields/doc/upload", data=data)
        assert resp.status == 404


async def test_upload_404_non_rest_field():
    """Field that is not FieldType.REST → 404."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result())
    form = FormSchema(
        form_id="f1",
        title="T",
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name")],
            )
        ],
    )
    async with _client(form, rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"x"), filename="x.bin", content_type="application/octet-stream"
        )
        resp = await c.post("/api/v1/forms/f1/fields/name/upload", data=data)
        assert resp.status == 404


async def test_upload_resolver_failure_returns_200_success_false():
    """Resolver returning success=False → 200 envelope with success: false (not 500)."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(
        return_value=RestFieldResult(success=False, error="callback not registered")
    )
    field = _rest_field()
    async with _client(_make_form(field), rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"data"), filename="f.bin", content_type="application/octet-stream"
        )
        resp = await c.post("/api/v1/forms/f1/fields/doc/upload", data=data)
        assert resp.status == 200
        body = await resp.json()
        assert body["success"] is False
        assert "callback not registered" in body["error"]


async def test_upload_blob_rejected_returns_400():
    """BlobRejectedError from pre-persist hook → 400."""
    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=_ok_result())

    blob_storage = AsyncMock()
    blob_storage.put = AsyncMock(side_effect=BlobRejectedError("virus detected"))

    field = _rest_field()
    async with _client(_make_form(field), blob_storage=blob_storage, rest_resolver=resolver) as c:
        data = FormData()
        data.add_field(
            "file", BytesIO(b"bad"), filename="f.bin", content_type="application/octet-stream"
        )
        resp = await c.post("/api/v1/forms/f1/fields/doc/upload", data=data)
        assert resp.status == 400
