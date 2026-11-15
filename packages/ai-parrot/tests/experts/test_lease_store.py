"""LeaseDurableCheckpointStore lease semantics (FEAT-890)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.experts.lease_store import LeaseDurableCheckpointStore


@pytest.fixture
def store(tmp_path: Path) -> LeaseDurableCheckpointStore:
    return LeaseDurableCheckpointStore(tmp_path / "nested" / "cp.sqlite")


@pytest.mark.asyncio
async def test_second_holder_is_refused_until_release(store: LeaseDurableCheckpointStore) -> None:
    assert await store.acquire_lease("f", "a", ttl=60) is True
    assert await store.acquire_lease("f", "b", ttl=60) is False
    assert await store.acquire_lease("f", "a", ttl=60) is True  # same holder may re-acquire
    await store.release_lease("f", "b")  # not the owner: no-op
    assert await store.acquire_lease("f", "b", ttl=60) is False
    await store.release_lease("f", "a")
    assert await store.acquire_lease("f", "b", ttl=60) is True


@pytest.mark.asyncio
async def test_expired_lease_can_be_taken_and_not_renewed(store: LeaseDurableCheckpointStore) -> None:
    assert await store.acquire_lease("f", "a", ttl=-1) is True  # already expired
    assert await store.renew_lease("f", "a", ttl=60) is False
    assert await store.acquire_lease("f", "b", ttl=60) is True


@pytest.mark.asyncio
async def test_renew_requires_ownership(store: LeaseDurableCheckpointStore) -> None:
    assert await store.acquire_lease("f", "a", ttl=60) is True
    assert await store.renew_lease("f", "b", ttl=60) is False
    assert await store.renew_lease("f", "a", ttl=60) is True


@pytest.mark.asyncio
async def test_leases_are_independent_per_flow_and_survive_a_new_instance(
    store: LeaseDurableCheckpointStore, tmp_path: Path
) -> None:
    assert await store.acquire_lease("f1", "a", ttl=60) is True
    assert await store.acquire_lease("f2", "b", ttl=60) is True
    other_process = LeaseDurableCheckpointStore(tmp_path / "nested" / "cp.sqlite")
    assert await other_process.acquire_lease("f1", "c", ttl=60) is False
