"""Tests for parrot.bots.flow.loader — FlowLoader file/Redis/materialization.

TASK-013: Parsing, file I/O, Redis I/O, to_agents_flow materialization.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock

import pytest

from parrot.bots.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    LogActionDef,
    NodeDefinition,
)
from parrot.bots.flow.loader import FlowLoader, REDIS_KEY_PREFIX


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _EchoAgent:
    """Minimal mock agent that echoes input."""

    is_configured = True

    def __init__(self, name: str = "echo"):
        self._name = name
        self.tool_manager = None

    @property
    def name(self) -> str:
        return self._name

    async def ask(self, question: str = "", **kwargs: Any) -> str:
        return question

    async def configure(self) -> None:
        pass


class _MockRedis:
    """In-memory async Redis mock for testing."""

    def __init__(self):
        self._store: Dict[str, str] = {}

    async def get(self, key: str) -> Optional[bytes]:
        val = self._store.get(key)
        return val.encode() if val else None

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def scan_iter(self, match: str = "*"):
        pattern = match.rstrip("*")
        for key in list(self._store.keys()):
            if key.startswith(pattern):
                yield key.encode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_flow_json() -> str:
    return json.dumps({
        "flow": "TestFlow",
        "version": "1.0",
        "metadata": {"enable_execution_memory": False},
        "nodes": [
            {"id": "__start__", "type": "start"},
            {"id": "worker", "type": "agent", "agent_ref": "echo_agent"},
            {"id": "__end__", "type": "end"},
        ],
        "edges": [
            {"from": "__start__", "to": "worker", "condition": "always"},
            {"from": "worker", "to": "__end__", "condition": "on_success"},
        ],
    })


@pytest.fixture
def echo_agent() -> _EchoAgent:
    return _EchoAgent(name="echo_agent")


@pytest.fixture
def mock_redis() -> _MockRedis:
    return _MockRedis()


@pytest.fixture
def simple_flow_file(tmp_path: Path, simple_flow_json: str) -> Path:
    p = tmp_path / "test_flow.json"
    p.write_text(simple_flow_json)
    return p


# ---------------------------------------------------------------------------
# Parsing Tests
# ---------------------------------------------------------------------------

class TestFlowLoaderParsing:
    def test_from_json(self, simple_flow_json: str):
        definition = FlowLoader.from_json(simple_flow_json)
        assert definition.flow == "TestFlow"
        assert len(definition.nodes) == 3
        assert len(definition.edges) == 2

    def test_from_dict(self):
        data = {
            "flow": "DictTest",
            "nodes": [{"id": "a", "type": "start"}],
            "edges": [],
        }
        definition = FlowLoader.from_dict(data)
        assert definition.flow == "DictTest"

    def test_from_json_invalid(self):
        with pytest.raises(Exception):
            FlowLoader.from_json("not valid json {{{")


# ---------------------------------------------------------------------------
# File I/O Tests
# ---------------------------------------------------------------------------

class TestFileIO:
    def test_load_from_file(self, simple_flow_file: Path):
        definition = FlowLoader.load_from_file(simple_flow_file)
        assert definition.flow == "TestFlow"

    def test_save_to_file(self, tmp_path: Path):
        definition = FlowDefinition(
            flow="SaveTest",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[],
        )
        flow_file = tmp_path / "saved.json"
        FlowLoader.save_to_file(definition, flow_file)

        assert flow_file.exists()
        loaded = FlowLoader.load_from_file(flow_file)
        assert loaded.flow == "SaveTest"
        assert loaded.updated_at is not None

    def test_save_creates_directories(self, tmp_path: Path):
        definition = FlowDefinition(
            flow="DeepSave",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[],
        )
        flow_file = tmp_path / "deep" / "nested" / "flow.json"
        FlowLoader.save_to_file(definition, flow_file)
        assert flow_file.exists()

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            FlowLoader.load_from_file("/nonexistent/path/to/flow.json")

    def test_load_from_fixture(self):
        fixture_path = Path(__file__).parent / "fixtures" / "flows" / "simple_flow.json"
        definition = FlowLoader.load_from_file(fixture_path)
        assert definition.flow == "SimpleFlow"


# ---------------------------------------------------------------------------
# Redis I/O Tests
# ---------------------------------------------------------------------------

class TestRedisIO:
    @pytest.mark.asyncio
    async def test_save_and_load(self, mock_redis: _MockRedis):
        definition = FlowDefinition(
            flow="RedisTest",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[],
        )
        await FlowLoader.save_to_redis(mock_redis, definition)
        loaded = await FlowLoader.load_from_redis(mock_redis, "RedisTest")
        assert loaded.flow == "RedisTest"

    @pytest.mark.asyncio
    async def test_load_missing_raises(self, mock_redis: _MockRedis):
        with pytest.raises(KeyError, match="not found"):
            await FlowLoader.load_from_redis(mock_redis, "nonexistent")

    @pytest.mark.asyncio
    async def test_list_flows(self, mock_redis: _MockRedis):
        d1 = FlowDefinition(flow="Flow1", nodes=[], edges=[])
        d2 = FlowDefinition(flow="Flow2", nodes=[], edges=[])
        await FlowLoader.save_to_redis(mock_redis, d1)
        await FlowLoader.save_to_redis(mock_redis, d2)

        flows = await FlowLoader.list_flows_in_redis(mock_redis)
        assert "Flow1" in flows
        assert "Flow2" in flows

    @pytest.mark.asyncio
    async def test_delete(self, mock_redis: _MockRedis):
        d = FlowDefinition(flow="ToDelete", nodes=[], edges=[])
        await FlowLoader.save_to_redis(mock_redis, d)
        await FlowLoader.delete_from_redis(mock_redis, "ToDelete")

        with pytest.raises(KeyError):
            await FlowLoader.load_from_redis(mock_redis, "ToDelete")

    @pytest.mark.asyncio
    async def test_save_with_ttl(self, mock_redis: _MockRedis):
        d = FlowDefinition(flow="TTLTest", nodes=[], edges=[])
        await FlowLoader.save_to_redis(mock_redis, d, ttl=3600)
        loaded = await FlowLoader.load_from_redis(mock_redis, "TTLTest")
        assert loaded.flow == "TTLTest"

    @pytest.mark.asyncio
    async def test_redis_key_prefix(self, mock_redis: _MockRedis):
        d = FlowDefinition(flow="PrefixTest", nodes=[], edges=[])
        await FlowLoader.save_to_redis(mock_redis, d)
        key = f"{REDIS_KEY_PREFIX}PrefixTest"
        assert await mock_redis.get(key) is not None


# ---------------------------------------------------------------------------
# Materialization Tests
# ---------------------------------------------------------------------------

class TestMaterialization:
    def test_to_agents_flow_basic(self, simple_flow_json: str, echo_agent: _EchoAgent):
        definition = FlowLoader.from_json(simple_flow_json)
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents={"echo_agent": echo_agent}
        )
        from parrot.bots.flow import AgentsFlow

        assert isinstance(flow, AgentsFlow)
        assert flow.name == "TestFlow"
        assert "__start__" in flow.nodes
        assert "worker" in flow.nodes
        assert "__end__" in flow.nodes

    def test_missing_agent_raises(self, simple_flow_json: str):
        definition = FlowLoader.from_json(simple_flow_json)
        with pytest.raises(LookupError, match="echo_agent"):
            FlowLoader.to_agents_flow(definition)

    def test_extra_agents_priority(self, simple_flow_json: str):
        agent1 = _EchoAgent(name="echo_agent")
        agent2 = _EchoAgent(name="echo_agent")
        definition = FlowLoader.from_json(simple_flow_json)
        flow = FlowLoader.to_agents_flow(
            definition,
            agent_registry={"echo_agent": agent1},
            extra_agents={"echo_agent": agent2},
        )
        # extra_agents should win
        assert flow.nodes["worker"].agent is agent2

    def test_cel_predicate_wired(self, echo_agent: _EchoAgent):
        definition = FlowDefinition(
            flow="CELTest",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(id="a", type="agent", agent_ref="echo_agent"),
                NodeDefinition(id="b", type="agent", agent_ref="echo_agent"),
            ],
            edges=[
                EdgeDefinition(
                    **{
                        "from": "a",
                        "to": "b",
                        "condition": "on_condition",
                        "predicate": 'result == "yes"',
                    }
                )
            ],
        )
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents={"echo_agent": echo_agent}
        )
        node_a = flow.nodes["a"]
        assert len(node_a.outgoing_transitions) == 1
        assert node_a.outgoing_transitions[0].predicate is not None

    def test_actions_attached(self, echo_agent: _EchoAgent):
        definition = FlowDefinition(
            flow="ActionTest",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(
                    id="w",
                    type="agent",
                    agent_ref="echo_agent",
                    pre_actions=[LogActionDef(level="info", message="pre {node_name}")],
                    post_actions=[LogActionDef(level="info", message="post {node_name}")],
                ),
            ],
            edges=[],
        )
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents={"echo_agent": echo_agent}
        )
        node = flow.nodes["w"]
        assert len(node._pre_actions) == 1
        assert len(node._post_actions) == 1

    def test_fan_out_edge(self, echo_agent: _EchoAgent):
        definition = FlowDefinition(
            flow="FanOut",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(id="src", type="agent", agent_ref="echo_agent"),
                NodeDefinition(id="dst1", type="agent", agent_ref="echo_agent"),
                NodeDefinition(id="dst2", type="agent", agent_ref="echo_agent"),
            ],
            edges=[
                EdgeDefinition(
                    **{"from": "src", "to": ["dst1", "dst2"], "condition": "always"}
                )
            ],
        )
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents={"echo_agent": echo_agent}
        )
        src = flow.nodes["src"]
        assert len(src.outgoing_transitions) == 1
        assert len(src.outgoing_transitions[0].targets) == 2


# ---------------------------------------------------------------------------
# Import Tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_from_package(self):
        from parrot.bots.flow import FlowLoader as FL

        assert FL is FlowLoader
