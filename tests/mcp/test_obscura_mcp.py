"""Tests for the native Obscura MCP integration (FEAT-530, TASK-2878).

Covers:
    - `create_obscura_mcp_server()` — the pure stdio-config factory.
    - Stdio interop — a mocked `obscura mcp` subprocess drives
      `StdioMCPSession` through initialize/list/call, verifying the
      JSON-RPC channel stays clean (non-JSON stdout noise is ignored,
      not fatal).
    - `WebAgent` configuration — Obscura MCP tools are registered
      alongside Chrome DevTools MCP (opt-in via `ObscuraMCPConfig`),
      never instead of it.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.bots.agent import BasicAgent
from parrot.bots.chrome import ChromeConfig, ObscuraMCPConfig, WebAgent
from parrot.mcp.integration import create_obscura_mcp_server


# ── Config Factory ───────────────────────────────────────────────


class TestCreateObscuraMCPServer:
    def test_create_obscura_mcp_server_args(self):
        """Default args build `obscura mcp --port 9222` over stdio."""
        config = create_obscura_mcp_server()

        assert config.command == "obscura"
        assert config.args == ["mcp", "--port", "9222"]
        assert config.transport == "stdio"
        assert config.name == "obscura"
        assert "--stealth" not in config.args
        assert "--allow-private-network" not in config.args

    def test_create_obscura_mcp_server_custom_binary_and_options(self):
        config = create_obscura_mcp_server(
            binary_path="/usr/local/bin/obscura",
            name="obscura-stealth",
            port=9333,
            stealth=True,
            allow_private_network=True,
            env={"OBSCURA_LOG": "debug"},
        )

        assert config.command == "/usr/local/bin/obscura"
        assert config.name == "obscura-stealth"
        assert config.args == [
            "mcp",
            "--port",
            "9333",
            "--stealth",
            "--allow-private-network",
        ]
        assert config.transport == "stdio"
        assert config.env == {"OBSCURA_LOG": "debug"}

    def test_create_obscura_mcp_server_does_not_affect_chrome_devtools(self):
        """A separate tool schema/factory — importing it changes nothing
        about Chrome DevTools MCP's own factory or defaults."""
        from parrot.mcp.integration import create_chrome_devtools_mcp_server

        chrome_config = create_chrome_devtools_mcp_server()
        assert chrome_config.command == "npx"
        assert chrome_config.name == "chrome-devtools"


# ── Stdio Interop ────────────────────────────────────────────────


def _fake_process(response_lines):
    """A fake asyncio subprocess speaking line-delimited JSON-RPC.

    Args:
        response_lines: Iterable of raw bytes lines `_stdout.readline()`
            yields in order (may include non-JSON "noise" lines that a
            spec-compliant client must skip rather than choke on).
    """
    process = MagicMock()
    process.returncode = None

    stdin = MagicMock()
    stdin.write = MagicMock()
    stdin.drain = AsyncMock()

    stdout = MagicMock()
    lines = iter(response_lines)
    stdout.readline = AsyncMock(side_effect=lambda: next(lines, b""))

    stderr = MagicMock()

    process.stdin = stdin
    process.stdout = stdout
    process.stderr = stderr
    return process


