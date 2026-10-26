"""Tests for owner-bound inter-agent artifact handles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from parrot.interagent import (
    ArtifactHandle,
    HandleClaimError,
    HandleDescriptor,
    HandleOwner,
    HandleProvenance,
    HandleStore,
    InMemoryHandleStore,
    MediaType,
    SquawkError,
    SquawkErrorCode,
    handle_key,
)


def _owner(agent_id: str = "caller") -> HandleOwner:
    """Build a complete test owner.

    Args:
        agent_id: Agent identity to place in the owner tuple.

    Returns:
        A frozen handle owner.
    """
    return HandleOwner(agent_id=agent_id, user_id="user", tenant_id="tenant", session_id="session")


def _handle(
    owner: HandleOwner,
    *,
    data: bytes = b"artifact",
    expires_at: datetime | None = None,
    grants: tuple[str, ...] = (),
) -> ArtifactHandle:
    """Build a valid artifact handle for store tests.

    Args:
        owner: Owner tuple for the handle.
        data: Bytes used to derive the content key.
        expires_at: Explicit expiry, or one minute from now by default.
        grants: Agent identities explicitly allowed to claim.

    Returns:
        A complete artifact handle.
    """
    now = datetime.now(timezone.utc)
    return ArtifactHandle(
        key=handle_key(data),
        media_type=MediaType.ARROW,
        byte_size=len(data),
        ttl_s=60,
        expires_at=expires_at or now + timedelta(seconds=60),
        owner=owner,
        grants=grants,
        descriptor=HandleDescriptor(media_type=MediaType.ARROW, byte_size=len(data), summary={"rows": 1}),
        provenance=HandleProvenance(
            serving_agent="hr",
            cap_id="hr.reports.example",
            contract_hash="sha256:" + "0" * 64,
            args_digest="digest",
            backing="deterministic",
            produced_at=now,
            trace_id="trace",
        ),
    )


def test_handle_key_and_model_validation() -> None:
    """Hash exact bytes and reject malformed keys and oversized summaries."""
    assert HandleStore.__name__ == "HandleStore"
    assert handle_key(b"artifact") == "sha256:" + "c7c5c1d70c5dec4416ab6158afd0b223ef40c29b1dc1f97ed9428b94d4cadb1c"

    invalid_handle = _handle(_owner()).model_dump()
    invalid_handle["key"] = "invalid"
    with pytest.raises(ValidationError):
        ArtifactHandle(**invalid_handle)
    with pytest.raises(ValidationError, match="summary JSON exceeds 1500 characters"):
        HandleDescriptor(media_type=MediaType.GENERIC, byte_size=1, summary={"value": "x" * 1500})


def test_models_are_frozen_and_forbid_extra_fields() -> None:
    """Apply the shared immutable strict-model contract."""
    owner = _owner()
    with pytest.raises(ValidationError):
        owner.agent_id = "changed"
    with pytest.raises(ValidationError):
        HandleOwner(agent_id="a", user_id="u", tenant_id="t", session_id="s", unexpected=True)


@pytest.mark.asyncio
async def test_claim_failures_are_indistinguishable() -> None:
    """Use one failure message for non-owner, expired, and unknown handles."""
    owner = _owner()
    store = InMemoryHandleStore()
    valid = _handle(owner)
    expired = _handle(owner, data=b"expired", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    await store.put(valid)
    await store.put(expired)

    failures = (
        (valid.key, _owner("other")),
        (expired.key, owner),
        (handle_key(b"unknown"), owner),
    )
    messages = set()
    for key, claimant in failures:
        with pytest.raises(HandleClaimError) as exc_info:
            await store.claim(key, owner=claimant)
        messages.add(str(exc_info.value))

    assert messages == {"handle_unavailable"}
    assert await store.claim(valid.key, owner=owner) == valid


@pytest.mark.asyncio
async def test_owner_can_grant_and_grantee_can_claim() -> None:
    """Permit owner-issued grants and reject grants from a non-owner."""
    owner = _owner()
    other = _owner("other")
    store = InMemoryHandleStore()
    handle = _handle(owner)
    await store.put(handle)

    with pytest.raises(HandleClaimError, match="handle_unavailable"):
        await store.grant(handle.key, owner=other, grantee="analyst")

    granted = await store.grant(handle.key, owner=owner, grantee="analyst")
    assert granted.grants == ("analyst",)
    assert await store.claim(handle.key, owner=other, grantee="analyst") == granted


@pytest.mark.asyncio
async def test_store_evicts_oldest_entry_at_capacity() -> None:
    """Keep the in-memory store bounded by evicting its oldest key."""
    owner = _owner()
    store = InMemoryHandleStore(max_entries=1)
    first = _handle(owner, data=b"first")
    second = _handle(owner, data=b"second")
    await store.put(first)
    await store.put(second)

    with pytest.raises(HandleClaimError, match="handle_unavailable"):
        await store.claim(first.key, owner=owner)
    assert await store.claim(second.key, owner=owner) == second


def test_squawk_error_exposes_typed_fields() -> None:
    """Preserve typed code, sanitized detail, and structured payload."""
    error = SquawkError(SquawkErrorCode.STALE_CONTRACT, "refresh", {"category": "hr"})

    assert str(error) == "STALE_CONTRACT: refresh"
    assert error.code is SquawkErrorCode.STALE_CONTRACT
    assert error.detail == "refresh"
    assert error.payload == {"category": "hr"}
