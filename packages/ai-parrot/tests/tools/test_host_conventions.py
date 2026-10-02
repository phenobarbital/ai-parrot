"""FEAT-622 M6: host read/write marker and strict marking of host write tools."""
import importlib

from parrot.tools.toolkit import effective_access

from ._host_probe import host_plugins  # noqa: F401


def _tools(host_plugins):
    mod = importlib.import_module("plugins.tools.probe")
    return {t.name: t for t in mod.ProbeToolkit().get_tools()}, mod


def test_host_write_tool_strict_marking_and_access_meta(host_plugins):
    """write → strict confirmation, window 0, access="write"; read → "read" unmarked."""
    tools, mod = _tools(host_plugins)
    write = tools["tp_bump"].routing_meta
    assert write["access"] == "write"
    assert write["requires_confirmation"] is True
    assert write["confirmation_enforced"] is True
    assert write["confirm_window_seconds"] == 0
    read = tools["tp_whoami"].routing_meta
    assert read["access"] == "read"
    assert "confirmation_enforced" not in read
    assert "requires_confirmation" not in read
    assert effective_access(mod.ProbeToolkit, "bump") == "write"
    assert effective_access(mod.ProbeToolkit, "whoami") == "read"


def test_builtin_toolkit_access_is_none(host_plugins):
    """Built-in toolkits keep access None and no strict marking (Q7)."""
    from parrot.tools.toolkit import AbstractToolkit

    class Plain(AbstractToolkit):
        tool_prefix = "plain"

        async def do(self) -> str:
            """Do."""
            return "x"

    meta = Plain().get_tools()[0].routing_meta
    assert meta["access"] is None
    assert "confirmation_enforced" not in meta
