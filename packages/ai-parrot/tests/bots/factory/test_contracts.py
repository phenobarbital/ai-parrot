"""Unit tests for parrot.bots.factory.contracts."""
import pytest

from parrot.bots.factory.contracts import (
    AgentDefinition,
    BuilderOutput,
    BuilderType,
    FactoryRequest,
    FactoryResult,
    FactoryStatus,
    HITLCheckpoint,
    ProvisioningRecord,
    RouterDecision,
)
from parrot.registry.registry import BotConfig


class TestAgentDefinition:
    def test_alias_points_at_bot_config(self):
        assert AgentDefinition is BotConfig


class TestBuilderType:
    def test_three_members(self):
        assert {b.value for b in BuilderType} == {"rag", "tool_agent", "clone"}


class TestHITLCheckpoint:
    def test_two_members(self):
        assert {c.value for c in HITLCheckpoint} == {
            "pre_delegation",
            "pre_finalize",
        }


class TestFactoryStatus:
    def test_four_members(self):
        assert {s.value for s in FactoryStatus} == {
            "success",
            "cancelled_by_user",
            "timeout",
            "failed",
        }


class TestFactoryRequest:
    def test_minimal_request_is_valid(self):
        req = FactoryRequest(description="Build a Jira agent.")
        assert req.description == "Build a Jira agent."
        assert req.clone_from is None
        assert req.hints == {}

    def test_empty_description_rejected(self):
        with pytest.raises(ValueError):
            FactoryRequest(description="")

    def test_clone_from_carries_through(self):
        req = FactoryRequest(description="Variant", clone_from="ATTBot")
        assert req.clone_from == "ATTBot"


class TestRouterDecision:
    def test_basic_decision_round_trip(self):
        decision = RouterDecision(
            builder=BuilderType.RAG,
            reasoning="User asked for a knowledge base.",
        )
        assert decision.builder == BuilderType.RAG
        assert decision.detected_integrations == []

    def test_serialises_via_model_dump(self):
        decision = RouterDecision(
            builder=BuilderType.TOOL_AGENT,
            reasoning="LinkedIn integration requested",
            detected_integrations=["linkedin"],
        )
        dumped = decision.model_dump()
        assert dumped["builder"] == "tool_agent"
        assert dumped["detected_integrations"] == ["linkedin"]


class TestBuilderOutput:
    def test_wraps_an_agent_definition(self):
        defn = BotConfig(
            name="Demo",
            class_name="BasicAgent",
            module="parrot.bots.agent",
        )
        output = BuilderOutput(builder=BuilderType.RAG, definition=defn)
        assert output.builder == BuilderType.RAG
        assert output.definition.name == "Demo"
        assert output.provisioning == []


class TestProvisioningRecord:
    def test_kind_constrained_to_known_set(self):
        rec = ProvisioningRecord(kind="vector_store", name="rag_demo")
        assert rec.kind == "vector_store"
        with pytest.raises(ValueError):
            ProvisioningRecord(kind="invalid", name="x")


class TestFactoryResult:
    def test_success_carries_definition(self):
        defn = BotConfig(
            name="Demo",
            class_name="BasicAgent",
            module="parrot.bots.agent",
        )
        result = FactoryResult(
            status=FactoryStatus.SUCCESS,
            definition=defn,
            yaml_path="/tmp/demo.yaml",
        )
        assert result.status == FactoryStatus.SUCCESS
        assert result.yaml_path.endswith("demo.yaml")

    def test_cancelled_marks_checkpoint(self):
        result = FactoryResult(
            status=FactoryStatus.CANCELLED_BY_USER,
            cancelled_at=HITLCheckpoint.PRE_DELEGATION,
        )
        assert result.cancelled_at == HITLCheckpoint.PRE_DELEGATION
        assert result.definition is None
