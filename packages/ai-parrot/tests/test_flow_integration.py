"""Integration tests for AgentsFlow Persistency feature.

TASK-015: End-to-end tests covering load → materialize → execute pipeline,
Redis persistence roundtrip, CEL routing, action execution, SvelteFlow
roundtrip, and error handling.
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from parrot.bots.flow import (
    AgentsFlow,
    FlowDefinition,
    FlowLoader,
    NodeDefinition,
    EdgeDefinition,
    from_svelteflow,
    to_svelteflow,
)
from parrot.bots.flow.definition import LogActionDef


# ---------------------------------------------------------------------------
# Mock Agents
# ---------------------------------------------------------------------------

class _EchoAgent:
    """Agent that echoes its input."""

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


class _FixedAgent:
    """Agent that returns a fixed response."""

    is_configured = True

    def __init__(self, name: str, response: Any):
        self._name = name
        self._response = response
        self.tool_manager = None

    @property
    def name(self) -> str:
        return self._name

    async def ask(self, question: str = "", **kwargs: Any) -> Any:
        return self._response

    async def configure(self) -> None:
        pass


class _MockRedis:
    """In-memory async Redis mock."""

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

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "flows"


@pytest.fixture
def simple_flow_path() -> Path:
    return FIXTURES_DIR / "simple_flow.json"


@pytest.fixture
def food_order_flow_path() -> Path:
    return FIXTURES_DIR / "food_order_flow.json"


@pytest.fixture
def decision_flow_path() -> Path:
    return FIXTURES_DIR / "decision_flow.json"


@pytest.fixture
def echo_agent() -> _EchoAgent:
    return _EchoAgent(name="echo_agent")


@pytest.fixture
def mock_redis() -> _MockRedis:
    return _MockRedis()


# ---------------------------------------------------------------------------
# Test: Load and Execute Simple Flow
# ---------------------------------------------------------------------------

class TestLoadAndExecute:
    @pytest.mark.asyncio
    async def test_simple_flow_pipeline(
        self, simple_flow_path: Path, echo_agent: _EchoAgent
    ):
        """Load JSON → materialize → execute → verify result."""
        definition = FlowLoader.load_from_file(simple_flow_path)
        assert definition.flow == "SimpleFlow"

        flow = FlowLoader.to_agents_flow(
            definition, extra_agents={"echo_agent": echo_agent}
        )
        assert isinstance(flow, AgentsFlow)

        result = await flow.run_flow("Hello world")
        assert result.status in ("completed", "partial")

    @pytest.mark.asyncio
    async def test_food_order_flow_pipeline(self, food_order_flow_path: Path):
        """Load food order flow, inject mock agents, execute."""
        definition = FlowLoader.load_from_file(food_order_flow_path)
        assert definition.flow == "FoodOrderFlow"
        assert len(definition.nodes) == 5

        mock_agents = {
            "food_decision": _FixedAgent(
                "food_decision",
                {"final_decision": "Pizza", "confidence": 0.9},
            ),
            "pizza_specialist": _FixedAgent(
                "pizza_specialist", "Margherita pizza ready!"
            ),
            "sushi_specialist": _FixedAgent(
                "sushi_specialist", "California roll ready!"
            ),
        }

        flow = FlowLoader.to_agents_flow(definition, extra_agents=mock_agents)
        result = await flow.run_flow("I want food")
        assert result.status in ("completed", "partial")


# ---------------------------------------------------------------------------
# Test: CEL Routing
# ---------------------------------------------------------------------------

class TestCELRouting:
    @pytest.mark.asyncio
    async def test_cel_routes_correctly(self):
        """CEL predicate routes to correct branch."""
        definition = FlowDefinition(
            flow="CELRouting",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(id="__start__", type="start"),
                NodeDefinition(id="branch_a", type="agent", agent_ref="agent_a"),
                NodeDefinition(id="branch_b", type="agent", agent_ref="agent_b"),
                NodeDefinition(id="__end__", type="end"),
            ],
            edges=[
                EdgeDefinition(
                    **{
                        "from": "__start__",
                        "to": "branch_a",
                        "condition": "on_condition",
                        "predicate": 'result == "go_a"',
                    }
                ),
                EdgeDefinition(
                    **{
                        "from": "__start__",
                        "to": "branch_b",
                        "condition": "on_condition",
                        "predicate": 'result == "go_b"',
                    }
                ),
                EdgeDefinition(
                    **{"from": "branch_a", "to": "__end__", "condition": "on_success"}
                ),
                EdgeDefinition(
                    **{"from": "branch_b", "to": "__end__", "condition": "on_success"}
                ),
            ],
        )
        agents = {
            "agent_a": _FixedAgent("agent_a", "Result from A"),
            "agent_b": _FixedAgent("agent_b", "Result from B"),
        }
        flow = FlowLoader.to_agents_flow(definition, extra_agents=agents)
        result = await flow.run_flow("go_a")
        assert result.status in ("completed", "partial")
        # branch_a should have executed
        assert flow.nodes["branch_a"].fsm.current_state.id == "completed"

    @pytest.mark.asyncio
    async def test_cel_dict_result_routing(self):
        """CEL predicate evaluates dict result fields."""
        definition = FlowDefinition(
            flow="DictRouting",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(id="classifier", type="agent", agent_ref="classifier"),
                NodeDefinition(id="handler", type="agent", agent_ref="handler"),
            ],
            edges=[
                EdgeDefinition(
                    **{
                        "from": "classifier",
                        "to": "handler",
                        "condition": "on_condition",
                        "predicate": 'result.category == "urgent"',
                    }
                ),
            ],
        )
        agents = {
            "classifier": _FixedAgent("classifier", {"category": "urgent"}),
            "handler": _FixedAgent("handler", "Handled!"),
        }
        flow = FlowLoader.to_agents_flow(definition, extra_agents=agents)
        result = await flow.run_flow("input")
        assert result.status in ("completed", "partial")


# ---------------------------------------------------------------------------
# Test: Action Execution
# ---------------------------------------------------------------------------

class TestActionExecution:
    @pytest.mark.asyncio
    async def test_pre_post_actions_fire(self, caplog: pytest.LogCaptureFixture):
        """Pre/post actions execute at correct lifecycle points."""
        caplog.set_level(logging.INFO)

        definition = FlowDefinition(
            flow="ActionTest",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(id="__start__", type="start"),
                NodeDefinition(
                    id="worker",
                    type="agent",
                    agent_ref="echo",
                    pre_actions=[
                        LogActionDef(level="info", message="PRE:{node_name}")
                    ],
                    post_actions=[
                        LogActionDef(level="info", message="POST:{node_name}")
                    ],
                ),
                NodeDefinition(id="__end__", type="end"),
            ],
            edges=[
                EdgeDefinition(
                    **{"from": "__start__", "to": "worker", "condition": "always"}
                ),
                EdgeDefinition(
                    **{"from": "worker", "to": "__end__", "condition": "on_success"}
                ),
            ],
        )
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents={"echo": _EchoAgent("echo")}
        )
        await flow.run_flow("test")
        # node_name in actions resolves to the agent's name, not the flow node ID
        assert "PRE:echo" in caplog.text
        assert "POST:echo" in caplog.text


# ---------------------------------------------------------------------------
# Test: Redis Persistence Roundtrip
# ---------------------------------------------------------------------------

class TestRedisPersistence:
    @pytest.mark.asyncio
    async def test_save_load_roundtrip(
        self, mock_redis: _MockRedis, simple_flow_path: Path
    ):
        """Save to Redis and load back preserves all data."""
        original = FlowLoader.load_from_file(simple_flow_path)
        await FlowLoader.save_to_redis(mock_redis, original)
        loaded = await FlowLoader.load_from_redis(mock_redis, "SimpleFlow")

        assert loaded.flow == original.flow
        assert len(loaded.nodes) == len(original.nodes)
        assert len(loaded.edges) == len(original.edges)

    @pytest.mark.asyncio
    async def test_list_and_delete(self, mock_redis: _MockRedis):
        """List flows and delete specific flow."""
        d1 = FlowDefinition(flow="Flow1", nodes=[], edges=[])
        d2 = FlowDefinition(flow="Flow2", nodes=[], edges=[])

        await FlowLoader.save_to_redis(mock_redis, d1)
        await FlowLoader.save_to_redis(mock_redis, d2)

        flows = await FlowLoader.list_flows_in_redis(mock_redis)
        assert len(flows) == 2

        await FlowLoader.delete_from_redis(mock_redis, "Flow1")
        flows = await FlowLoader.list_flows_in_redis(mock_redis)
        assert flows == ["Flow2"]

    @pytest.mark.asyncio
    async def test_redis_roundtrip_then_execute(
        self, mock_redis: _MockRedis, echo_agent: _EchoAgent
    ):
        """Save to Redis → load → materialize → execute."""
        definition = FlowDefinition(
            flow="RedisExec",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(id="__start__", type="start"),
                NodeDefinition(id="w", type="agent", agent_ref="echo_agent"),
                NodeDefinition(id="__end__", type="end"),
            ],
            edges=[
                EdgeDefinition(
                    **{"from": "__start__", "to": "w", "condition": "always"}
                ),
                EdgeDefinition(
                    **{"from": "w", "to": "__end__", "condition": "on_success"}
                ),
            ],
        )

        await FlowLoader.save_to_redis(mock_redis, definition)
        loaded = await FlowLoader.load_from_redis(mock_redis, "RedisExec")
        flow = FlowLoader.to_agents_flow(
            loaded, extra_agents={"echo_agent": echo_agent}
        )
        result = await flow.run_flow("Redis test")
        assert result.status in ("completed", "partial")


# ---------------------------------------------------------------------------
# Test: SvelteFlow Integration
# ---------------------------------------------------------------------------

class TestSvelteflowIntegration:
    def test_roundtrip_structure(self, simple_flow_path: Path):
        """SvelteFlow roundtrip preserves structure."""
        original = FlowLoader.load_from_file(simple_flow_path)
        sf = to_svelteflow(original)
        restored = from_svelteflow(sf, original.flow)

        assert restored.flow == original.flow
        assert len(restored.nodes) == len(original.nodes)
        assert len(restored.edges) == len(original.edges)

    @pytest.mark.asyncio
    async def test_roundtrip_execution(
        self, simple_flow_path: Path, echo_agent: _EchoAgent
    ):
        """SvelteFlow roundtrip produces executable flow."""
        original = FlowLoader.load_from_file(simple_flow_path)
        sf = to_svelteflow(original)
        restored = from_svelteflow(sf, original.flow)

        flow = FlowLoader.to_agents_flow(
            restored, extra_agents={"echo_agent": echo_agent}
        )
        result = await flow.run_flow("Roundtrip test")
        assert result.status in ("completed", "partial")


# ---------------------------------------------------------------------------
# Test: Error Handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_agent_ref_error(self):
        """Clear error when agent_ref not found."""
        definition = FlowDefinition(
            flow="MissingAgent",
            nodes=[
                NodeDefinition(
                    id="worker", type="agent", agent_ref="nonexistent"
                )
            ],
            edges=[],
        )
        with pytest.raises(LookupError) as exc_info:
            FlowLoader.to_agents_flow(definition)
        assert "nonexistent" in str(exc_info.value)

    def test_invalid_cel_error(self):
        """Clear error for invalid CEL expression at materialization."""
        definition = FlowDefinition(
            flow="BadCEL",
            nodes=[
                NodeDefinition(id="a", type="start"),
                NodeDefinition(id="b", type="end"),
            ],
            edges=[
                EdgeDefinition(
                    **{
                        "from": "a",
                        "to": "b",
                        "condition": "on_condition",
                        "predicate": "result..invalid..syntax",
                    }
                )
            ],
        )
        with pytest.raises(ValueError):
            FlowLoader.to_agents_flow(definition, extra_agents={})

    def test_invalid_json_file(self, tmp_path: Path):
        """Clear error for malformed JSON file."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        with pytest.raises(Exception):
            FlowLoader.load_from_file(bad)

    def test_missing_file(self):
        """Clear error for missing file."""
        with pytest.raises(FileNotFoundError):
            FlowLoader.load_from_file("/tmp/nonexistent_flow_file.json")


# ---------------------------------------------------------------------------
# Test: File I/O Roundtrip
# ---------------------------------------------------------------------------

class TestFileRoundtrip:
    def test_save_load_file(self, tmp_path: Path, echo_agent: _EchoAgent):
        """Save to file → load → materialize → verify."""
        definition = FlowDefinition(
            flow="FileSave",
            metadata={"enable_execution_memory": False},
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(id="w", type="agent", agent_ref="echo_agent"),
                NodeDefinition(id="e", type="end"),
            ],
            edges=[
                EdgeDefinition(
                    **{"from": "s", "to": "w", "condition": "always"}
                ),
                EdgeDefinition(
                    **{"from": "w", "to": "e", "condition": "on_success"}
                ),
            ],
        )

        path = tmp_path / "flow.json"
        FlowLoader.save_to_file(definition, path)
        loaded = FlowLoader.load_from_file(path)

        assert loaded.flow == "FileSave"
        assert loaded.updated_at is not None

        flow = FlowLoader.to_agents_flow(
            loaded, extra_agents={"echo_agent": echo_agent}
        )
        assert isinstance(flow, AgentsFlow)
