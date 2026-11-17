"""FEAT-730 — file upload on public forms without a session."""
import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web

from parrot_formdesigner.api.file_upload import handle_file_upload
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry

URL_TENANT = "acme"


def _form(*, is_public: bool) -> FormSchema:
    field = FormField(field_id="photo", field_type=FieldType.IMAGE, label={"en": "Photo"})
    return FormSchema(
        form_id="pub-upload",
        title={"en": "Pub"},
        sections=[FormSection(section_id="s1", fields=[field])],
        tenant=URL_TENANT,
        is_public=is_public,
    )


@pytest.fixture
def mock_blob_storage() -> MagicMock:
    storage = MagicMock()
    storage.put = AsyncMock(return_value="temp://bucket/test-blob")
    storage.delete = AsyncMock(return_value=None)
    return storage


def _wrapper(session: dict | None):
    async def _handler(request: web.Request) -> web.Response:
        # public-mode route: validates the URL tenant only, no membership at the route level
        request["tenant"] = request.match_info["tenant"]
        if session is not None:
            request.session = session
        return await handle_file_upload(request)

    return _handler


async def _client(aiohttp_client, form, storage, session):
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = storage
    app.router.add_post("/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload", _wrapper(session))
    return await aiohttp_client(app)


async def _post(client, form, headers=None):
    field = form.sections[0].fields[0]
    data = FormData()
    data.add_field("file", io.BytesIO(b"\x89PNG\r\n\x1a\nxx"), filename="a.png", content_type="image/png")
    return await client.post(
        f"/api/v1/{URL_TENANT}/forms/{form.form_uid}/fields/{field.field_uid}/file-upload",
        data=data,
        headers=headers or {},
    )


def _blob_tenant(storage: MagicMock) -> str | None:
    return storage.put.await_args.kwargs["metadata"].tenant


async def test_file_upload_public_form_no_session(aiohttp_client, mock_blob_storage):
    """Public form, no session -> 200; X-Parrot-Tenant ignored (blob tenant == URL tenant)."""
    form = _form(is_public=True)
    client = await _client(aiohttp_client, form, mock_blob_storage, None)
    resp = await _post(client, form, {"X-Parrot-Tenant": "evil"})
    assert resp.status == 200
    assert _blob_tenant(mock_blob_storage) == URL_TENANT


async def test_file_upload_public_form_header_ignored_with_session(aiohttp_client, mock_blob_storage):
    """Same result with a session: decided by the form, not the caller."""
    form = _form(is_public=True)
    session = {"session": {"programs": [URL_TENANT, "evil"]}}
    client = await _client(aiohttp_client, form, mock_blob_storage, session)
    resp = await _post(client, form, {"X-Parrot-Tenant": "evil"})
    assert resp.status == 200
    assert _blob_tenant(mock_blob_storage) == URL_TENANT


async def test_file_upload_private_requires_member(aiohttp_client, mock_blob_storage):
    """Private form, non-member -> 403; X-Parrot-Tenant still honoured for members."""
    form = _form(is_public=False)
    client = await _client(aiohttp_client, form, mock_blob_storage, None)
    resp = await _post(client, form)
    assert resp.status == 403
    mock_blob_storage.put.assert_not_called()

    member = {"session": {"programs": [URL_TENANT]}}
    client = await _client(aiohttp_client, form, mock_blob_storage, member)
    resp = await _post(client, form, {"X-Parrot-Tenant": "other-blob-tenant"})
    assert resp.status == 200
    assert _blob_tenant(mock_blob_storage) == "other-blob-tenant"
