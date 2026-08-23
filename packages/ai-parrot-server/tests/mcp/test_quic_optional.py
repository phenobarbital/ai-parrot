"""The QUIC transport (aioquic) must stay optional.

``aioquic`` ships in the ``ai-parrot-server[mcp]`` extra. Before this guard,
``parrot/mcp/server.py``, ``parrot/mcp/simple_server.py`` and
``parrot/mcp/integration.py`` imported ``parrot.mcp.transports.quic`` at module
top level, so a bare install could not import the MCP layer at all — stdio,
http, sse, unix and websocket included.

These tests re-run the imports in a subprocess where ``aioquic`` is blocked at
the meta-path level, which reproduces a machine without the extra even though
the dev environment has it installed.
"""
import subprocess
import sys
import textwrap

import pytest

_BLOCK_AIOQUIC = '''
import sys
from importlib.abc import MetaPathFinder


class _BlockAioquic(MetaPathFinder):
    """Simulate an environment where the [mcp] extra is not installed."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "aioquic" or fullname.startswith("aioquic."):
            raise ImportError("aioquic is blocked for this test")
        return None


sys.meta_path.insert(0, _BlockAioquic())
'''


def _run_without_aioquic(body: str) -> subprocess.CompletedProcess:
    """Execute ``body`` in a subprocess that cannot import aioquic."""
    script = _BLOCK_AIOQUIC + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_mcp_layer_imports_without_aioquic():
    """Every MCP module must import cleanly with the extra missing."""
    result = _run_without_aioquic(
        """
        import parrot.mcp.server
        import parrot.mcp.simple_server
        import parrot.mcp.integration
        from parrot.mcp.transports.http import HttpMCPServer
        from parrot.mcp.transports.stdio import StdioMCPServer
        print("IMPORTS_OK")
        """
    )
    assert "IMPORTS_OK" in result.stdout, (
        f"MCP layer failed to import without aioquic:\n{result.stderr}"
    )
    assert result.returncode == 0


@pytest.mark.parametrize(
    "body",
    [
        # Server side: selecting the quic transport.
        """
        from parrot.mcp.config import MCPServerConfig
        from parrot.mcp.server import MCPServer
        try:
            MCPServer(MCPServerConfig(name="t", transport="quic"))
        except ImportError as exc:
            print("HINT:", exc)
        """,
        # Client side: the create_quic_mcp_server helper.
        """
        from parrot.mcp.integration import create_quic_mcp_server
        try:
            create_quic_mcp_server(name="t", host="localhost", port=4433)
        except ImportError as exc:
            print("HINT:", exc)
        """,
    ],
    ids=["server-transport", "client-helper"],
)
def test_quic_use_raises_actionable_import_error(body):
    """Only *using* QUIC fails, and the error names the extra to install."""
    result = _run_without_aioquic(body)
    assert "HINT:" in result.stdout, f"expected ImportError, got:\n{result.stderr}"
    assert "aioquic" in result.stdout
    assert "ai-parrot-server[mcp]" in result.stdout
