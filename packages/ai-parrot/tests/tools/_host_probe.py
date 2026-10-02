"""Core host fixture (spec §4 "Host fixture"): writes a tmp ``plugins/tools`` package."""
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
    }
    '''
)

PROBE_MODULE = textwrap.dedent(
    '''
    from typing import ClassVar

    from pydantic import BaseModel

    from parrot.tools.abstract import AbstractTool
    from parrot.tools.toolkit import AbstractToolkit

    COUNTERS = {"opened": 0, "bump": 0, "options_calls": 0, "executed": 0, "tool_opened": 0}


    class ProbeToolkit(AbstractToolkit):
        """Tenant-bound probe toolkit with NO scope checks of its own."""

        tool_prefix = "tp"
        tenant_bound: ClassVar[bool] = True
        auto_open = True
        read_tools: ClassVar[frozenset] = frozenset({"whoami"})

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
        """Tenant-bound standalone probe tool with NO scope check."""

        name = "tp_probe_tool"
        description = "Probe tool"
        args_schema = ProbeArgs
        tenant_bound: ClassVar[bool] = True

        async def _open(self) -> None:
            COUNTERS["tool_opened"] += 1

        async def _execute(self, **kwargs):
            COUNTERS["executed"] += 1
            return {"ok": True}
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
