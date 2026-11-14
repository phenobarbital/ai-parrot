"""FEAT-886 M4 — error hierarchy, abstract surface and a self-test of the shared durable checks."""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import pytest

from parrot.exceptions import ParrotError
from parrot.storage import (
    BackfillBatch,
    ConversationBackend,
    ConversationDeletedError,
    IndexNotReadyError,
    InvalidTurnPayloadError,
    StorageError,
    StorageUnavailableError,
    StorageWriteError,
)

from . import durable_contract
from .durable_contract import ALL_CHECKS, DurableHarness, check_window_newest_ascending

NEW_ABSTRACT = {
    "query_turn_window",
    "max_sequence",
    "put_tombstone",
    "is_deleted",
    "get_index_state",
    "backfill_batch",
    "deleted_turn_ids",
    "deleted_session_ids",
}


def test_error_hierarchy():
    """Every storage error is a StorageError, which is a ParrotError."""
    for cls in (
        StorageUnavailableError,
        StorageWriteError,
        ConversationDeletedError,
        IndexNotReadyError,
        InvalidTurnPayloadError,
    ):
        assert issubclass(cls, StorageError)
    assert issubclass(StorageError, ParrotError)
    assert str(StorageWriteError("boom")) == "boom"


def test_new_operations_are_abstract():
    """The durable operations are @abstractmethod; the ABC is still not instantiable."""
    assert NEW_ABSTRACT <= set(ConversationBackend.__abstractmethods__)
    with pytest.raises(TypeError):
        ConversationBackend()  # type: ignore[abstract]


