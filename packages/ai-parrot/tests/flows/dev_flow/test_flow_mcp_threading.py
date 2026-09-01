"""Threading tests for dev-flow's research-seat extra-MCP seam (FEAT-485).

``build_dev_flow(research_mcp_servers=..., research_mcp_tools=...)`` must
reach the materialized ``IdeationNode``; unset kwargs must leave its
dispatch byte-identical (the built-in wikitoolkit entry alone). Mirrors
``test_plan_threading.py``'s style.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from parrot.flows.dev_flow.definition import IDEATION
from parrot.flows.dev_flow.flow import build_dev_flow

_SERVERS = {"parrot-repo": {"command": "/x/parrot", "args": ["mcp-local", "repo"], "env": {}}}


def _flow(**kwargs: Any):
    return build_dev_flow(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
        lifecycle_events=False,
        **kwargs,
    )


class TestIdeationExtraMcpThreading:
    def test_defaults_leave_ideation_unwired(self):
        node = _flow()._nodes[IDEATION]
        assert node._extra_mcp_servers is None
        assert node._extra_mcp_tools is None

    def test_extra_servers_and_tools_reach_ideation(self):
        tools = ["mcp__parrot-repo"]
        node = _flow(research_mcp_servers=_SERVERS, research_mcp_tools=tools)._nodes[IDEATION]
        assert node._extra_mcp_servers == _SERVERS
        assert node._extra_mcp_tools == tools

    def test_explicit_coordinator_still_wins(self):
        sentinel = MagicMock()
        node = _flow(research_coordinator=sentinel)._nodes[IDEATION]
        assert node._coordinator is sentinel
