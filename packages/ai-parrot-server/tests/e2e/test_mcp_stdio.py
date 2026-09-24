"""Real persistent stdio MCP scenario coverage for FEAT-581."""

from __future__ import annotations

import asyncio

import pytest

from parrot.e2e.models import TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets.mcp import build_mcp_stdio_adapter


@pytest.mark.e2e
async def test_stdio_tool_roundtrip_and_eof(e2e_supervisor_factory, mcp_stdio_config: TargetConfig) -> None:
    """Validate persistent JSON-RPC purity, a tool effect, and clean stdin EOF."""
    adapter = build_mcp_stdio_adapter()
    supervisor: E2ESupervisor = e2e_supervisor_factory(lambda _kind: adapter)
    state = await supervisor.start("mcp-stdio", mcp_stdio_config)

    try:
        initialized = await supervisor.request_stdio(
            state.run_id, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert initialized["id"] == 1
        assert initialized["result"]["serverInfo"]["name"] == "parrot-memory"

        live = supervisor._runs[state.run_id]
        assert live.process.stdin is not None
        live.process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n')
        await live.process.stdin.drain()

        listed = await supervisor.request_stdio(
            state.run_id, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert {"wm_store_result", "wm_get_result"} <= names

        stored = await supervisor.request_stdio(
            state.run_id,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "wm_store_result", "arguments": {"key": "stdio", "data": "stdio-e2e"}},
            },
        )
        assert stored["result"]["isError"] is False

        fetched = await supervisor.request_stdio(
            state.run_id,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "wm_get_result", "arguments": {"key": "stdio"}},
            },
        )
        assert fetched["result"]["isError"] is False
        assert "stdio-e2e" in fetched["result"]["content"][0]["text"]

        live.process.stdin.close()
        await asyncio.wait_for(live.process.wait(), timeout=10)
        assert live.process.returncode == 0
    finally:
        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True
