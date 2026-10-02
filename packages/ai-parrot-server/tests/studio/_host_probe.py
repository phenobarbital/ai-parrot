"""Server host fixture (spec §4): a tmp ``plugins/tools`` package with probe toolkit/tools and a write variant.

The probe entries are NOT ``tenant_bound`` so the resolver (rule 5) keeps them resolvable until FEAT-622 M3b.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

PROBE_INIT = textwrap.dedent(
    '''
    HOST_TOOL_PREFIX = "tp_"
    TOOL_REGISTRY = {
        "tp_probe": "plugins.tools.probe.ProbeToolkit",
        "tp_probe_tool": "plugins.tools.probe.ProbeTool",
        "tp_probe_tool_write": "plugins.tools.probe.ProbeWriteTool",
    }
    '''
)

PROBE_MODULE = textwrap.dedent(
    '''
    from typing import ClassVar

    from pydantic import BaseModel

    from parrot.tools.abstract import AbstractTool
    from parrot.tools.toolkit import AbstractToolkit

    COUNTERS = {"opened": 0, "bump": 0, "options_calls": 0, "executed": 0, "written": 0}


    class ProbeToolkit(AbstractToolkit):
        """Probe toolkit with NO scope checks of its own."""

        tool_prefix = "tp"
        auto_open = True
        read_tools: ClassVar[frozenset] = frozenset({"whoami"})
        options_params = frozenset({"project"})

        async def _open(self) -> None:
            COUNTERS["opened"] += 1

        async def whoami(self) -> str:
            """Read tool: report the probe identity."""
            return "probe"

        async def bump(self) -> int:
            """Write tool: increment the bump counter."""
            COUNTERS["bump"] += 1
            return COUNTERS["bump"]

        @classmethod
        async def config_options(cls, *args, **kwargs):
            """Options provider with no scope check."""
            COUNTERS["options_calls"] += 1
            return []


    class ProbeArgs(BaseModel):
        """Probe tool arguments."""

        value: str = ""


    class ProbeTool(AbstractTool):
        """Standalone read probe tool."""

        name = "tp_probe_tool"
        description = "Probe tool"
        args_schema = ProbeArgs

        async def _execute(self, **kwargs):
            COUNTERS["executed"] += 1
            return {"ok": True}


    class ProbeWriteTool(AbstractTool):
        """Standalone WRITE probe tool: every execution bumps the write counter."""

        name = "tp_probe_tool_write"
        description = "Probe write tool"
        args_schema = ProbeArgs
        access = "write"

        async def _execute(self, **kwargs):
            COUNTERS["written"] += 1
            return {"written": COUNTERS["written"]}
    '''
)


@pytest.fixture
def host_plugins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write plugins/tools/{__init__,probe}.py under tmp_path, prepend it to sys.path, reset the resolver."""
    from parrot.tools.resolver import get_toolkit_resolver

    pkg = tmp_path / "plugins" / "tools"
    pkg.mkdir(parents=True)
    (tmp_path / "plugins" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text(PROBE_INIT)
    (pkg / "probe.py").write_text(PROBE_MODULE)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m == "plugins" or m.startswith("plugins.")]:
        monkeypatch.delitem(sys.modules, name)
    get_toolkit_resolver().reload()
    yield pkg
    for name in [m for m in sys.modules if m == "plugins" or m.startswith("plugins.")]:
        sys.modules.pop(name, None)
    get_toolkit_resolver().reload()


@pytest.fixture
def no_subprocess(monkeypatch: pytest.MonkeyPatch):
    """Record and fail any ``asyncio.create_subprocess_exec``; assert zero calls at teardown."""
    import asyncio

    calls: list[tuple] = []

    async def _fail(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("subprocess spawn is forbidden in this test")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail)
    yield calls
    assert not calls, f"unexpected subprocess spawns: {calls}"


def probe_counters() -> dict:
    """Return the live COUNTERS dict of the imported probe module."""
    return sys.modules["plugins.tools.probe"].COUNTERS
