"""BusCore — queued, worker-pool event dispatcher (FEAT-310, Module 2).

Replaces the sequential-await defect of the legacy ``EventBus.publish()``
(evb.py) with:

- **O(1) publish**: ``publish()`` enqueues into per-priority
  ``asyncio.Queue``s and returns before any handler runs (goal G2).
- **Bounded worker pool**: an ``asyncio.TaskGroup`` of N workers drains the
  queues in strict priority order (CRITICAL before LOW under load).
- **Severity-filtered subscriptions**: ``min_severity`` filters delivery
  only — severity NEVER affects scheduling (goal G3, filtering half).
- **Retry-with-backoff → DLQ hook**: exhausted retries hand the envelope to
  an ``on_dlq`` callback (persistence arrives with ``DLQHandler``).
- **Per-topic-class backpressure**: ``block`` (default), ``drop_oldest``,
  ``reject`` — activation emits a ``bus.backpressure`` meta-event (goal G7).
- **Error isolation model B**: handler exceptions never propagate to the
  emitter; they surface as ``bus.subscriber_error`` meta-events guarded
  against recursion by a ``contextvars.ContextVar`` (same mechanism as
  ``EventRegistry`` in ``lifecycle/registry.py``).
"""
from __future__ import annotations

import asyncio
import contextvars
import fnmatch
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from navconfig.logging import logging

from parrot.core.events.evb import EventPriority
from parrot.core.events.bus.envelope import EventEnvelope, Severity

# Backpressure policy names (per topic class).
POLICY_BLOCK = "block"
POLICY_DROP_OLDEST = "drop_oldest"
POLICY_REJECT = "reject"
_VALID_POLICIES = (POLICY_BLOCK, POLICY_DROP_OLDEST, POLICY_REJECT)

# Meta-event topics defined by this module.
TOPIC_SUBSCRIBER_ERROR = "bus.subscriber_error"
TOPIC_BACKPRESSURE = "bus.backpressure"

# Recursion guard: True while a ``bus.*`` meta-envelope is being dispatched,
# so a failing meta-event handler does not spawn another meta-event and loop
# (mirror of ``_emitting_meta`` in lifecycle/registry.py).
_in_meta_dispatch: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_in_meta_dispatch", default=False
)

# DLQ callback: (envelope, *, attempts, error, subscriber_id) -> None|Awaitable
DLQCallback = Callable[..., Any]


class BusClosedError(RuntimeError):
    """Raised when publishing after ``close()`` has begun."""


class BackpressureError(RuntimeError):
    """Raised to the emitter when the ``reject`` policy is active and full."""


@dataclass
class _BusSubscription:
    """Internal record for a single topic subscription.

    Attributes:
        pattern: Exact topic or glob pattern (``order.*``, ``*``).
        handler: Callable invoked with the matching :class:`EventEnvelope`.
        subscriber_id: Unique id returned to the caller for unsubscribe.
        priority: Execution ordering among matching handlers (higher first).
        filter_fn: Optional predicate — envelope delivered only if truthy.
        min_severity: Optional severity floor — envelopes below are skipped.
        async_handler: Whether ``handler`` is a coroutine function.
    """

    pattern: str
    handler: Callable[[EventEnvelope], Any]
    subscriber_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 0
    filter_fn: Optional[Callable[[EventEnvelope], bool]] = None
    min_severity: Optional[Severity] = None
    async_handler: bool = True


