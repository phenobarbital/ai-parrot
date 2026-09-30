"""Idempotent file upload via ``X-Parrot-Client-Upload-Id``.

A mobile device that queues photos while offline replays each upload until the
server answers — so the same file can arrive twice. With the header, the same
id for the same field names the SAME blob: the retry returns the same
``blob_ref`` and the storage holds one copy, not two. Without it nothing
changes (a fresh random name per upload).

Real ``LocalBlobStorage`` on a temp directory, so "one copy" is counted on disk,
not inferred from a mock.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from aiohttp import FormData, web
from parrot_formdesigner.api.file_upload import CLIENT_UPLOAD_ID_HEADER, handle_file_upload
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.blob_storage import LocalBlobStorage
from parrot_formdesigner.services.registry import FormRegistry


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _form(field_type: FieldType = FieldType.IMAGE, field_id: str = "photo") -> tuple[FormSchema, uuid.UUID]:
    field = FormField(field_id=field_id, field_type=field_type, label={"en": "Photo"})
    form = FormSchema(
        form_id="visit", title={"en": "Visit"},
        sections=[FormSection(section_id="s1", fields=[field])], tenant="navigator",
    )
    return form, field.field_uid


async def _tenant_wrapped(request: web.Request) -> web.Response:
    request["tenant"] = request.match_info["tenant"]
    return await handle_file_upload(request)


@pytest.fixture
def storage(tmp_path: Path) -> LocalBlobStorage:
    return LocalBlobStorage(base_path=tmp_path)


async def _client(aiohttp_client, form: FormSchema, storage: LocalBlobStorage):
    app = web.Application()
    registry = FormRegistry()
    await registry.register(form)
    app["form_registry"] = registry
    app["blob_storage"] = storage
    app.router.add_post("/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload", _tenant_wrapped)
    return await aiohttp_client(app)


def _files(tmp_path: Path) -> list[Path]:
    return sorted(p for p in tmp_path.rglob("*") if p.is_file())


def _photo(content: bytes, name: str = "shelf.png") -> FormData:
    data = FormData()
    data.add_field("file", io.BytesIO(content), filename=name, content_type="image/png")
    return data


async def _upload(client, form, field_uid, content, *, tenant="navigator", headers=None):
    resp = await client.post(
        f"/api/v1/{tenant}/forms/{form.form_uid}/fields/{field_uid}/file-upload",
        data=_photo(content), headers=headers or {},
    )
    assert resp.status == 200, await resp.text()
    return await resp.json()


class TestIdempotentUpload:
    @pytest.mark.asyncio
    async def test_a_retry_with_the_same_id_stores_one_photo(self, aiohttp_client, storage, tmp_path):
        # RED/GREEN BY MUTATION: ignore `metadata.blob_id` in `_build_key`,
        # and the retry adds a second photo (and a second thumbnail).
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        photo = _png()
        headers = {CLIENT_UPLOAD_ID_HEADER: "photo-7f3a"}

        first = await _upload(client, form, field_uid, photo, headers=headers)
        again = await _upload(client, form, field_uid, photo, headers=headers)

        assert again == first  # same blob_ref, same thumbnail_url, same checksum
        assert len(_files(tmp_path)) == 2  # one photo + its one thumbnail

    @pytest.mark.asyncio
    async def test_without_the_header_every_upload_is_new_as_before(self, aiohttp_client, storage, tmp_path):
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        photo = _png()
        first = await _upload(client, form, field_uid, photo)
        again = await _upload(client, form, field_uid, photo)
        assert first["blob_ref"] != again["blob_ref"]
        assert len(_files(tmp_path)) == 4

    @pytest.mark.asyncio
    async def test_different_ids_are_different_photos(self, aiohttp_client, storage, tmp_path):
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        a = await _upload(client, form, field_uid, _png(), headers={CLIENT_UPLOAD_ID_HEADER: "a"})
        b = await _upload(client, form, field_uid, _png(), headers={CLIENT_UPLOAD_ID_HEADER: "b"})
        assert a["blob_ref"] != b["blob_ref"]

    @pytest.mark.asyncio
    async def test_one_id_never_collides_across_tenants(self, aiohttp_client, storage):
        # RED/GREEN BY MUTATION: drop the tenant from the hashed name.
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        # The blob tenant is `X-Parrot-Tenant` (else the URL tenant); the form
        # registry already hides a form from another URL tenant.
        a = await _upload(client, form, field_uid, _png(),
                          headers={CLIENT_UPLOAD_ID_HEADER: "same-id", "X-Parrot-Tenant": "epson"})
        b = await _upload(client, form, field_uid, _png(),
                          headers={CLIENT_UPLOAD_ID_HEADER: "same-id", "X-Parrot-Tenant": "flexroc"})
        assert a["blob_ref"] != b["blob_ref"]

    @pytest.mark.asyncio
    async def test_the_raw_header_never_becomes_the_storage_key(self, aiohttp_client, storage):
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        body = await _upload(client, form, field_uid, _png(), headers={CLIENT_UPLOAD_ID_HEADER: "../../etc/passwd"})
        assert "passwd" not in body["blob_ref"] and ".." not in body["blob_ref"]

    @pytest.mark.asyncio
    async def test_a_retry_naming_itself_as_prior_does_not_delete_the_photo(self, aiohttp_client, storage, tmp_path):
        # RED/GREEN BY MUTATION: remove the `not in written` guard, and the
        # retry deletes the very photo it just (re)wrote.
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        photo = _png()
        headers = {CLIENT_UPLOAD_ID_HEADER: "photo-9"}
        first = await _upload(client, form, field_uid, photo, headers=headers)
        await _upload(client, form, field_uid, photo, headers={**headers, "X-Parrot-Prior-Blob-Ref": first["blob_ref"]})
        stream = await storage.get(first["blob_ref"])
        stored = b"".join([chunk async for chunk in stream])
        assert stored == photo

    @pytest.mark.asyncio
    async def test_a_too_long_id_is_refused(self, aiohttp_client, storage):
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{field_uid}/file-upload",
            data=_photo(_png()), headers={CLIENT_UPLOAD_ID_HEADER: "x" * 129},
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_each_file_of_a_multi_upload_keeps_its_own_blob(self, aiohttp_client, storage, tmp_path):
        form, field_uid = _form(FieldType.MULTI_UPLOAD, "gallery")
        client = await _client(aiohttp_client, form, storage)
        data = FormData()
        data.add_field("file", io.BytesIO(b"one"), filename="a.txt", content_type="text/plain")
        data.add_field("file", io.BytesIO(b"two"), filename="b.txt", content_type="text/plain")
        url = f"/api/v1/navigator/forms/{form.form_uid}/fields/{field_uid}/file-upload"
        headers = {CLIENT_UPLOAD_ID_HEADER: "batch-1"}
        first = await (await client.post(url, data=data, headers=headers)).json()
        assert len({env["blob_ref"] for env in first}) == 2
        data2 = FormData()
        data2.add_field("file", io.BytesIO(b"one"), filename="a.txt", content_type="text/plain")
        data2.add_field("file", io.BytesIO(b"two"), filename="b.txt", content_type="text/plain")
        again = await (await client.post(url, data=data2, headers=headers)).json()
        assert [e["blob_ref"] for e in again] == [e["blob_ref"] for e in first]
        assert len(_files(tmp_path)) == 2


class TestIdempotentUploadReview:
    """Blind review, 2026-09-30: the blob name must follow the FILE, not its position."""

    @staticmethod
    def _two(first: tuple[str, bytes], second: tuple[str, bytes]) -> FormData:
        data = FormData()
        for name, content in (first, second):
            data.add_field("file", io.BytesIO(content), filename=name, content_type="text/plain")
        return data

    @pytest.mark.asyncio
    async def test_a_retry_with_the_parts_reordered_never_swaps_content(self, aiohttp_client, storage, tmp_path):
        # RED/GREEN BY MUTATION: name the blob by part index again, and the
        # reordered retry writes B's bytes over A's blob.
        form, field_uid = _form(FieldType.MULTI_UPLOAD, "gallery")
        client = await _client(aiohttp_client, form, storage)
        url = f"/api/v1/navigator/forms/{form.form_uid}/fields/{field_uid}/file-upload"
        headers = {CLIENT_UPLOAD_ID_HEADER: "batch-9"}
        first = await (await client.post(url, data=self._two(("a.txt", b"AAAA"), ("b.txt", b"BBBB")), headers=headers)).json()
        await client.post(url, data=self._two(("b.txt", b"BBBB"), ("a.txt", b"AAAA")), headers=headers)
        for env, expected in zip(first, (b"AAAA", b"BBBB")):
            stream = await storage.get(env["blob_ref"])
            assert b"".join([c async for c in stream]) == expected
        assert len(_files(tmp_path)) == 2

    @pytest.mark.asyncio
    async def test_a_rejected_retry_never_deletes_the_live_blob(self, aiohttp_client, storage):
        # RED/GREEN BY MUTATION: drop the client-id guard on the
        # single-cardinality cleanup, and the 400 deletes the stored photo.
        form, field_uid = _form()
        client = await _client(aiohttp_client, form, storage)
        photo = _png()
        headers = {CLIENT_UPLOAD_ID_HEADER: "photo-live"}
        live = await _upload(client, form, field_uid, photo, headers=headers)
        bad = FormData()
        bad.add_field("file", io.BytesIO(photo), filename="shelf.png", content_type="image/png")
        bad.add_field("file", io.BytesIO(photo), filename="again.png", content_type="image/png")
        resp = await client.post(
            f"/api/v1/navigator/forms/{form.form_uid}/fields/{field_uid}/file-upload", data=bad, headers=headers
        )
        assert resp.status == 400
        stream = await storage.get(live["blob_ref"])
        assert b"".join([c async for c in stream]) == photo

    @pytest.mark.asyncio
    async def test_two_chunked_sessions_under_one_client_id_store_one_file(self, aiohttp_client, storage, tmp_path):
        # RED/GREEN BY MUTATION: stop threading the seed into the chunked path.
        form, field_uid = _form(FieldType.FILE, "doc")
        client = await _client(aiohttp_client, form, storage)
        url = f"/api/v1/navigator/forms/{form.form_uid}/fields/{field_uid}/file-upload"
        body = b"0123456789"
        refs = []
        for session in ("s-1", "s-2"):
            for offset in (0, 5):
                resp = await client.post(url, data=body[offset:offset + 5], headers={
                    "X-Parrot-Upload-Offset": str(offset), "X-Parrot-Upload-Length": str(len(body)),
                    "X-Parrot-Upload-Id": session, CLIENT_UPLOAD_ID_HEADER: "doc-1",
                    "Content-Type": "application/octet-stream"})
            assert resp.status == 200, await resp.text()
            refs.append((await resp.json())["blob_ref"])
        assert refs[0] == refs[1]
        assert len(_files(tmp_path)) == 1

    @pytest.mark.asyncio
    async def test_one_client_id_on_two_fields_is_two_blobs(self, aiohttp_client, storage):
        # RED/GREEN BY MUTATION: drop the field from the seed.
        first = FormField(field_id="front", field_type=FieldType.IMAGE, label={"en": "Front"})
        second = FormField(field_id="back", field_type=FieldType.IMAGE, label={"en": "Back"})
        form = FormSchema(form_id="visit2", title={"en": "Visit"},
                          sections=[FormSection(section_id="s1", fields=[first, second])], tenant="navigator")
        client = await _client(aiohttp_client, form, storage)
        photo = _png()
        headers = {CLIENT_UPLOAD_ID_HEADER: "same"}
        a = await _upload(client, form, first.field_uid, photo, headers=headers)
        b = await _upload(client, form, second.field_uid, photo, headers=headers)
        assert a["blob_ref"] != b["blob_ref"]
