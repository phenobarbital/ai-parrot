"""Shared deterministic fixtures for the task-memory suite (FEAT-538 / TASK-2978).

Deliberately **fixtures only**: no hooks, no ``autouse``, no collection
configuration. Every module in this directory passed before this file
existed, and adding it must not change how any of them behave.

Every fixture is prefixed ``tm_`` for the same reason. A conftest fixture
named ``scope`` or ``store`` would silently shadow nothing today — a
module-local fixture of the same name still wins — but it would become a
trap the moment someone deleted a local fixture and got a different object
than they expected, with no error to point at. The prefix makes the
provenance obvious at the call site.

The clock and id fixtures exist because the reducer is required to be
pure: replaying the same journal must produce byte-identical state. Tests
that build journals therefore need timestamps and identifiers they
control, not ``utc_now()`` and ``uuid4()``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import pytest
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    EventType,
    JournalEvent,
    TaskLifecyclePayload,
    TaskScope,
    TaskStatus,
)
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore

#: A fixed instant every deterministic fixture derives from. Chosen once
#: so that a journal built in one test is comparable with one built in
#: another.
TM_EPOCH: datetime = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def tm_scope() -> TaskScope:
    """Return the canonical trusted scope for task-memory tests."""
    return TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


@pytest.fixture()
def tm_other_scope() -> TaskScope:
    """Return a second scope, for cross-scope isolation checks."""
    return TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")


@pytest.fixture()
def tm_clock() -> Callable[[], datetime]:
    """Return a deterministic, monotonically advancing clock.

    Each call returns :data:`TM_EPOCH` plus one more second. Journals
    built with it are reproducible, which is what lets a replay assertion
    mean something.

    Returns:
        A zero-argument callable yielding successive UTC timestamps.
    """
    counter = {"n": 0}

    def _tick() -> datetime:
        counter["n"] += 1
        return TM_EPOCH + timedelta(seconds=counter["n"])

    return _tick


@pytest.fixture()
def tm_config() -> TaskMemoryConfig:
    """Return the default (opt-in, non-durable) task-memory configuration."""
    return TaskMemoryConfig()


@pytest.fixture()
async def tm_store(tm_config: TaskMemoryConfig) -> AsyncIterator[InMemoryTaskMemoryStore]:
    """Yield a fresh, empty in-memory task store.

    Args:
        tm_config: Capacity configuration.

    Yields:
        The store, closed on teardown.
    """
    store = InMemoryTaskMemoryStore(tm_config)
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture()
def tm_event(tm_clock: Callable[[], datetime]) -> Callable[..., JournalEvent]:
    """Return a factory for deterministic lifecycle journal events.

    Args:
        tm_clock: The deterministic clock.

    Returns:
        A callable ``(task_id, *, event_id, event_type=..., status=...,
        goal=None, reason=None) -> JournalEvent``.
    """

    def _make(
        task_id: str,
        *,
        event_id: str,
        event_type: EventType = EventType.TASK_STARTED,
        status: TaskStatus = TaskStatus.ACTIVE,
        goal: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> JournalEvent:
        return JournalEvent(
            event_id=event_id,
            task_id=task_id,
            event_type=event_type,
            occurred_at=tm_clock(),
            payload=TaskLifecyclePayload(status=status, goal=goal, reason=reason),
        )

    return _make


class SideEffectCounter:
    """Counts invocations of a fake tool, for exactly-once assertions.

    The spec is emphatic that an uncertain external effect must never be
    retried automatically. Proving that requires a tool whose *side
    effect* is observable independently of its return value — a mock's
    ``call_count`` is not enough, because it cannot distinguish "called
    once and the result was lost" from "called twice".

    Attributes:
        calls: One entry per invocation, in order, recording the
            arguments it was given.
    """

    def __init__(self) -> None:
        """Initialize an unused counter."""
        self.calls: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        """How many times the effect has actually run."""
        return len(self.calls)

    async def run(self, **kwargs: Any) -> Dict[str, Any]:
        """Perform the recorded side effect once.

        Args:
            **kwargs: Arbitrary arguments, recorded verbatim.

        Returns:
            A result dict carrying this invocation's 1-based ordinal, so
            a caller can tell two invocations apart.
        """
        async with self._lock:
            self.calls.append(dict(kwargs))
            return {"status": "ok", "invocation": len(self.calls)}

    def assert_ran_once(self) -> None:
        """Assert the effect ran exactly once.

        Raises:
            AssertionError: If it ran a different number of times.
        """
        assert self.count == 1, f"side effect ran {self.count} times, expected exactly 1: {self.calls}"


@pytest.fixture()
def tm_side_effects() -> SideEffectCounter:
    """Return a fresh :class:`SideEffectCounter` for exactly-once assertions."""
    return SideEffectCounter()
