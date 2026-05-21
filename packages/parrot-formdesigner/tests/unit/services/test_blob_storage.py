"""Unit tests for parrot_formdesigner.services.blob_storage.

Tests mock at the ``FileManager`` boundary — concrete I/O against real S3,
GCS, or disk is out of scope. ``TempBlobStorage`` is exercised end-to-end
against a real temp directory since it requires no credentials and is the
lazy default.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot_formdesigner.services.blob_storage import (
    AbstractBlobStorage,
    BlobMetadata,
    BlobRejectedError,
    LocalBlobStorage,
    PrePersistContext,
    S3BlobStorage,
    TempBlobStorage,
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


_FAKE_CREDS = {
    "aws_key": "AKIATESTTESTTESTTEST",
    "aws_secret": "secret-test-secret-test-secret-test-secre",
    "region_name": "us-east-1",
    "bucket_name": "default-bucket",
}


# ---------------------------------------------------------------------------
# AbstractBlobStorage
# ---------------------------------------------------------------------------


class TestAbstractBlobStorage:
    def test_cannot_instantiate_abstract(self):
        """Instantiating the ABC directly must raise TypeError."""
        with pytest.raises(TypeError):
            AbstractBlobStorage()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# S3BlobStorage — construction
# ---------------------------------------------------------------------------


class TestS3BlobStorageConstruction:
    def test_requires_bucket(self, monkeypatch):
        """Without bucket arg, env, or profile bucket_name → RuntimeError.

        navconfig populates ``PARROT_BLOB_BUCKET`` at import time from
        settings, so the test sets it to an empty string (falsy) rather
        than deleting it — ``delenv`` does not survive the navconfig load.
        """
        monkeypatch.setenv("PARROT_BLOB_BUCKET", "")
        empty_creds = {"aws_key": "k", "aws_secret": "s", "region_name": "us-east-1"}
        with pytest.raises(RuntimeError, match="bucket"):
            S3BlobStorage(credentials=empty_creds)

    def test_env_var_bucket(self, monkeypatch):
        """PARROT_BLOB_BUCKET wins over the credential profile's bucket_name."""
        monkeypatch.setenv("PARROT_BLOB_BUCKET", "env-bucket")
        storage = S3BlobStorage(credentials=_FAKE_CREDS)
        assert storage.bucket == "env-bucket"

    def test_constructor_arg_wins_over_env(self, monkeypatch):
        """Constructor arg takes priority over env var."""
        monkeypatch.setenv("PARROT_BLOB_BUCKET", "env-bucket")
        storage = S3BlobStorage(bucket="arg-bucket", credentials=_FAKE_CREDS)
        assert storage.bucket == "arg-bucket"

    def test_falls_back_to_profile_bucket(self, monkeypatch):
        """Credential profile's bucket_name is the last fallback."""
        monkeypatch.setenv("PARROT_BLOB_BUCKET", "")
        storage = S3BlobStorage(credentials=_FAKE_CREDS)
        assert storage.bucket == "default-bucket"

    def test_prefix_normalised(self, monkeypatch):
        """Trailing slash is normalised onto the prefix."""
        monkeypatch.setenv("PARROT_BLOB_PREFIX", "")
        storage = S3BlobStorage(
            bucket="b", prefix="forms", credentials=_FAKE_CREDS
        )
        assert storage.prefix == "forms/"


# ---------------------------------------------------------------------------
# S3BlobStorage — put / get / delete via mocked FileManager
# ---------------------------------------------------------------------------


@pytest.fixture
def s3_storage_with_mock_manager() -> S3BlobStorage:
    storage = S3BlobStorage(
        bucket="test-bucket", prefix="forms/", credentials=_FAKE_CREDS
    )
    mock_manager = MagicMock()
    mock_manager.bucket_name = "test-bucket"
    mock_manager.create_file = AsyncMock(return_value=True)
    mock_manager.delete_file = AsyncMock(return_value=True)
    storage._manager = mock_manager  # type: ignore[attr-defined]
    return storage


class TestS3BlobStoragePut:
    @pytest.mark.asyncio
    async def test_put_returns_s3_ref(self, s3_storage_with_mock_manager):
        ref = await s3_storage_with_mock_manager.put(
            _chunks(b"hello"), metadata=_make_metadata()
        )
        assert ref.startswith("s3://test-bucket/forms/")
        mock = s3_storage_with_mock_manager._manager.create_file
        mock.assert_awaited_once()
        # First positional arg = key, second = bytes
        args, _ = mock.call_args
        assert args[0].startswith("forms/form1/photo/")
        assert args[1] == b"hello"

    @pytest.mark.asyncio
    async def test_put_multiple_chunks_joined(
        self, s3_storage_with_mock_manager
    ):
        await s3_storage_with_mock_manager.put(
            _chunks(b"hell", b"o wor", b"ld"),
            metadata=_make_metadata(size_bytes=11),
        )
        args, _ = s3_storage_with_mock_manager._manager.create_file.call_args
        assert args[1] == b"hello world"

    @pytest.mark.asyncio
    async def test_pre_persist_hook_reject_aborts_put(self):
        class StrictStorage(S3BlobStorage):
            async def pre_persist_hook(self, ctx: PrePersistContext) -> None:
                raise BlobRejectedError("content rejected")

        storage = StrictStorage(
            bucket="b", prefix="p/", credentials=_FAKE_CREDS
        )
        mock_manager = MagicMock()
        mock_manager.create_file = AsyncMock()
        storage._manager = mock_manager  # type: ignore[attr-defined]

        with pytest.raises(BlobRejectedError, match="content rejected"):
            await storage.put(_chunks(b"x"), metadata=_make_metadata())
        mock_manager.create_file.assert_not_awaited()


