"""Unit tests for parrot_formdesigner.services.blob_storage.

All S3 calls are mocked — no live S3 invocations.
"""

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _chunks(*parts: bytes):
    """Async generator yielding each part as a chunk."""
    for part in parts:
        yield part


def _make_metadata(**kwargs) -> BlobMetadata:
    defaults = dict(
        form_id="form1",
        field_id="photo",
        content_type="image/jpeg",
        size_bytes=5,
    )
    defaults.update(kwargs)
    return BlobMetadata(**defaults)


# ---------------------------------------------------------------------------
# AbstractBlobStorage — cannot instantiate directly
# ---------------------------------------------------------------------------


class TestAbstractBlobStorage:
    def test_cannot_instantiate_abstract(self):
        """Instantiating the ABC directly must raise TypeError."""
        with pytest.raises(TypeError):
            AbstractBlobStorage()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# S3BlobStorage unit tests
# ---------------------------------------------------------------------------


class TestS3BlobStorageConstruction:
    def test_requires_bucket(self):
        """Constructing without bucket or env var raises RuntimeError."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            original = os.environ.pop("PARROT_BLOB_BUCKET", None)
            try:
                with pytest.raises(RuntimeError, match="bucket"):
                    S3BlobStorage()
            finally:
                if original is not None:
                    os.environ["PARROT_BLOB_BUCKET"] = original

    def test_env_var_bucket(self, monkeypatch):
        """Bucket can be supplied via PARROT_BLOB_BUCKET env var."""
        monkeypatch.setenv("PARROT_BLOB_BUCKET", "env-bucket")
        storage = S3BlobStorage()
        assert storage.bucket == "env-bucket"

    def test_constructor_arg_wins_over_env(self, monkeypatch):
        """Constructor arg takes priority over env var."""
        monkeypatch.setenv("PARROT_BLOB_BUCKET", "env-bucket")
        storage = S3BlobStorage(bucket="arg-bucket")
        assert storage.bucket == "arg-bucket"


class TestS3BlobStoragePut:
    @pytest.fixture
    def storage(self) -> S3BlobStorage:
        return S3BlobStorage(bucket="test-bucket", prefix="forms/")

    @pytest.mark.asyncio
    async def test_put_returns_s3_ref(self, storage: S3BlobStorage):
        """put() returns a valid s3://bucket/key reference."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        mock_client_ctx = MagicMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.client = MagicMock(return_value=mock_client_ctx)

        with patch("aioboto3.Session", return_value=mock_session):
            metadata = _make_metadata()
            ref = await storage.put(_chunks(b"hello"), metadata=metadata)

        assert ref.startswith("s3://test-bucket/forms/")
        mock_s3.put_object.assert_awaited_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"hello"
        assert call_kwargs["ContentType"] == "image/jpeg"

    @pytest.mark.asyncio
    async def test_put_multiple_chunks_joined(self, storage: S3BlobStorage):
        """put() joins multiple chunks before uploading."""
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        mock_client_ctx = MagicMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.client = MagicMock(return_value=mock_client_ctx)

        with patch("aioboto3.Session", return_value=mock_session):
            metadata = _make_metadata(size_bytes=10)
            await storage.put(_chunks(b"hell", b"o wor", b"ld"), metadata=metadata)

        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Body"] == b"hello world"

    @pytest.mark.asyncio
    async def test_pre_persist_hook_reject_aborts_put(self):
        """A hook raising BlobRejectedError prevents the put_object call."""

        class StrictStorage(S3BlobStorage):
            async def pre_persist_hook(self, ctx: PrePersistContext) -> None:
                raise BlobRejectedError("content rejected")

        storage = StrictStorage(bucket="b", prefix="p/")
        mock_s3 = AsyncMock()
        mock_s3.put_object = AsyncMock()

        mock_client_ctx = MagicMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.client = MagicMock(return_value=mock_client_ctx)

        with patch("aioboto3.Session", return_value=mock_session):
            with pytest.raises(BlobRejectedError, match="content rejected"):
                await storage.put(_chunks(b"x"), metadata=_make_metadata())

        mock_s3.put_object.assert_not_awaited()


class TestS3BlobStorageDelete:
    @pytest.fixture
    def storage(self) -> S3BlobStorage:
        return S3BlobStorage(bucket="test-bucket", prefix="forms/")

    @pytest.mark.asyncio
    async def test_delete_present_key(self, storage: S3BlobStorage):
        """delete() calls delete_object with correct bucket + key."""
        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock()

        mock_client_ctx = MagicMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.client = MagicMock(return_value=mock_client_ctx)

        with patch("aioboto3.Session", return_value=mock_session):
            await storage.delete("s3://test-bucket/forms/f1/photo/abc123")

        mock_s3.delete_object.assert_awaited_once_with(
            Bucket="test-bucket", Key="forms/f1/photo/abc123"
        )

    @pytest.mark.asyncio
    async def test_delete_absent_key_no_raise(self, storage: S3BlobStorage):
        """delete() is idempotent — absent key does not raise."""
        mock_s3 = AsyncMock()
        # Simulate S3 NoSuchKey error code
        err = Exception("NoSuchKey")
        err.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
        mock_s3.delete_object = AsyncMock(side_effect=err)

        mock_client_ctx = MagicMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_s3)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.client = MagicMock(return_value=mock_client_ctx)

        # Must NOT raise
        with patch("aioboto3.Session", return_value=mock_session):
            await storage.delete("s3://test-bucket/forms/missing")


class TestS3BlobStoragePrePersistHook:
    @pytest.mark.asyncio
    async def test_pre_persist_hook_noop(self):
        """Default pre_persist_hook returns None (no-op coroutine)."""
        storage = S3BlobStorage(bucket="b")
        ctx = PrePersistContext(
            metadata=BlobMetadata(
                form_id="f1",
                field_id="x",
                content_type="text/plain",
                size_bytes=0,
            )
        )
        result = await storage.pre_persist_hook(ctx)
        assert result is None
