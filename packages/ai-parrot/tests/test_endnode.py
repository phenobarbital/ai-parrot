"""Tests for parrot.bots.flow.nodes.end — EndNode implementation.

TASK-010: EndNode as first-class FSM citizen alongside StartNode.
"""
import pytest

from parrot.bots.flow import EndNode, StartNode


class TestEndNodeConstruction:
    def test_default_name(self):
        node = EndNode()
        assert node.name == "__end__"

    def test_custom_name(self):
        node = EndNode(name="my_end")
        assert node.name == "my_end"

    def test_default_metadata(self):
        node = EndNode()
        assert node.metadata == {}

    def test_custom_metadata(self):
        node = EndNode(metadata={"label": "Final Output"})
        assert node.metadata["label"] == "Final Output"

    def test_is_configured(self):
        node = EndNode()
        assert node.is_configured is True

    def test_has_tool_manager(self):
        node = EndNode()
        assert hasattr(node, "tool_manager")


class TestEndNodeAsk:
    @pytest.mark.asyncio
    async def test_passthrough(self):
        node = EndNode()
        result = await node.ask("Final result text")
        assert result == "Final result text"

    @pytest.mark.asyncio
    async def test_empty_passthrough(self):
        node = EndNode()
        result = await node.ask("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_default_passthrough(self):
        node = EndNode()
        result = await node.ask()
        assert result == ""


class TestEndNodeConfigure:
    @pytest.mark.asyncio
    async def test_configure_noop(self):
        node = EndNode()
        await node.configure()


class TestEndNodeActions:
    @pytest.mark.asyncio
    async def test_pre_post_actions(self):
        node = EndNode()
        called = []

        async def pre_action(name, prompt, **ctx):
            called.append(("pre", name, prompt))

        async def post_action(name, result, **ctx):
            called.append(("post", name, result))

        node.add_pre_action(pre_action)
        node.add_post_action(post_action)

        result = await node.ask("input")
        assert result == "input"
        assert len(called) == 2
        assert called[0][0] == "pre"
        assert called[1][0] == "post"


class TestEndNodeSameInterfaceAsStartNode:
    def test_same_attributes(self):
        end = EndNode(name="end", metadata={"k": "v"})
        start = StartNode(name="start", metadata={"k": "v"})

        assert hasattr(end, "name")
        assert hasattr(end, "metadata")
        assert hasattr(end, "ask")
        assert hasattr(end, "configure")
        assert hasattr(end, "add_pre_action")
        assert hasattr(end, "add_post_action")

        assert hasattr(start, "name")
        assert hasattr(start, "metadata")
        assert hasattr(start, "ask")

    @pytest.mark.asyncio
    async def test_both_passthrough(self):
        end = EndNode()
        start = StartNode()

        end_result = await end.ask("test")
        start_result = await start.ask("test")

        assert end_result == start_result == "test"


class TestEndNodeImports:
    def test_import_from_package(self):
        from parrot.bots.flow import EndNode as EN

        assert EN is EndNode

    def test_import_from_nodes(self):
        from parrot.bots.flow.nodes import EndNode as EN

        assert EN is EndNode
