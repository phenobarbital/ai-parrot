import pytest
from parrot.bots.database.prompts import (
    DATABASE_CONTEXT_LAYER,
    DATABASE_SAFETY_LAYER,
    SCHEMA_GROUNDING_LAYER,
    DATABASE_INSTRUCTIONS_LAYER,
    _build_database_prompt_builder,
)


def test_database_prompt_builder_factory_assembles_layers():
    """The factory returns a PromptBuilder containing all four DB layers."""
    builder = _build_database_prompt_builder()
    names = set(builder.layer_names)
    expected = {
        "database_context",
        "database_safety",
        "schema_grounding",
        "database_instructions",
    }
    assert expected.issubset(names)


def test_database_prompt_layers_render_with_minimal_context():
    """builder.configure(...) + builder.build(...) does not raise."""
    builder = _build_database_prompt_builder()
    static_ctx = {
        "agent_name": "DatabaseAgent",
        "agent_role": "Database analyst",
    }
    dynamic_ctx = {
        "query": "SELECT 1",
        "database": "postgres",
        "intent": "explore_schema",
        "output_components": "QUERY",
        "schema_summary": "public.users(id, name)",
    }
    builder.configure(static_ctx)
    rendered = builder.build(dynamic_ctx)
    assert rendered  # smoke: non-empty string


def test_no_legacy_placeholder_constants_remain():
    """The five legacy constants are deleted."""
    import parrot.bots.database.prompts as prompts_mod
    for legacy in (
        "DB_AGENT_PROMPT",
        "BASIC_HUMAN_PROMPT",
        "DATA_ANALYSIS_PROMPT",
        "DATABASE_EDUCATION_PROMPT",
        "DATABASE_TROUBLESHOOTING_PROMPT",
    ):
        assert not hasattr(prompts_mod, legacy), f"{legacy} should be deleted"
