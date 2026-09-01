"""Threading tests for the dev-loop build surface's research/pool seams.

Covers ``build_dev_loop_flow``'s new ``research_coordinator`` /
``research_mcp_servers`` / ``research_mcp_tools`` kwargs and
``build_dev_loop_feature_flow``'s ``development_pool_config`` passthrough.
Mirrors ``dev_flow/test_plan_threading.py``'s materialized-node assertion
style (``publish_flow_events=False`` — no Redis in tests).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from parrot.flows.dev_loop.definition import DEVELOPMENT, PLANNER, RESEARCH
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.models.base import DevAgentPoolConfig, DevAgentSpec
from parrot.flows.dev_loop.runner import build_dev_loop_feature_flow

_SERVERS = {"parrot-repo": {"command": "/x/parrot", "args": ["mcp-local", "repo"], "env": {}}}


def _flow(**kwargs: Any):
    return build_dev_loop_flow(
        dispatcher=MagicMock(),
        jira_toolkit=MagicMock(),
        log_toolkits={},
        redis_url="redis://x",
        publish_flow_events=False,
        lifecycle_events=False,
        **kwargs,
    )


def _feature_flow(**kwargs: Any):
    return build_dev_loop_feature_flow(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
        lifecycle_events=False,
        **kwargs,
    )


class TestResearchSeamThreading:
    def test_defaults_leave_research_node_unwired(self):
        node = _flow()._nodes[RESEARCH]
        assert node._mcp_servers is None
        assert node._mcp_tools is None
        # The factories' None-default coordinator is a fresh conf-driven one.
        assert node._coordinator is not None

    def test_mcp_servers_and_tools_reach_research_node(self):
        tools = ["mcp__parrot-repo__read_file"]
        node = _flow(research_mcp_servers=_SERVERS, research_mcp_tools=tools)._nodes[RESEARCH]
        assert node._mcp_servers == _SERVERS
        assert node._mcp_tools == tools

    def test_explicit_coordinator_reaches_research_node(self):
        sentinel = MagicMock()
        node = _flow(research_coordinator=sentinel)._nodes[RESEARCH]
        assert node._coordinator is sentinel


class TestFeatureFlowPoolThreading:
    def test_default_leaves_pool_unwired(self):
        flow = _feature_flow()
        assert flow._nodes[DEVELOPMENT]._pool_config is None
        assert flow._nodes[PLANNER]._pool_config is None

    def test_pool_config_reaches_development_and_planner(self):
        cfg = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="nova", model="zai.glm-5")],
            isolation_mode="shared",
        )
        flow = _feature_flow(development_pool_config=cfg)
        assert flow._nodes[DEVELOPMENT]._pool_config is cfg
        assert flow._nodes[PLANNER]._pool_config is cfg
