"""FEAT-731 — strict delete + reaper outcomes (fake blob storage / fake stores)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot_formdesigner.services.blob_storage import S3BlobStorage
from parrot_formdesigner.services.pending_uploads import (
    DEFAULT_PUBLIC_FORM_TTL,
    DEFAULT_TTL,
    PendingUpload,
    PendingUploadReaper,
)

_CREDS = {"aws_key": "k", "aws_secret": "s", "region_name": "us-east-1", "bucket_name": "test-bucket"}


def _s3(delete_file: Any) -> S3BlobStorage:
    storage = S3BlobStorage(bucket="test-bucket", prefix="forms/", credentials=_CREDS)
    manager = MagicMock()
    manager.delete_file = delete_file
    storage._manager = manager  # type: ignore[attr-defined]
    return storage


async def test_delete_strict():
    boom = RuntimeError("500 InternalError")
    boom.response = {"Error": {"Code": "InternalError"}}  # type: ignore[attr-defined]
    ref = "s3://test-bucket/forms/a"
    # strict re-raises a non-missing error
    with pytest.raises(RuntimeError):
        await _s3(AsyncMock(side_effect=boom)).delete(ref, strict=True)
    # non-strict unchanged: swallowed
    await _s3(AsyncMock(side_effect=boom)).delete(ref)
    await _s3(AsyncMock(side_effect=boom)).delete(ref, strict=False)
    # "missing" stays silent in strict mode
    nosuch = Exception("NoSuchKey")
    nosuch.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
    await _s3(AsyncMock(side_effect=nosuch)).delete(ref, strict=True)
    await _s3(AsyncMock(side_effect=FileNotFoundError("gone"))).delete(ref, strict=True)
    # success path
    ok = AsyncMock(return_value=True)
    await _s3(ok).delete(ref, strict=True)
    ok.assert_awaited_once_with("forms/a")


class FakePending:
    """Honours the TTL arguments like the SQL does, so the reaper's wiring is what is under test."""

    def __init__(self, rows: list[PendingUpload]) -> None:
        self.rows = list(rows)
        self.cleared: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def expired(self, *, tenant, public_form_ttl, ttl, limit, conn=None):
        now = datetime.now(timezone.utc)
        out = [
            r
            for r in self.rows
            if now - r.uploaded_at > (public_form_ttl if r.public_form else ttl)  # type: ignore[operator]
        ]
        return sorted(out, key=lambda r: r.uploaded_at)[:limit]  # type: ignore[arg-type,return-value]

    async def clear(self, refs, *, tenant, conn=None):
        refs = list(refs)
        self.cleared.extend(refs)
        self.rows = [r for r in self.rows if r.blob_ref not in refs]
        return len(refs)


class FakeBlobs:
    def __init__(self, fail: set[str] | None = None, bad_scheme: set[str] | None = None) -> None:
        self.deleted: list[tuple[str, bool]] = []
        self.fail = fail or set()
        self.bad_scheme = bad_scheme or set()

    async def delete(self, ref: str, *, strict: bool = False) -> None:
        if ref in self.bad_scheme:
            raise ValueError(f"scheme mismatch: {ref}")
        if ref in self.fail:
            raise RuntimeError("backend 500")
        self.deleted.append((ref, strict))


class FakeSubmissions:
    def __init__(self, referenced: set[str] | None = None) -> None:
        self.referenced = referenced or set()
        self.calls: list[tuple[uuid.UUID, str, str | None]] = []

    async def references_blob(self, form_uid, blob_ref, *, tenant):
        self.calls.append((form_uid, blob_ref, tenant))
        return blob_ref in self.referenced


def _row(ref: str, *, age: timedelta, public: bool, thumb: str | None = None) -> PendingUpload:
    return PendingUpload(
        blob_ref=ref,
        thumbnail_ref=thumb,
        form_uid=uuid.uuid4(),
        field_uid=uuid.uuid4(),
        tenant="t",
        public_form=public,
        uploaded_at=datetime.now(timezone.utc) - age,
    )


def test_default_ttls():
    assert DEFAULT_PUBLIC_FORM_TTL == timedelta(hours=48) and DEFAULT_TTL == timedelta(days=7)


