"""`parrot.mcp.integration` must import on a core-only install.

The transport sessions and `ChromeManager` live in ai-parrot-server. A project
venv holding only the `ai-parrot` wheel (querysource's, for one) used to fail
`import parrot.mcp.integration` — and with it `parrot.bots.abstract` and the
`parrot mcp-local sdd-coder` server — with ``No module named
'parrot.mcp.transports'``. The check runs in a subprocess with a meta-path
finder that hides those server-only modules, so it is meaningful even when
the server package IS installed (as it is in this workspace).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import parrot

_BLOCKER = r"""
import importlib.abc, sys

class _Hide(importlib.abc.MetaPathFinder):
    HIDDEN = ("parrot.mcp.transports", "parrot.mcp.chrome")
    def find_spec(self, name, path=None, target=None):
        if name in self.HIDDEN or name.startswith("parrot.mcp.transports."):
            raise ImportError(f"No module named {name!r} (hidden for test)")
        return None

sys.meta_path.insert(0, _Hide())
"""


def _run(snippet: str) -> subprocess.CompletedProcess[str]:
    src_root = Path(parrot.__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(src_root), env.get("PYTHONPATH", "")) if p)
    return subprocess.run(
        [sys.executable, "-c", _BLOCKER + snippet],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )


def test_integration_imports_without_server_transports() -> None:
    proc = _run(
        "import parrot.mcp.integration as m\n"
        "from parrot.mcp import MCPClient\n"
        "try:\n"
        "    m._transport_session_cls('stdio')\n"
        "except ImportError as exc:\n"
        "    assert 'ai-parrot-server' in str(exc), exc\n"
        "else:\n"
        "    raise SystemExit('expected ImportError')\n"
        "print('LAZY_OK')\n"
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "LAZY_OK" in proc.stdout


def test_sdd_coder_toolkit_imports_without_server_transports() -> None:
    proc = _run("import parrot.flows.dev_loop.sdd_coder.toolkit\nprint('LAZY_OK')\n")
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "LAZY_OK" in proc.stdout
