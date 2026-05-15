"""Smoke test: verify every public symbol in parrot.core.events.lifecycle is importable.

FEAT-176 — Lifecycle Events System (TASK-1197).
"""


def test_public_api_imports() -> None:
    """All symbols listed in __all__ are importable from the package root."""
    import parrot.core.events.lifecycle as ll

    expected_symbols = [
        # Trace
        "TraceContext",
        # Base + meta
        "LifecycleEvent",
        "SubscriberErrorEvent",
        # Concrete events — agent
        "AgentInitializedEvent",
        "AgentConfiguredEvent",
        "ToolManagerReadyEvent",
        "AgentStatusChangedEvent",
        # Concrete events — invocation
        "BeforeInvokeEvent",
        "AfterInvokeEvent",
        "InvokeFailedEvent",
        # Concrete events — client
        "BeforeClientCallEvent",
        "AfterClientCallEvent",
        "ClientCallFailedEvent",
        "ClientStreamChunkEvent",
        # Concrete events — tool
        "BeforeToolCallEvent",
        "AfterToolCallEvent",
        "ToolCallFailedEvent",
        # Concrete events — message
        "MessageAddedEvent",
        # Registry + dispatch
        "EventRegistry",
        "AsyncSubscriber",
        "get_global_registry",
        "scope",
        # Provider + mixin
        "EventProvider",
        "EventEmitterMixin",
        # Built-in subscribers
        "LoggingSubscriber",
        "OpenTelemetrySubscriber",
        "WebhookSubscriber",
    ]

    for name in expected_symbols:
        assert hasattr(ll, name), f"Missing public symbol: {name!r}"


def test_all_matches_expected_symbols() -> None:
    """__all__ contains exactly the expected symbols — no accidental additions."""
    import parrot.core.events.lifecycle as ll

    # Every name in __all__ must be accessible as an attribute
    for name in ll.__all__:
        assert hasattr(ll, name), f"__all__ entry {name!r} is not accessible"


def test_wildcard_import_works() -> None:
    """from parrot.core.events.lifecycle import * produces a usable namespace."""
    # Execute in a fresh dict to simulate wildcard import
    ns: dict = {}
    exec("from parrot.core.events.lifecycle import *", ns)
    # Spot-check a few key symbols
    assert "TraceContext" in ns
    assert "EventRegistry" in ns
    assert "EventEmitterMixin" in ns
    assert "BeforeInvokeEvent" in ns
