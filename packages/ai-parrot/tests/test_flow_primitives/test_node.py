"""Unit tests for parrot.bots.flows.core.node (TASK-916)."""
import pytest
from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
from parrot.bots.flows.core.types import AgentLike
from parrot.bots.flows.core.fsm import AgentTaskMachine


class MockAgent:
    """Minimal AgentLike implementation for testing."""

    @property
    def name(self) -> str:
        return "test-agent"

    async def invoke(self, prompt: str, **kwargs):
        return f"response: {prompt}"


class TestNodeIdVsName:
    def test_agent_node_separates_id_from_name(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="node-1")
        assert node.node_id == "node-1"
        assert node.name == "test-agent"
        assert node.node_id != node.name

    def test_node_id_is_unique_from_name(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="researcher-1")
        assert node.node_id == "researcher-1"
        assert node.name == "test-agent"  # agent identity unchanged

    def test_agent_node_fsm_auto_created(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="n1")
        assert node.fsm is not None
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_agent_node_custom_fsm(self):
        agent = MockAgent()
        custom_fsm = AgentTaskMachine(agent_name="custom")
        node = AgentNode(agent=agent, node_id="n1", fsm=custom_fsm)
        assert node.fsm is custom_fsm

    def test_agent_node_default_deps_and_successors(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="n1")
        assert node.dependencies == set()
        assert node.successors == set()

    def test_agent_node_with_deps(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="n2", dependencies={"n1"})
        assert "n1" in node.dependencies

    def test_mock_agent_conforms_to_agent_like(self):
        agent = MockAgent()
        assert isinstance(agent, AgentLike)


class TestStartEndNodes:
    def test_start_node_defaults(self):
        node = StartNode()
        assert node.name == "__start__"

    def test_end_node_defaults(self):
        node = EndNode()
        assert node.name == "__end__"

    def test_start_node_custom_name(self):
        node = StartNode(name="entry")
        assert node.name == "entry"

    def test_end_node_custom_name(self):
        node = EndNode(name="exit")
        assert node.name == "exit"

    def test_start_node_node_id_equals_name(self):
        node = StartNode()
        assert node.node_id == "__start__"

    def test_end_node_node_id_equals_name(self):
        node = EndNode()
        assert node.node_id == "__end__"

    def test_start_node_is_configured(self):
        node = StartNode()
        assert node.is_configured is True

    def test_end_node_is_configured(self):
        node = EndNode()
        assert node.is_configured is True

    def test_start_node_metadata(self):
        node = StartNode(metadata={"trigger": "webhook"})
        assert node.metadata == {"trigger": "webhook"}

    def test_start_node_empty_metadata_default(self):
        node = StartNode()
        assert node.metadata == {}

    @pytest.mark.asyncio
    async def test_start_node_ask_returns_prompt(self):
        node = StartNode()
        result = await node.ask("hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_end_node_ask_returns_prompt(self):
        node = EndNode()
        result = await node.ask("final")
        assert result == "final"

    @pytest.mark.asyncio
    async def test_start_node_configure_no_op(self):
        node = StartNode()
        await node.configure()  # should not raise


class TestActionHooks:
    def test_pre_action_sync(self):
        calls = []
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: calls.append(("pre", n, p)))

    def test_post_action_sync(self):
        calls = []
        node = StartNode()
        node.add_post_action(lambda n, r, **kw: calls.append(("post", r)))

    @pytest.mark.asyncio
    async def test_pre_action_executes(self):
        calls = []
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: calls.append(("pre", n)))
        await node.run_pre_actions(prompt="test")
        assert len(calls) == 1
        assert calls[0] == ("pre", "__start__")

    @pytest.mark.asyncio
    async def test_post_action_executes(self):
        calls = []
        node = StartNode()
        node.add_post_action(lambda n, r, **kw: calls.append(("post", r)))
        await node.run_post_actions(result="done")
        assert len(calls) == 1
        assert calls[0] == ("post", "done")

    @pytest.mark.asyncio
    async def test_post_action_async(self):
        calls = []

        async def async_action(n, r, **kw):
            calls.append(("post", n, r))

        node = StartNode()
        node.add_post_action(async_action)
        await node.run_post_actions(result="done")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_pre_action_async(self):
        calls = []

        async def async_pre(n, p, **kw):
            calls.append(("pre", n, p))

        node = StartNode()
        node.add_pre_action(async_pre)
        await node.run_pre_actions(prompt="hello")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_multiple_pre_actions_order(self):
        order = []
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: order.append(1))
        node.add_pre_action(lambda n, p, **kw: order.append(2))
        await node.run_pre_actions(prompt="x")
        assert order == [1, 2]

    @pytest.mark.asyncio
    async def test_agent_node_action_hooks(self):
        calls = []
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="n1")
        node.add_pre_action(lambda n, p, **kw: calls.append(n))
        await node.run_pre_actions(prompt="q")
        assert calls == ["test-agent"]

    @pytest.mark.asyncio
    async def test_ask_runs_hooks(self):
        pre_calls = []
        post_calls = []
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: pre_calls.append(p))
        node.add_post_action(lambda n, r, **kw: post_calls.append(r))
        await node.ask("my prompt")
        assert pre_calls == ["my prompt"]
        assert post_calls == ["my prompt"]


class TestNodeLogger:
    def test_start_node_has_logger(self):
        node = StartNode()
        assert node.logger is not None

    def test_agent_node_has_logger(self):
        agent = MockAgent()
        node = AgentNode(agent=agent, node_id="n1")
        assert node.logger is not None
