"""FEAT-622 M2: ``ToolInterface._resolve_spec_class`` delegates to the shared ToolkitResolver."""

from __future__ import annotations

from parrot.interfaces.tools import ToolInterface
from parrot.tools import resolver as resolver_module

from ..tools._host_probe import host_plugins  # noqa: F401


def test_resolve_spec_class_resolves_host_slug(host_plugins, monkeypatch):  # noqa: F811
    import importlib

    # rule 5 hides tenant-bound host entries until FEAT-622 M3b: use the non-tenant-bound variant.
    monkeypatch.setattr(importlib.import_module("plugins.tools.probe").ProbeTool, "tenant_bound", False)
    cls = ToolInterface._resolve_spec_class("tp_probe_tool")
    assert cls is not None and cls.__name__ == "ProbeTool"


def test_resolve_spec_class_uses_resolver(monkeypatch):
    class _Stub:
        def resolve(self, slug):
            return int if slug == "x" else None

    monkeypatch.setattr("parrot.interfaces.tools.get_toolkit_resolver", lambda: _Stub())
    assert ToolInterface._resolve_spec_class("x") is int
    assert ToolInterface._resolve_spec_class("y") is None
    assert resolver_module.get_toolkit_resolver is not None
