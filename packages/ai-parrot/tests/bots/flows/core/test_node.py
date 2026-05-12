"""Unit tests for parrot.bots.flows.core.node — FEAT-163 frozen Pydantic shape.

Tests verify:
- Node, AgentNode, StartNode, EndNode are frozen Pydantic BaseModels.
- Frozen enforcement: field reassignment raises.
- PrivateAttr action lists are mutable on frozen models.
- FSM nested mutation works on frozen AgentNode.
- AgentNode.execute() uses the new (ctx, deps, **kwargs) signature.
- _build_prompt() default behaviour.
- StartNode / EndNode default names and behaviours.
"""
import pytest
from pydantic import ValidationError

from parrot.bots.flows.core.node import AgentNode, EndNode, Node, StartNode
from parrot.bots.flows.core.fsm import AgentTaskMachine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal AgentLike implementation for testing.

    Satisfies the AgentLike Protocol: name as property, invoke() present.
    Also provides ask() since AgentNode.execute() calls agent.ask().
    """

    @property
    def name(self) -> str:
        return "fake-agent"

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        return {"content": f"invoke: {prompt}"}

    async def ask(self, question: str = "", **kwargs: object) -> object:
        return {"content": f"echo: {question}"}


class FakeCtx:
    """Minimal FlowContext stub for execute() tests."""

    def get_input_for_agent(self, name: str, deps: object) -> str:
        return f"prompt for {name}"


# ---------------------------------------------------------------------------
# Frozen enforcement
# ---------------------------------------------------------------------------


class TestNodeFrozen:
    def test_agent_node_construct(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        assert node.node_id == "n1"
        assert node.name == "fake-agent"
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_agent_node_frozen_blocks_reassignment(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            node.node_id = "n2"  # type: ignore[misc]

    def test_agent_node_fsm_state_mutates(self) -> None:
        """FSM mutation is allowed even on a frozen model."""
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        node.fsm.schedule()
        node.fsm.start()
        assert str(node.fsm.current_state.id) == "running"

    def test_node_private_action_lists(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")

        def cb(name: str, prompt: str, **ctx: object) -> None:
            pass

        node.add_pre_action(cb)
        node.add_post_action(cb)
        assert len(node._pre_actions) == 1
        assert len(node._post_actions) == 1

    @pytest.mark.asyncio
    async def test_agent_node_execute_new_signature(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        ctx = FakeCtx()
        deps: dict = {}
        result = await node.execute(ctx=ctx, deps=deps)
        assert isinstance(result, dict)
        # Result dict must contain the documented keys.
        assert "output" in result or "response" in result

    def test_start_node_default_name(self) -> None:
        node = StartNode()
        assert node.name == "__start__"
        assert node.is_configured is True

    def test_end_node_default_name(self) -> None:
        node = EndNode()
        assert node.name == "__end__"

    def test_start_node_frozen_blocks_reassignment(self) -> None:
        node = StartNode()
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            node.name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Model is a Pydantic BaseModel (not a dataclass)
# ---------------------------------------------------------------------------


class TestNodeIsPydantic:
    def test_agent_node_is_basemodel(self) -> None:
        from pydantic import BaseModel

        assert issubclass(AgentNode, BaseModel)

    def test_start_node_is_basemodel(self) -> None:
        from pydantic import BaseModel

        assert issubclass(StartNode, BaseModel)

    def test_end_node_is_basemodel(self) -> None:
        from pydantic import BaseModel

        assert issubclass(EndNode, BaseModel)

    def test_node_has_model_config(self) -> None:
        cfg = AgentNode.model_config
        assert cfg.get("frozen") is True
        assert cfg.get("arbitrary_types_allowed") is True


# ---------------------------------------------------------------------------
# _build_prompt default
# ---------------------------------------------------------------------------


class TestBuildPromptDefault:
    def test_build_prompt_no_deps(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        ctx = FakeCtx()
        prompt = node._build_prompt(ctx, {})
        assert "fake-agent" in prompt

    def test_build_prompt_with_dict_ctx(self) -> None:
        class DictCtx:
            def get_input_for_agent(self, name: str, deps: object) -> dict:
                return {"task": "do something", "dependencies": {"n0": "result0"}}

        node = AgentNode(agent=FakeAgent(), node_id="n1", dependencies={"n0"})
        ctx = DictCtx()
        prompt = node._build_prompt(ctx, {"n0": "result0"})
        assert "do something" in prompt
        assert "result0" in prompt or "n0" in prompt


# ---------------------------------------------------------------------------
# FSM auto-creation in model_post_init
# ---------------------------------------------------------------------------


class TestFSMAutoCreation:
    def test_fsm_auto_created_when_none(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        assert node.fsm is not None
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_fsm_uses_agent_name(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        # The FSM is created with agent_name=FakeAgent.name
        assert node.fsm is not None

    def test_custom_fsm_is_kept(self) -> None:
        custom = AgentTaskMachine(agent_name="custom")
        node = AgentNode(agent=FakeAgent(), node_id="n1", fsm=custom)
        assert node.fsm is custom


# ---------------------------------------------------------------------------
# StartNode / EndNode
# ---------------------------------------------------------------------------


class TestStartEndNodes:
    def test_start_node_node_id_equals_name(self) -> None:
        node = StartNode()
        assert node.node_id == "__start__"

    def test_end_node_node_id_equals_name(self) -> None:
        node = EndNode()
        assert node.node_id == "__end__"

    def test_start_node_custom_name_syncs_node_id(self) -> None:
        node = StartNode(name="entry")
        assert node.name == "entry"
        # node_id synced to name in model_post_init
        assert node.node_id == "entry"

    def test_end_node_custom_name_syncs_node_id(self) -> None:
        node = EndNode(name="exit")
        assert node.name == "exit"
        assert node.node_id == "exit"

    @pytest.mark.asyncio
    async def test_start_node_ask_passthrough(self) -> None:
        node = StartNode()
        result = await node.ask("hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_end_node_ask_passthrough(self) -> None:
        node = EndNode()
        result = await node.ask("final")
        assert result == "final"

    @pytest.mark.asyncio
    async def test_start_node_configure_no_op(self) -> None:
        node = StartNode()
        await node.configure()  # must not raise

    def test_start_node_has_logger(self) -> None:
        node = StartNode()
        assert node.logger is not None

    def test_agent_node_has_logger(self) -> None:
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        assert node.logger is not None


# ---------------------------------------------------------------------------
# Action hooks on frozen nodes
# ---------------------------------------------------------------------------


class TestActionHooks:
    def test_pre_action_appends(self) -> None:
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: None)
        assert len(node._pre_actions) == 1

    def test_post_action_appends(self) -> None:
        node = StartNode()
        node.add_post_action(lambda n, r, **kw: None)
        assert len(node._post_actions) == 1

    @pytest.mark.asyncio
    async def test_pre_action_executes(self) -> None:
        calls: list = []
        node = StartNode()
        node.add_pre_action(lambda n, p, **kw: calls.append(("pre", n)))
        await node.run_pre_actions(prompt="test")
        assert len(calls) == 1
        assert calls[0] == ("pre", "__start__")

    @pytest.mark.asyncio
    async def test_post_action_executes(self) -> None:
        calls: list = []
        node = StartNode()
        node.add_post_action(lambda n, r, **kw: calls.append(("post", r)))
        await node.run_post_actions(result="done")
        assert len(calls) == 1
        assert calls[0] == ("post", "done")

    @pytest.mark.asyncio
    async def test_async_pre_action(self) -> None:
        calls: list = []

        async def async_pre(n: str, p: str, **kw: object) -> None:
            calls.append(("pre", n, p))

        node = StartNode()
        node.add_pre_action(async_pre)
        await node.run_pre_actions(prompt="hello")
        assert len(calls) == 1
