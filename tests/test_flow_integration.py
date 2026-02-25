"""Integration tests for AgentsFlow Persistency feature.

Verifies the complete lifecycle:
- Load JSON → materialize → execute → verify results
- Redis persistence roundtrip
- CEL predicate routing
- Pre/post action execution
- SvelteFlow roundtrip with execution
- Error handling
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from parrot.bots.flow import (
    AgentsFlow,
    FlowDefinition,
    FlowLoader,
    NodeDefinition,
    EdgeDefinition,
    LogActionDef,
    to_svelteflow,
    from_svelteflow,
)
from parrot.bots.flow.decision_node import DecisionMode, DecisionResult


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "flows"


class _StubAgent:
    """Minimal agent stub returning a fixed response."""

    is_configured: bool = True

    def __init__(self, name: str, response: Any = "ok"):
        self._name = name
        self._response = response
        from parrot.tools.manager import ToolManager

        self.tool_manager = ToolManager()

    @property
    def name(self) -> str:
        return self._name

    async def ask(self, question: str = "", **kwargs: Any) -> Any:
        return self._response

    async def configure(self) -> None:
        pass


class _DecisionAgent(_StubAgent):
    """Agent stub that returns a DecisionResult (simulates decision node)."""

    def __init__(self, name: str, decision: str):
        super().__init__(name, response=None)
        self._decision = decision

    async def ask(self, question: str = "", **kwargs: Any) -> DecisionResult:
        return DecisionResult(
            mode=DecisionMode.CIO,
            final_decision=self._decision,
            decision=self._decision,
            confidence=0.95,
            reasoning="Test decision",
        )


class _MockRedis:
    """In-memory async Redis mock."""

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
        for k in list(self._store.keys()):
            if fnmatch.fnmatch(k, match):
                yield k


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> _MockRedis:
    return _MockRedis()


@pytest.fixture
def food_order_flow_path() -> Path:
    return FIXTURES_DIR / "food_order_flow.json"


@pytest.fixture
def decision_flow_path() -> Path:
    return FIXTURES_DIR / "decision_flow.json"


@pytest.fixture
def pizza_agents() -> Dict[str, _StubAgent]:
    """Mock agents for the food order flow."""
    return {
        "food_decision": _DecisionAgent("food_decision", "pizza"),
        "pizza_specialist": _StubAgent("pizza_specialist", "Margherita pizza, ready!"),
        "sushi_specialist": _StubAgent("sushi_specialist", "Dragon roll, ready!"),
    }


@pytest.fixture
def sushi_agents() -> Dict[str, _StubAgent]:
    """Mock agents for the sushi branch of food order flow."""
    return {
        "food_decision": _DecisionAgent("food_decision", "sushi"),
        "pizza_specialist": _StubAgent("pizza_specialist", "Margherita pizza, ready!"),
        "sushi_specialist": _StubAgent("sushi_specialist", "Dragon roll, ready!"),
    }


@pytest.fixture
def category_agents() -> Dict[str, _StubAgent]:
    """Mock agents for the decision routing flow."""
    return {
        "classifier_agent": _StubAgent("classifier_agent", "category_a"),
        "handler_a": _StubAgent("handler_a", "Handled by A"),
        "handler_b": _StubAgent("handler_b", "Handled by B"),
    }


# ---------------------------------------------------------------------------
# Test: Full Pipeline (Load → Materialize → Execute)
# ---------------------------------------------------------------------------


class TestLoadAndExecute:
    @pytest.mark.asyncio
    async def test_full_pipeline_pizza(
        self, food_order_flow_path: Path, pizza_agents: Dict[str, _StubAgent]
    ) -> None:
        """Load JSON → materialize → execute → verify pizza route."""
        definition = FlowLoader.load_from_file(food_order_flow_path)
        assert definition.flow == "FoodOrderFlow"
        assert len(definition.nodes) == 5
        assert len(definition.edges) == 5

        flow = FlowLoader.to_agents_flow(
            definition, extra_agents=pizza_agents
        )
        assert isinstance(flow, AgentsFlow)
        assert flow.name == "FoodOrderFlow"

        result = await flow.run_flow("I want to order food")
        assert result.status in ("completed", "partial")

        # Pizza agent should have completed (routed by CEL predicate)
        pizza_node = flow.nodes["pizza_agent"]
        assert pizza_node.fsm.current_state == pizza_node.fsm.completed

    @pytest.mark.asyncio
    async def test_full_pipeline_sushi(
        self, food_order_flow_path: Path, sushi_agents: Dict[str, _StubAgent]
    ) -> None:
        """Load JSON → materialize → execute → verify sushi route."""
        definition = FlowLoader.load_from_file(food_order_flow_path)
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents=sushi_agents
        )

        result = await flow.run_flow("I want sushi please")
        assert result.status in ("completed", "partial")

        # Sushi agent should have completed
        sushi_node = flow.nodes["sushi_agent"]
        assert sushi_node.fsm.current_state == sushi_node.fsm.completed

    @pytest.mark.asyncio
    async def test_simple_flow_from_fixture(self) -> None:
        """Load and run the simple_flow.json fixture end-to-end."""
        definition = FlowLoader.load_from_file(FIXTURES_DIR / "simple_flow.json")
        echo = _StubAgent("echo_agent", "echo response")
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents={"echo_agent": echo}
        )

        result = await flow.run_flow("Hello world")
        assert result.status in ("completed", "partial")
        assert "worker" in flow.nodes
        worker = flow.nodes["worker"]
        assert worker.fsm.current_state == worker.fsm.completed


# ---------------------------------------------------------------------------
# Test: CEL Predicate Routing
# ---------------------------------------------------------------------------


class TestCELRouting:
    @pytest.mark.asyncio
    async def test_cel_routes_to_correct_branch(
        self, decision_flow_path: Path, category_agents: Dict[str, _StubAgent]
    ) -> None:
        """CEL predicate routes classifier → handler_a when result = 'category_a'."""
        definition = FlowLoader.load_from_file(decision_flow_path)
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents=category_agents
        )

        await flow.run_flow("classify this input")

        handler_a = flow.nodes["handler_a"]
        handler_b = flow.nodes["handler_b"]

        assert handler_a.fsm.current_state == handler_a.fsm.completed
        # handler_b should NOT have been reached
        assert handler_b.fsm.current_state != handler_b.fsm.completed

    @pytest.mark.asyncio
    async def test_cel_routes_to_other_branch(self) -> None:
        """CEL predicate routes to handler_b when result = 'category_b'."""
        definition = FlowLoader.load_from_file(
            FIXTURES_DIR / "decision_flow.json"
        )
        agents = {
            "classifier_agent": _StubAgent("classifier_agent", "category_b"),
            "handler_a": _StubAgent("handler_a", "A"),
            "handler_b": _StubAgent("handler_b", "B"),
        }
        flow = FlowLoader.to_agents_flow(definition, extra_agents=agents)

        await flow.run_flow("classify this")

        handler_a = flow.nodes["handler_a"]
        handler_b = flow.nodes["handler_b"]

        assert handler_b.fsm.current_state == handler_b.fsm.completed
        assert handler_a.fsm.current_state != handler_a.fsm.completed

    @pytest.mark.asyncio
    async def test_cel_with_string_comparison(self) -> None:
        """CEL predicate matches string results (plain agent output).

        Note: AgentsFlow._extract_result() str()-ifies raw dict returns,
        so CEL predicates on non-Pydantic results work with string equality.
        """
        definition = FlowDefinition(
            flow="StringCEL",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(id="src", type="agent", agent_ref="src"),
                NodeDefinition(id="dst", type="agent", agent_ref="dst"),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "s", "to": "src", "condition": "always"
                }),
                EdgeDefinition(**{
                    "from": "src", "to": "dst",
                    "condition": "on_condition",
                    "predicate": 'result == "approved"',
                }),
            ],
        )

        agents = {
            "src": _StubAgent("src", "approved"),
            "dst": _StubAgent("dst", "done"),
        }
        flow = FlowLoader.to_agents_flow(definition, extra_agents=agents)
        await flow.run_flow("test")

        dst_node = flow.nodes["dst"]
        assert dst_node.fsm.current_state == dst_node.fsm.completed

    @pytest.mark.asyncio
    async def test_cel_with_pydantic_result(self) -> None:
        """CEL predicate works with Pydantic model results (coerced to dict)."""
        definition = FlowLoader.load_from_file(
            FIXTURES_DIR / "food_order_flow.json"
        )
        agents = {
            "food_decision": _DecisionAgent("food_decision", "pizza"),
            "pizza_specialist": _StubAgent("pizza_specialist", "Pizza!"),
            "sushi_specialist": _StubAgent("sushi_specialist", "Sushi!"),
        }
        flow = FlowLoader.to_agents_flow(definition, extra_agents=agents)
        await flow.run_flow("order food")

        pizza = flow.nodes["pizza_agent"]
        sushi = flow.nodes["sushi_agent"]
        assert pizza.fsm.current_state == pizza.fsm.completed
        assert sushi.fsm.current_state != sushi.fsm.completed


# ---------------------------------------------------------------------------
# Test: Action Execution
# ---------------------------------------------------------------------------


class TestActionExecution:
    @pytest.mark.asyncio
    async def test_actions_fire_during_execution(self, caplog: Any) -> None:
        """Pre/post actions log messages during execution."""
        import logging

        caplog.set_level(logging.INFO)

        definition = FlowDefinition(
            flow="ActionTest",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(
                    id="worker",
                    type="agent",
                    agent_ref="echo",
                    pre_actions=[
                        LogActionDef(message="PRE:{node_name}")
                    ],
                    post_actions=[
                        LogActionDef(message="POST:{node_name}")
                    ],
                ),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "s", "to": "worker", "condition": "always"
                }),
            ],
        )

        flow = FlowLoader.to_agents_flow(
            definition,
            extra_agents={"echo": _StubAgent("echo", "response")},
        )
        await flow.run_flow("test")

        # LogAction formats {node_name} with the agent's actual name
        # (passed by Node.run_pre_actions / run_post_actions), which is
        # the agent.name attribute — "echo", not the flow-node id "worker".
        assert "PRE:echo" in caplog.text
        assert "POST:echo" in caplog.text

    @pytest.mark.asyncio
    async def test_actions_in_food_order_flow(
        self, food_order_flow_path: Path, pizza_agents: Dict[str, _StubAgent],
        caplog: Any,
    ) -> None:
        """Pre/post actions from fixture flow fire correctly."""
        import logging

        caplog.set_level(logging.INFO)

        definition = FlowLoader.load_from_file(food_order_flow_path)
        flow = FlowLoader.to_agents_flow(
            definition, extra_agents=pizza_agents
        )
        await flow.run_flow("order food")

        # The food_order_flow.json has log actions on pizza_agent
        assert "Processing pizza order" in caplog.text
        assert "Pizza order complete" in caplog.text


# ---------------------------------------------------------------------------
# Test: Redis Persistence Roundtrip
# ---------------------------------------------------------------------------


class TestRedisIntegration:
    @pytest.mark.asyncio
    async def test_save_load_roundtrip(
        self, mock_redis: _MockRedis, food_order_flow_path: Path
    ) -> None:
        """Save to Redis and load back preserves all data."""
        original = FlowLoader.load_from_file(food_order_flow_path)

        await FlowLoader.save_to_redis(mock_redis, original)
        loaded = await FlowLoader.load_from_redis(mock_redis, "FoodOrderFlow")

        assert loaded.flow == original.flow
        assert loaded.version == original.version
        assert len(loaded.nodes) == len(original.nodes)
        assert len(loaded.edges) == len(original.edges)
        assert loaded.metadata.max_parallel_tasks == original.metadata.max_parallel_tasks

    @pytest.mark.asyncio
    async def test_redis_roundtrip_then_execute(
        self, mock_redis: _MockRedis, pizza_agents: Dict[str, _StubAgent]
    ) -> None:
        """Save → load from Redis → materialize → execute."""
        original = FlowLoader.load_from_file(
            FIXTURES_DIR / "food_order_flow.json"
        )
        await FlowLoader.save_to_redis(mock_redis, original)

        loaded = await FlowLoader.load_from_redis(mock_redis, "FoodOrderFlow")
        flow = FlowLoader.to_agents_flow(loaded, extra_agents=pizza_agents)
        result = await flow.run_flow("test")

        assert result.status in ("completed", "partial")

    @pytest.mark.asyncio
    async def test_list_and_delete(self, mock_redis: _MockRedis) -> None:
        """List all flows and delete specific one."""
        d1 = FlowDefinition(flow="FlowAlpha", nodes=[], edges=[])
        d2 = FlowDefinition(flow="FlowBeta", nodes=[], edges=[])

        await FlowLoader.save_to_redis(mock_redis, d1)
        await FlowLoader.save_to_redis(mock_redis, d2)

        flows = await FlowLoader.list_flows_in_redis(mock_redis)
        assert len(flows) == 2
        assert "FlowAlpha" in flows
        assert "FlowBeta" in flows

        await FlowLoader.delete_from_redis(mock_redis, "FlowAlpha")
        flows = await FlowLoader.list_flows_in_redis(mock_redis)
        assert flows == ["FlowBeta"]

    @pytest.mark.asyncio
    async def test_load_missing_raises_keyerror(
        self, mock_redis: _MockRedis
    ) -> None:
        """Loading non-existent flow raises KeyError."""
        with pytest.raises(KeyError, match="NonExistent"):
            await FlowLoader.load_from_redis(mock_redis, "NonExistent")


# ---------------------------------------------------------------------------
# Test: SvelteFlow Roundtrip
# ---------------------------------------------------------------------------


class TestSvelteflowIntegration:
    def test_roundtrip_preserves_structure(
        self, food_order_flow_path: Path
    ) -> None:
        """Convert to SvelteFlow and back preserves node/edge counts."""
        original = FlowLoader.load_from_file(food_order_flow_path)

        sf = to_svelteflow(original)
        assert "nodes" in sf
        assert "edges" in sf
        assert len(sf["nodes"]) == len(original.nodes)

        restored = from_svelteflow(sf, original.flow)
        assert restored.flow == original.flow
        assert len(restored.nodes) == len(original.nodes)

    @pytest.mark.asyncio
    async def test_roundtrip_then_execute(
        self, food_order_flow_path: Path, pizza_agents: Dict[str, _StubAgent]
    ) -> None:
        """SvelteFlow roundtrip → materialize → execute."""
        original = FlowLoader.load_from_file(food_order_flow_path)

        sf = to_svelteflow(original)
        restored = from_svelteflow(sf, original.flow)

        flow = FlowLoader.to_agents_flow(restored, extra_agents=pizza_agents)
        result = await flow.run_flow("test")
        assert result.status in ("completed", "partial")

    def test_roundtrip_preserves_actions(
        self, food_order_flow_path: Path
    ) -> None:
        """SvelteFlow roundtrip preserves pre/post actions on nodes."""
        original = FlowLoader.load_from_file(food_order_flow_path)

        sf = to_svelteflow(original)
        restored = from_svelteflow(sf, original.flow)

        # Find pizza_agent node in restored — it should have pre_actions
        pizza_nodes = [n for n in restored.nodes if n.id == "pizza_agent"]
        assert len(pizza_nodes) == 1
        assert len(pizza_nodes[0].pre_actions) == 1
        assert pizza_nodes[0].pre_actions[0].type == "log"

    def test_roundtrip_preserves_predicates(
        self, food_order_flow_path: Path
    ) -> None:
        """SvelteFlow roundtrip preserves CEL predicate strings."""
        original = FlowLoader.load_from_file(food_order_flow_path)

        sf = to_svelteflow(original)
        restored = from_svelteflow(sf, original.flow)

        on_condition_edges = [
            e for e in restored.edges if e.condition == "on_condition"
        ]
        assert len(on_condition_edges) == 2
        predicates = {e.predicate for e in on_condition_edges}
        assert 'result.final_decision == "pizza"' in predicates
        assert 'result.final_decision == "sushi"' in predicates


# ---------------------------------------------------------------------------
# Test: Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_missing_agent_ref_lookup_error(self) -> None:
        """Clear LookupError when agent_ref not found."""
        definition = FlowDefinition(
            flow="MissingAgent",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(
                    id="w", type="agent", agent_ref="nonexistent_agent"
                ),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "s", "to": "w", "condition": "always"
                }),
            ],
        )

        with pytest.raises(LookupError, match="nonexistent_agent"):
            FlowLoader.to_agents_flow(definition)

    def test_invalid_cel_expression_error(self) -> None:
        """Clear ValueError for invalid CEL expression."""
        definition = FlowDefinition(
            flow="BadCEL",
            nodes=[
                NodeDefinition(id="a", type="start"),
                NodeDefinition(id="b", type="end"),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "a",
                    "to": "b",
                    "condition": "on_condition",
                    "predicate": "result..invalid..syntax",
                }),
            ],
        )

        with pytest.raises(ValueError, match="CEL|expression"):
            FlowLoader.to_agents_flow(definition, extra_agents={})

    def test_file_not_found_error(self) -> None:
        """Clear FileNotFoundError for missing flow file."""
        with pytest.raises(FileNotFoundError):
            FlowLoader.load_from_file("/nonexistent/path/flow.json")

    def test_invalid_json_error(self, tmp_path: Path) -> None:
        """Clear error for malformed JSON file."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            FlowLoader.load_from_file(bad_file)

    def test_missing_required_field_error(self) -> None:
        """Pydantic validation error for missing required field."""
        with pytest.raises(Exception):  # pydantic ValidationError
            FlowLoader.from_dict({"nodes": [], "edges": []})

    def test_edge_references_unknown_node(self) -> None:
        """Validation error when edge references non-existent node."""
        with pytest.raises(Exception):  # pydantic ValidationError
            FlowDefinition(
                flow="BadEdge",
                nodes=[NodeDefinition(id="a", type="start")],
                edges=[
                    EdgeDefinition(**{
                        "from": "a",
                        "to": "nonexistent",
                        "condition": "always",
                    })
                ],
            )


