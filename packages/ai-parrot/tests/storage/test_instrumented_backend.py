"""Unit tests for parrot.storage.instrumented.InstrumentedBackend.

TASK-831: Observability Hooks — FEAT-116.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.storage.backends.base import BackfillBatch, ConversationBackend
from parrot.storage.metrics import NoopStorageMetrics, StorageMetrics
from parrot.storage.instrumented import InstrumentedBackend


class _CountingMetrics:
    def __init__(self):
        self.latency_calls = []
        self.error_calls = []

    def record_latency(self, backend, method, ms):
        self.latency_calls.append((backend, method, ms))

    def record_error(self, backend, method, err):
        self.error_calls.append((backend, method, err))


class _Stub(ConversationBackend):
    async def initialize(self): ...
    async def close(self): ...

    @property
    def is_connected(self):
        return True

    async def put_thread(self, *a, **kw):
        return None

    async def update_thread(self, *a, **kw): ...
    async def query_threads(self, *a, **kw):
        return []

    async def put_turn(self, *a, **kw): ...
    async def query_turns(self, *a, **kw):
        return []

    async def delete_turn(self, *a, **kw):
        return True

    async def delete_thread_cascade(self, *a, **kw):
        return 0

    async def put_artifact(self, *a, **kw):
        raise RuntimeError("boom")

    async def get_artifact(self, *a, **kw):
        return None

    async def query_artifacts(self, *a, **kw):
        return []

    async def delete_artifact(self, *a, **kw): ...
    async def delete_session_artifacts(self, *a, **kw):
        return 0

    async def query_turn_window(self, *a, **kw):
        return []

    async def max_sequence(self, *a, **kw):
        return 0

    async def put_tombstone(self, *a, **kw): ...
    async def deleted_turn_ids(self, *a, **kw):
        return set()

    async def deleted_session_ids(self, *a, **kw):
        return {"s"}

    async def is_deleted(self, *a, **kw):
        raise RuntimeError("guard-boom")

    async def get_index_state(self, *a, **kw):
        return "ready"

    async def backfill_batch(self, *a, **kw):
        return BackfillBatch(0, None, ())


async def test_noop_metrics_does_nothing():
    m = NoopStorageMetrics()
    m.record_latency("b", "m", 1.0)
    m.record_error("b", "m", "E")


def test_noop_implements_protocol():
    m = NoopStorageMetrics()
    assert isinstance(m, StorageMetrics)


async def test_records_latency_on_success():
    metrics = _CountingMetrics()
    b = InstrumentedBackend(_Stub(), metrics=metrics)
    await b.put_thread("u", "a", "s", {"t": "x"})
    assert len(metrics.latency_calls) == 1
    _name, method, ms = metrics.latency_calls[0]
    assert method == "put_thread"
    assert ms >= 0


async def test_records_error_and_reraises():
    metrics = _CountingMetrics()
    b = InstrumentedBackend(_Stub(), metrics=metrics)
    with pytest.raises(RuntimeError, match="boom"):
        await b.put_artifact("u", "a", "s", "aid", {})
    assert len(metrics.error_calls) == 1
    assert metrics.error_calls[0][1] == "put_artifact"


async def test_error_also_records_latency():
    metrics = _CountingMetrics()
    b = InstrumentedBackend(_Stub(), metrics=metrics)
    with pytest.raises(RuntimeError):
        await b.put_artifact("u", "a", "s", "aid", {})
    # latency recorded even on error (via finally block)
    assert len(metrics.latency_calls) == 1


def test_is_connected_passes_through():
    b = InstrumentedBackend(_Stub())
    assert b.is_connected is True


def test_build_overflow_prefix_passes_through():
    b = InstrumentedBackend(_Stub())
    assert b.build_overflow_prefix("u", "a", "s", "aid") == "artifacts/USER#u#AGENT#a/THREAD#s/aid"


def test_load_metrics_from_path_bad_path():
    from parrot.storage.backends import load_metrics_from_path

    with pytest.raises(RuntimeError):
        load_metrics_from_path("nonexistent.module:THING")
    with pytest.raises(RuntimeError):
        load_metrics_from_path("invalid-format-no-colon")


async def test_default_metrics_is_noop():
    b = InstrumentedBackend(_Stub())
    # Should not raise
    await b.put_thread("u", "a", "s", {})


async def test_new_operations_are_delegated_and_measured():
    """Each FEAT-886 operation reaches the inner backend, is timed, and errors propagate + are counted."""
    metrics = _CountingMetrics()
    b = InstrumentedBackend(_Stub(), metrics=metrics)
    assert await b.query_turn_window("u", "a", "s", 5) == []
    assert await b.max_sequence("u", "a", "s") == 0
    assert await b.get_index_state("u", "a", "s") == "ready"
    assert (await b.backfill_batch(None, 10)).next_cursor is None
    await b.put_tombstone("u", "a", "s")
    assert await b.deleted_session_ids("u", "a", ["s", "t"]) == {"s"}
    with pytest.raises(RuntimeError, match="guard-boom"):
        await b.is_deleted("u", "a", "s")
    assert [c[1] for c in metrics.error_calls] == ["is_deleted"]
    assert [c[1] for c in metrics.latency_calls] == [
        "query_turn_window",
        "max_sequence",
        "get_index_state",
        "backfill_batch",
        "put_tombstone",
        "deleted_session_ids",
        "is_deleted",
    ]
