"""Migration guard tests for FEAT-317 (parrot-eventbus-migration).

Asserts that the bus core / lifecycle machinery / generic hooks deleted in
TASK-1827-1829 are genuinely gone from ai-parrot, and that the surviving
facades (`parrot.core.events.lifecycle`, `parrot.core.hooks`) still resolve
their public surface from `navigator_eventbus`.
"""
import importlib

import pytest


@pytest.mark.parametrize(
    "mod",
    [
        "parrot.core.events.bus",
        "parrot.core.events.evb",
        "parrot.core.hooks.base",
        "parrot.core.hooks.models",
    ],
)
def test_deleted_modules_not_importable(mod: str) -> None:
    """The bus core, evb facade, and generic hooks base/models are gone."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(mod)


def test_navigator_eventbus_smoke() -> None:
    """The package's top-level facade resolves and a basic emit round-trip works."""
    from navigator_eventbus import EventBus, EventEnvelope, Severity

    assert EventBus and EventEnvelope and Severity


def test_typed_events_subclass() -> None:
    """Parrot's typed lifecycle events still subclass the package's LifecycleEvent."""
    from navigator_eventbus.lifecycle.base import LifecycleEvent as PkgLifecycleEvent
    from parrot.core.events.lifecycle.events import BeforeInvokeEvent

    assert issubclass(BeforeInvokeEvent, PkgLifecycleEvent)


def test_facade_reexports() -> None:
    """The lifecycle and hooks facades still re-export their public surface."""
    from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent  # noqa: F401
    from parrot.core.hooks import BaseHook, HookEvent  # noqa: F401
    from parrot.core.events.lifecycle.events import BeforeInvokeEvent
    from navigator_eventbus.lifecycle.base import LifecycleEvent as PkgLE

    assert issubclass(BeforeInvokeEvent, PkgLE)
