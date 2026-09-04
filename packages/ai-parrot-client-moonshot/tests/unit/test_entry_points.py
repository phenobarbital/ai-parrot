"""TASK-2853: every `MoonshotClient` provider_keys entry must be
discoverable as a real `parrot.clients` entry point, resolving to the
exact class.
"""
import importlib
from importlib.metadata import entry_points


def test_entry_points_cover_provider_keys():
    eps = {e.name: e for e in entry_points(group="parrot.clients")}
    pkg = importlib.import_module("parrot.clients.moonshot")
    for name in pkg.__all__:
        cls = getattr(pkg, name)
        for key in getattr(cls, "provider_keys", ()):
            assert key in eps, f"'{key}' missing from parrot.clients entry points"
            assert eps[key].load() is cls, f"'{key}' entry point does not load {cls!r}"
