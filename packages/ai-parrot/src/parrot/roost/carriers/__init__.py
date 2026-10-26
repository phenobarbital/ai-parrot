"""Roost carriers (FEAT-747). Lazy exports so optional carriers never import their dependencies eagerly."""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "Carrier": "base", "CarrierError": "base", "Undeliverable": "base", "CarrierClosed": "base", "Inbound": "base",
    "InProcessCarrier": "inprocess", "SharedMemoryCarrier": "shm", "ShmPayloadRef": "shm",
    "EventBusCarrier": "bus", "build_roost_bus": "bus",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    mod = _EXPORTS.get(name)
    if mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{mod}"), name)
    globals()[name] = value
    return value
