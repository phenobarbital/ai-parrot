"""FEAT-848 — AbstractClient.supports_tool_loop: the declared text ask() tool-loop capability."""

from __future__ import annotations

import pytest

from parrot.clients.base import AbstractClient

# Classes whose text ask() runs no tool loop (spec §6 provider audit): name -> (module, attribute).
KNOWN_FALSE: dict[str, tuple[str, str]] = {
    "TransformersClient": ("parrot.clients.hf.client", "TransformersClient"),
    "JevClient": ("parrot.clients.jev.client", "JevClient"),
    "GeminiLiveClient": ("parrot.clients.google.live", "GeminiLiveClient"),
}


def test_default_is_true() -> None:
    """The base class declares the flag itself, defaulting to True."""
    assert AbstractClient.supports_tool_loop is True
    assert "supports_tool_loop" in vars(AbstractClient)


@pytest.mark.parametrize("name", sorted(KNOWN_FALSE))
def test_known_false_classes(name: str) -> None:
    """hf / jev / google-live declare False on their own class body; skipped when the satellite is absent."""
    module_name, attribute = KNOWN_FALSE[name]
    module = pytest.importorskip(module_name)
    cls = getattr(module, attribute)
    assert cls.supports_tool_loop is False
    assert "supports_tool_loop" in vars(cls)