class TestS3BlobStorageDelete:
    @pytest.mark.asyncio
    async def test_delete_strips_scheme_and_bucket(
        self, s3_storage_with_mock_manager
    ):
        await s3_storage_with_mock_manager.delete(
            "s3://test-bucket/forms/f1/photo/abc123"
        )
        s3_storage_with_mock_manager._manager.delete_file.assert_awaited_once_with(
            "forms/f1/photo/abc123"
        )

    @pytest.mark.asyncio
    async def test_delete_absent_key_no_raise(self, s3_storage_with_mock_manager):
        """FileNotFoundError and S3 NoSuchKey errors are swallowed."""
        err = Exception("NoSuchKey")
        err.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
        s3_storage_with_mock_manager._manager.delete_file = AsyncMock(
            side_effect=err
        )
        # Must NOT raise
        await s3_storage_with_mock_manager.delete(
            "s3://test-bucket/forms/missing"
        )

    @pytest.mark.asyncio
    async def test_delete_file_not_found_no_raise(
        self, s3_storage_with_mock_manager
    ):
        s3_storage_with_mock_manager._manager.delete_file = AsyncMock(
            side_effect=FileNotFoundError("gone")
        )
        await s3_storage_with_mock_manager.delete(
            "s3://test-bucket/forms/missing"
        )


class TestS3BlobStoragePrePersistHook:
    @pytest.mark.asyncio
    async def test_pre_persist_hook_noop(self):
        storage = S3BlobStorage(bucket="b", credentials=_FAKE_CREDS)
        ctx = PrePersistContext(
            metadata=BlobMetadata(
                form_id="f1",
                field_id="x",
                content_type="text/plain",
                size_bytes=0,
            )
        )
        assert await storage.pre_persist_hook(ctx) is None


# ---------------------------------------------------------------------------
# TempBlobStorage — end-to-end (no mocks)
# ---------------------------------------------------------------------------


class TestTempBlobStorageRoundTrip:
    @pytest.mark.asyncio
    async def test_put_then_get_returns_same_bytes(self):
        storage = TempBlobStorage()
        ref = await storage.put(
            _chunks(b"hello ", b"world"),
            metadata=_make_metadata(size_bytes=11),
        )
        assert ref.startswith("temp://")

        stream = await storage.get(ref)
        collected = b"".join([chunk async for chunk in stream])
        assert collected == b"hello world"

    @pytest.mark.asyncio
    async def test_delete_removes_blob(self):
        storage = TempBlobStorage()
        ref = await storage.put(
            _chunks(b"data"), metadata=_make_metadata(size_bytes=4)
        )
        await storage.delete(ref)
        # Second delete is idempotent
        await storage.delete(ref)

    @pytest.mark.asyncio
    async def test_pre_persist_hook_reject(self):
        class StrictTemp(TempBlobStorage):
            async def pre_persist_hook(self, ctx: PrePersistContext) -> None:
                raise BlobRejectedError("nope")

        storage = StrictTemp()
        with pytest.raises(BlobRejectedError, match="nope"):
            await storage.put(_chunks(b"x"), metadata=_make_metadata())


# ---------------------------------------------------------------------------
# LocalBlobStorage — end-to-end against a tmp_path sandbox
# ---------------------------------------------------------------------------


class TestLocalBlobStorageRoundTrip:
    @pytest.mark.asyncio
    async def test_put_creates_file_under_base_path(self, tmp_path: Path):
        storage = LocalBlobStorage(base_path=tmp_path, prefix="blobs")
        ref = await storage.put(
            _chunks(b"payload"), metadata=_make_metadata(size_bytes=7)
        )
        assert ref.startswith("file://blobs/")
        # The relative key from the ref must exist on disk under tmp_path
        key = ref.removeprefix("file://")
        assert (tmp_path / key).read_bytes() == b"payload"

    @pytest.mark.asyncio
    async def test_get_returns_same_bytes(self, tmp_path: Path):
        storage = LocalBlobStorage(base_path=tmp_path)
        ref = await storage.put(
            _chunks(b"abc", b"def"), metadata=_make_metadata(size_bytes=6)
        )
        stream = await storage.get(ref)
        collected = b"".join([chunk async for chunk in stream])
        assert collected == b"abcdef"

    @pytest.mark.asyncio
    async def test_delete_is_idempotent(self, tmp_path: Path):
        storage = LocalBlobStorage(base_path=tmp_path)
        ref = await storage.put(
            _chunks(b"x"), metadata=_make_metadata(size_bytes=1)
        )
        await storage.delete(ref)
        await storage.delete(ref)  # idempotent
