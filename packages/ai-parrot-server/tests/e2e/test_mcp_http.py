"""Real HTTP MCP scenario coverage for FEAT-581."""

from __future__ import annotations

import aiohttp
import pytest

from parrot.e2e.models import TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets.mcp import build_mcp_toolkit_adapter


async def _request(
    session: aiohttp.ClientSession, base_url: str, method: str, params: dict[str, object], request_id: int
) -> dict[str, object]:
    """Send one bounded MCP JSON-RPC request to the real HTTP target.

    Args:
        session: Open asynchronous HTTP client session.
        base_url: Target loopback base URL.
        method: JSON-RPC method name.
        params: JSON-RPC method parameters.
        request_id: Request correlation identifier.

    Returns:
        The parsed JSON-RPC response object.
    """
    async with session.post(
        f"{base_url}/mcp",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    ) as response:
        assert response.status == 200
        payload = await response.json()
    assert isinstance(payload, dict)
    return payload


@pytest.mark.e2e
async def test_http_cli_stays_alive_and_stops(
    e2e_supervisor_factory, mcp_toolkit_config: TargetConfig
) -> None:
    """Exercise initialize/list/store/get/drop against one owned HTTP MCP child."""
    adapter = build_mcp_toolkit_adapter()
    supervisor: E2ESupervisor = e2e_supervisor_factory(lambda _kind: adapter)
    state = await supervisor.start("mcp-http", mcp_toolkit_config)

    try:
        assert state.status == "ready"
        endpoint = adapter._endpoints[state.run_id]
        base_url = f"http://{endpoint.host}:{endpoint.port}"
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{base_url}/mcp/info") as response:
                assert response.status == 200
                info = await response.json()
            assert info["name"] == f"e2e-mcp-toolkit-{state.run_id}"

            initialize = await _request(session, base_url, "initialize", {}, 1)
            assert initialize["id"] == 1
            assert "result" in initialize

            tools = await _request(session, base_url, "tools/list", {}, 2)
            names = {tool["name"] for tool in tools["result"]["tools"]}
            assert {"wm_store_result", "wm_get_result", "wm_drop_stored"} <= names

            key = f"fixture-{state.run_id}"
            stored = await _request(
                session,
                base_url,
                "tools/call",
                {"name": "wm_store_result", "arguments": {"key": key, "data": "http-e2e"}},
                3,
            )
            assert stored["result"]["isError"] is False

            fetched = await _request(
                session, base_url, "tools/call", {"name": "wm_get_result", "arguments": {"key": key}}, 4
            )
            assert fetched["result"]["isError"] is False
            assert "http-e2e" in fetched["result"]["content"][0]["text"]

            dropped = await _request(
                session, base_url, "tools/call", {"name": "wm_drop_stored", "arguments": {"key": key}}, 5
            )
            assert dropped["result"]["isError"] is False
    finally:
        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True
