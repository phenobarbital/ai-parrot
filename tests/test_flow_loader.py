from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from parrot.bots.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    FlowMetadata,
    LogActionDef,
    NodeDefinition,
)
from parrot.bots.flow.loader import FlowLoader
from parrot.bots.flow.fsm import AgentsFlow


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "flows"


class _EchoAgent:
    """Minimal agent stub that echoes input."""

    is_configured: bool = True

    def __init__(self, name: str = "echo_agent"):
        self._name = name
        from parrot.tools.manager import ToolManager

        self.tool_manager = ToolManager()

    @property
    def name(self) -> str:
        return self._name

    async def ask(self, question: str = "", **kwargs: Any) -> str:
        return question

    async def configure(self) -> None:
        pass


class _MockRedis:
    """In-memory async Redis mock for testing without external deps."""

    def __init__(self) -> None:
        self._store: Dict[str, str] = {}

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def scan_iter(self, match: str = "*") -> Any:
        """Async generator yielding matching keys."""
        import fnmatch

        for k in list(self._store.keys()):
            if fnmatch.fnmatch(k, match):
                yield k


@pytest.fixture
def echo_agent() -> _EchoAgent:
    return _EchoAgent()


@pytest.fixture
def mock_redis() -> _MockRedis:
    return _MockRedis()


@pytest.fixture
def simple_flow_json() -> str:
    return (FIXTURES_DIR / "simple_flow.json").read_text()


@pytest.fixture
def simple_flow_dict() -> Dict[str, Any]:
    return json.loads((FIXTURES_DIR / "simple_flow.json").read_text())


@pytest.fixture
def cel_flow_json() -> str:
    return (FIXTURES_DIR / "cel_decision_flow.json").read_text()


# ---------------------------------------------------------------------------
# Test: Parsing (from_dict / from_json)
# ---------------------------------------------------------------------------


class TestFlowLoaderParsing:
    def test_from_json(self, simple_flow_json: str) -> None:
        """Parse valid JSON into FlowDefinition."""
        definition = FlowLoader.from_json(simple_flow_json)
        assert definition.flow == "SimpleTestFlow"
        assert len(definition.nodes) == 3
        assert len(definition.edges) == 2

    def test_from_dict(self, simple_flow_dict: Dict[str, Any]) -> None:
        """Parse valid dict into FlowDefinition."""
        definition = FlowLoader.from_dict(simple_flow_dict)
        assert definition.flow == "SimpleTestFlow"
        assert len(definition.nodes) == 3

    def test_from_json_invalid(self) -> None:
        """Invalid JSON raises json.JSONDecodeError."""
        with pytest.raises(json.JSONDecodeError):
            FlowLoader.from_json("{invalid")

    def test_from_dict_missing_flow(self) -> None:
        """Missing required field raises ValidationError."""
        with pytest.raises(Exception):  # pydantic ValidationError
            FlowLoader.from_dict({"nodes": [], "edges": []})


