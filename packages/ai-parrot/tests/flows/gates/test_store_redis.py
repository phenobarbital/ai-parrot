"""Unit tests for the Redis-backed gate store."""

from __future__ import annotations

from collections import defaultdict

import pytest

from parrot.bots.flows.core.gates import GateRecord, GateSpec, GateStore
from parrot.bots.flows.core.gates.stores.redis import RedisGateStore


class FakeAsyncRedis:
    """Small in-process fake for the Redis operations used by the gate store."""

    def __init__(self) -> None:
        """Initialize empty string and set storage."""
        self.values: dict[str, str] = {}
        self.sets: defaultdict[str, set[bytes]] = defaultdict(set)

    async def set(self, key: str, value: str) -> None:
        """Store one string value."""
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        """Return one string value when present."""
        return self.values.get(key)

    async def sadd(self, key: str, member: str) -> None:
        """Add a member to a set, returning bytes like a default Redis client."""
        self.sets[key].add(member.encode("utf-8"))

    async def srem(self, key: str, member: str) -> None:
        """Remove a member from a set."""
        self.sets[key].discard(member.encode("utf-8"))

    async def smembers(self, key: str) -> set[bytes]:
        """Return a copy of a set's members."""
        return set(self.sets[key])


def make_record(gate_id: str, owner: str, opened_at: float) -> GateRecord:
    """Build a pending gate record for store tests."""
    spec = GateSpec(kind="review", title="Review")
    return GateRecord(gate_id=gate_id, kind=spec.kind, owner=owner, spec=spec, opened_at=opened_at)


@pytest.mark.asyncio
async def test_put_get_and_missing_record() -> None:
    """Records round-trip through JSON and absent identifiers return None."""
    store = RedisGateStore(FakeAsyncRedis(), prefix="test:gates")
    record = make_record("gate-1", "alice", 2.0)

    await store.put(record)

    assert isinstance(store, GateStore)
    assert await store.get(record.gate_id) == record
    assert await store.get("missing") is None


@pytest.mark.asyncio
async def test_pending_filters_by_owner_and_orders_by_opened_at() -> None:
    """Pending queries use global or owner indexes and return chronological records."""
    store = RedisGateStore(FakeAsyncRedis())
    later = make_record("gate-later", "alice", 3.0)
    other_owner = make_record("gate-other", "bob", 2.0)
    earlier = make_record("gate-earlier", "alice", 1.0)

    for record in (later, other_owner, earlier):
        await store.put(record)

    assert await store.pending() == [earlier, other_owner, later]
    assert await store.pending("alice") == [earlier, later]
    assert await store.pending("unknown") == []


@pytest.mark.asyncio
async def test_put_resolved_record_removes_pending_indexes() -> None:
    """Updating a gate to a terminal status removes it from both pending indexes."""
    store = RedisGateStore(FakeAsyncRedis())
    pending = make_record("gate-1", "alice", 1.0)
    await store.put(pending)

    approved = pending.model_copy(update={"status": "approved", "resolved_by": "reviewer", "resolved_at": 2.0})
    await store.put(approved)

    assert await store.get(pending.gate_id) == approved
    assert await store.pending() == []
    assert await store.pending("alice") == []
