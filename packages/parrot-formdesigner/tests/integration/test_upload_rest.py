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
    # Delete failure becomes a warning with the canonical prefix
    assert any("blob_cleanup_failed" in w for w in body.get("warnings", []))


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


# ---------------------------------------------------------------------------
# Backwards compatibility (FEAT-167 forms must still work unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_backwards_compat_existing_forms(
    aiohttp_client,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Pre-FEAT-170 forms (no REST fields) must load, validate, and route correctly.

    Ensures that the addition of FieldType.REST does not break any existing
    field types when the handler is asked to upload to a non-REST field.
    """
    from parrot_formdesigner.core.types import FieldType

    # Build a form using several pre-FEAT-170 field types
    text_field = FormField(
        field_id="name",
        field_type=FieldType.TEXT,
        label={"en": "Full Name"},
        required=True,
    )
    number_field = FormField(
        field_id="age",
        field_type=FieldType.NUMBER,
        label={"en": "Age"},
        required=False,
    )
    select_field = FormField(
        field_id="country",
        field_type=FieldType.SELECT,
        label={"en": "Country"},
        required=False,
    )

    legacy_form = FormSchema(
        form_id="legacy-form",
        title={"en": "Legacy Form"},
        sections=[
            FormSection(
                section_id="s1",
                fields=[text_field, number_field, select_field],
            )
        ],
    )

    client = await _make_client(aiohttp_client, legacy_form, mock_blob_storage, mock_resolver)

    # Trying to upload to a non-REST field must return 404 (not a server crash)
    data = FormData()
    data.add_field("file", io.BytesIO(b"ignored"), filename="f.jpg", content_type="image/jpeg")

    resp = await client.post(
        "/api/v1/forms/legacy-form/fields/name/upload",
        data=data,
    )
    # The handler must return 404 with a clear message (field is not FieldType.REST)
    assert resp.status == 404
    # Form integrity: all three legacy fields are still accessible via iteration
    field_ids = [
        item.field_id
        for section in legacy_form.sections
        for item in section.iter_fields()
    ]
    assert "name" in field_ids
    assert "age" in field_ids
    assert "country" in field_ids
    # REST field is NOT present (backwards compat: adding REST doesn't pollute others)
    assert "rest" not in field_ids


# ---------------------------------------------------------------------------
# Sequential uploads — last-write-wins (no state corruption)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_concurrent_uploads_last_write_wins(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_resolver: MagicMock,
) -> None:
    """Two sequential uploads to the same field must each produce independent blob refs.

    Validates the last-write-wins design: neither upload corrupts the other's
    blob reference. blob_storage.put() is called twice; each call returns a
    distinct blob_ref. The response envelope for each upload contains only
    its own blob_ref.
    """
    # Storage mock returns distinct refs on successive calls
    mock_blob_storage = MagicMock()
    mock_blob_storage.put = AsyncMock(
        side_effect=["s3://bucket/upload-1", "s3://bucket/upload-2"]
    )
    mock_blob_storage.delete = AsyncMock(return_value=None)

    client = await _make_client(aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver)

    async def _do_upload() -> dict:
        data = FormData()
        data.add_field(
            "file",
            io.BytesIO(b"photo bytes"),
            filename="photo.jpg",
            content_type="image/jpeg",
        )
        resp = await client.post(
            "/api/v1/forms/demo-form/fields/planogram_photo/upload",
            data=data,
        )
        assert resp.status == 200
        return await resp.json()

    body1 = await _do_upload()
    body2 = await _do_upload()

    # Both uploads succeed independently
    assert body1["success"] is True
    assert body2["success"] is True

    # Each gets its own blob_ref — no cross-contamination
    assert body1["blob_ref"] == "s3://bucket/upload-1"
    assert body2["blob_ref"] == "s3://bucket/upload-2"
    assert body1["blob_ref"] != body2["blob_ref"]

    # Storage was called exactly twice
    assert mock_blob_storage.put.call_count == 2


# ---------------------------------------------------------------------------
# Additional args (public / private)
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field_with_args() -> FormField:
    """REST field with public (tenant, n) and private (prompt) args."""
    return FormField(
        field_id="image_analyze",
        field_type=FieldType.REST,
        label={"en": "Image Analyze"},
        required=True,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "image_analyze",
                "additional_args": [
                    {
                        "name": "prompt",
                        "visibility": "private",
                        "value": "describe-this-image",
                    },
                    {
                        "name": "tenant",
                        "visibility": "public",
                        "required": True,
                    },
                    {
                        "name": "n",
                        "visibility": "public",
                        "data_type": "integer",
                        "value": 1,
                    },
                ],
            }
        },
    )


@pytest.fixture
def form_with_args(rest_field_with_args: FormField) -> FormSchema:
    return FormSchema(
        form_id="form-args",
        title={"en": "Args"},
        sections=[FormSection(section_id="s1", fields=[rest_field_with_args])],
    )


@pytest.mark.asyncio
async def test_upload_merges_public_and_private_args(
    aiohttp_client,
    form_with_args: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Resolver receives merged extra_fields: private from spec, public from form."""
    client = await _make_client(
        aiohttp_client, form_with_args, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"fake image"),
        filename="photo.jpg",
        content_type="image/jpeg",
    )
    data.add_field("tenant", "acme")
    data.add_field("n", "5")

    resp = await client.post(
        "/api/v1/forms/form-args/fields/image_analyze/upload",
        data=data,
    )
    assert resp.status == 200

    # Inspect the payload passed to resolver.resolve
    call_args = mock_resolver.resolve.call_args
    payload = call_args.args[1]
    assert payload.extra_fields == {
        "prompt": "describe-this-image",  # private from spec
        "tenant": "acme",                  # public coerced from form
        "n": 5,                            # public coerced int
    }