# ---------------------------------------------------------------------------
# Test: Fan-out Edges
# ---------------------------------------------------------------------------


class TestFanOut:
    @pytest.mark.asyncio
    async def test_fan_out_executes_all_targets(self) -> None:
        """Fan-out edge activates all target agents."""
        definition = FlowDefinition(
            flow="FanOutTest",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(id="a", type="agent", agent_ref="a"),
                NodeDefinition(id="b", type="agent", agent_ref="b"),
                NodeDefinition(id="e", type="end"),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "s", "to": ["a", "b"], "condition": "always"
                }),
                EdgeDefinition(**{
                    "from": "a", "to": "e", "condition": "on_success"
                }),
                EdgeDefinition(**{
                    "from": "b", "to": "e", "condition": "on_success"
                }),
            ],
        )

        agents = {
            "a": _StubAgent("a", "result_a"),
            "b": _StubAgent("b", "result_b"),
        }
        flow = FlowLoader.to_agents_flow(definition, extra_agents=agents)
        result = await flow.run_flow("test fan-out")

        assert result.status in ("completed", "partial")

        node_a = flow.nodes["a"]
        node_b = flow.nodes["b"]
        assert node_a.fsm.current_state == node_a.fsm.completed
        assert node_b.fsm.current_state == node_b.fsm.completed


