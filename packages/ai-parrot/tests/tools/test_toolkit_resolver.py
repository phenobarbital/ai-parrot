"""M1 unit tests for ToolkitResolver (FEAT-622)."""
import logging

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


def test_resolver_no_host_package_is_not_an_error():
    """ImportError on plugins.tools -> no host entries (rule 4)."""
    resolver = get_toolkit_resolver()
    resolver.reload()
    assert not [e for e in resolver.entries() if e.source in {"host", "walk"}]


def test_tenant_bound_host_entry_unavailable_before_enforcement(host_plugins):
    """Rule 5: tenant-bound host entry is unavailable until M3b (TASK-3989 replaces this test)."""
    resolver = get_toolkit_resolver()
    assert resolver.entry("tp_probe") is not None
    assert resolver.resolve("tp_probe") is None
