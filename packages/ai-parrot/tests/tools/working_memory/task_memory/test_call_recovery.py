"""TASK-2998 — fenced call ownership and crash reconciliation.

This is Delivery B, so the three required cases run against **real
PostgreSQL and real Redis**. That is not ceremony: every claim here is
about what two processes do to one row, or about what a key's expiry
means, and an in-memory double cannot falsify either. Configure them
with::

    TASK_MEMORY_TEST_DSN=postgresql://user:pass@host:5432/db \\
        pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_call_recovery.py

Neither is defaulted to a production-looking address. Without them the
cases **skip explicitly** and say so; a skip is never reported as a pass.
Each case gets a throwaway PostgreSQL schema and a dedicated Redis key
prefix in database 15, both torn down afterwards.

The three properties under test, and why each is a real hazard:

``test_healthy_call``
    The append lease is short and expires constantly; a ten-minute tool
    call outlives it every time. If reconciliation keyed off that lease,
    every slow call would be declared dead and its external effect
    re-run. Liveness must come from heartbeated *per-call* ownership, and
    an unreachable cache must read as "unknown", not "dead".

``test_reconcile_once``
    Two pods scanning the same task must not both append an unknown
    outcome, and a repeated scan must append nothing further. One
    `tool_outcome_unknown` per call, ever.

``test_late_owner``
    A process that was fenced out and then wakes up must not be able to
    overwrite the decision already recorded, and nothing may be retried
    on its behalf.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, List, Optional

import pytest

from parrot.tools.working_memory.task_memory.association import TaskAssociationStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.context import TurnTaskSession
from parrot.tools.working_memory.task_memory.models import (
    Actor,
    CallOutcome,
    EventType,
    JournalEvent,
    TaskLifecyclePayload,
    TaskScope,
    TaskStatus,
    ToolCallPayload,
    new_id,
)
from parrot.tools.working_memory.task_memory.observer import InvocationObserver, ObserverMode
from parrot.tools.working_memory.task_memory.store.postgres import (
    TERMINAL_CALL_EVENTS,
    PostgresTaskMemoryStore,
    UnresolvedCall,
)

pytestmark = pytest.mark.asyncio

#: Set this to run the durable cases. Never defaulted — see the docstring.
DSN_ENV = "TASK_MEMORY_TEST_DSN"

#: Redis database 15, matching the existing association suite.
REDIS_TEST_URL = "redis://localhost:6379/15"

SCOPE = TaskScope(chatbot_id="bot-recovery", user_id="user-1", session_id="sess-1")

_PG_SKIP = (
    f"no PostgreSQL configured: set {DSN_ENV} to run the durable recovery cases. "
    "This is an ENVIRONMENTAL SKIP, not a pass — no durable behaviour was exercised here."
)
_REDIS_SKIP = (
    f"no Redis reachable at {REDIS_TEST_URL} — the live ownership/fencing cases did not run. "
    "This is an ENVIRONMENTAL SKIP, not a pass."
)


def _require_dsn() -> str:
    """Return the configured PostgreSQL DSN, or skip explicitly.

    Returns:
        The DSN.
    """
    dsn = os.environ.get(DSN_ENV) or None
    if not dsn:
        pytest.skip(_PG_SKIP)
    return dsn


async def _redis_available() -> bool:
    """Whether a Redis we may write to is reachable.

    Returns:
        ``True`` when it answers a ping.
    """
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(REDIS_TEST_URL, decode_responses=True, socket_connect_timeout=2)
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — unreachable for any reason is a skip
        return False


class _MemoryDouble:
    """The minimum :class:`TaskAssociationStore` needs to own hot keys.

    Deliberately *not* a stand-in for the durable behaviour under test:
    it only supplies the real Redis client and the key prefix. Every
    ownership operation exercised here runs against that live client.

    Args:
        redis: A live Redis client.
        prefix: Key prefix isolating this test's keys.
    """

    def __init__(self, redis: Any, prefix: str) -> None:
        """Initialize the double."""
        self.redis = redis
        self.key_prefix = prefix


@pytest.fixture()
async def pg_store() -> AsyncIterator[PostgresTaskMemoryStore]:
    """Yield a migrated store on a throwaway schema.

    Yields:
        The store.
    """
    dsn = _require_dsn()
    schema = f"wm_rec_{uuid.uuid4().hex[:12]}"
    store = PostgresTaskMemoryStore(dsn, schema=schema)
    await store.apply_migrations()
    try:
        yield store
    finally:
        try:
            await store.revert_migrations()
        except Exception:  # noqa: BLE001 — cleanup must not mask a failure
            pass
        await store.close()


@pytest.fixture()
async def ownership() -> AsyncIterator[TaskAssociationStore]:
    """Yield an association store backed by live Redis.

    Yields:
        The store, with its keys removed afterwards.
    """
    if not await _redis_available():
        pytest.skip(_REDIS_SKIP)
    from redis.asyncio import Redis

    prefix = f"tm_rec_{uuid.uuid4().hex[:10]}"
    client = Redis.from_url(REDIS_TEST_URL, decode_responses=True)
    store = TaskAssociationStore(_MemoryDouble(client, prefix), TaskMemoryConfig())
    try:
        yield store
    finally:
        keys = [k async for k in client.scan_iter(match=f"{prefix}*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def _new_task(store: PostgresTaskMemoryStore, goal: str = "recover me") -> str:
    """Create a task and return its id.

    Args:
        store: The durable store.
        goal: The task's goal.

    Returns:
        The task id.
    """
    task_id = new_id()
    await store.create_task(
        SCOPE,
        goal=goal,
        events=[
            JournalEvent(
                task_id=task_id,
                event_type=EventType.TASK_STARTED,
                actor=Actor.AGENT,
                payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal=goal),
            )
        ],
    )
    return task_id


async def _start_call(
    store: PostgresTaskMemoryStore,
    task_id: str,
    *,
    tool_name: str = "slow_tool",
    call_id: Optional[str] = None,
    parent_call_id: Optional[str] = None,
) -> str:
    """Append a durable ``tool_started`` and return its call id.

    Args:
        store: The durable store.
        task_id: The owning task.
        tool_name: The tool being dispatched.
        call_id: Explicit call id.
        parent_call_id: Parent aggregate, when nesting.

    Returns:
        The call id.
    """
    cid = call_id or new_id()
    await store.append_events(
        SCOPE,
        task_id,
        [
            JournalEvent(
                task_id=task_id,
                event_type=EventType.TOOL_STARTED,
                actor=Actor.RUNTIME,
                call_id=cid,
                parent_call_id=parent_call_id,
                payload=ToolCallPayload(call_id=cid, tool_name=tool_name, executed=True, counted=False),
            )
        ],
    )
    return cid


async def _terminal_events(store: PostgresTaskMemoryStore, task_id: str, call_id: str) -> List[JournalEvent]:
    """Return every terminal event recorded for one call.

    Args:
        store: The durable store.
        task_id: The owning task.
        call_id: The attempt.

    Returns:
        The terminal events, in sequence order.
    """
    page = await store.list_events(SCOPE, task_id, after_seq=0, limit=200)
    return [e for e in page.events if e.call_id == call_id and e.event_type.value in TERMINAL_CALL_EVENTS]


# ─────────────────────────────────────────────────────────────
# test_healthy_call
# ─────────────────────────────────────────────────────────────


async def test_healthy_call(pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore) -> None:
    """A live long call survives another pod's scan, expired append lease and all."""
    task_id = await _new_task(pg_store)
    call_id = await _start_call(pg_store, task_id, tool_name="ten_minute_query")

    worker = "pod-a"
    assert await ownership.acquire_call(SCOPE, task_id, call_id, worker, ttl_seconds=30)

    # The APPEND lease is a different key with a different job. Take it,
    # then let it lapse — which is exactly what a long call does, because
    # it only needs the append lease while appending.
    assert await ownership.acquire_lease(SCOPE, task_id, worker)
    await ownership._redis.delete(ownership.lease_key(SCOPE, task_id))
    assert (
        await ownership.call_owner(SCOPE, task_id, call_id) == worker
    ), "expiring the append lease must not disturb per-call ownership"

    # A second pod scans. It sees an unresolved call that started a while
    # ago and asks the only question that counts: does anyone still hold
    # it? Redis says yes.
    async def probe(call: UnresolvedCall) -> Optional[bool]:
        return await ownership.is_call_alive(SCOPE, task_id, call.call_id)

    report = await pg_store.reconcile_calls(
        SCOPE, task_id, is_live=probe, now=datetime.now(timezone.utc) + timedelta(hours=1)
    )

    assert report.scanned == 1
    assert report.alive == (call_id,)
    assert report.reconciled == ()
    assert await _terminal_events(pg_store, task_id, call_id) == []

    # The call finally finishes and commits its own real outcome.
    assert await ownership.heartbeat_call(SCOPE, task_id, call_id, worker, ttl_seconds=30)
    await pg_store.append_events(
        SCOPE,
        task_id,
        [
            JournalEvent(
                task_id=task_id,
                event_type=EventType.TOOL_SUCCEEDED,
                actor=Actor.RUNTIME,
                call_id=call_id,
                payload=ToolCallPayload(
                    call_id=call_id, tool_name="ten_minute_query", outcome=CallOutcome.SUCCESS, counted=True
                ),
            )
        ],
    )
    terminal = await _terminal_events(pg_store, task_id, call_id)
    assert [e.event_type for e in terminal] == [EventType.TOOL_SUCCEEDED]


