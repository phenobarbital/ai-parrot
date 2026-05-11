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
