"""Integration tests for POST /api/v1/forms/{form_id}/fields/{field_id}/upload.

Tests the full upload pipeline via aiohttp test client (no real S3 or
external network). All blob storage and resolver calls are mocked.
"""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import FormData, web

from parrot_formdesigner.api.uploads import handle_rest_upload
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.rest_field_resolver import RestFieldResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field_callback() -> FormField:
    return FormField(
        field_id="planogram_photo",
        field_type=FieldType.REST,
        label={"en": "Planogram Photo"},
        required=True,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "planogram_compliance",
            }
        },
    )


@pytest.fixture
def form_with_rest(rest_field_callback: FormField) -> FormSchema:
    return FormSchema(
        form_id="demo-form",
        title={"en": "Demo"},
        sections=[FormSection(section_id="s1", fields=[rest_field_callback])],
    )


@pytest.fixture
def mock_blob_storage() -> MagicMock:
    storage = MagicMock()
    storage.put = AsyncMock(return_value="s3://bucket/test-blob")
    storage.delete = AsyncMock(return_value=None)
    return storage


@pytest.fixture
def mock_resolver() -> MagicMock:
    resolver = MagicMock()
    resolver.resolve = AsyncMock(
        return_value=RestFieldResult(
            success=True,
            raw_value=0.92,
            answer=0.92,
            blob_ref="s3://bucket/test-blob",
            display="Compliance: 92/100",
            warnings=[],
            error=None,
        )
    )
    return resolver


async def _make_client(aiohttp_client, form: FormSchema, mock_storage, mock_resolver):
    """Create a test client with the upload route and mocked services."""
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = mock_storage
    app["rest_resolver"] = mock_resolver
    app.router.add_post(
        "/api/v1/forms/{form_id}/fields/{field_id}/upload",
        handle_rest_upload,
    )
    return await aiohttp_client(app)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_callback_happy_path(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Happy path: multipart upload returns success=True envelope."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"fake image bytes"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )

    resp = await client.post(
        "/api/v1/forms/demo-form/fields/planogram_photo/upload",
        data=data,
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert body["blob_ref"] == "s3://bucket/test-blob"


@pytest.mark.asyncio
async def test_upload_blob_stored(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """blob_storage.put must be called once for a successful upload."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"fake image bytes"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )

    await client.post(
        "/api/v1/forms/demo-form/fields/planogram_photo/upload",
        data=data,
    )
    mock_blob_storage.put.assert_called_once()


@pytest.mark.asyncio
async def test_upload_prior_blob_deleted(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Prior blob must be deleted when X-Parrot-Prior-Blob-Ref header is present."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"fake image bytes"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )

    await client.post(
        "/api/v1/forms/demo-form/fields/planogram_photo/upload",
        data=data,
        headers={"X-Parrot-Prior-Blob-Ref": "s3://bucket/old-blob"},
    )
    mock_blob_storage.delete.assert_called_once_with("s3://bucket/old-blob")


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_404_unknown_form(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """404 when form_id is not in registry."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field("file", io.BytesIO(b"x"), filename="x.jpg", content_type="image/jpeg")

    resp = await client.post(
        "/api/v1/forms/nonexistent/fields/planogram_photo/upload",
        data=data,
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_upload_404_unknown_field(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """404 when field_id is not in the form."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field("file", io.BytesIO(b"x"), filename="x.jpg", content_type="image/jpeg")

    resp = await client.post(
        "/api/v1/forms/demo-form/fields/nonexistent_field/upload",
        data=data,
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_upload_400_no_file_part(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """400 when multipart body has no 'file' part."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field("other_field", "not a file")

    resp = await client.post(
        "/api/v1/forms/demo-form/fields/planogram_photo/upload",
        data=data,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_upload_415_disallowed_mime(
    aiohttp_client,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """415 when MIME type is not in allowed list."""
    from parrot_formdesigner.core.schema import FieldConstraints

    field = FormField(
        field_id="photo",
        field_type=FieldType.REST,
        label={"en": "Photo"},
        required=False,
        constraints=FieldConstraints(allowed_mime_types=["image/jpeg", "image/png"]),
        meta={"rest": {"mode": "callback", "callback_ref": "cb"}},
    )
    form = FormSchema(
        form_id="demo-form",
        title={"en": "Demo"},
        sections=[FormSection(section_id="s1", fields=[field])],
    )

    client = await _make_client(aiohttp_client, form, mock_blob_storage, mock_resolver)

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"<html></html>"),
        filename="page.html",
        content_type="text/html",
    )

    resp = await client.post(
        "/api/v1/forms/demo-form/fields/photo/upload",
        data=data,
    )
    assert resp.status == 415


@pytest.mark.asyncio
async def test_upload_delete_failure_appends_warning(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Delete failure must append a warning string, not 500."""
    mock_blob_storage.delete = AsyncMock(side_effect=RuntimeError("delete failed"))

    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"fake image bytes"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )

    resp = await client.post(
        "/api/v1/forms/demo-form/fields/planogram_photo/upload",
        data=data,
        headers={"X-Parrot-Prior-Blob-Ref": "s3://bucket/old-blob"},
    )
    assert resp.status == 200
    body = await resp.json()
    # Delete failure becomes a warning, not an error
    assert any("delete" in w.lower() for w in body.get("warnings", []))


@pytest.mark.asyncio
async def test_upload_resolver_failure_returns_200_with_success_false(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
) -> None:
    """Resolver failure (success=False) maps to 200 envelope, NOT 500."""
    failing_resolver = MagicMock()
    failing_resolver.resolve = AsyncMock(
        return_value=RestFieldResult(
            success=False,
            raw_value=None,
            answer=None,
            blob_ref=None,
            display=None,
            warnings=[],
            error="callback not found",
        )
    )

    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, failing_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"fake image bytes"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )

    resp = await client.post(
        "/api/v1/forms/demo-form/fields/planogram_photo/upload",
        data=data,
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is False
    assert body["error"] is not None
