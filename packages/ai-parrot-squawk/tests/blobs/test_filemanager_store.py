"""Conformance tests for the duck-typed file-manager Squawk blob store."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

import pytest
from cryptography.fernet import Fernet

from parrot.interagent import HandleClaimError, HandleOwner, MediaType, SquawkError, SquawkErrorCode, handle_key
from parrot.squawk.blobs.filemanager import FileManagerBlobStore


@dataclass(frozen=True)
class _FileMetadata:
    """Minimal file-manager metadata returned by the fake."""

    path: str
    size: int


class _FakeFileManager:
    """In-memory manager exposing exactly the six supported duck methods."""

    def __init__(self) -> None:
        self.storage: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []

    async def create_from_bytes(self, path: str, data: bytes) -> bool:
        """Store bytes at a path."""
        self.calls.append(("create_from_bytes", path))
        self.storage[path] = data
        return True

    async def download_file(self, path: str, destination: io.BytesIO) -> None:
        """Write stored bytes into a file-like destination."""
        self.calls.append(("download_file", path))
        if path not in self.storage:
            raise FileNotFoundError(path)
        destination.write(self.storage[path])

    async def exists(self, path: str) -> bool:
        """Return whether a path exists."""
        self.calls.append(("exists", path))
        return path in self.storage

    async def delete_file(self, path: str) -> bool:
        """Delete a path if present."""
        self.calls.append(("delete_file", path))
        return self.storage.pop(path, None) is not None

    async def get_file_metadata(self, path: str) -> _FileMetadata:
        """Return the path and size of a stored object."""
        self.calls.append(("get_file_metadata", path))
        if path not in self.storage:
            raise FileNotFoundError(path)
        return _FileMetadata(path=path, size=len(self.storage[path]))

    async def find_files(self, *, prefix: str) -> list[_FileMetadata]:
        """Return every object recursively under a prefix."""
        self.calls.append(("find_files", prefix))
        return [_FileMetadata(path=path, size=len(data)) for path, data in self.storage.items() if path.startswith(prefix)]

    def __getattr__(self, name: str) -> object:
        """Reject every method outside the six-method duck contract."""
        raise AttributeError(f"unsupported file-manager attribute: {name}")


async def _frames(data: bytes, n: int = 3) -> AsyncIterator[bytes]:
    """Yield test bytes in approximately ``n`` chunks."""
    step = max(1, len(data) // n)
    for index in range(0, len(data), step):
        yield data[index : index + step]


def _owner(agent_id: str = "owner") -> HandleOwner:
    """Build a stable owner tuple for a test agent."""
    return HandleOwner(agent_id=agent_id, user_id="user", tenant_id="tenant", session_id="session")


@pytest.fixture
def blob_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Install and return an isolated Fernet key."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SQUAWK_BLOB_KEY", key)
    return key


async def _read_all(
    store: FileManagerBlobStore,
    key: str,
    *,
    owner: HandleOwner,
    grantee: str | None = None,
    offset: int = 0,
    length: int | None = None,
) -> bytes:
    """Collect an asynchronous blob range into bytes."""
    return b"".join(
        [
            chunk
            async for chunk in store.open_read(
                key,
                owner=owner,
                grantee=grantee,
                offset=offset,
                length=length,
            )
        ]
    )


@pytest.mark.asyncio
async def test_blob_dedup_digest_mismatch_and_publish_order(blob_key: str) -> None:
    """Deduplicate bytes, reject a wrong digest, and publish metadata last."""
    manager = _FakeFileManager()
    store = FileManagerBlobStore(manager)
    owner = _owner()
    data = b"content-addressed payload"

    first = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)
    first_calls = list(manager.calls)
    second = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=owner, ttl_s=120)

    assert first == second
    assert first.key == handle_key(data)
    assert len([path for path in manager.storage if path.endswith(".bin")]) == 1
    assert len([path for path in manager.storage if path.endswith(".meta.json")]) == 1
    binary_create = next(index for index, call in enumerate(first_calls) if call[0] == "create_from_bytes")
    metadata_create = next(
        index for index, call in enumerate(first_calls) if call[0] == "create_from_bytes" and call[1].endswith(".meta.json")
    )
    assert binary_create < metadata_create
    assert any(call[0] == "exists" and call[1].endswith(".bin") for call in first_calls[binary_create:metadata_create])
    assert any(call[0] == "get_file_metadata" for call in first_calls[binary_create:metadata_create])

    with pytest.raises(SquawkError) as exc_info:
        await store.put_stream(
            _frames(b"different"),
            media_type=MediaType.GENERIC,
            owner=owner,
            ttl_s=60,
            expected_digest=handle_key(b"not different"),
        )

    assert exc_info.value.code is SquawkErrorCode.UPSTREAM_FAILED
    assert exc_info.value.detail == "digest_mismatch"
    assert len([path for path in manager.storage if path.endswith(".bin")]) == 1


@pytest.mark.asyncio
async def test_blob_acl_grant_delete_and_expiry(blob_key: str) -> None:
    """Enforce ACLs and expiry while supporting owner grant and deletion."""
    manager = _FakeFileManager()
    store = FileManagerBlobStore(manager)
    owner = _owner()
    stranger = _owner("stranger")
    metadata = await store.put_stream(_frames(b"private"), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)

    with pytest.raises(HandleClaimError, match="handle_unavailable"):
        await _read_all(store, metadata.key, owner=stranger)

    granted = await store.grant(metadata.key, owner=owner, grantee="reader")
    assert granted.grants == ("reader",)
    assert await _read_all(store, metadata.key, owner=stranger, grantee="reader") == b"private"

    expired = await store.put_stream(_frames(b"already expired"), media_type=MediaType.GENERIC, owner=owner, ttl_s=-1)
    with pytest.raises(HandleClaimError, match="handle_unavailable"):
        await _read_all(store, expired.key, owner=owner)

    assert await store.delete(metadata.key, owner=owner) is True
    assert await store.delete(metadata.key, owner=owner) is False


@pytest.mark.asyncio
async def test_encryption_round_trip_range_and_six_method_contract(blob_key: str) -> None:
    """Encrypt configured data and use no file-manager API outside the six-method contract."""
    manager = _FakeFileManager()
    store = FileManagerBlobStore(manager)
    owner = _owner()
    data = b"confidential employee record"

    metadata = await store.put_stream(
        _frames(data),
        media_type=MediaType.GENERIC,
        owner=owner,
        ttl_s=60,
        data_class="hr",
    )
    binary = next(value for path, value in manager.storage.items() if path.endswith(".bin"))

    assert metadata.encrypted is True
    assert data not in binary
    assert await _read_all(store, metadata.key, owner=owner) == data
    assert await _read_all(store, metadata.key, owner=owner, offset=5, length=12) == data[5:17]
    assert {name for name, _ in manager.calls} <= {
        "create_from_bytes",
        "download_file",
        "exists",
        "delete_file",
        "get_file_metadata",
        "find_files",
    }


@pytest.mark.asyncio
async def test_sweep_removes_only_expired_objects(blob_key: str) -> None:
    """Sweep expired pairs while preserving unexpired objects."""
    manager = _FakeFileManager()
    store = FileManagerBlobStore(manager)
    owner = _owner()
    expired = await store.put_stream(_frames(b"expired"), media_type=MediaType.GENERIC, owner=owner, ttl_s=1)
    current = await store.put_stream(_frames(b"current"), media_type=MediaType.GENERIC, owner=owner, ttl_s=3600)
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=2)

    assert await store.sweep(cutoff) == 1
    assert await store.has(expired.key) is False
    assert await store.has(current.key) is True
    assert any(name == "find_files" for name, _ in manager.calls)


def test_encryption_requires_environment_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed when encrypted classes are enabled without a key."""
    monkeypatch.delenv("SQUAWK_BLOB_KEY", raising=False)

    with pytest.raises(SquawkError) as exc_info:
        FileManagerBlobStore(_FakeFileManager())

    assert exc_info.value.code is SquawkErrorCode.UPSTREAM_FAILED
    assert exc_info.value.detail == "no_blob_key"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_key", ["sha256:../../escape", "sha256:" + "a" * 63, "nocolon", "sha256:" + "A" * 64, ""])
async def test_malformed_keys_are_refused(blob_key: str, bad_key: str) -> None:
    """Never turn an unvalidated caller key into an object name."""
    manager = _FakeFileManager()
    store = FileManagerBlobStore(manager)

    with pytest.raises(HandleClaimError):
        await store.meta(bad_key)
    with pytest.raises(HandleClaimError):
        await store.delete(bad_key, owner=_owner())
    assert manager.calls == []
