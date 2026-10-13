"""Deterministic concurrent Redis state regressions without a network service."""

import asyncio
from typing import Any

import pytest
from redis.exceptions import WatchError

from parrot.scheduler.models import FireContext, utcnow
from parrot.scheduler.runstate import RedisRunState


class InterleavedRedis:
    """Hash store which yields after reads, exposing lost-update races."""

    def __init__(self) -> None:
        self.fields: dict[str, str] = {}
        self.version = 0

    async def hgetall(self, key: str) -> dict[str, str]:
        """Capture the hash before allowing a competing operation to run."""
        snapshot = dict(self.fields)
        await asyncio.sleep(0)
        return snapshot

    async def hset(self, key: str, *, mapping: dict[str, str]) -> None:
        """Apply a hash write and invalidate outstanding watches."""
        self.fields.update(mapping)
        self.version += 1

    def pipeline(self, *, transaction: bool) -> "Pipeline":
        """Build a transactional pipeline over this shared hash."""
        return Pipeline(self)


class Pipeline:
    """Implement Redis WATCH/MULTI semantics used by the state store."""

    def __init__(self, client: InterleavedRedis) -> None:
        """Bind one transaction to the shared hash."""
        self.client = client
        self.version = 0
        self.mapping: dict[str, str] = {}

    async def __aenter__(self) -> "Pipeline":
        """Return this transaction."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Leave the transaction without suppressing errors."""
        return None

    async def watch(self, key: str) -> None:
        """Remember the hash version before reading."""
        self.version = self.client.version

    async def hgetall(self, key: str) -> dict[str, str]:
        """Read the watched hash."""
        return await self.client.hgetall(key)

    def multi(self) -> None:
        """Begin queueing mutations."""

    def hset(self, key: str, *, mapping: dict[str, str]) -> None:
        """Queue the new fields for commit."""
        self.mapping = mapping

    async def execute(self) -> None:
        """Commit only if no competing writer changed the hash."""
        if self.version != self.client.version:
            raise WatchError("hash changed")
        await self.client.hset("job", mapping=self.mapping)


@pytest.mark.parametrize("operation", ["success", "delivery", "enable"])
async def test_transitions_preserve_concurrent_pause(operation: str) -> None:
    """A pause must survive a competing operation which read the old hash."""
    client = InterleavedRedis()
    first = RedisRunState(client, prefix="test:")
    second = RedisRunState(client, prefix="test:")
    fire = FireContext.for_fire("job", utcnow())
    if operation == "success":
        transition = first.stamp_success("job", result_text="ok", fire=fire, next_run=None)
    elif operation == "delivery":
        transition = first.stamp_delivery("job", [{"status": "sent"}])
    else:
        transition = first.set_enabled("job", True)
    await asyncio.gather(transition, second.set_enabled("job", False))
    state = await first.read("job")
    assert state.enabled is False
    if operation == "success":
        assert state.run_count == 1
    elif operation == "delivery":
        assert state.last_delivery_status == "ok"


async def test_concurrent_successes_both_increment_run_count() -> None:
    """Overlapping completed fires must not lose an execution increment."""
    client = InterleavedRedis()
    stores = [RedisRunState(client, prefix="test:") for _ in range(2)]
    fire = FireContext.for_fire("job", utcnow())
    await asyncio.gather(*(store.stamp_success("job", result_text="ok", fire=fire, next_run=None) for store in stores))
    assert (await stores[0].read("job")).run_count == 2


async def test_delivery_preserves_concurrent_threshold_failure() -> None:
    """Delivery fields and an auto-disable transition must both survive."""
    client = InterleavedRedis()
    first = RedisRunState(client, prefix="test:")
    second = RedisRunState(client, prefix="test:")
    fire = FireContext.for_fire("job", utcnow())
    await asyncio.gather(
        first.stamp_delivery("job", [{"status": "sent"}]),
        second.stamp_failure("job", status="error", error="boom", fire=fire, threshold=1),
    )
    state = await first.read("job")
    assert state.enabled is False
    assert state.consecutive_failures == 1
    assert state.last_delivery_status == "ok"
