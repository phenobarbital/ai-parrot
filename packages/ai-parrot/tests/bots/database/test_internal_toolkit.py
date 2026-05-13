import inspect
import pytest
from parrot.bots.database.toolkits import DatabaseAgentToolkit


EXPECTED_TOOLS = {
    "format_explain_plan",
    "simplify_column_type",
    "extract_sql_from_response",
    "extract_table_name_from_query",
    "extract_table_names_from_metadata",
    "generate_create_table_statement",
    "generate_optimization_tips",
    "generate_basic_optimization_tips",
    "generate_table_specific_tips",
    "generate_examples",
    "extract_performance_metrics",
    "format_as_text",
    "format_query_history",
    "parse_tips",
    "is_explanatory_response",
    "get_schema_counts_direct",
}


@pytest.fixture
def toolkit():
    return DatabaseAgentToolkit()


def test_all_expected_tools_present(toolkit):
    missing = EXPECTED_TOOLS - {name for name in dir(toolkit) if not name.startswith("_")}
    assert not missing, f"Missing tools: {missing}"


def test_internal_toolkit_tools_have_docstrings(toolkit):
    """Every @tool method carries a non-empty docstring."""
    for tool_name in EXPECTED_TOOLS:
        method = getattr(toolkit, tool_name)
        assert method.__doc__ and method.__doc__.strip(), f"{tool_name} has no docstring"


def test_format_explain_plan_handles_json_string(toolkit):
    """Smoke test for format_explain_plan with a representative EXPLAIN JSON."""
    sample = '[{"Plan": {"Node Type": "Seq Scan", "Relation Name": "users"}}]'
    result = toolkit.format_explain_plan(sample)
    assert isinstance(result, str) and result


def test_simplify_column_type(toolkit):
    """numeric(10,2) -> numeric, varchar(255) -> varchar, compound timestamp."""
    assert toolkit.simplify_column_type("numeric(10,2)") == "numeric"
    assert toolkit.simplify_column_type("varchar(255)") == "varchar"
    assert toolkit.simplify_column_type("timestamp without time zone") == "timestamp"


def test_extract_sql_from_response(toolkit):
    """Pulls SQL out of an LLM markdown response."""
    text = "Here is the query:\n```sql\nSELECT * FROM users\n```\nDone."
    assert "SELECT * FROM users" in toolkit.extract_sql_from_response(text)


@pytest.mark.asyncio
async def test_generate_optimization_tips_signature(toolkit):
    """Async helpers are reachable; smoke-test signature only (no LLM call)."""
    assert inspect.iscoroutinefunction(toolkit.generate_optimization_tips)