# ---------------------------------------------------------------------------
# Test: File I/O
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_load_from_file(self) -> None:
        """Load flow from an absolute file path."""
        definition = FlowLoader.load_from_file(FIXTURES_DIR / "simple_flow.json")
        assert definition.flow == "SimpleTestFlow"

    def test_save_to_file(self, tmp_path: Path) -> None:
        """Save flow to file with updated_at timestamp."""
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

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        """save_to_file creates intermediate directories."""
        definition = FlowDefinition(
            flow="DeepSave",
            nodes=[NodeDefinition(id="s", type="start")],
            edges=[],
        )
        deep_path = tmp_path / "a" / "b" / "c" / "flow.json"
        FlowLoader.save_to_file(definition, deep_path)
        assert deep_path.exists()

    def test_file_not_found(self) -> None:
        """Raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            FlowLoader.load_from_file("/nonexistent/path.json")

    def test_roundtrip_file(self, tmp_path: Path, simple_flow_json: str) -> None:
        """Load → save → load preserves data."""
        original = FlowLoader.from_json(simple_flow_json)

        path = tmp_path / "roundtrip.json"
        FlowLoader.save_to_file(original, path)

        reloaded = FlowLoader.load_from_file(path)
        assert reloaded.flow == original.flow
        assert len(reloaded.nodes) == len(original.nodes)
        assert len(reloaded.edges) == len(original.edges)


# ---------------------------------------------------------------------------
# Test: Redis I/O
# ---------------------------------------------------------------------------


class TestRedisIO:
    @pytest.mark.asyncio
    async def test_save_and_load_redis(self, mock_redis: _MockRedis) -> None:
        """Save and load flow from Redis."""
        definition = FlowDefinition(
            flow="RedisTest",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[],
        )
        await FlowLoader.save_to_redis(mock_redis, definition)
        loaded = await FlowLoader.load_from_redis(mock_redis, "RedisTest")
        assert loaded.flow == "RedisTest"
        assert loaded.updated_at is not None

    @pytest.mark.asyncio
    async def test_load_missing_raises(self, mock_redis: _MockRedis) -> None:
        """Loading a non-existent flow raises KeyError."""
        with pytest.raises(KeyError, match="NoSuchFlow"):
            await FlowLoader.load_from_redis(mock_redis, "NoSuchFlow")

    @pytest.mark.asyncio
    async def test_list_flows(self, mock_redis: _MockRedis) -> None:
        """List all flows stored in Redis."""
        d1 = FlowDefinition(flow="Flow1", nodes=[], edges=[])
        d2 = FlowDefinition(flow="Flow2", nodes=[], edges=[])
        await FlowLoader.save_to_redis(mock_redis, d1)
        await FlowLoader.save_to_redis(mock_redis, d2)

        flows = await FlowLoader.list_flows_in_redis(mock_redis)
        assert "Flow1" in flows
        assert "Flow2" in flows

    @pytest.mark.asyncio
    async def test_delete_from_redis(self, mock_redis: _MockRedis) -> None:
        """Delete a flow from Redis."""
        definition = FlowDefinition(flow="ToDelete", nodes=[], edges=[])
        await FlowLoader.save_to_redis(mock_redis, definition)
        await FlowLoader.delete_from_redis(mock_redis, "ToDelete")

        with pytest.raises(KeyError):
            await FlowLoader.load_from_redis(mock_redis, "ToDelete")

    @pytest.mark.asyncio
    async def test_save_with_ttl(self, mock_redis: _MockRedis) -> None:
        """Save with TTL (mock stores it; just verify no exception)."""
        definition = FlowDefinition(flow="TTLTest", nodes=[], edges=[])
        await FlowLoader.save_to_redis(mock_redis, definition, ttl=3600)
        loaded = await FlowLoader.load_from_redis(mock_redis, "TTLTest")
        assert loaded.flow == "TTLTest"


# ---------------------------------------------------------------------------
# Test: Materialization (to_agents_flow)
# ---------------------------------------------------------------------------


class TestMaterialization:
    def test_to_agents_flow(
        self, simple_flow_json: str, echo_agent: _EchoAgent
    ) -> None:
        """Materialize definition into runnable AgentsFlow."""
        definition = FlowLoader.from_json(simple_flow_json)
        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent},
        )

        assert isinstance(flow, AgentsFlow)
        assert flow.name == "SimpleTestFlow"
        assert "__start__" in flow.nodes
        assert "worker" in flow.nodes
        assert "__end__" in flow.nodes

    def test_missing_agent_raises(self, simple_flow_json: str) -> None:
        """Raise LookupError when agent_ref not found."""
        definition = FlowLoader.from_json(simple_flow_json)
        with pytest.raises(LookupError, match="echo_agent"):
            FlowLoader.to_agents_flow(definition)

    def test_cel_predicate_wired(
        self, cel_flow_json: str, echo_agent: _EchoAgent
    ) -> None:
        """CEL predicates attached to ON_CONDITION transitions."""
        definition = FlowLoader.from_json(cel_flow_json)
        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent},
        )

        # classifier node should have transitions with predicates
        classifier_node = flow.nodes["classifier"]
        on_condition_transitions = [
            t
            for t in classifier_node.outgoing_transitions
            if t.predicate is not None
        ]
        assert len(on_condition_transitions) == 2

    def test_actions_attached(self, echo_agent: _EchoAgent) -> None:
        """Pre/post actions attached to nodes from definition."""
        definition = FlowDefinition(
            flow="ActionTest",
            nodes=[
                NodeDefinition(id="__start__", type="start"),
                NodeDefinition(
                    id="worker",
                    type="agent",
                    agent_ref="echo_agent",
                    post_actions=[
                        LogActionDef(message="Done: {result}")
                    ],
                ),
                NodeDefinition(id="__end__", type="end"),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "__start__", "to": "worker", "condition": "always"
                }),
                EdgeDefinition(**{
                    "from": "worker", "to": "__end__", "condition": "on_success"
                }),
            ],
        )

        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent},
        )

        worker_node = flow.nodes["worker"]
        assert len(worker_node._post_actions) == 1

    def test_agent_registry_fallback(self, echo_agent: _EchoAgent) -> None:
        """Resolve agent from registry when not in extra_agents."""
        definition = FlowDefinition(
            flow="RegistryTest",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(id="w", type="agent", agent_ref="echo_agent"),
            ],
            edges=[
                EdgeDefinition(**{"from": "s", "to": "w", "condition": "always"})
            ],
        )

        registry = {"echo_agent": echo_agent}
        flow = FlowLoader.to_agents_flow(definition, agent_registry=registry)
        assert "w" in flow.nodes

    def test_extra_agents_priority(self) -> None:
        """extra_agents takes priority over agent_registry."""
        primary = _EchoAgent(name="primary")
        fallback = _EchoAgent(name="fallback")

        definition = FlowDefinition(
            flow="PriorityTest",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(id="w", type="agent", agent_ref="my_agent"),
            ],
            edges=[
                EdgeDefinition(**{"from": "s", "to": "w", "condition": "always"})
            ],
        )

        flow = FlowLoader.to_agents_flow(
            definition,
            agent_registry={"my_agent": fallback},
            extra_agents={"my_agent": primary},
        )

        # The resolved agent should be the one from extra_agents
        worker_node = flow.nodes["w"]
        assert worker_node.agent.name == "primary"

    def test_metadata_forwarded(self, echo_agent: _EchoAgent) -> None:
        """Flow metadata forwarded to AgentsFlow constructor."""
        definition = FlowDefinition(
            flow="MetaTest",
            metadata=FlowMetadata(
                max_parallel_tasks=5,
                default_max_retries=1,
                execution_timeout=30.0,
            ),
            nodes=[NodeDefinition(id="s", type="start")],
            edges=[],
        )
        flow = FlowLoader.to_agents_flow(definition)
        assert flow.max_parallel_tasks == 5
        assert flow.default_max_retries == 1
        assert flow.execution_timeout == 30.0

    def test_fan_out_edges(self, echo_agent: _EchoAgent) -> None:
        """Fan-out edge (one source → multiple targets) wired correctly."""
        definition = FlowDefinition(
            flow="FanOutTest",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(id="a", type="agent", agent_ref="echo_agent"),
                NodeDefinition(id="b", type="agent", agent_ref="echo_agent"),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "s",
                    "to": ["a", "b"],
                    "condition": "always",
                })
            ],
        )

        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent},
        )

        start_node = flow.nodes["s"]
        assert len(start_node.outgoing_transitions) == 1
        targets = start_node.outgoing_transitions[0].targets
        assert "a" in targets
        assert "b" in targets


# ---------------------------------------------------------------------------
# Test: End-to-end execution
# ---------------------------------------------------------------------------


class TestExecution:
    @pytest.mark.asyncio
    async def test_load_and_run(self, echo_agent: _EchoAgent) -> None:
        """Load from file, materialize, run flow end-to-end."""
        definition = FlowLoader.load_from_file(FIXTURES_DIR / "simple_flow.json")
        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo_agent": echo_agent},
        )

        result = await flow.run_flow("Hello world")
        assert result.status in ("completed", "partial")
