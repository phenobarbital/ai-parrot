"""M1 unit tests for ToolkitResolver (FEAT-622)."""

import logging
import sys
from pathlib import Path

import pytest

from parrot.tools.resolver import get_toolkit_resolver

from ._host_probe import host_plugins  # noqa: F401


def test_resolver_sees_declared_host_registry(host_plugins):
    """tp_probe resolves (entry) and appears in entries() with source="host"; built-ins come first."""
    resolver = get_toolkit_resolver()
    assert resolver.entry("TP_PROBE").source == "host"
    assert "tp_probe" in {e.slug for e in resolver.entries() if e.source == "host"}
    assert resolver.entry("wiki").source == "builtin"
    assert resolver.resolve("dataset_manager") is not None


def test_resolver_rejects_unprefixed_and_colliding_host_slugs(host_plugins, caplog):
    """`probe` (no prefix) and a slug equal to a builtin are excluded, one error logged each."""
    (host_plugins / "__init__.py").write_text(
        'HOST_TOOL_PREFIX = "tp_"\n'
        "TOOL_REGISTRY = {\n"
        '    "probe": "plugins.tools.probe.ProbeToolkit",\n'
        '    "WIKI": "plugins.tools.probe.ProbeToolkit",\n'
        '    "tp_probe": "plugins.tools.probe.ProbeToolkit",\n'
        "}\n"
    )
    resolver = get_toolkit_resolver()
    with caplog.at_level(logging.ERROR, logger="parrot.tools.resolver"):
        resolver.reload()
        assert resolver.entry("probe") is None
        assert resolver.entry("wiki").source == "builtin"
        assert resolver.entry("tp_probe").source == "host"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2


def test_resolver_rejects_wrong_tool_prefix(host_plugins, caplog):
    """A toolkit whose tool_prefix differs from HOST_TOOL_PREFIX is rejected."""
    (host_plugins / "__init__.py").write_text(
        'HOST_TOOL_PREFIX = "zz_"\nTOOL_REGISTRY = {"zz_probe": "plugins.tools.probe.ProbeToolkit"}\n'
    )
    resolver = get_toolkit_resolver()
    with caplog.at_level(logging.ERROR, logger="parrot.tools.resolver"):
        resolver.reload()
        assert resolver.entry("zz_probe") is None
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


def test_resolver_walk_fallback_without_registry(host_plugins):
    """A plugins.tools without TOOL_REGISTRY still resolves walked classes, source="walk"."""
    (host_plugins / "__init__.py").write_text("")
    resolver = get_toolkit_resolver()
    with pytest.warns(DeprecationWarning):
        resolver.reload()
        entries = resolver.entries()
    walk = {e.slug for e in entries if e.source == "walk"}
    assert "tp_probe_tool" in walk
    assert resolver.resolve("tp_probe_tool") is not None


def test_resolver_no_host_package_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ImportError on plugins.tools -> no host entries (rule 4)."""
    resolver = get_toolkit_resolver()
    monkeypatch.setitem(sys.modules, "plugins.tools", None)
    resolver.reload()
    try:
        assert not [e for e in resolver.entries() if e.source in {"host", "walk"}]
    finally:
        resolver.reload()


def test_resolver_rejects_missing_toolkit_prefix(host_plugins: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Inherited None is invalid for a toolkit, while standalone tools need no prefix."""
    probe = host_plugins / "probe.py"
    probe.write_text(probe.read_text().replace('tool_prefix = "tp"', ""))
    resolver = get_toolkit_resolver()
    with caplog.at_level(logging.ERROR, logger="parrot.tools.resolver"):
        assert resolver.entry("tp_probe") is None
        assert resolver.entry("tp_probe_tool").source == "host"
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "tool_prefix None" in errors[0].getMessage()


def test_tenant_bound_host_entry_resolves_after_enforcement(host_plugins):
    """Rule 5 is lifted: the scope gate lives in the core (FEAT-622 M3b), so a tenant-bound entry resolves."""
    resolver = get_toolkit_resolver()
    assert resolver.entry("tp_probe") is not None
    cls = resolver.resolve("tp_probe")
    assert cls is not None and cls.__name__ == "ProbeToolkit" and cls.tenant_bound is True
    assert resolver.resolve("tp_probe_tool").__name__ == "ProbeTool"


def test_malformed_dotted_path_is_unavailable(host_plugins):
    """resolve() returns None (not ValueError) when a registry value has no module separator."""
    resolver = get_toolkit_resolver()
    resolver.reload()
    resolver._ensure()
    from parrot.tools.resolver import ToolkitEntry

    resolver._entries["tp_bad"] = ToolkitEntry(slug="tp_bad", dotted_path="nodots", source="host")
    assert resolver.entry("tp_bad") is not None
    assert resolver.resolve("tp_bad") is None


def test_resolver_does_not_deadlock_when_host_module_instantiates_a_tool_at_import(host_plugins):
    """A host module building a tool at import time re-enters the resolver; it must not hang (PR #1564 F1)."""
    import threading

    (host_plugins / "ping.py").write_text(
        "from parrot.tools.abstract import AbstractTool\n"
        "\n"
        "\n"
        "class PingTool(AbstractTool):\n"
        '    """Host tool with no declared access, instantiated at import time."""\n'
        '    name = "acme_ping"\n'
        '    description = "ping"\n'
        "    args_schema = None\n"
        "\n"
        "    async def _execute(self, **kwargs):\n"
        "        return {}\n"
        "\n"
        "\n"
        "SINGLETON = PingTool()\n"
    )
    (host_plugins / "__init__.py").write_text(
        'HOST_TOOL_PREFIX = "acme_"\nTOOL_REGISTRY = {"acme_ping": "plugins.tools.ping.PingTool"}\n'
    )
    resolver = get_toolkit_resolver()
    resolver.reload()
    outcome: dict = {}

    def build() -> None:
        outcome["slugs"] = {e.slug for e in resolver.entries()}

    worker = threading.Thread(target=build, daemon=True)
    worker.start()
    worker.join(timeout=15)
    assert not worker.is_alive(), "resolver deadlocked: host module instantiated a tool at import time"
    assert "acme_ping" in outcome["slugs"]
    assert resolver.entry("acme_ping").source == "host"