class BusCore:
    """Queued event dispatcher with a bounded worker pool.

    ``publish()`` is an O(1) enqueue into one ``asyncio.Queue`` per
    :class:`EventPriority`; a pool of ``workers`` tasks drains the queues in
    strict priority order and dispatches to matching subscriptions.

    Args:
        workers: Number of concurrent dispatch workers.
        queue_size: Max size of EACH per-priority queue (0 = unbounded).
        handler_timeout: Per-handler ``asyncio.timeout`` in seconds; a
            timeout counts as a failure toward retry.
        retry_attempts: Total delivery attempts per handler (>=1).
        retry_base_delay: Base backoff delay in seconds; attempt *n* waits
            ``retry_base_delay * 2**(n-1)``.
        backpressure: Optional mapping of topic (exact) or topic class
            (first dot-segment) to a policy name (``block`` /
            ``drop_oldest`` / ``reject``).
        default_backpressure: Policy used when no mapping matches.
        drain_timeout: Deadline in seconds for the graceful drain in
            :meth:`close`.
        on_dlq: Optional callback invoked (sync or async) when a handler
            exhausts its retries, as
            ``on_dlq(envelope, attempts=..., error=..., subscriber_id=...)``.

    Raises:
        ValueError: If a configured backpressure policy name is unknown.
    """

    def __init__(
        self,
        *,
        workers: int = 4,
        queue_size: int = 1024,
        handler_timeout: float = 30.0,
        retry_attempts: int = 3,
        retry_base_delay: float = 0.1,
        backpressure: Optional[dict[str, str]] = None,
        default_backpressure: str = POLICY_BLOCK,
        drain_timeout: float = 5.0,
        on_dlq: Optional[DLQCallback] = None,
    ) -> None:
        for policy in [default_backpressure, *(backpressure or {}).values()]:
            if policy not in _VALID_POLICIES:
                raise ValueError(
                    f"Unknown backpressure policy {policy!r}; "
                    f"expected one of {_VALID_POLICIES}"
                )
        self._workers = max(1, workers)
        self._queue_size = queue_size
        self._handler_timeout = handler_timeout
        self._retry_attempts = max(1, retry_attempts)
        self._retry_base_delay = retry_base_delay
        self._backpressure = dict(backpressure or {})
        self._default_backpressure = default_backpressure
        self._drain_timeout = drain_timeout
        self._on_dlq = on_dlq

        # Highest priority first — workers scan in this order.
        self._priority_order: list[EventPriority] = sorted(
            EventPriority, key=lambda p: p.value, reverse=True
        )
        self._queues: dict[EventPriority, asyncio.Queue[EventEnvelope]] = {
            prio: asyncio.Queue(maxsize=queue_size)
            for prio in self._priority_order
        }
        # Counts enqueued items; workers block here when idle. Workers are
        # spurious-wakeup tolerant (drop_oldest can skew the count by design).
        self._items = asyncio.Semaphore(0)

        # Subscriptions: exact-topic map + wildcard list (same algorithm as
        # the legacy EventBus._get_matching_subscriptions).
        self._subscriptions: dict[str, list[_BusSubscription]] = {}
        self._pattern_subscriptions: list[_BusSubscription] = []

        self._runner: Optional[asyncio.Task[None]] = None
        self._started = False
        self._closing = False
        self._stopping = False
        self._in_flight = 0

        self.logger = logging.getLogger("parrot.core.events.bus.core")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the worker pool. Idempotent."""
        if self._started:
            return
        self._started = True
        self._closing = False
        self._stopping = False
        self._runner = asyncio.create_task(
            self._run_workers(), name="bus-core-workers"
        )
        self.logger.debug("BusCore started with %d workers", self._workers)

    async def close(self, drain_timeout: Optional[float] = None) -> None:
        """Gracefully shut down: reject new publishes, drain, stop workers.

        Args:
            drain_timeout: Optional override of the configured drain
                deadline (seconds).
        """
        if self._closing:
            return
        self._closing = True
        deadline = drain_timeout if drain_timeout is not None else self._drain_timeout
        try:
            await asyncio.wait_for(self._drain(), timeout=deadline)
        except (asyncio.TimeoutError, TimeoutError):
            pending = sum(q.qsize() for q in self._queues.values())
            self.logger.warning(
                "BusCore drain deadline (%.1fs) exceeded; %d envelopes "
                "still pending", deadline, pending
            )
        self._stopping = True
        # Wake every worker so it can observe _stopping and exit.
        for _ in range(self._workers):
            self._items.release()
        if self._runner is not None:
            try:
                await asyncio.wait_for(self._runner, timeout=deadline)
            except (asyncio.TimeoutError, TimeoutError):
                self._runner.cancel()
                try:
                    await self._runner
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self._runner = None
        self._started = False
        self.logger.debug("BusCore closed")

    async def _drain(self) -> None:
        """Wait until all queues are empty and no dispatch is in flight."""
        while (
            any(not q.empty() for q in self._queues.values())
            or self._in_flight > 0
        ):
            await asyncio.sleep(0.01)

    # ------------------------------------------------------------------
    # Publish / subscribe API
    # ------------------------------------------------------------------

    async def publish(self, envelope: EventEnvelope) -> None:
        """Enqueue *envelope* for dispatch — O(1), never awaits a handler.

        Args:
            envelope: The envelope to dispatch.

        Raises:
            BusClosedError: If :meth:`close` has begun.
            BackpressureError: If the target queue is full and the
                ``reject`` policy applies to the envelope's topic class.
        """
        if self._closing:
            raise BusClosedError(
                "BusCore is closing — publish() rejected"
            )
        queue = self._queues[envelope.priority]
        if queue.full():
            policy = self._policy_for(envelope.topic)
            self._emit_backpressure_meta(envelope, policy)
            if policy == POLICY_REJECT:
                raise BackpressureError(
                    f"Queue for priority {envelope.priority.name} is full "
                    f"(policy=reject, topic={envelope.topic})"
                )
            if policy == POLICY_DROP_OLDEST:
                try:
                    dropped = queue.get_nowait()
                    self.logger.warning(
                        "Backpressure drop_oldest: dropped %s (%s)",
                        dropped.topic, dropped.event_id,
                    )
                except asyncio.QueueEmpty:  # drained meanwhile
                    pass
                queue.put_nowait(envelope)
                self._items.release()
                return
            # POLICY_BLOCK: await until space frees up.
            await queue.put(envelope)
            self._items.release()
            return
        queue.put_nowait(envelope)
        self._items.release()

    def subscribe(
        self,
        pattern: str,
        handler: Callable[[EventEnvelope], Any],
        *,
        priority: int = 0,
        filter_fn: Optional[Callable[[EventEnvelope], bool]] = None,
        min_severity: Optional[Severity] = None,
    ) -> str:
        """Subscribe *handler* to topics matching *pattern*.

        Args:
            pattern: Exact topic (``order.created``) or glob (``order.*``).
            handler: Sync or async callable receiving the envelope.
            priority: Execution order among matching handlers (higher first).
            filter_fn: Optional predicate; envelope delivered only if truthy.
            min_severity: Optional severity floor — filters delivery only,
                never scheduling.

        Returns:
            The ``subscriber_id`` usable with :meth:`unsubscribe`.
        """
        subscription = _BusSubscription(
            pattern=pattern,
            handler=handler,
            priority=priority,
            filter_fn=filter_fn,
            min_severity=min_severity,
            async_handler=asyncio.iscoroutinefunction(handler),
        )
        if "*" in pattern or "?" in pattern:
            self._pattern_subscriptions.append(subscription)
            self._pattern_subscriptions.sort(key=lambda s: -s.priority)
        else:
            self._subscriptions.setdefault(pattern, []).append(subscription)
            self._subscriptions[pattern].sort(key=lambda s: -s.priority)
        self.logger.debug(
            "Subscribed to '%s' with id %s", pattern, subscription.subscriber_id
        )
        return subscription.subscriber_id

    def unsubscribe(self, subscriber_id: str) -> bool:
        """Remove a subscription by id.

        Args:
            subscriber_id: Value returned by :meth:`subscribe`.

        Returns:
            ``True`` if found and removed, ``False`` otherwise.
        """
        for subs in self._subscriptions.values():
            for sub in subs:
                if sub.subscriber_id == subscriber_id:
                    subs.remove(sub)
                    return True
        for sub in self._pattern_subscriptions:
            if sub.subscriber_id == subscriber_id:
                self._pattern_subscriptions.remove(sub)
                return True
        return False

    # ------------------------------------------------------------------
    # Worker pool
    # ------------------------------------------------------------------

    async def _run_workers(self) -> None:
        """Run the bounded worker pool until shutdown."""
        async with asyncio.TaskGroup() as tg:
            for n in range(self._workers):
                tg.create_task(self._worker(), name=f"bus-core-worker-{n}")

    async def _worker(self) -> None:
        """Drain queues in strict priority order and dispatch envelopes."""
        while True:
            await self._items.acquire()
            envelope = self._pop_next()
            if envelope is None:
                if self._stopping:
                    return
                continue  # spurious wakeup (drop_oldest skew) — re-wait
            self._in_flight += 1
            try:
                await self._dispatch(envelope)
            finally:
                self._in_flight -= 1

    def _pop_next(self) -> Optional[EventEnvelope]:
        """Pop the next envelope, highest priority queue first."""
        for prio in self._priority_order:
            try:
                return self._queues[prio].get_nowait()
            except asyncio.QueueEmpty:
                continue
        return None

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, envelope: EventEnvelope) -> None:
        """Dispatch *envelope* to all matching subscriptions (model B)."""
        is_meta = envelope.topic.startswith("bus.")
        token = _in_meta_dispatch.set(True) if is_meta else None
        try:
            for sub in self._matching_subscriptions(envelope.topic):
                if (
                    sub.min_severity is not None
                    and envelope.severity < sub.min_severity
                ):
                    continue
                try:
                    if sub.filter_fn is not None and not sub.filter_fn(envelope):
                        continue
                except Exception:  # noqa: BLE001 — filter errors are isolated
                    self.logger.exception(
                        "filter_fn raised for subscriber %s on %s",
                        sub.subscriber_id, envelope.topic,
                    )
                    continue
                await self._invoke_with_retry(sub, envelope)
        finally:
            if token is not None:
                _in_meta_dispatch.reset(token)

    def _matching_subscriptions(self, topic: str) -> list[_BusSubscription]:
        """Find subscriptions matching *topic* (exact + glob), by priority."""
        matching: list[_BusSubscription] = []
        if topic in self._subscriptions:
            matching.extend(self._subscriptions[topic])
        matching.extend(
            sub
            for sub in self._pattern_subscriptions
            if fnmatch.fnmatch(topic, sub.pattern)
        )
        matching.sort(key=lambda s: -s.priority)
        return matching

    async def _invoke_with_retry(
        self, sub: _BusSubscription, envelope: EventEnvelope
    ) -> None:
        """Invoke one handler with timeout + retry-with-backoff (model B).

        Exhausted retries emit a ``bus.subscriber_error`` meta-event and
        hand the envelope to the DLQ callback. Never raises.
        """
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                async with asyncio.timeout(self._handler_timeout):
                    if sub.async_handler:
                        await sub.handler(envelope)
                    else:
                        sub.handler(envelope)
                return
            except Exception as exc:  # noqa: BLE001 — model B isolation
                last_exc = exc
                self.logger.warning(
                    "Handler %s failed on %s (attempt %d/%d): %s",
                    sub.subscriber_id, envelope.topic,
                    attempt, self._retry_attempts, exc,
                )
                if attempt < self._retry_attempts:
                    await asyncio.sleep(
                        self._retry_base_delay * (2 ** (attempt - 1))
                    )
        # Retries exhausted.
        assert last_exc is not None
        self._emit_subscriber_error(envelope, sub, last_exc)
        await self._invoke_dlq(envelope, sub, last_exc)

    async def _invoke_dlq(
        self,
        envelope: EventEnvelope,
        sub: _BusSubscription,
        error: BaseException,
    ) -> None:
        """Hand a terminally-failed envelope to the DLQ callback, if set.

        ``bus.*`` meta-envelopes are never sent to the DLQ — that would
        allow ``bus.dlq`` → notify → error → DLQ loops (spec §7).
        """
        if self._on_dlq is None or envelope.topic.startswith("bus."):
            return
        try:
            result = self._on_dlq(
                envelope,
                attempts=self._retry_attempts,
                error=error,
                subscriber_id=sub.subscriber_id,
            )
            if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
                await result
        except Exception:  # noqa: BLE001 — DLQ failures are isolated too
            self.logger.exception(
                "DLQ callback failed for %s (%s)",
                envelope.topic, envelope.event_id,
            )

    # ------------------------------------------------------------------
    # Meta-events
    # ------------------------------------------------------------------

    def _emit_subscriber_error(
        self,
        envelope: EventEnvelope,
        sub: _BusSubscription,
        exc: BaseException,
    ) -> None:
        """Enqueue a ``bus.subscriber_error`` meta-event (recursion-guarded)."""
        if _in_meta_dispatch.get():
            self.logger.error(
                "Recursion guard triggered: dropping nested "
                "bus.subscriber_error for %s", envelope.topic,
            )
            return
        self._publish_meta(
            TOPIC_SUBSCRIBER_ERROR,
            {
                "original_topic": envelope.topic,
                "original_event_id": envelope.event_id,
                "subscriber_id": sub.subscriber_id,
                "pattern": sub.pattern,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "attempts": self._retry_attempts,
            },
        )

    def _emit_backpressure_meta(
        self, envelope: EventEnvelope, policy: str
    ) -> None:
        """Enqueue a ``bus.backpressure`` meta-event (best-effort)."""
        if _in_meta_dispatch.get():
            return
        self._publish_meta(
            TOPIC_BACKPRESSURE,
            {
                "topic": envelope.topic,
                "event_id": envelope.event_id,
                "priority": envelope.priority.name,
                "policy": policy,
                "queue_size": self._queue_size,
            },
        )

    def _publish_meta(self, topic: str, payload: dict[str, Any]) -> None:
        """Best-effort enqueue of a ``bus.*`` meta-envelope.

        Meta-events default to ``Severity.INFO`` — capped below alert
        thresholds so they cannot trigger notification loops (spec §7).
        Dropped (with a log) if the target queue is full.
        """
        meta = EventEnvelope(
            topic=topic,
            payload=payload,
            source="bus-core",
            severity=Severity.INFO,
            priority=EventPriority.HIGH,
        )
        try:
            self._queues[meta.priority].put_nowait(meta)
            self._items.release()
        except asyncio.QueueFull:
            self.logger.warning("Meta-event %s dropped: queue full", topic)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _policy_for(self, topic: str) -> str:
        """Resolve the backpressure policy for *topic*.

        Lookup order: exact topic → topic class (first dot-segment) →
        configured default.
        """
        if topic in self._backpressure:
            return self._backpressure[topic]
        topic_class = topic.split(".", 1)[0]
        return self._backpressure.get(topic_class, self._default_backpressure)
