"""FEAT-860 regression tests for strict conditional Redis source cleanup."""

from __future__ import annotations

import json
from typing import Any

import pytest

from parrot.handlers.crew.redis_persistence import CrewRedis, CrewRedisCleanupResult


class FakeRedis:
    """Minimal in-memory Redis double for snapshot protocol tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.raise_on_smembers = False
        self.failing_smembers: set[str] = set()
        self.eval_calls = 0

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def smembers(self, key: str) -> set[str]:
        if self.raise_on_smembers or key in self.failing_smembers:
            raise RuntimeError("Redis unavailable")
        return set(self.sets.get(key, set()))

    async def eval(self, _: str, numkeys: int, *arguments: str) -> int:
        """Execute the cleanup contract represented by the Lua arguments."""
        self.eval_calls += 1
        keys = arguments[:numkeys]
        args = arguments[numkeys:]
        namespaced_key, legacy_key, namespaced_list, legacy_list, tenants_key = keys[:5]
        namespaced_present, namespaced_raw, has_legacy, legacy_present, legacy_raw = args[:5]
        name, mapping_start, mapping_count, tenant = args[5:]
        if (namespaced_present == "1") != (self.values.get(namespaced_key) is not None):
            return 0
        if namespaced_present == "1" and self.values[namespaced_key] != namespaced_raw:
            return 0
        if has_legacy == "1":
            if (legacy_present == "1") != (self.values.get(legacy_key) is not None):
                return 0
            if legacy_present == "1" and self.values[legacy_key] != legacy_raw:
                return 0

        if namespaced_key not in self.values and (has_legacy == "0" or legacy_key not in self.values):
            return 2
        self.values.pop(namespaced_key, None)
        self.sets.get(namespaced_list, set()).discard(name)
        if has_legacy == "1":
            self.values.pop(legacy_key, None)
            self.sets.get(legacy_list, set()).discard(name)
        for mapping_key in keys[int(mapping_start) - 1 : int(mapping_start) - 1 + int(mapping_count)]:
            if self.values.get(mapping_key) == name:
                self.values.pop(mapping_key)
        if not self.sets.get(namespaced_list, set()):
            self.sets.get(tenants_key, set()).discard(tenant)
        return 1


@pytest.fixture
def store() -> CrewRedis:
    """Build a CrewRedis store with an isolated deterministic Redis fake."""
    redis_store = CrewRedis(redis_url="redis://localhost:6379/15")
    redis_store.redis = FakeRedis()
    return redis_store


def _payload(name: str, crew_id: str, tenant: str = "global") -> str:
    """Create a valid persisted crew document."""
    return json.dumps({"name": name, "crew_id": crew_id, "tenant": tenant, "agents": []})


def _seed(store: CrewRedis, name: str = "crew", crew_id: str = "id-1", tenant: str = "global") -> str:
    """Seed namespaced crew data and its inventory/mapping indexes."""
    payload = _payload(name, crew_id, tenant)
    fake: FakeRedis = store.redis
    fake.values[store._get_key(name, tenant)] = payload
    fake.values[store._get_id_mapping_key(crew_id, tenant)] = name
    fake.sets[store._get_list_key(tenant)] = {name}
    fake.sets[store._get_tenants_key()] = {tenant}
    return payload


@pytest.mark.asyncio
async def test_snapshot_retains_missing_and_legacy_states(store: CrewRedis) -> None:
    """Snapshots preserve absence and reject conflicting global source payloads."""
    assert await store.snapshot_crew("missing") is None
    payload = _seed(store)
    fake: FakeRedis = store.redis
    fake.values[store._get_legacy_key("crew")] = payload
    snapshot = await store.snapshot_crew("crew")
    assert snapshot is not None
    assert snapshot.namespaced_raw == snapshot.legacy_raw == payload
    assert snapshot.mapping_ids == ["id-1"]

    fake.values[store._get_legacy_key("crew")] = _payload("crew", "other")
    with pytest.raises(ValueError, match="Conflicting"):
        await store.snapshot_crew("crew")


@pytest.mark.asyncio
async def test_changed_source_mutates_nothing(store: CrewRedis) -> None:
    """A changed captured payload leaves all source and index state untouched."""
    _seed(store)
    snapshot = await store.snapshot_crew("crew")
    assert snapshot is not None
    fake: FakeRedis = store.redis
    fake.values[store._get_key("crew", "global")] = _payload("crew", "id-2")

    assert await store.delete_snapshot(snapshot) is CrewRedisCleanupResult.source_changed
    assert fake.values[store._get_key("crew", "global")] == _payload("crew", "id-2")
    assert fake.values[store._get_id_mapping_key("id-1", "global")] == "crew"
    assert fake.sets[store._get_list_key("global")] == {"crew"}
    assert fake.eval_calls == 1


@pytest.mark.asyncio
async def test_mapping_reassignment_is_preserved(store: CrewRedis) -> None:
    """Conditional cleanup removes a mapping only while it belongs to the snapshot name."""
    _seed(store)
    snapshot = await store.snapshot_crew("crew")
    assert snapshot is not None
    fake: FakeRedis = store.redis
    mapping_key = store._get_id_mapping_key("id-1", "global")
    legacy_mapping_key = store._get_legacy_id_mapping_key("id-1")
    fake.values[mapping_key] = "replacement"
    fake.values[legacy_mapping_key] = "crew"

    fake.is_cluster = True
    with pytest.raises(RuntimeError, match="Redis Cluster"):
        await store.delete_snapshot(snapshot)
    assert fake.eval_calls == 0
    fake.is_cluster = False

    assert await store.delete_snapshot(snapshot) is CrewRedisCleanupResult.deleted
    assert fake.values[mapping_key] == "replacement"
    assert legacy_mapping_key not in fake.values
    assert fake.sets[store._get_tenants_key()] == set()


@pytest.mark.asyncio
async def test_inventory_failure_raises(store: CrewRedis) -> None:
    """Strict inventory propagates backend errors instead of returning empty data."""
    fake: FakeRedis = store.redis
    fake.sets[store._get_tenants_key()] = {"tenant-a"}
    fake.failing_smembers.add(store._get_list_key("tenant-a"))

    with pytest.raises(RuntimeError, match="Redis unavailable"):
        await store.list_all_crews_strict()
