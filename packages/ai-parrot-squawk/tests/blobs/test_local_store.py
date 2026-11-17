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

    assert (second.key, second.owner, second.created_at) == (first.key, first.owner, first.created_at)
    assert second.expires_at > first.expires_at  # same owner, longer TTL: expiry extended
    assert first.key == handle_key(data)
    assert len(list(tmp_path.glob("[0-9a-f][0-9a-f]/*/*.bin"))) == 1
    assert len(list(tmp_path.glob("[0-9a-f][0-9a-f]/*/*.meta.json"))) == 1

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
    assert len(list(tmp_path.glob("[0-9a-f][0-9a-f]/*/*.bin"))) == 1


@pytest.mark.asyncio
async def test_blob_acl_grant_and_expiry(tmp_path: Path, blob_key: str) -> None:
    """Refuse strangers, allow explicit grantees, and refuse expired blobs."""
    store = LocalDiskBlobStore(tmp_path)
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
    bin_path = store._paths(metadata.key, metadata.owner)[0]

    assert metadata.encrypted is True
    assert data not in bin_path.read_bytes()
    assert await _read_all(store, metadata.key, owner=owner) == data
    assert await _read_all(store, metadata.key, owner=owner, offset=5, length=12) == data[5:17]


@pytest.mark.asyncio
async def test_sweep_removes_only_expired_objects(tmp_path: Path, blob_key: str) -> None:
    """Sweep expired pairs while preserving unexpired objects."""
    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    expired = await store.put_stream(_frames(b"expired"), media_type=MediaType.GENERIC, owner=owner, ttl_s=1)
    current = await store.put_stream(_frames(b"current"), media_type=MediaType.GENERIC, owner=owner, ttl_s=3600)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_key", ["sha256:../../escape", "sha256:" + "a" * 63, "nocolon", "sha256:" + "A" * 64, ""])
async def test_malformed_keys_are_refused_without_touching_disk(tmp_path: Path, blob_key: str, bad_key: str) -> None:
    """A caller-supplied key is never used as a path segment unless it is sha256:<64 hex>."""
    store = LocalDiskBlobStore(tmp_path / "store")
    with pytest.raises(HandleClaimError):
        await store.meta(bad_key)
    with pytest.raises(HandleClaimError):
        await store.delete(bad_key, owner=_owner())


async def _raising_frames() -> AsyncIterator[bytes]:
    """Yield one chunk then fail, as a cancelled/broken upstream would."""
    yield b"partial"
    raise RuntimeError("upstream broke")


@pytest.mark.asyncio
async def test_cross_owner_dedup_keeps_records_isolated(tmp_path: Path, blob_key: str) -> None:
    """Identical bytes from two owners never share TTL, ACL or ownership."""
    store = LocalDiskBlobStore(tmp_path)
    alice, bob = _owner("alice"), _owner("bob")
    data = b"same report bytes"

    a_meta = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=alice, ttl_s=1)
    await store.grant(a_meta.key, owner=alice, grantee="friend")
    b_meta = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=bob, ttl_s=100)

    assert b_meta.owner == bob and b_meta.expires_at > a_meta.expires_at
    assert await _read_all(store, b_meta.key, owner=bob) == data
    assert await _read_all(store, a_meta.key, owner=alice) == data
    assert await _read_all(store, a_meta.key, owner=_owner("friend"), grantee="friend") == data
    assert (await store.meta(a_meta.key, owner=alice)).grants == ("friend",)
    with pytest.raises(HandleClaimError):
        await store.grant(a_meta.key, owner=_owner("mallory"), grantee="mallory")
    assert await store.delete(a_meta.key, owner=_owner("mallory")) is False
    assert await _read_all(store, a_meta.key, owner=alice) == data


@pytest.mark.asyncio
async def test_expired_or_reclassified_record_is_republished(tmp_path: Path, blob_key: str) -> None:
    """An expired record or a stricter data class republishes instead of deduping."""
    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    data = b"sensitive rows"
    plain = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)
    assert plain.encrypted is False

    hr = await store.put_stream(_frames(data), media_type=MediaType.GENERIC, owner=owner, ttl_s=60, data_class="hr")
    assert hr.encrypted is True and hr.data_class == "hr"
    assert store._paths(hr.key, owner)[0].read_bytes() != data
    assert await _read_all(store, hr.key, owner=owner) == data


@pytest.mark.asyncio
async def test_has_is_expiry_aware_and_grant_idempotent(tmp_path: Path, blob_key: str) -> None:
    """``has`` ignores expired records; repeated grants do not duplicate grantees."""
    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    meta = await store.put_stream(_frames(b"x"), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)
    await store.grant(meta.key, owner=owner, grantee="r")
    again = await store.grant(meta.key, owner=owner, grantee="r")
    assert again.grants == ("r",)
    assert await store.has(meta.key, owner=owner) is True

    meta_path = store._paths(meta.key, owner)[1]
    expired = meta.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    meta_path.write_text(expired.model_dump_json())
    assert await store.has(meta.key) is False
    assert await store.has(meta.key, owner=owner) is False


@pytest.mark.asyncio
async def test_sweep_survives_corrupt_metadata_and_removes_orphans(tmp_path: Path, blob_key: str) -> None:
    """A truncated meta file is skipped; stale orphan binaries are removed."""
    store = LocalDiskBlobStore(tmp_path, orphan_grace_s=0)
    owner = _owner()
    keep = await store.put_stream(_frames(b"keep"), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)
    gone = await store.put_stream(_frames(b"gone"), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)
    bad_dir = tmp_path / "ab" / ("ab" + "0" * 62)
    bad_dir.mkdir(parents=True)
    (bad_dir / "x.meta.json").write_text('{"key": "sha256:trunc')
    orphan = bad_dir / "y.bin"
    orphan.write_bytes(b"orphan")

    removed = await store.sweep(now=datetime.now(timezone.utc) + timedelta(seconds=120))
    assert removed == 2
    assert not orphan.exists()
    assert await store.has(keep.key) is False and await store.has(gone.key) is False


@pytest.mark.asyncio
async def test_failed_stream_leaves_no_temp_file(tmp_path: Path, blob_key: str) -> None:
    """A raising frame iterator never leaks its staging file."""
    store = LocalDiskBlobStore(tmp_path)
    with pytest.raises(RuntimeError):
        await store.put_stream(_raising_frames(), media_type=MediaType.GENERIC, owner=_owner(), ttl_s=60)
    assert list((tmp_path / ".tmp").iterdir()) == []


@pytest.mark.asyncio
async def test_size_cap_and_no_grant_on_expired(tmp_path: Path, blob_key: str) -> None:
    """put_stream refuses objects over max_bytes; grant refuses an expired record."""
    store = LocalDiskBlobStore(tmp_path, max_bytes=4)
    with pytest.raises(SquawkError) as exc_info:
        await store.put_stream(_frames(b"too big"), media_type=MediaType.GENERIC, owner=_owner(), ttl_s=60)
    assert exc_info.value.detail == "blob_too_large"
    assert list((tmp_path / ".tmp").iterdir()) == []

    store = LocalDiskBlobStore(tmp_path)
    owner = _owner()
    meta = await store.put_stream(_frames(b"x"), media_type=MediaType.GENERIC, owner=owner, ttl_s=60)
    expired = meta.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    store._paths(meta.key, owner)[1].write_text(expired.model_dump_json())
    with pytest.raises(HandleClaimError):
        await store.grant(meta.key, owner=owner, grantee="late")