def test_backfill_batch_is_frozen():
    batch = BackfillBatch(1, None, ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        batch.processed = 2  # type: ignore[misc]


def test_durable_contract_is_not_collected():
    """durable_contract.py must not be a pytest module (no test_ prefix, no collectable test functions)."""
    assert not durable_contract.__name__.rsplit(".", 1)[-1].startswith("test_")
    assert not [n for n in dir(durable_contract) if n.startswith("test_")]


# ---------------------------------------------------------------------------
# In-file reference backend: the executable definition of the contract.
# ---------------------------------------------------------------------------


def _parse(ts) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(ts)).astimezone(timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


class _ReferenceBackend(ConversationBackend):
    """Complete in-memory implementation of the durable contract."""

    ascending_limit = False  # flipped by the mutation test

    def __init__(self) -> None:
        self.connected = True
        self.fail_writes = False
        self.turns: Dict[Tuple[str, str, str], Dict[str, dict]] = {}
        self.indexed: Dict[Tuple[str, str, str], Set[str]] = {}
        self.tombs: Set[Tuple[str, str, str, Optional[str]]] = set()
        self.state: Dict[Tuple[str, str, str], str] = {}

    async def initialize(self): ...
    async def close(self):
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def put_thread(self, *a, **kw): ...
    async def update_thread(self, *a, **kw): ...
    async def query_threads(self, *a, **kw):
        return []

    async def delete_turn(self, *a, **kw):
        return False

    async def put_artifact(self, *a, **kw): ...
    async def get_artifact(self, *a, **kw):
        return None

    async def query_artifacts(self, *a, **kw):
        return []

    async def delete_artifact(self, *a, **kw): ...
    async def delete_session_artifacts(self, *a, **kw):
        return 0

    def _need(self) -> None:
        if not self.connected:
            raise StorageUnavailableError("disconnected")

    async def put_turn(self, user_id, agent_id, session_id, turn_id, data):
        self._need()
        if (user_id, agent_id, session_id, None) in self.tombs or (
            user_id,
            agent_id,
            session_id,
            turn_id,
        ) in self.tombs:
            raise ConversationDeletedError(turn_id)
        if self.fail_writes:
            raise StorageWriteError("injected")
        key = (user_id, agent_id, session_id)
        rows = self.turns.setdefault(key, {})
        if turn_id not in rows:
            rows[turn_id] = dict(data)
            self.state.setdefault(key, "ready")

    async def query_turns(self, user_id, agent_id, session_id, limit=10, newest_first=True):
        self._need()
        return list(self.turns.get((user_id, agent_id, session_id), {}).values())[:limit]

    async def delete_thread_cascade(self, user_id, agent_id, session_id):
        n = len(self.turns.pop((user_id, agent_id, session_id), {}))
        return n

    async def query_turn_window(self, user_id, agent_id, session_id, limit):
        self._need()
        if (user_id, agent_id, session_id, None) in self.tombs:
            raise ConversationDeletedError(session_id)
        key = (user_id, agent_id, session_id)
        if self.state.get(key, "ready") != "ready":
            raise IndexNotReadyError(session_id)
        rows = sorted(
            self.turns.get(key, {}).values(),
            key=lambda r: (_parse(r["timestamp"]), r.get("sequence") or 0, r["turn_id"]),
        )
        return rows[:limit] if self.ascending_limit else rows[-limit:]

    async def max_sequence(self, user_id, agent_id, session_id):
        rows = self.turns.get((user_id, agent_id, session_id), {}).values()
        return max((r.get("sequence") or 0 for r in rows), default=0)

    async def put_tombstone(self, user_id, agent_id, session_id, turn_id=None):
        self.tombs.add((user_id, agent_id, session_id, turn_id))

    async def deleted_turn_ids(self, user_id, agent_id, session_id):
        self._need()
        return {t for (u, a, s_, t) in self.tombs if (u, a, s_) == (user_id, agent_id, session_id) and t}

    async def deleted_session_ids(self, user_id, agent_id, session_ids):
        self._need()
        return {s for s in session_ids if (user_id, agent_id, s, None) in self.tombs}

    async def is_deleted(self, user_id, agent_id, session_id, turn_id=None):
        self._need()
        session_gone = (user_id, agent_id, session_id, None) in self.tombs
        return session_gone or (turn_id is not None and (user_id, agent_id, session_id, turn_id) in self.tombs)

    async def get_index_state(self, user_id, agent_id, session_id):
        return self.state.get((user_id, agent_id, session_id), "ready")

    async def backfill_batch(self, cursor, batch_size):
        pending = sorted(k for k, v in self.state.items() if v == "pending")
        pending = [k for k in pending if cursor is None or "/".join(k) > cursor][:batch_size]
        processed, invalid = 0, []
        for key in pending:
            rows = self.turns[key].values()
            processed += len(self.turns[key])
            bad = any(_parse(r.get("timestamp")) is None for r in rows)
            self.state[key] = "invalid" if bad else "ready"
            if bad:
                invalid.append(key[2])
        more = any(v == "pending" for v in self.state.values())
        return BackfillBatch(processed, "/".join(pending[-1]) if pending and more else None, tuple(invalid))


def _reference_harness(backend: Optional[_ReferenceBackend] = None) -> DurableHarness:
    backend = backend or _ReferenceBackend()

    @asynccontextmanager
    async def fail():
        backend.fail_writes = True
        try:
            yield
        finally:
            backend.fail_writes = False

    async def seed(session_id: str, rows: List[dict]) -> None:
        key = (durable_contract.USER, durable_contract.AGENT, session_id)
        backend.turns[key] = {r["turn_id"]: dict(r) for r in rows}
        backend.state[key] = "pending"

    async def expire(session_id: str) -> None:
        backend.turns.pop((durable_contract.USER, durable_contract.AGENT, session_id), None)

    return DurableHarness(backend, backend.close, fail, seed, expire)


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.__name__)
async def test_shared_checks_pass_against_reference_backend(check):
    await check(_reference_harness())


async def test_window_check_fails_against_broken_backend():
    """Mutation: a backend applying ``limit`` ascending must be caught by the shared check."""

    class _BrokenWindow(_ReferenceBackend):
        ascending_limit = True

    with pytest.raises(AssertionError):
        await check_window_newest_ascending(_reference_harness(_BrokenWindow()))
