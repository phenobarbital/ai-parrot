"""Shared contract tests for the gate-store backends and resolver."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from parrot.bots.flows.core.gates import GateError, GateErrorCode, GateRecord, GateSpec, GateStore
from parrot.bots.flows.core.gates.stores import RedisGateStore, SQLiteGateStore, resolve_gate_store


class FakeAsyncRedis:
    """In-process Redis substitute for the operations used by RedisGateStore."""

    def __init__(self) -> None:
        """Initialize empty string and set storage."""
        self.values: dict[str, str] = {}
        self.sets: defaultdict[str, set[bytes]] = defaultdict(set)

    async def set(self, key: str, value: str) -> None:
        """Store one string value."""
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        """Return the stored value, if any."""
        return self.values.get(key)

    async def sadd(self, key: str, member: str) -> None:
        """Add a member to a set."""
        self.sets[key].add(member.encode("utf-8"))

    async def srem(self, key: str, member: str) -> None:
        """Remove a member from a set."""
        self.sets[key].discard(member.encode("utf-8"))

    async def smembers(self, key: str) -> set[bytes]:
        """Return the members of a set."""
        return set(self.sets[key])


def make_record(gate_id: str, owner: str, opened_at: float) -> GateRecord:
    """Create a pending gate record for contract checks."""
    spec = GateSpec(kind="review", title="Review")
    return GateRecord(gate_id=gate_id, kind=spec.kind, owner=owner, spec=spec, opened_at=opened_at)


def make_store(backend: str, tmp_path: Path) -> GateStore:
    """Build one independently configured store for the named backend."""
    if backend == "redis":
        return RedisGateStore(FakeAsyncRedis(), prefix="test:gates")
    return SQLiteGateStore(tmp_path / "gates.sqlite")


@pytest.mark.parametrize("backend", ["redis", "sqlite"])
@pytest.mark.asyncio
async def test_store_contract(backend: str, tmp_path: Path) -> None:
    """Both backends round-trip, filter, order, and retire gate records alike."""
    store = make_store(backend, tmp_path)
    later = make_record("gate-later", "alice", 3.0)
    other_owner = make_record("gate-other", "bob", 2.0)
    earlier = make_record("gate-earlier", "alice", 1.0)

    assert isinstance(store, GateStore)
    assert await store.get("missing") is None
    for record in (later, other_owner, earlier):
        await store.put(record)

    assert await store.get(earlier.gate_id) == earlier
    assert await store.pending() == [earlier, other_owner, later]
    assert await store.pending("alice") == [earlier, later]
    assert await store.pending("unknown") == []

    approved = earlier.model_copy(update={"status": "approved", "resolved_by": "reviewer", "resolved_at": 4.0})
    await store.put(approved)

    assert await store.get(earlier.gate_id) == approved
    assert await store.pending() == [other_owner, later]
    assert await store.pending("alice") == [later]


def test_resolver_prefers_explicit_backend_and_defaults_to_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver honors explicit selection, Redis injection, and local SQLite fallback."""
    redis_client = FakeAsyncRedis()
    sqlite_path = tmp_path / "configured.sqlite"

    assert isinstance(resolve_gate_store(backend="redis", redis_client=redis_client), RedisGateStore)
    explicit_sqlite = resolve_gate_store(backend="sqlite", redis_client=redis_client, sqlite_path=sqlite_path)
    assert isinstance(explicit_sqlite, SQLiteGateStore)
    assert explicit_sqlite.path == sqlite_path
    assert isinstance(resolve_gate_store(redis_client=redis_client), RedisGateStore)

    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot-home"))
    default_store = resolve_gate_store()
    assert isinstance(default_store, SQLiteGateStore)
    assert default_store.path == tmp_path / "parrot-home" / "gates.sqlite"


def test_resolver_rejects_unimplemented_helix_and_missing_redis_client() -> None:
    """Unavailable resolver choices expose the stable store error code."""
    with pytest.raises(GateError) as helix_error:
        resolve_gate_store(backend="helix")
    assert helix_error.value.code is GateErrorCode.STORE_UNAVAILABLE
    assert "HelixDB store not implemented (FEAT-890 §8 Q1)" in str(helix_error.value)

    with pytest.raises(GateError) as redis_error:
        resolve_gate_store(backend="redis")
    assert redis_error.value.code is GateErrorCode.STORE_UNAVAILABLE
