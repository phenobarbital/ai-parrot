"""FEAT-731 — /file-upload records pending uploads."""

from __future__ import annotations

import io
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import FormData, web
from parrot_formdesigner.api.file_upload import _thumbnail_ref, handle_file_upload
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry


def _form(*fields: FormField, is_public: bool = False) -> FormSchema:
    return FormSchema(
        form_id="upload-demo",
        title={"en": "Upload Demo"},
        sections=[FormSection(section_id="s1", fields=list(fields))],
        tenant="navigator",
        is_public=is_public,
    )


def _fuid(form: FormSchema, field_id: str):
    return next(f.field_uid for f in form.iter_fields_recursive() if f.field_id == field_id)


class FakePending:
    def __init__(self, fail: bool = False) -> None:
        self.recorded: list[tuple] = []
        self.deleted: list[tuple] = []
        self.fail = fail

    async def record(self, entry, *, tenant):
        if self.fail:
            raise RuntimeError("db down")
        self.recorded.append((entry, tenant))

    async def delete_rows(self, refs, *, tenant):
        self.deleted.append((list(refs), tenant))
        return len(list(refs))


@pytest.fixture
def storage() -> MagicMock:
    counter = {"n": 0}

    async def put(stream, *, metadata):
        counter["n"] += 1
        return f"temp://bucket/blob-{counter['n']}"

    s = MagicMock()
    s.put = AsyncMock(side_effect=put)
    s.delete = AsyncMock(return_value=None)
    return s


async def _upload(request: web.Request) -> web.Response:
    request["tenant"] = request.match_info["tenant"]
    if request.headers.get("X-Test-Session"):
        request["user"] = object()
    return await handle_file_upload(request)


async def _client(aiohttp_client, form, storage, pending, thumbs=None):
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = storage
    if pending is not None:
        app["form_pending_uploads"] = pending
    if thumbs is not None:
        app["thumbnail_service"] = thumbs
    app.router.add_post("/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload", _upload)
    return await aiohttp_client(app)


def _data(*names: str, content_type="application/pdf") -> FormData:
    data = FormData()
    for name in names:
        data.add_field("file", io.BytesIO(b"x" + name.encode()), filename=name, content_type=content_type)
    return data


def _url(form, field_id, tenant="navigator"):
    return f"/api/v1/{tenant}/forms/{form.form_uid}/fields/{_fuid(form, field_id)}/file-upload"


def test_thumbnail_ref_from_url():
    url = "/x/fields/y/thumbnail?ref=" + "temp%3A%2F%2Fthumb-ref"
    assert _thumbnail_ref(url) == "temp://thumb-ref"
    assert _thumbnail_ref(None) is None
    assert _thumbnail_ref("/x/thumbnail") is None
    assert _thumbnail_ref("/x/thumbnail?ref=") is None


async def test_upload_records_pending(aiohttp_client, storage):
    single = FormField(field_id="doc", field_type=FieldType.IMAGE, label={"en": "Doc"})
    multi = FormField(field_id="pics", field_type=FieldType.IMAGE_DROPZONE, label={"en": "Pics"})
    thumbs = MagicMock()
    thumbs.generate = AsyncMock(side_effect=lambda b, m: f"temp://thumb/{len(b)}")
    pending = FakePending()
    form = _form(single, multi, is_public=True)
    client = await _client(aiohttp_client, form, storage, pending, thumbs)

    resp = await client.post(
        _url(form, "doc"), data=_data("a.png", content_type="image/png"), headers={"X-Parrot-Tenant": "other"}
    )
    assert resp.status == 200
    body = await resp.json()
    assert len(pending.recorded) == 1
    entry, tenant = pending.recorded[0]
    assert tenant == "navigator" and entry.tenant == "navigator"  # URL tenant, NOT X-Parrot-Tenant
    assert entry.blob_ref == body["blob_ref"]
    assert entry.thumbnail_ref == f"temp://thumb/{len(b'xa.png')}"
    assert entry.form_uid == form.form_uid and entry.field_uid == _fuid(form, "doc")
    assert entry.public_form is True

    resp = await client.post(
        _url(form, "pics"),
        data=_data("b.png", "c.png", content_type="image/png"),
        headers={"X-Test-Session": "1"},
    )
    assert resp.status == 200
    assert len(await resp.json()) == 2
    assert len(pending.recorded) == 3
    assert {e.blob_ref for e, _ in pending.recorded[1:]} == {"temp://bucket/blob-2", "temp://bucket/blob-3"}
    # same public_form value with and without a session: decided by the form
    assert {e.public_form for e, _ in pending.recorded} == {True}


async def test_non_public_form_records_false(aiohttp_client, storage):
    form = _form(FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"}))
    pending = FakePending()
    client = await _client(aiohttp_client, form, storage, pending)
    resp = await client.post(_url(form, "doc"), data=_data("a.pdf"))
    assert resp.status == 200
    assert pending.recorded[0][0].public_form is False
    assert pending.recorded[0][0].thumbnail_ref is None


async def test_upload_record_failure_is_soft(aiohttp_client, storage, caplog):
    form = _form(FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"}))
    client = await _client(aiohttp_client, form, storage, FakePending(fail=True))
    with caplog.at_level(logging.WARNING):
        resp = await client.post(_url(form, "doc"), data=_data("a.pdf"))
    assert resp.status == 200
    assert (await resp.json())["blob_ref"] == "temp://bucket/blob-1"
    assert "Failed to record pending upload" in caplog.text


async def test_prior_replacement_clears_prior_row(aiohttp_client, storage):
    form = _form(FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"}))
    pending = FakePending()
    client = await _client(aiohttp_client, form, storage, pending)
    resp = await client.post(
        _url(form, "doc"), data=_data("a.pdf"), headers={"X-Parrot-Prior-Blob-Ref": "temp://bucket/old"}
    )
    assert resp.status == 200
    storage.delete.assert_awaited_once_with("temp://bucket/old")
    assert pending.deleted == [(["temp://bucket/old"], "navigator")]


async def test_multi_file_rejection_deletes_thumbnail(aiohttp_client, storage):
    form = _form(FormField(field_id="doc", field_type=FieldType.IMAGE, label={"en": "Doc"}))
    thumbs = MagicMock()
    thumbs.generate = AsyncMock(return_value="temp://thumb-ref")
    pending = FakePending()
    client = await _client(aiohttp_client, form, storage, pending, thumbs)
    resp = await client.post(_url(form, "doc"), data=_data("a.png", "b.png", content_type="image/png"))
    assert resp.status == 400
    deleted = [c.args[0] for c in storage.delete.await_args_list]
    assert "temp://bucket/blob-1" in deleted
    assert "temp://thumb-ref" in deleted  # the THUMBNAIL REF ...
    assert not any(d.startswith("/") or "?ref=" in d for d in deleted)  # ... never the URL
    assert pending.recorded == []


async def test_no_store_configured_unchanged(aiohttp_client, storage):
    form = _form(FormField(field_id="doc", field_type=FieldType.FILE, label={"en": "Doc"}))
    client = await _client(aiohttp_client, form, storage, None)
    resp = await client.post(
        _url(form, "doc"), data=_data("a.pdf"), headers={"X-Parrot-Prior-Blob-Ref": "temp://bucket/old"}
    )
    assert resp.status == 200
    storage.delete.assert_awaited_once_with("temp://bucket/old")
