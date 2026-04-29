"""Unit tests for parrot.bots.flows.core.transition (TASK-918)."""
import pytest
from parrot.bots.flows.core.transition import FlowTransition
from parrot.bots.flows.core.fsm import TransitionCondition
from parrot.bots.flows.core.result import NodeExecutionInfo


class TestTransitionShouldActivate:
    @pytest.mark.asyncio
    async def test_always_activates(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ALWAYS)
        assert await t.should_activate(result="ok") is True

    @pytest.mark.asyncio
    async def test_always_activates_with_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ALWAYS)
        assert await t.should_activate(result=None, error=Exception("fail")) is True

    @pytest.mark.asyncio
    async def test_on_success_no_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_SUCCESS)
        assert await t.should_activate(result="ok", error=None) is True

    @pytest.mark.asyncio
    async def test_on_success_with_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_SUCCESS)
        assert await t.should_activate(result=None, error=Exception("fail")) is False

    @pytest.mark.asyncio
    async def test_on_error_with_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_ERROR)
        assert await t.should_activate(result=None, error=Exception("fail")) is True

    @pytest.mark.asyncio
    async def test_on_error_without_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_ERROR)
        assert await t.should_activate(result="ok", error=None) is False

    @pytest.mark.asyncio
    async def test_on_condition_with_sync_predicate(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ON_CONDITION,
            predicate=lambda r: "yes" in str(r),
        )
        assert await t.should_activate(result="yes please") is True
        assert await t.should_activate(result="no thanks") is False

    @pytest.mark.asyncio
    async def test_on_condition_with_async_predicate(self):
        async def pred(r):
            return r > 10

        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ON_CONDITION,
            predicate=pred,
        )
        assert await t.should_activate(result=20) is True
        assert await t.should_activate(result=5) is False

    @pytest.mark.asyncio
    async def test_on_condition_without_predicate_returns_false(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ON_CONDITION,
            predicate=None,
        )
        assert await t.should_activate(result="any") is False

    @pytest.mark.asyncio
    async def test_on_timeout_returns_false_by_default(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ON_TIMEOUT,
        )
        assert await t.should_activate(result=None) is False


class TestTransitionBuildPrompt:
    class FakeContext:
        original_query = "do research"

    @pytest.mark.asyncio
    async def test_uses_instruction_when_set(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            instruction="Write a summary.",
        )
        result = await t.build_prompt(self.FakeContext(), {})
        assert result == "Write a summary."

    @pytest.mark.asyncio
    async def test_default_no_deps(self):
        t = FlowTransition(source="a", targets={"b"})
        result = await t.build_prompt(self.FakeContext(), {})
        assert result == "Task: do research"

    @pytest.mark.asyncio
    async def test_default_with_deps(self):
        t = FlowTransition(source="a", targets={"b"})
        deps = {"researcher": "some findings"}
        result = await t.build_prompt(self.FakeContext(), deps)
        assert "do research" in result
        assert "researcher" in result
        assert "some findings" in result

    @pytest.mark.asyncio
    async def test_sync_prompt_builder(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            prompt_builder=lambda ctx, deps: f"custom: {ctx.original_query}",
        )
        result = await t.build_prompt(self.FakeContext(), {})
        assert result == "custom: do research"

    @pytest.mark.asyncio
    async def test_async_prompt_builder(self):
        async def builder(ctx, deps):
            return f"async: {ctx.original_query}"

        t = FlowTransition(source="a", targets={"b"}, prompt_builder=builder)
        result = await t.build_prompt(self.FakeContext(), {})
        assert result == "async: do research"

    @pytest.mark.asyncio
    async def test_prompt_builder_takes_priority_over_instruction(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            instruction="fallback",
            prompt_builder=lambda ctx, deps: "from builder",
        )
        result = await t.build_prompt(self.FakeContext(), {})
        assert result == "from builder"


class TestTransitionFields:
    def test_default_condition_is_on_success(self):
        t = FlowTransition(source="a", targets={"b"})
        assert t.condition == TransitionCondition.ON_SUCCESS

    def test_default_priority_is_zero(self):
        t = FlowTransition(source="a", targets={"b"})
        assert t.priority == 0

    def test_metadata_field_accepts_node_execution_info(self):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1", status="completed")
        t = FlowTransition(source="a", targets={"b"}, metadata=info)
        assert t.metadata is info
        assert isinstance(t.metadata, NodeExecutionInfo)

    def test_targets_is_set(self):
        t = FlowTransition(source="a", targets={"b", "c"})
        assert "b" in t.targets
        assert "c" in t.targets
