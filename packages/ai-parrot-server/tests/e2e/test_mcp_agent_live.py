"""Real live-agent MCP scenario coverage for FEAT-581 M6.

Exercises the real ``mcp-agent`` target end to end: a genuine, budgeted
:class:`~parrot.bots.agent.Agent`, mounted at its own per-agent HTTP path via
:class:`~parrot.mcp.agent_mount.AgentMCPMount`, actually asked to invoke a
synthetic fixture tool. Only runs with explicit live opt-in
(``PARROT_TEST_E2E=1 PARROT_TEST_REAL_LLM=1`` plus a real ``GOOGLE_API_KEY``)
-- honestly skipped otherwise (never xfail, never a silent pass). This file's
own test never claims E2E gate success by itself (spec: "This task cannot
claim E2E success solely from agent-tier tests"); the declared node ID below
is frozen and must not be renamed without updating every scenario plan that
references it.
"""

from __future__ import annotations

import json

import aiohttp
import pytest

from parrot.e2e import live as e2e_live
from parrot.e2e.errors import E2EPrerequisiteError
from parrot.e2e.models import TargetConfig
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets.mcp import build_mcp_agent_adapter

pytestmark = [pytest.mark.live, pytest.mark.real_llm]


def _live_opt_in_unavailable_reason() -> str | None:
    """Return why live opt-in is unavailable, or ``None`` if it is fully satisfied."""
    try:
        e2e_live.require_live_opt_in()
    except E2EPrerequisiteError as exc:
        return str(exc)
    return None


async def _json_rpc(
    session: aiohttp.ClientSession,
    base_url: str,
    path: str,
    method: str,
    params: dict[str, object],
    request_id: int,
    *,
    api_key: str,
) -> dict[str, object]:
    """Send one bounded, API-key-authenticated MCP JSON-RPC request.

    Args:
        session: Open asynchronous HTTP client session.
        base_url: Target loopback base URL.
        path: The per-agent route path.
        method: JSON-RPC method name.
        params: JSON-RPC method parameters.
        request_id: Request correlation identifier.
        api_key: This run's fixture API key.

    Returns:
        The parsed JSON-RPC response object.
    """
    async with session.post(
        f"{base_url}{path}",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        headers={"X-API-Key": api_key},
    ) as response:
        assert response.status == 200
        payload = await response.json()
    assert isinstance(payload, dict)
    return payload


async def test_live_google_tool_and_schema(e2e_supervisor_factory) -> None:
    """A real budgeted live Google agent call must invoke and record the fixture tool.

    Frozen integration node ID -- see module docstring; no renaming without
    updating every scenario plan that references it.
    """
    reason = _live_opt_in_unavailable_reason()
    if reason:
        pytest.skip(f"live opt-in unavailable, skipping honestly: {reason}")

    adapter = build_mcp_agent_adapter()
    supervisor: E2ESupervisor = e2e_supervisor_factory(lambda _kind: adapter)
    config = TargetConfig(kind="mcp-agent", startup_timeout_s=30)
    state = await supervisor.start("mcp-agent", config)

    try:
        assert state.status == "ready"
        endpoint = adapter._endpoints[state.run_id]
        base_url = f"http://{endpoint.host}:{endpoint.port}"
        agent_path = f"{e2e_live.AGENT_MOUNT_BASE_PATH}/{endpoint.agent_name}"
        timeout = aiohttp.ClientTimeout(total=90)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Handshake/readiness performed no generation (mcp-agent's own
            # `ready()` already proved this before `start()` returned); this
            # is the one call in the whole scenario that actually generates.
            called = await _json_rpc(
                session,
                base_url,
                agent_path,
                "tools/call",
                {"name": "live_ask", "arguments": {}},
                3,
                api_key=endpoint.api_key,
            )

        result = called["result"]
        assert result["isError"] is False
        payload = result["content"][0]["text"]
        schema = json.loads(payload)
        assert set(schema) == {"tool_called", "marker", "model", "calls_used"}
        # Assert the observable synthetic tool effect and schema, never prose:
        assert schema["tool_called"] is True
        assert schema["marker"] == e2e_live.FIXTURE_MARKER_VALUE
        assert schema["calls_used"] >= 1
    finally:
        final_state = await supervisor.stop(state.run_id)
        assert final_state.status == "stopped"
        assert final_state.cleanup_complete is True