async def test_reaper_ttls_and_outcomes():
    h = timedelta(hours=1)
    pub_old = _row("s3://b/pub-49h", age=49 * h, public=True)
    pub_new = _row("s3://b/pub-47h", age=47 * h, public=True)
    priv_new = _row("s3://b/priv-6d", age=6 * 24 * h, public=False)
    priv_old = _row("s3://b/priv-8d", age=8 * 24 * h, public=False)
    referenced = _row("s3://b/ref-9d", age=9 * 24 * h, public=False)
    failing = _row("s3://b/fail-9d", age=9 * 24 * h, public=False)
    pending = FakePending([pub_old, pub_new, priv_new, priv_old, referenced, failing])
    blobs = FakeBlobs(fail={"s3://b/fail-9d"})
    subs = FakeSubmissions(referenced={"s3://b/ref-9d"})

    result = await PendingUploadReaper(pending, blobs, subs).reap_once(tenant="t")

    assert (result.deleted, result.failed, result.still_referenced) == (2, 1, 1)
    assert sorted(r for r, _ in blobs.deleted) == ["s3://b/priv-8d", "s3://b/pub-49h"]
    assert all(strict is True for _, strict in blobs.deleted)
    assert "s3://b/ref-9d" not in [r for r, _ in blobs.deleted]  # blob untouched
    assert sorted(pending.cleared) == ["s3://b/priv-8d", "s3://b/pub-49h", "s3://b/ref-9d"]
    kept = {r.blob_ref for r in pending.rows}
    assert kept == {"s3://b/pub-47h", "s3://b/priv-6d", "s3://b/fail-9d"}  # not expired + failed
    assert all(c[2] == "t" for c in subs.calls)


async def test_reaper_custom_ttls_and_batch():
    rows = [_row(f"s3://b/{i}", age=timedelta(hours=3 + i), public=True) for i in range(5)]
    pending = FakePending(rows)
    result = await PendingUploadReaper(pending, FakeBlobs(), FakeSubmissions()).reap_once(
        tenant="t", public_form_ttl=timedelta(hours=1), ttl=timedelta(days=30), batch=2
    )
    assert result.deleted == 2 and len(pending.rows) == 3


async def test_reaper_bad_scheme_counts_failed():
    row = _row("temp://old/blob", age=timedelta(days=30), public=False)
    pending = FakePending([row])
    result = await PendingUploadReaper(pending, FakeBlobs(bad_scheme={"temp://old/blob"}), FakeSubmissions()).reap_once(
        tenant="t"
    )
    assert (result.deleted, result.failed) == (0, 1)
    assert [r.blob_ref for r in pending.rows] == ["temp://old/blob"]


async def test_reaper_deletes_thumbnail_too():
    row = _row("s3://b/p", age=timedelta(days=30), public=False, thumb="s3://b/t")
    pending, blobs = FakePending([row]), FakeBlobs()
    result = await PendingUploadReaper(pending, blobs, FakeSubmissions()).reap_once(tenant="t")
    assert result.deleted == 1
    assert [r for r, _ in blobs.deleted] == ["s3://b/p", "s3://b/t"]
    assert pending.rows == []


async def test_reaper_thumbnail_failure_keeps_row():
    row = _row("s3://b/p", age=timedelta(days=30), public=False, thumb="s3://b/t")
    pending = FakePending([row])
    result = await PendingUploadReaper(pending, FakeBlobs(fail={"s3://b/t"}), FakeSubmissions()).reap_once(tenant="t")
    assert (result.deleted, result.failed) == (0, 1) and len(pending.rows) == 1


async def test_reference_check_error_keeps_row_and_blob():
    row = _row("s3://b/p", age=timedelta(days=30), public=False)
    pending, blobs = FakePending([row]), FakeBlobs()
    subs = FakeSubmissions()
    subs.references_blob = AsyncMock(side_effect=RuntimeError("db down"))  # type: ignore[method-assign]
    result = await PendingUploadReaper(pending, blobs, subs).reap_once(tenant="t")
    assert result.failed == 1 and blobs.deleted == [] and len(pending.rows) == 1