# ---------------------------------------------------------------------------
# Test: File I/O Roundtrip
# ---------------------------------------------------------------------------


class TestFileRoundtrip:
    def test_save_then_load_preserves_data(self, tmp_path: Path) -> None:
        """Save to file and load back preserves all fields."""
        original = FlowLoader.load_from_file(
            FIXTURES_DIR / "food_order_flow.json"
        )

        out_path = tmp_path / "roundtrip.json"
        FlowLoader.save_to_file(original, out_path)

        loaded = FlowLoader.load_from_file(out_path)
        assert loaded.flow == original.flow
        assert len(loaded.nodes) == len(original.nodes)
        assert len(loaded.edges) == len(original.edges)
        assert loaded.updated_at is not None

    @pytest.mark.asyncio
    async def test_save_load_then_execute(
        self, tmp_path: Path, pizza_agents: Dict[str, _StubAgent]
    ) -> None:
        """File save → load → materialize → execute."""
        original = FlowLoader.load_from_file(
            FIXTURES_DIR / "food_order_flow.json"
        )
        out_path = tmp_path / "execute_test.json"
        FlowLoader.save_to_file(original, out_path)

        loaded = FlowLoader.load_from_file(out_path)
        flow = FlowLoader.to_agents_flow(loaded, extra_agents=pizza_agents)
        result = await flow.run_flow("let's eat")

        assert result.status in ("completed", "partial")
