"""Tests for parrot.bots.flows.core.checkpoint.store (TASK-2048).

Validates the CheckpointStore ABC contract and the get_checkpoint_store()
factory resolution order (instance > arg > env > default), without
requiring Redis or any durable DB driver.
"""
from typing import Any

import pytest
from parrot.bots.flows.core.checkpoint import CheckpointStore, FlowCheckpoint
from parrot.bots.flows.core.checkpoint.store.factory import get_checkpoint_store


class FakeCheckpointStore(CheckpointStore):
    """Minimal in-memory CheckpointStore implementation for tests."""

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        pass

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        return None

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        return None

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        return []

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
        return []

    async def delete_flow(self, flow_id: str) -> None:
        pass

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return True

    async def release_lease(self, flow_id: str, holder: str) -> None:
        pass

    async def close(self) -> None:
        pass


def test_checkpoint_store_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        CheckpointStore()  # type: ignore[abstract]


def test_factory_instance_passthrough():
    store = FakeCheckpointStore()
    assert get_checkpoint_store(store) is store


def test_factory_arg_name_selection(monkeypatch):
    called = {}

    def fake_import(path):
        called["path"] = path
        return FakeCheckpointStore

    monkeypatch.setattr(
        "parrot.bots.flows.core.checkpoint.store.factory._import_class",
        fake_import,
    )
    store = get_checkpoint_store("redis")
    assert isinstance(store, FakeCheckpointStore)
    assert "redis" in called["path"]


def test_factory_env_fallback(monkeypatch):
    monkeypatch.setattr(
        "parrot.bots.flows.core.checkpoint.store.factory.FLOW_CHECKPOINT_STORE",
        "redis",
    )
    monkeypatch.setattr(
        "parrot.bots.flows.core.checkpoint.store.factory._import_class",
        lambda path: FakeCheckpointStore,
    )
    store = get_checkpoint_store(None)
    assert isinstance(store, FakeCheckpointStore)


def test_factory_default_is_redis(monkeypatch):
    monkeypatch.setattr(
        "parrot.bots.flows.core.checkpoint.store.factory.FLOW_CHECKPOINT_STORE",
        None,
    )
    captured = {}

    def fake_import(path):
        captured["path"] = path
        return FakeCheckpointStore

    monkeypatch.setattr(
        "parrot.bots.flows.core.checkpoint.store.factory._import_class",
        fake_import,
    )
    get_checkpoint_store(None)
    assert "redis" in captured["path"]


def test_factory_durable_backends_pass_driver_kwarg(monkeypatch):
    captured = {}

    class RecordingDurableStore(FakeCheckpointStore):
        def __init__(self, driver: str):
            captured["driver"] = driver

    monkeypatch.setattr(
        "parrot.bots.flows.core.checkpoint.store.factory._import_class",
        lambda path: RecordingDurableStore,
    )
    for driver in ("sqlite", "postgres", "mongodb"):
        get_checkpoint_store(driver)
        assert captured["driver"] == driver


def test_factory_unknown_name_raises():
    with pytest.raises(ValueError, match="Unknown CheckpointStore backend"):
        get_checkpoint_store("etcd")


def test_conf_flow_checkpoint_env_vars_have_documented_defaults():
    from parrot.conf import (
        FLOW_CHECKPOINT_HISTORY,
        FLOW_CHECKPOINT_LEASE_TTL,
        FLOW_CHECKPOINT_REDIS_TTL,
        FLOW_CHECKPOINT_SHUTDOWN_DEADLINE,
        FLOW_CHECKPOINT_STORE,
    )

    assert FLOW_CHECKPOINT_STORE == "redis"
    assert FLOW_CHECKPOINT_REDIS_TTL == 86400
    assert FLOW_CHECKPOINT_HISTORY == 10
    assert FLOW_CHECKPOINT_SHUTDOWN_DEADLINE == 15
    assert FLOW_CHECKPOINT_LEASE_TTL == 60