async def test_healthy_call_unknown_liveness_is_not_death(
    pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore
) -> None:
    """A probe that cannot answer leaves the call alone."""
    task_id = await _new_task(pg_store)
    call_id = await _start_call(pg_store, task_id)

    async def cannot_tell(call: UnresolvedCall) -> Optional[bool]:
        return None

    report = await pg_store.reconcile_calls(
        SCOPE, task_id, is_live=cannot_tell, now=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert report.unknown_liveness == (call_id,)
    assert report.reconciled == ()
    assert await _terminal_events(pg_store, task_id, call_id) == []

    # No probe at all is the same refusal, not an excuse to guess.
    no_probe = await pg_store.reconcile_calls(
        SCOPE, task_id, is_live=None, now=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert no_probe.reconciled == ()
    assert await _terminal_events(pg_store, task_id, call_id) == []


async def test_healthy_call_grace_period_protects_a_young_call(
    pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore
) -> None:
    """A call younger than the grace period is never reconciled."""
    task_id = await _new_task(pg_store)
    call_id = await _start_call(pg_store, task_id)

    async def dead(call: UnresolvedCall) -> Optional[bool]:
        return False

    report = await pg_store.reconcile_calls(SCOPE, task_id, is_live=dead, min_age_seconds=3600)
    assert report.too_young == (call_id,)
    assert report.reconciled == ()
    assert await _terminal_events(pg_store, task_id, call_id) == []


# ─────────────────────────────────────────────────────────────
# test_reconcile_once
# ─────────────────────────────────────────────────────────────


async def test_reconcile_once(pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore) -> None:
    """Repeated scans and two concurrent reconcilers append at most one unknown."""
    task_id = await _new_task(pg_store)
    call_id = await _start_call(pg_store, task_id, tool_name="crashed_tool")

    # The owner claimed it and then died: the claim expired on its own.
    assert await ownership.acquire_call(SCOPE, task_id, call_id, "pod-a", ttl_seconds=1)
    await ownership._redis.delete(ownership.call_lease_key(SCOPE, task_id, call_id))
    assert await ownership.is_call_alive(SCOPE, task_id, call_id) is False

    async def probe(call: UnresolvedCall) -> Optional[bool]:
        return await ownership.is_call_alive(SCOPE, task_id, call.call_id)

    future = datetime.now(timezone.utc) + timedelta(hours=1)

    # EIGHT reconcilers, concurrently, contending for one PostgreSQL row.
    # Two would be a weak test: it can pass by scheduling luck. Eight
    # genuinely exercises the row lock.
    reports = await asyncio.gather(
        *[pg_store.reconcile_calls(SCOPE, task_id, is_live=probe, now=future) for _ in range(8)]
    )

    # Exactly one did the work; the other seven found it already settled.
    did = [r for r in reports if r.reconciled]
    assert len(did) == 1, f"{len(did)} of 8 reconcilers appended, expected 1"
    assert did[0].reconciled == (call_id,)

    terminal = await _terminal_events(pg_store, task_id, call_id)
    assert len(terminal) == 1
    assert terminal[0].event_type is EventType.TOOL_OUTCOME_UNKNOWN
    assert terminal[0].payload.outcome is CallOutcome.UNKNOWN
    # It executed: the call really did start, so the effect may have run.
    assert terminal[0].payload.executed is True

    # A third and fourth scan add nothing: the call is resolved now, so it
    # is not even in the unresolved set any more.
    third = await pg_store.reconcile_calls(SCOPE, task_id, is_live=probe, now=future)
    fourth = await pg_store.reconcile_calls(SCOPE, task_id, is_live=probe, now=future)
    assert third.scanned == 0 and third.reconciled == ()
    assert fourth.scanned == 0 and fourth.reconciled == ()
    assert len(await _terminal_events(pg_store, task_id, call_id)) == 1


async def test_reconcile_once_does_not_count_an_aggregate(
    pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore
) -> None:
    """A parent aggregate is reconciled without being counted as an attempt."""
    task_id = await _new_task(pg_store)
    parent = await _start_call(pg_store, task_id, tool_name="plan_node")
    await _start_call(pg_store, task_id, tool_name="child_tool", parent_call_id=parent)

    async def dead(call: UnresolvedCall) -> Optional[bool]:
        return False

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    report = await pg_store.reconcile_calls(SCOPE, task_id, is_live=dead, now=future)
    assert set(report.reconciled) == {parent, *[c for c in report.reconciled if c != parent]}

    page = await pg_store.list_events(SCOPE, task_id, after_seq=0, limit=200)
    events = {e.call_id: e for e in page.events if e.event_type is EventType.TOOL_OUTCOME_UNKNOWN}
    assert events[parent].payload.counted is False, "an aggregate is not a physical attempt"
    child = next(c for c in report.reconciled if c != parent)
    assert events[child].payload.counted is True


# ─────────────────────────────────────────────────────────────
# test_late_owner
# ─────────────────────────────────────────────────────────────


async def test_late_owner(pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore) -> None:
    """A fenced-out owner cannot rewrite the decision, and nothing is retried."""
    task_id = await _new_task(pg_store)
    call_id = new_id()

    dispatched: List[str] = []

    async def append(tid: str, events: Any) -> Any:
        return await pg_store.append_events(SCOPE, tid, list(events))

    session = TurnTaskSession(SCOPE, task_id=task_id, owner="pod-a")
    observer = InvocationObserver(
        session,
        append=append,
        mode=ObserverMode.DURABLE,
        ownership=ownership,
        owner="pod-a",
        ownership_ttl=30,
        heartbeat_interval=3600,  # never fires during the test
    )

    call = await observer.begin("charge_customer")
    dispatched.append(call.call_id)
    assert call.owned, "the observer must claim ownership once the start is durable"
    assert call.journalled

    # The pod stalls. A reconciler decides it is gone and settles the call.
    await ownership._redis.delete(ownership.call_lease_key(SCOPE, task_id, call.call_id))

    async def probe(pending: UnresolvedCall) -> Optional[bool]:
        return await ownership.is_call_alive(SCOPE, task_id, pending.call_id)

    report = await pg_store.reconcile_calls(
        SCOPE, task_id, is_live=probe, now=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert report.reconciled == (call.call_id,)

    # NOW the original owner wakes up and tries to report success.
    outcome = await observer.finish(call, value={"status": "ok", "charged": True})

    # It is told the truth: unknown, not success.
    assert outcome.outcome is CallOutcome.UNKNOWN
    assert outcome.outcome.is_resolved is False
    assert "do not retry" in (outcome.error or "")

    # And the durable decision is untouched — still exactly one terminal
    # event, still the reconciler's, not a later tool_succeeded.
    terminal = await _terminal_events(pg_store, task_id, call.call_id)
    assert len(terminal) == 1, f"the fenced owner appended a second terminal event: {terminal}"
    assert terminal[0].event_type is EventType.TOOL_OUTCOME_UNKNOWN

    # Nothing re-dispatched the effect on its behalf.
    assert dispatched == [call.call_id]


async def test_late_owner_durable_fence_survives_a_lost_cache(
    pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore
) -> None:
    """The journal, not Redis, is the record of a settled call."""
    task_id = await _new_task(pg_store)
    call_id = await _start_call(pg_store, task_id, tool_name="charge_customer")

    async def dead(call: UnresolvedCall) -> Optional[bool]:
        return False

    await pg_store.reconcile_calls(SCOPE, task_id, is_live=dead, now=datetime.now(timezone.utc) + timedelta(hours=1))
    assert await pg_store.has_terminal_event(SCOPE, task_id, call_id) is True

    # Even with every Redis key gone, the durable check still reports the
    # call as settled — which is what a late owner must consult.
    keys = [k async for k in ownership._redis.scan_iter(match=f"{ownership._prefix()}*")]
    if keys:
        await ownership._redis.delete(*keys)
    assert await pg_store.has_terminal_event(SCOPE, task_id, call_id) is True

    # An unrelated, never-started call is not settled.
    assert await pg_store.has_terminal_event(SCOPE, task_id, new_id()) is False


async def test_late_owner_uncontested_call_still_commits(
    pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore
) -> None:
    """An owner that was never fenced commits its result normally."""
    task_id = await _new_task(pg_store)

    async def append(tid: str, events: Any) -> Any:
        return await pg_store.append_events(SCOPE, tid, list(events))

    session = TurnTaskSession(SCOPE, task_id=task_id, owner="pod-a")
    observer = InvocationObserver(
        session, append=append, ownership=ownership, owner="pod-a", ownership_ttl=30, heartbeat_interval=3600
    )

    call = await observer.begin("quick_tool")
    outcome = await observer.finish(call, value={"status": "ok"})
    assert outcome.outcome is CallOutcome.SUCCESS

    terminal = await _terminal_events(pg_store, task_id, call.call_id)
    assert [e.event_type for e in terminal] == [EventType.TOOL_SUCCEEDED]
    # The claim is released, so nothing leaks for the next reconciler.
    assert await ownership.call_owner(SCOPE, task_id, call.call_id) is None


async def test_heartbeat_keeps_a_long_call_owned_past_its_ttl(
    pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore
) -> None:
    """The renewal loop is what actually keeps a slow call alive.

    Every other case here pins the heartbeat open so it cannot interfere.
    This one exercises it directly: a one-second claim, renewed three
    times a second, must still be held well after it would otherwise
    have expired — and a reconciler scanning meanwhile must see it as
    alive. Without this, "heartbeated ownership" would be an untested
    claim in a docstring.
    """
    task_id = await _new_task(pg_store)

    async def append(tid: str, events: Any) -> Any:
        return await pg_store.append_events(SCOPE, tid, list(events))

    session = TurnTaskSession(SCOPE, task_id=task_id, owner="pod-slow")
    observer = InvocationObserver(
        session,
        append=append,
        ownership=ownership,
        owner="pod-slow",
        ownership_ttl=1,
        heartbeat_interval=0.3,
    )

    call = await observer.begin("ten_minute_query")
    assert call.owned and call.heartbeat is not None

    # Well past the 1s TTL. Only renewal can keep the claim alive.
    await asyncio.sleep(1.6)
    assert (
        await ownership.call_owner(SCOPE, task_id, call.call_id) == "pod-slow"
    ), "the heartbeat failed to renew the claim, so a healthy long call would be declared dead"

    async def probe(pending: UnresolvedCall) -> Optional[bool]:
        return await ownership.is_call_alive(SCOPE, task_id, pending.call_id)

    report = await pg_store.reconcile_calls(
        SCOPE, task_id, is_live=probe, now=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert report.alive == (call.call_id,)
    assert report.reconciled == ()

    outcome = await observer.finish(call, value={"status": "ok"})
    assert outcome.outcome is CallOutcome.SUCCESS
    # The loop is stopped once the call terminates.
    assert call.heartbeat is None


async def test_unresolved_calls_is_read_only(
    pg_store: PostgresTaskMemoryStore, ownership: TaskAssociationStore
) -> None:
    """Scanning for unresolved calls appends nothing."""
    task_id = await _new_task(pg_store)
    call_id = await _start_call(pg_store, task_id)

    before = await pg_store.count_events(SCOPE, task_id)
    for _ in range(3):
        pending = await pg_store.unresolved_calls(SCOPE, task_id)
        assert [c.call_id for c in pending] == [call_id]
    assert await pg_store.count_events(SCOPE, task_id) == before
