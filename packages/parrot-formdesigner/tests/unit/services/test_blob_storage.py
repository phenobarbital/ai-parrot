"""Unit tests for blob_storage module (mocked aioboto3 — no live S3 calls)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_formdesigner.services.blob_storage import (
    AbstractBlobStorage,
    BlobMetadata,
    BlobRejectedError,
    PrePersistContext,
    S3BlobStorage,
)


class TestAbstractBlobStorage:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            AbstractBlobStorage()  # type: ignore[abstract]


def _make_s3_mock() -> AsyncMock:
    """Return an AsyncMock pre-configured for multipart upload calls."""
    s3 = AsyncMock()
    s3.create_multipart_upload.return_value = {"UploadId": "test-upload-id"}
    s3.upload_part.return_value = {"ETag": '"etag-abc123"'}
    s3.complete_multipart_upload.return_value = {}
    s3.abort_multipart_upload.return_value = {}
    s3.delete_object.return_value = {}
    return s3


def _make_session_patch(s3_mock: AsyncMock) -> MagicMock:
    """Wrap s3_mock in a properly nested aioboto3.Session mock."""
    client_cm = AsyncMock()
    client_cm.__aenter__ = AsyncMock(return_value=s3_mock)
    client_cm.__aexit__ = AsyncMock(return_value=False)

    session_instance = MagicMock()
    session_instance.client.return_value = client_cm

    return MagicMock(return_value=session_instance)


class TestS3BlobStorage:
    @pytest.fixture
    def storage(self) -> S3BlobStorage:
        return S3BlobStorage(bucket="test-bucket", prefix="forms/")

    async def test_put_returns_s3_ref(self, storage: S3BlobStorage) -> None:
        async def chunks():
            yield b"hello"

        s3 = _make_s3_mock()
        session_cls = _make_session_patch(s3)

        with patch("aioboto3.Session", session_cls):
            ref = await storage.put(
                chunks(),
                metadata=BlobMetadata(
                    form_id="f1",
                    field_id="photo",
                    content_type="image/jpeg",
                    size_bytes=5,
                ),
            )

        assert ref.startswith("s3://test-bucket/forms/")
        s3.create_multipart_upload.assert_called_once()
        s3.upload_part.assert_called_once()
        s3.complete_multipart_upload.assert_called_once()

    async def test_delete_absent_key_no_raise(self, storage: S3BlobStorage) -> None:
        s3 = _make_s3_mock()
        session_cls = _make_session_patch(s3)

        with patch("aioboto3.Session", session_cls):
            await storage.delete("s3://test-bucket/forms/missing")

        s3.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="forms/missing"
        )

    async def test_pre_persist_hook_noop(self, storage: S3BlobStorage) -> None:
        ctx = PrePersistContext(
            metadata=BlobMetadata(
                form_id="f1",
                field_id="x",
                content_type="text/plain",
                size_bytes=0,
            )
        )
        assert await storage.pre_persist_hook(ctx) is None

    async def test_pre_persist_hook_reject_aborts_put(self) -> None:
        class Strict(S3BlobStorage):
            async def pre_persist_hook(self, ctx: PrePersistContext) -> None:
                raise BlobRejectedError("reject")

        strict_storage = Strict(bucket="b", prefix="p/")

        async def chunks():
            yield b"x"

        with patch("aioboto3.Session"):
            with pytest.raises(BlobRejectedError):
                await strict_storage.put(
                    chunks(),
                    metadata=BlobMetadata(
                        form_id="f",
                        field_id="x",
                        content_type="text/plain",
                        size_bytes=1,
                    ),
                )

    async def test_put_key_format(self, storage: S3BlobStorage) -> None:
        async def chunks():
            yield b"data"

        s3 = _make_s3_mock()
        session_cls = _make_session_patch(s3)

        with patch("aioboto3.Session", session_cls):
            ref = await storage.put(
                chunks(),
                metadata=BlobMetadata(
                    form_id="myform",
                    field_id="attachment",
                    content_type="application/pdf",
                    size_bytes=4,
                ),
            )

        # ref format: s3://<bucket>/<prefix><form_id>/<field_id>/<uuid>
        assert ref.startswith("s3://test-bucket/forms/myform/attachment/")
        parts = ref.split("/")
        # last segment must be a valid UUID
        import uuid as _uuid
        _uuid.UUID(parts[-1])  # raises ValueError if not UUID

    async def test_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PARROT_BLOB_BUCKET", "env-bucket")
        monkeypatch.setenv("PARROT_BLOB_PREFIX", "env-prefix/")

        storage = S3BlobStorage()
        assert storage._bucket == "env-bucket"
        assert storage._prefix == "env-prefix/"