@pytest.mark.asyncio
async def test_obscura_native_mcp_stdio_interop():
    """A mocked `obscura mcp` process drives initialize + tools/list
    cleanly, including a stray non-JSON stdout line that must be
    skipped rather than breaking the session (FEAT-530 acceptance:
    'lifecycle and tool discovery work over stdio without polluting
    the JSON-RPC channel')."""
    from parrot.mcp.transports.stdio import StdioMCPSession

    init_response = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}
    ).encode() + b"\n"
    tools_response = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": "navigate", "description": "Navigate to a URL"}
                ]
            },
        }
    ).encode() + b"\n"

    process = _fake_process(
        [
            b"Obscura v0.2.2 starting up...\n",  # non-JSON noise on stdout
            init_response,
            tools_response,
        ]
    )

    config = create_obscura_mcp_server(binary_path="/usr/local/bin/obscura")
    session = StdioMCPSession(config, logger=MagicMock())

    with patch(
        "parrot.mcp.transports.stdio.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        await session.connect()
        tools = await session.list_tools()

    assert session._initialized is True
    assert len(tools) == 1
    assert tools[0].name == "navigate"

    # The client only ever wrote valid JSON-RPC lines to stdin.
    for call in stdin_write_calls(process):
        json.loads(call.strip())


def stdin_write_calls(process):
    return [c.args[0].decode() for c in process.stdin.write.call_args_list]


# ── WebAgent Configuration ───────────────────────────────────────


class TestObscuraWebAgentConfiguration:
    @staticmethod
    def _stub_basic_agent_init(self, name="Agent", **kwargs):
        """Minimal `BasicAgent.__init__` stand-in: sets `self.name` only,
        so `WebAgent.__init__`'s own body (chrome_config/obscura_config/
        logger) runs for real without pulling in the full agent stack."""
        self.name = name

    def test_default_no_obscura_config(self):
        with patch.object(
            BasicAgent, "__init__", self._stub_basic_agent_init
        ):
            agent = WebAgent(name="test-agent")
        assert agent.obscura_config is None

    def test_custom_obscura_config(self):
        config = ObscuraMCPConfig(port=9333, stealth=True)
        with patch.object(
            BasicAgent, "__init__", self._stub_basic_agent_init
        ):
            agent = WebAgent(name="test-agent", obscura_config=config)
        assert agent.obscura_config.port == 9333
        assert agent.obscura_config.stealth is True

    @pytest.mark.asyncio
    async def test_obscura_webagent_configuration(self):
        """Agent receives native Obscura MCP tools while Chrome
        DevTools MCP configuration remains available/unaffected."""
        with patch.object(BasicAgent, "__init__", return_value=None), \
             patch.object(BasicAgent, "configure", new_callable=AsyncMock):
            agent = WebAgent.__new__(WebAgent)
            agent.name = "WebAgent"
            agent.chrome_config = ChromeConfig(headless=True, port=9333)
            agent.obscura_config = ObscuraMCPConfig(
                binary_path="/usr/local/bin/obscura", port=9222, stealth=True
            )
            agent.logger = MagicMock()
            agent.add_chrome_devtools_mcp_server = AsyncMock(
                return_value=["click", "fill"]
            )
            agent.add_obscura_mcp_server = AsyncMock(
                return_value=["navigate", "screenshot"]
            )

            await agent.configure()

            agent.add_chrome_devtools_mcp_server.assert_called_once()
            agent.add_obscura_mcp_server.assert_called_once()
            obscura_kwargs = agent.add_obscura_mcp_server.call_args.kwargs
            assert obscura_kwargs["binary_path"] == "/usr/local/bin/obscura"
            assert obscura_kwargs["stealth"] is True
            # Chrome configuration is still present/available, unaffected.
            assert agent.chrome_config.headless is True
            assert agent.chrome_config.port == 9333

    @pytest.mark.asyncio
    async def test_obscura_not_registered_when_unconfigured(self):
        """Chrome DevTools MCP defaults remain unchanged when
        `obscura_config` is not set (opt-in only)."""
        with patch.object(BasicAgent, "__init__", return_value=None), \
             patch.object(BasicAgent, "configure", new_callable=AsyncMock):
            agent = WebAgent.__new__(WebAgent)
            agent.name = "WebAgent"
            agent.chrome_config = ChromeConfig()
            agent.obscura_config = None
            agent.logger = MagicMock()
            agent.add_chrome_devtools_mcp_server = AsyncMock(return_value=[])
            agent.add_obscura_mcp_server = AsyncMock(return_value=[])

            await agent.configure()

            agent.add_chrome_devtools_mcp_server.assert_called_once()
            agent.add_obscura_mcp_server.assert_not_called()
