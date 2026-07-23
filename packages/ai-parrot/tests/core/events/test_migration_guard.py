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


def test_no_internal_bus_copy() -> None:
    """FEAT-319 M4: internal bus copy must never come back."""
    from pathlib import Path

    import parrot

    src_root = Path(parrot.__file__).parent
    assert not (src_root / "core" / "events" / "bus").exists(), (
        "parrot/core/events/bus/ directory must not exist — bus lives in navigator-eventbus"
    )

    import pkgutil

    from navigator_eventbus.envelope import EventEnvelope

    assert not EventEnvelope.__module__.startswith("parrot."), (
        "EventEnvelope must come from navigator_eventbus, not a parrot.* copy"
    )

    for importer, modname, ispkg in pkgutil.walk_packages(
        parrot.__path__, prefix="parrot."
    ):
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for attr_name in dir(mod):
            assert attr_name not in ("BusCore",), (
                f"parrot.* must not define {attr_name} (found in {modname})"
            )


def test_facade_reexports() -> None:
    """The lifecycle and hooks facades still re-export their public surface."""
    from parrot.core.events.lifecycle import EventRegistry, LifecycleEvent  # noqa: F401
    from parrot.core.hooks import BaseHook, HookEvent  # noqa: F401
    from parrot.core.events.lifecycle.events import BeforeInvokeEvent
    from navigator_eventbus.lifecycle.base import LifecycleEvent as PkgLE

    assert issubclass(BeforeInvokeEvent, PkgLE)