@pytest.mark.asyncio
async def test_upload_private_arg_cannot_be_overridden_by_frontend(
    aiohttp_client,
    form_with_args: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """A frontend-supplied value for a private arg is silently ignored."""
    client = await _make_client(
        aiohttp_client, form_with_args, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"x"),
        filename="x.jpg",
        content_type="image/jpeg",
    )
    data.add_field("tenant", "acme")
    data.add_field("prompt", "HACKED")  # attempt to override private arg

    resp = await client.post(
        "/api/v1/forms/form-args/fields/image_analyze/upload",
        data=data,
    )
    assert resp.status == 200

    payload = mock_resolver.resolve.call_args.args[1]
    assert payload.extra_fields["prompt"] == "describe-this-image"


@pytest.mark.asyncio
async def test_upload_missing_required_public_arg_returns_400(
    aiohttp_client,
    form_with_args: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Missing required public arg yields 400."""
    client = await _make_client(
        aiohttp_client, form_with_args, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"x"),
        filename="x.jpg",
        content_type="image/jpeg",
    )
    # 'tenant' is required but omitted

    resp = await client.post(
        "/api/v1/forms/form-args/fields/image_analyze/upload",
        data=data,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_upload_public_arg_falls_back_to_default(
    aiohttp_client,
    form_with_args: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Public arg with default 'n' uses the spec default when unsubmitted."""
    client = await _make_client(
        aiohttp_client, form_with_args, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"x"),
        filename="x.jpg",
        content_type="image/jpeg",
    )
    data.add_field("tenant", "acme")  # required, but skip 'n'

    resp = await client.post(
        "/api/v1/forms/form-args/fields/image_analyze/upload",
        data=data,
    )
    assert resp.status == 200

    payload = mock_resolver.resolve.call_args.args[1]
    assert payload.extra_fields["n"] == 1  # default from spec


@pytest.mark.asyncio
async def test_upload_invalid_data_type_returns_400(
    aiohttp_client,
    form_with_args: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """Non-integer value for an integer-typed public arg yields 400."""
    client = await _make_client(
        aiohttp_client, form_with_args, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field(
        "file",
        io.BytesIO(b"x"),
        filename="x.jpg",
        content_type="image/jpeg",
    )
    data.add_field("tenant", "acme")
    data.add_field("n", "not-a-number")

    resp = await client.post(
        "/api/v1/forms/form-args/fields/image_analyze/upload",
        data=data,
    )
    assert resp.status == 400
