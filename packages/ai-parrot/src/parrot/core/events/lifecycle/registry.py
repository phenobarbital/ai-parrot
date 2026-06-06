"""EventRegistry: typed lifecycle event dispatch with error isolation.

FEAT-176 — Lifecycle Events System.

This module provides the ``EventRegistry`` class — the central dispatch engine
for typed ``LifecycleEvent`` instances.  Key properties:

- **isinstance-based matching**: subscribing to ``LifecycleEvent`` receives
  every concrete event; subscribing to ``BeforeToolCallEvent`` receives only
  that subtype.
- **Deterministic ordering**: ``Before*`` events fire subscribers in
  FORWARD registration order (setup); ``After*`` and ``*Failed`` events fire
  subscribers in REVERSE registration order (cleanup symmetry).
- **Error isolation (model B)**: subscriber exceptions are caught, logged,
  and emitted as ``SubscriberErrorEvent`` to the global registry. The agent
  flow is NEVER interrupted by a subscriber failure.
- **Per-subscriber dual-emit opt-in**: set ``forward_to_bus=True`` on a
  subscription to also push the event payload to ``EventBus``.  Note:
  ``ClientStreamChunkEvent`` is never auto-forwarded — the per-subscriber
  flag is the only forwarding mechanism, which avoids bus pressure on high-
  frequency streaming events.
- **Recursion guard**: a ``contextvars.ContextVar`` prevents infinite loops
  when a ``SubscriberErrorEvent`` subscriber itself raises.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import traceback
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Type, TypeVar

from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent

if TYPE_CHECKING:
    from parrot.core.events.evb import EventBus

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

AsyncSubscriber = Callable[[LifecycleEvent], Awaitable[None]]
E = TypeVar("E", bound=LifecycleEvent)

# ContextVar used as recursion guard: True while _emit_meta() is running so
# that a failing SubscriberErrorEvent subscriber does not spawn another
# SubscriberErrorEvent and loop infinitely.
_emitting_meta: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_emitting_meta", default=False
)

logger = logging.getLogger("parrot.core.events.lifecycle.registry")


# ---------------------------------------------------------------------------
# Internal subscription record
# ---------------------------------------------------------------------------

@dataclass
class _Subscription:
    """Internal record for a single event subscription.

    Attributes:
        subscription_id: Unique identifier returned to the caller.
        event_type: The ``LifecycleEvent`` subclass this subscription matches.
        callback: Async callable invoked when a matching event is emitted.
        where: Optional predicate; if provided the event is only dispatched
            when ``where(event)`` is truthy.
        forward_to_bus: When ``True``, the event payload is also forwarded to
            the ``EventBus`` after the callback completes successfully.
        order: Monotonically increasing insertion counter for stable ordering.
    """

    subscription_id: str
    event_type: Type[LifecycleEvent]
    callback: AsyncSubscriber
    where: Optional[Callable[[Any], bool]]
    forward_to_bus: bool
    order: int


# ---------------------------------------------------------------------------
# EventRegistry
# ---------------------------------------------------------------------------

class EventRegistry:
    """Typed lifecycle event dispatcher.

    Args:
        event_bus: Optional ``EventBus`` instance for dual-emit subscribers.
        bus_channel_prefix: Prefix for ``EventBus`` channel names.
            Final channel: ``f"{prefix}.{EventClassName}"``.
            Defaults to ``"lifecycle"``.
        forward_to_global: When ``True`` (default), each emitted event is
            also forwarded to the process-wide global registry via
            ``get_global_registry()``. Set ``False`` in unit tests to keep
            tests isolated from the global singleton.
    """

    def __init__(
        self,
        *,
        event_bus: "Optional[EventBus]" = None,
        bus_channel_prefix: str = "lifecycle",
        forward_to_global: bool = True,
    ) -> None:
        self._subscriptions: list[_Subscription] = []
        self._event_bus = event_bus
        self._bus_channel_prefix = bus_channel_prefix
        self._forward_to_global = forward_to_global
        self._insertion_counter: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_type: Type[E],
        callback: AsyncSubscriber,
        *,
        where: "Optional[Callable[[E], bool]]" = None,
        forward_to_bus: bool = False,
    ) -> str:
        """Register an async subscriber for *event_type* (and its subclasses).

        Args:
            event_type: The ``LifecycleEvent`` subclass to listen for.  Use
                ``LifecycleEvent`` itself to receive all events.
            callback: An async callable ``async def f(event: E) -> None``.
            where: Optional predicate.  The subscriber is only invoked when
                ``where(event)`` returns truthy.
            forward_to_bus: When ``True`` and an ``EventBus`` is attached to
                this registry, the event payload is forwarded to the bus after
                the callback completes.

        Returns:
            A unique ``subscription_id`` string that can be passed to
            :meth:`unsubscribe` to remove the registration.
        """
        subscription_id = str(uuid.uuid4())
        self._subscriptions.append(
            _Subscription(
                subscription_id=subscription_id,
                event_type=event_type,
                callback=callback,
                where=where,
                forward_to_bus=forward_to_bus,
                order=self._insertion_counter,
            )
        )
        self._insertion_counter += 1
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription by its ID.

        Args:
            subscription_id: The value returned by :meth:`subscribe`.

        Returns:
            ``True`` if the subscription was found and removed, ``False`` if
            the ID was unknown.
        """
        before = len(self._subscriptions)
        self._subscriptions = [
            s for s in self._subscriptions if s.subscription_id != subscription_id
        ]
        return len(self._subscriptions) < before

    def has_subscribers(self, event_type: Type[E]) -> bool:
        """Return ``True`` if any subscriber would receive *event_type*.

        A subscriber matches if the registered ``event_type`` is a superclass or
        subclass of the queried ``event_type`` (bidirectional ``issubclass``).
        This catches both narrowly-typed subscribers (``ClientStreamChunkEvent``)
        and broadly-typed ones (``LifecycleEvent``).

        Use this on hot paths to short-circuit event construction when no one
        is listening (e.g., ``ClientStreamChunkEvent`` per streamed chunk).

        Args:
            event_type: The ``LifecycleEvent`` subclass to query.

        Returns:
            ``True`` if at least one registered subscription would match.
        """
        for s in self._subscriptions:
            try:
                if issubclass(event_type, s.event_type) or issubclass(s.event_type, event_type):
                    return True
            except TypeError:
                continue
        return False

    def add_provider(self, provider: Any) -> list[str]:
        """Register all subscriptions declared by an ``EventProvider``.

        The ``EventProvider`` protocol is defined in TASK-1188.  This method
        imports it lazily to avoid a circular dependency at module load time.

        Args:
            provider: An object implementing the ``EventProvider`` protocol
                (i.e., it has a ``register(registry)`` method).

        Returns:
            List of subscription IDs created by the provider.

        Raises:
            TypeError: If *provider* does not conform to ``EventProvider``
                (missing ``register(self, registry)`` method).
        """
        # Lazy import to avoid circularity: EventProvider depends on EventRegistry.
        from parrot.core.events.lifecycle.provider import EventProvider

        if not isinstance(provider, EventProvider):
            raise TypeError(
                f"{type(provider).__name__} is not an EventProvider "
                "(missing register(registry) method)."
            )
        # Capture the set of existing subscription IDs before the provider runs.
        before_ids = {s.subscription_id for s in self._subscriptions}
        provider.register(self)
        # Return only the newly added IDs in insertion order.
        return [
            s.subscription_id
            for s in self._subscriptions
            if s.subscription_id not in before_ids
        ]

    async def emit(self, event: LifecycleEvent) -> None:
        """Dispatch *event* to all matching subscribers.

        This method NEVER raises.  Subscriber exceptions are caught and
        emitted as ``SubscriberErrorEvent`` to the global registry (model B
        error isolation).

        Args:
            event: A frozen ``LifecycleEvent`` instance to dispatch.
        """
        # Find matching subscriptions
        matching = [
            s for s in self._subscriptions
            if isinstance(event, s.event_type)
            and (s.where is None or s.where(event))
        ]

        if not matching:
            # Short-circuit: skip to_dict() on hot paths (e.g. ClientStreamChunkEvent)
            if self._forward_to_global:
                self._forward_to_global_safely(event)
            return

        # Determine dispatch order
        cls_name = type(event).__name__
        reverse = cls_name.startswith("After") or "Failed" in cls_name
        if reverse:
            matching = list(reversed(matching))

        for sub in matching:
            try:
                await sub.callback(event)
            except Exception as exc:
                logger.exception(
                    "Lifecycle subscriber %s raised on %s",
                    getattr(sub.callback, "__qualname__", repr(sub.callback)),
                    cls_name,
                )
                self._emit_subscriber_error(event, sub, exc)

            # Per-subscriber dual-emit to EventBus (fire-and-forget, FEAT-177 TASK-1227).
            # A slow bus must never block the agent request path — the §5 performance
            # budget (< 0.1% LLM-latency overhead) is unenforceable otherwise.
            # Asyncio's default task-exception handler logs unhandled exceptions raised
            # inside ``_event_bus.emit``; we do not attach an explicit done-callback.
            if sub.forward_to_bus and self._event_bus is not None:
                channel = f"{self._bus_channel_prefix}.{cls_name}"
                try:
                    asyncio.create_task(
                        self._event_bus.emit(channel, event.to_dict()),
                        name=f"lifecycle.bus.{cls_name}",
                    )
                except RuntimeError:
                    # No running loop at scheduling time — log and continue.
                    logger.exception(
                        "Dual-emit scheduling failed for channel %s", channel
                    )

        # Forward to global registry (if enabled and not already the global)
        if self._forward_to_global:
            self._forward_to_global_safely(event)

    async def _emit_meta(self, event: LifecycleEvent) -> None:
        """Internal entry point for meta-events (e.g. SubscriberErrorEvent).

        Sets the recursion guard before dispatching to prevent infinite loops
        when a SubscriberErrorEvent subscriber itself raises.

        Args:
            event: The meta ``LifecycleEvent`` to dispatch.
        """
        if _emitting_meta.get():
            # Recursion guard: a previous meta-emit is still in progress.
            # Log and drop to prevent an infinite SubscriberErrorEvent loop.
            logger.error(
                "Recursion guard triggered: dropping nested meta-event %s",
                type(event).__name__,
            )
            return
        token = _emitting_meta.set(True)
        try:
            await self.emit(event)
        finally:
            _emitting_meta.reset(token)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _emit_subscriber_error(
        self, original_event: LifecycleEvent, sub: _Subscription, exc: Exception
    ) -> None:
        """Schedule a SubscriberErrorEvent on the global registry.

        Uses ``asyncio.create_task`` so the meta-event dispatch does not
        block the current emit loop.

        Args:
            original_event: The event that triggered the failing subscriber.
            sub: The subscription record whose callback raised.
            exc: The exception that was caught.
        """
        err_evt = SubscriberErrorEvent(
            trace_context=original_event.trace_context,
            failed_subscriber=repr(sub.callback),
            original_event_class=type(original_event).__name__,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback=traceback.format_exc(),
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "No running loop — SubscriberErrorEvent dropped for %s",
                repr(sub.callback),
            )
            return
        try:
            from parrot.core.events.lifecycle.global_registry import get_global_registry
            global_reg = get_global_registry()
            loop.create_task(
                global_reg._emit_meta(err_evt),
                name=f"lifecycle.meta.{type(original_event).__name__}",
            )
        except Exception:
            logger.exception(
                "Failed to schedule SubscriberErrorEvent for failed subscriber %s",
                repr(sub.callback),
            )

    def emit_nowait(self, event: LifecycleEvent) -> None:
        """Schedule :meth:`emit` on the running event loop, or drop silently.

        Use this from synchronous contexts (e.g., property setters) where
        ``await`` is not available.  The event is NOT guaranteed to be
        processed if no event loop is running at call time — this is
        acceptable for observability events.

        Resolution of spec open question Q9.

        Args:
            event: The ``LifecycleEvent`` to schedule.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "emit_nowait dropped %s: no running event loop",
                type(event).__name__,
            )
            return
        loop.create_task(
            self.emit(event),
            name=f"lifecycle.{type(event).__name__}",
        )

    def forward_to_global(self, event: LifecycleEvent) -> None:
        """Forward *event* to the global registry regardless of ``forward_to_global``.

        Public, opt-in counterpart to the automatic forwarding done inside
        :meth:`emit`.  An isolated registry (one constructed with
        ``forward_to_global=False`` — e.g. an LLM client, see
        ``clients/base.py``) can call this for the specific events it wants
        global observers (cost/token recorders, OTel subscribers) to receive,
        without forwarding *every* event it emits (e.g. high-frequency
        ``ClientStreamChunkEvent`` stays isolated).

        Reuses the same safe, guarded path as automatic forwarding: a no-op
        when this registry IS the global one, when no event loop is running,
        or when no global subscriber would receive ``type(event)``.

        Args:
            event: The ``LifecycleEvent`` to forward to the global registry.
        """
        self._forward_to_global_safely(event)

    def _forward_to_global_safely(self, event: LifecycleEvent) -> None:
        """Forward *event* to the global registry as a fire-and-forget task.

        Skips forwarding when this registry IS the global registry (avoids
        re-emit loops), when no running event loop is available, or when no
        subscriber on the global registry would receive this event type (avoids
        unbounded task creation on hot paths with no global observers).

        Args:
            event: The event to forward.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(
                "No running loop — forward of %s dropped",
                type(event).__name__,
            )
            return
        try:
            from parrot.core.events.lifecycle.global_registry import get_global_registry
            global_reg = get_global_registry()
            if global_reg is self:
                return  # don't re-emit to self
            if not global_reg.has_subscribers(type(event)):
                return  # skip task creation when nobody is listening globally
            loop.create_task(
                global_reg.emit(event),
                name=f"lifecycle.forward.{type(event).__name__}",
            )
        except Exception as exc:
            logger.debug(
                "Failed to forward event %s to global registry: %s",
                type(event).__name__,
                exc,
            )
