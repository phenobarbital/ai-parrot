"""
Unit tests for crew definition models relocated to parrot.models.crew_definition.

Verifies that:
- The models are importable from the new canonical location.
- Backward-compat imports from parrot.handlers.crew.models still work.
- Model semantics (defaults, round-trip, etc.) are correct.
"""
from parrot.models.crew_definition import (
    ExecutionMode,
    AgentDefinition,
    ToolNodeDefinition,
    FlowRelation,
    CrewDefinition,
)


class TestModelRelocation:
    """Test that the relocated models behave correctly."""

    def test_execution_mode_values(self):
        """ExecutionMode enum values must match expected strings."""
        assert ExecutionMode.SEQUENTIAL == "sequential"
        assert ExecutionMode.PARALLEL == "parallel"
        assert ExecutionMode.FLOW == "flow"
        assert ExecutionMode.LOOP == "loop"

    def test_agent_definition_defaults(self):
        """AgentDefinition must have sensible defaults."""
        ad = AgentDefinition(agent_id="test-agent")
        assert ad.agent_class == "BaseAgent"
        assert ad.config == {}
        assert ad.tools == []
        assert ad.name is None
        assert ad.system_prompt is None

    def test_crew_definition_roundtrip(self):
        """CrewDefinition must survive a model_dump / re-instantiation round-trip."""
        cd = CrewDefinition(
            name="test-crew",
            agents=[AgentDefinition(agent_id="a1")],
        )
        data = cd.model_dump()
        cd2 = CrewDefinition(**data)
        assert cd2.name == "test-crew"
        assert cd2.crew_id == cd.crew_id

    def test_backward_compat_import(self):
        """parrot.handlers.crew.models still re-exports CrewDefinition."""
        from parrot.handlers.crew.models import CrewDefinition as CD
        assert CD is CrewDefinition

    def test_backward_compat_execution_mode(self):
        """parrot.handlers.crew.models still re-exports ExecutionMode."""
        from parrot.handlers.crew.models import ExecutionMode as EM
        assert EM is ExecutionMode

    def test_parrot_models_init_exports(self):
        """parrot.models package must export the definition models."""
        from parrot.models import CrewDefinition as CD, ExecutionMode as EM
        assert CD is CrewDefinition
        assert EM is ExecutionMode

    def test_crew_definition_defaults(self):
        """CrewDefinition must use SEQUENTIAL as default execution_mode."""
        cd = CrewDefinition(
            name="minimal",
            agents=[AgentDefinition(agent_id="x")],
        )
        assert cd.execution_mode == ExecutionMode.SEQUENTIAL
        assert cd.shared_tools == []
        assert cd.flow_relations == []
        assert cd.max_parallel_tasks == 10
        assert cd.tenant == "global"
        # FEAT: deterministic tool nodes default to empty (backward compat)
        assert cd.tool_nodes == []


class TestToolNodeDefinition:
    """Test the deterministic ToolNodeDefinition model."""

    def test_defaults(self):
        """ToolNodeDefinition must have sensible defaults."""
        tn = ToolNodeDefinition(node_id="fetch", tool="yfinance")
        assert tn.node_id == "fetch"
        assert tn.tool == "yfinance"
        assert tn.name is None
        assert tn.description is None
        assert tn.args == []
        assert tn.kwargs == {}

    def test_roundtrip_preserves_placeholders(self):
        """Template placeholders survive a dump/reload round-trip verbatim."""
        tn = ToolNodeDefinition(
            node_id="fetch",
            tool="yfinance",
            args=["{input}"],
            kwargs={"symbol": "{nodes.researcher.output}", "period": "1mo"},
        )
        tn2 = ToolNodeDefinition(**tn.model_dump())
        assert tn2.args == ["{input}"]
        assert tn2.kwargs["symbol"] == "{nodes.researcher.output}"

    def test_crew_definition_with_tool_nodes_roundtrip(self):
        """CrewDefinition carrying tool_nodes must round-trip."""
        cd = CrewDefinition(
            name="crew-with-tools",
            agents=[AgentDefinition(agent_id="a1")],
            tool_nodes=[ToolNodeDefinition(node_id="fetch", tool="yfinance")],
        )
        cd2 = CrewDefinition(**cd.model_dump())
        assert len(cd2.tool_nodes) == 1
        assert cd2.tool_nodes[0].node_id == "fetch"

    def test_backward_compat_reexport(self):
        """parrot.handlers.crew.models re-exports ToolNodeDefinition."""
        from parrot.handlers.crew.models import ToolNodeDefinition as TND
        assert TND is ToolNodeDefinition

    def test_parrot_models_init_export(self):
        """parrot.models package must export ToolNodeDefinition."""
        from parrot.models import ToolNodeDefinition as TND
        assert TND is ToolNodeDefinition


class TestFlowRelation:
    """Test FlowRelation model."""

    def test_single_source_target(self):
        """FlowRelation with string source/target."""
        fr = FlowRelation(source="agent-a", target="agent-b")
        assert fr.source == "agent-a"
        assert fr.target == "agent-b"

    def test_list_source_target(self):
        """FlowRelation with list source/target."""
        fr = FlowRelation(source=["a", "b"], target=["c"])
        assert isinstance(fr.source, list)
        assert isinstance(fr.target, list)
        assert "a" in fr.source
