"""Unit tests for domain-specific layers."""
import pytest
from parrot.bots.prompts.domain_layers import (
    DATAFRAME_CONTEXT_LAYER,
    SQL_DIALECT_LAYER,
    COMPANY_CONTEXT_LAYER,
    CREW_CONTEXT_LAYER,
    STRICT_GROUNDING_LAYER,
    get_domain_layer,
)
from parrot.bots.prompts.layers import LayerPriority, RenderPhase


class TestDataframeContextLayer:

    def test_renders_when_schemas_present(self):
        result = DATAFRAME_CONTEXT_LAYER.render({"dataframe_schemas": "col1: int, col2: str"})
        assert "<dataframe_context>" in result
        assert "col1: int" in result

    def test_skipped_when_empty(self):
        assert DATAFRAME_CONTEXT_LAYER.render({"dataframe_schemas": ""}) is None

    def test_skipped_when_missing(self):
        assert DATAFRAME_CONTEXT_LAYER.render({}) is None

    def test_priority_after_knowledge(self):
        assert DATAFRAME_CONTEXT_LAYER.priority > LayerPriority.KNOWLEDGE
        assert DATAFRAME_CONTEXT_LAYER.priority < LayerPriority.USER_SESSION

    def test_phase_is_request(self):
        assert DATAFRAME_CONTEXT_LAYER.phase == RenderPhase.REQUEST


class TestSqlDialectLayer:

    def test_renders_with_dialect(self):
        ctx = {"dialect": "PostgreSQL", "top_k": "10"}
        result = SQL_DIALECT_LAYER.render(ctx)
        assert "<sql_policy>" in result
        assert "PostgreSQL" in result
        assert "10" in result

    def test_skipped_when_no_dialect(self):
        assert SQL_DIALECT_LAYER.render({"dialect": ""}) is None
        assert SQL_DIALECT_LAYER.render({}) is None

    def test_priority_after_tools(self):
        assert SQL_DIALECT_LAYER.priority > LayerPriority.TOOLS
        assert SQL_DIALECT_LAYER.priority < LayerPriority.OUTPUT

    def test_phase_is_configure(self):
        assert SQL_DIALECT_LAYER.phase == RenderPhase.CONFIGURE


class TestCompanyContextLayer:

    def test_renders_when_present(self):
        result = COMPANY_CONTEXT_LAYER.render({"company_information": "Acme Corp"})
        assert "<company_information>" in result
        assert "Acme Corp" in result

    def test_skipped_when_empty(self):
        assert COMPANY_CONTEXT_LAYER.render({"company_information": ""}) is None

    def test_skipped_when_missing(self):
        assert COMPANY_CONTEXT_LAYER.render({}) is None

    def test_priority_after_dataframe(self):
        assert COMPANY_CONTEXT_LAYER.priority > DATAFRAME_CONTEXT_LAYER.priority

    def test_phase_is_configure(self):
        assert COMPANY_CONTEXT_LAYER.phase == RenderPhase.CONFIGURE


class TestCrewContextLayer:

    def test_renders_when_present(self):
        result = CREW_CONTEXT_LAYER.render({"crew_context": "Agent 1 found: X"})
        assert "<prior_agent_results>" in result
        assert "Agent 1 found" in result

    def test_skipped_when_empty(self):
        assert CREW_CONTEXT_LAYER.render({"crew_context": ""}) is None

    def test_skipped_when_missing(self):
        assert CREW_CONTEXT_LAYER.render({}) is None

    def test_priority_after_company(self):
        assert CREW_CONTEXT_LAYER.priority > COMPANY_CONTEXT_LAYER.priority

    def test_phase_is_request(self):
        assert CREW_CONTEXT_LAYER.phase == RenderPhase.REQUEST


class TestStrictGroundingLayer:

    def test_renders_always(self):
        result = STRICT_GROUNDING_LAYER.render({})
        assert "<grounding_policy>" in result
        assert "Data not available" in result

    def test_no_condition(self):
        assert STRICT_GROUNDING_LAYER.condition is None

    def test_priority_before_behavior(self):
        assert STRICT_GROUNDING_LAYER.priority < LayerPriority.BEHAVIOR

    def test_priority_after_output(self):
        assert STRICT_GROUNDING_LAYER.priority > LayerPriority.OUTPUT

    def test_phase_is_configure(self):
        assert STRICT_GROUNDING_LAYER.phase == RenderPhase.CONFIGURE


class TestGetDomainLayer:

    def test_lookup_dataframe_context(self):
        layer = get_domain_layer("dataframe_context")
        assert layer is DATAFRAME_CONTEXT_LAYER

    def test_lookup_sql_dialect(self):
        assert get_domain_layer("sql_dialect") is SQL_DIALECT_LAYER

    def test_lookup_company_context(self):
        assert get_domain_layer("company_context") is COMPANY_CONTEXT_LAYER

    def test_lookup_crew_context(self):
        assert get_domain_layer("crew_context") is CREW_CONTEXT_LAYER

    def test_lookup_strict_grounding(self):
        assert get_domain_layer("strict_grounding") is STRICT_GROUNDING_LAYER

    def test_unknown_raises_keyerror(self):
        with pytest.raises(KeyError, match="Unknown domain layer"):
            get_domain_layer("nonexistent")

    def test_error_lists_available(self):
        with pytest.raises(KeyError, match="dataframe_context"):
            get_domain_layer("nonexistent")


class TestPriorityOrdering:

    def test_all_domain_layers_between_builtins(self):
        """Domain layers should fit between built-in layer priority slots."""
        # Knowledge sub-layers: dataframe (35) < company (40) < crew (45)
        assert LayerPriority.KNOWLEDGE < DATAFRAME_CONTEXT_LAYER.priority
        assert DATAFRAME_CONTEXT_LAYER.priority < COMPANY_CONTEXT_LAYER.priority
        assert COMPANY_CONTEXT_LAYER.priority < CREW_CONTEXT_LAYER.priority
        # SQL dialect sits between TOOLS and OUTPUT
        assert LayerPriority.TOOLS < SQL_DIALECT_LAYER.priority < LayerPriority.OUTPUT
        # Strict grounding sits between OUTPUT and BEHAVIOR
        assert LayerPriority.OUTPUT < STRICT_GROUNDING_LAYER.priority < LayerPriority.BEHAVIOR
