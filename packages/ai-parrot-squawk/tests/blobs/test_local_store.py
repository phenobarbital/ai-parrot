"""Tests for the local-disk Squawk blob store."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

import pytest
from cryptography.fernet import Fernet

from parrot.interagent import HandleClaimError, HandleOwner, MediaType, SquawkError, SquawkErrorCode, handle_key
from parrot.squawk.blobs.local import LocalDiskBlobStore


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
    store: LocalDiskBlobStore,
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
async def test_blob_dedup_and_digest_mismatch(tmp_path: Path, blob_key: str) -> None:
    """Deduplicate equal plaintext and clean a mismatched temporary object."""
    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    data = b"content-addressed payload"

    first = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)
    second = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=owner, ttl_s=120)

    assert first == second
    assert first.key == handle_key(data)
    assert len(list(tmp_path.glob("[0-9a-f][0-9a-f]/*.bin"))) == 1
    assert len(list(tmp_path.glob("[0-9a-f][0-9a-f]/*.meta.json"))) == 1

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
    assert list((tmp_path / ".tmp").iterdir()) == []
    assert len(list(tmp_path.glob("[0-9a-f][0-9a-f]/*.bin"))) == 1


@pytest.mark.asyncio
async def test_blob_acl_grant_and_expiry(tmp_path: Path, blob_key: str) -> None:
    """Refuse strangers, allow explicit grantees, and refuse expired blobs."""
    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    stranger = _owner("stranger")
    metadata = await store.put_stream(
        _frames(b"private"), media_type=MediaType.GENERIC, owner=owner, ttl_s=60
    )

    with pytest.raises(HandleClaimError, match="handle_unavailable"):
        await _read_all(store, metadata.key, owner=stranger)

    granted = await store.grant(metadata.key, owner=owner, grantee="reader")
    assert granted.grants == ("reader",)
    assert await _read_all(store, metadata.key, owner=stranger, grantee="reader") == b"private"

    expired = await store.put_stream(
        _frames(b"already expired"), media_type=MediaType.GENERIC, owner=owner, ttl_s=-1
    )
    with pytest.raises(HandleClaimError, match="handle_unavailable"):
        await _read_all(store, expired.key, owner=owner)


@pytest.mark.asyncio
async def test_encryption_round_trip_and_range_read(tmp_path: Path, blob_key: str) -> None:
    """Encrypt configured data classes and return exact plaintext ranges."""
    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    data = b"confidential employee record"
    metadata = await store.put_stream(
        _frames(data),
        media_type=MediaType.GENERIC,
        owner=owner,
        ttl_s=60,
        data_class="hr",
    )
    bin_path = store._paths(metadata.key)[0]

    assert metadata.encrypted is True
    assert data not in bin_path.read_bytes()
    assert await _read_all(store, metadata.key, owner=owner) == data
    assert await _read_all(store, metadata.key, owner=owner, offset=5, length=12) == data[5:17]


@pytest.mark.asyncio
async def test_sweep_removes_only_expired_objects(tmp_path: Path, blob_key: str) -> None:
    """Sweep expired pairs while preserving unexpired objects."""
    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    expired = await store.put_stream(
        _frames(b"expired"), media_type=MediaType.GENERIC, owner=owner, ttl_s=1
    )
    current = await store.put_stream(
        _frames(b"current"), media_type=MediaType.GENERIC, owner=owner, ttl_s=3600
    )
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=2)

    assert await store.sweep(cutoff) == 1
    assert await store.has(expired.key) is False
    assert await store.has(current.key) is True


def test_encryption_requires_environment_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed when encrypted classes are enabled without a key."""
    monkeypatch.delenv("SQUAWK_BLOB_KEY", raising=False)

    with pytest.raises(SquawkError) as exc_info:
        LocalDiskBlobStore(tmp_path)

    assert exc_info.value.code is SquawkErrorCode.UPSTREAM_FAILED
    assert exc_info.value.detail == "no_blob_key"
