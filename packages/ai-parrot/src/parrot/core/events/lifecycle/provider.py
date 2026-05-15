"""EventProvider Protocol for batch subscriber registration.

FEAT-176 — Lifecycle Events System.

Any object that implements ``register(self, registry: EventRegistry) -> None``
conforms to this protocol.  No inheritance required — conformance is
structural (duck-typed) via ``typing.Protocol`` with ``@runtime_checkable``
so ``isinstance()`` works at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry


@runtime_checkable
class EventProvider(Protocol):
    """Bundles multiple subscriber callbacks for batch registration.

    Implement ``register(registry)`` and call ``registry.subscribe()`` for
    each callback you want to register.  Pass the provider to
    ``EventRegistry.add_provider(provider)`` to register all callbacks at
    once and receive back the list of subscription IDs.

    Example::

        class TelemetryProvider:
            def register(self, registry: EventRegistry) -> None:
                registry.subscribe(BeforeInvokeEvent, self.on_invoke_start)
                registry.subscribe(AfterInvokeEvent, self.on_invoke_end)
                registry.subscribe(InvokeFailedEvent, self.on_invoke_failed)

        reg = EventRegistry(forward_to_global=False)
        ids = reg.add_provider(TelemetryProvider())
        # ids contains 3 subscription IDs

    Note:
        ``register()`` MUST be synchronous — subscriber registration happens
        at agent setup time, before any event loop is running.
    """

    def register(self, registry: "EventRegistry") -> None:
        """Register this provider's subscribers with *registry*.

        Args:
            registry: The ``EventRegistry`` instance to subscribe to.
        """
        ...
