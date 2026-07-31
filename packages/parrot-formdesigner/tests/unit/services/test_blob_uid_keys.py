"""Unit tests for FEAT-393 Module 8 — blob storage keys + upload route on field_uid.

Spec §4 Module 8 (TASK-2002). Covers the dedicated Test Specification rows:

* ``test_build_key_uses_uids`` — object keys embed form_uid/field_uid, never
  the editable form_id/field_id slugs.
* ``test_legacy_ref_still_resolvable`` — refs built under the pre-FEAT-393
  key shape must still round-trip through ``_from_ref`` (opaque parsing,
  unchanged).
* ``test_upload_route_invalid_uuid_400`` — malformed field_uid path segment
  yields 400.
* ``test_upload_route_unknown_uid_404`` — well-formed but unknown field_uid
  yields 404.
* ``test_upload_metadata_carries_both_ids`` — BlobMetadata built by the
  upload handler carries both field_uid (identity) and field_id (label).
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web

from parrot_formdesigner.api.uploads import handle_rest_upload
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.blob_storage import BlobMetadata, LocalBlobStorage
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.rest_field_resolver import RestFieldResult

_TEST_FORM_UID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
_TEST_FIELD_UID = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _make_metadata(**kwargs) -> BlobMetadata:
    defaults = dict(
        form_uid=_TEST_FORM_UID,
        form_id="form1",
        field_uid=_TEST_FIELD_UID,
        field_id="photo",
        content_type="image/jpeg",
        size_bytes=5,
    )
    defaults.update(kwargs)
    return BlobMetadata(**defaults)


# ---------------------------------------------------------------------------
# _build_key / _from_ref
# ---------------------------------------------------------------------------


def test_build_key_uses_uids(tmp_path: Path) -> None:
    """_build_key() keys new blobs on form_uid/field_uid, never the editable
    form_id/field_id slugs (FEAT-393)."""
    storage = LocalBlobStorage(base_path=tmp_path)
    meta = _make_metadata()
    key = storage._build_key(meta)
    assert key.startswith(f"{_TEST_FORM_UID}/{_TEST_FIELD_UID}/")
    assert "form1" not in key
    assert "photo" not in key


def test_legacy_ref_still_resolvable(tmp_path: Path) -> None:
    """Refs written under the pre-FEAT-393 {form_id}/{field_id}/{blob_id}
    key shape must still resolve through `_from_ref` — it parses opaquely
    and is explicitly unchanged by this task."""
    storage = LocalBlobStorage(base_path=tmp_path)
    legacy_key = "legacy-form/legacy-field/abc123"
    legacy_ref = storage._to_ref(legacy_key)
    assert storage._from_ref(legacy_ref) == legacy_key


# ---------------------------------------------------------------------------
# Upload route — field_uid path param
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field() -> FormField:
    return FormField(
        field_id="planogram_photo",
        field_type=FieldType.REST,
        label={"en": "Planogram Photo"},
        required=True,
        meta={"rest": {"mode": "callback", "callback_ref": "planogram_compliance"}},
    )


@pytest.fixture
def form_with_rest(rest_field: FormField) -> FormSchema:
    return FormSchema(
        form_id="demo-form",
        title={"en": "Demo"},
        sections=[FormSection(section_id="s1", fields=[rest_field])],
        tenant="navigator",
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
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = mock_storage
    app["rest_resolver"] = mock_resolver
    app.router.add_post(
        "/api/v1/forms/{form_uid}/fields/{field_uid}/upload",
        handle_rest_upload,
    )
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_upload_route_invalid_uuid_400(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """A field_uid path segment that is not a well-formed UUID yields 400."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field("file", io.BytesIO(b"x"), filename="x.jpg", content_type="image/jpeg")

    resp = await client.post(
        f"/api/v1/forms/{form_with_rest.form_uid}/fields/not-a-uuid/upload",
        data=data,
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_upload_route_unknown_uid_404(
    aiohttp_client,
    form_with_rest: FormSchema,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """A well-formed field_uid that matches no field in the form yields 404."""
    client = await _make_client(
        aiohttp_client, form_with_rest, mock_blob_storage, mock_resolver
    )

    data = FormData()
    data.add_field("file", io.BytesIO(b"x"), filename="x.jpg", content_type="image/jpeg")

    unknown_uid = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/forms/{form_with_rest.form_uid}/fields/{unknown_uid}/upload",
        data=data,
    )
    assert resp.status == 404


@pytest.mark.asyncio
async def test_upload_metadata_carries_both_ids(
    aiohttp_client,
    form_with_rest: FormSchema,
    rest_field: FormField,
    mock_blob_storage: MagicMock,
    mock_resolver: MagicMock,
) -> None:
    """BlobMetadata built for a successful upload carries both the immutable
    field_uid and the human-readable field_id."""
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
        f"/api/v1/forms/{form_with_rest.form_uid}/fields/{rest_field.field_uid}/upload",
        data=data,
    )
    assert resp.status == 200

    mock_blob_storage.put.assert_called_once()
    _, kwargs = mock_blob_storage.put.call_args
    metadata: BlobMetadata = kwargs["metadata"]
    assert metadata.field_uid == rest_field.field_uid
    assert metadata.field_id == "planogram_photo"
    assert metadata.form_uid == form_with_rest.form_uid
