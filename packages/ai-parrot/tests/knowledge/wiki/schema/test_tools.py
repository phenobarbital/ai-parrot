"""Tests for schema-plane tools and toolkit."""

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.schema.toolkit import SchemaPlaneToolkit
from parrot.knowledge.wiki.schema.tools import create_schema_tools


async def test_schema_tools_round_trip(plane_dir, sales_metadata):
    """All four tools should operate over an in-memory schema plane."""
    service = SchemaPlaneService.from_dir(plane_dir, config=SchemaPlaneConfig(), read_only=False)
    await service.put_table("bigquery", "bigquery", sales_metadata)

    tools = {tool.name: tool for tool in create_schema_tools(service.store, None, WikiProjectConfig(), service=service)}
    assert set(tools) == {
        "wiki_schema_lookup",
        "wiki_schema_search",
        "wiki_schema_neighbors",
        "wiki_schema_sources",
    }

    result = await tools["wiki_schema_lookup"]._execute(ref="bigquery:epson.sales")
    assert result.success
    assert result.result["page_id"] == "table:bigquery/epson.sales"
    assert "## DDL" in result.result["text"]
    assert "| Column | Type | Nullable |" in result.result["text"]


async def test_ambiguous_lookup_returns_candidates(plane_dir, sales_metadata):
    """A schema-only reference must not guess between matching origins."""
    service = SchemaPlaneService.from_dir(
        plane_dir,
        config=SchemaPlaneConfig(
            sources={
                "bigquery": {
                    "alias": "bigquery",
                    "dialect": "bigquery",
                    "dsn_env": "BQ_DSN",
                    "allowed_schemas": ["epson"],
                },
                "warehouse": {
                    "alias": "warehouse",
                    "dialect": "postgres",
                    "dsn_env": "WAREHOUSE_DSN",
                    "allowed_schemas": ["epson"],
                },
            }
        ),
        read_only=False,
    )
    await service.put_table("bigquery", "bigquery", sales_metadata)

    tool = create_schema_tools(service.store, None, WikiProjectConfig(), service=service)[0]
    result = await tool._execute(ref="epson.sales")
    assert result.status == "ambiguous"
    assert result.result == {
        "candidates": [
            "table:bigquery/epson.sales",
            "table:warehouse/epson.sales",
        ]
    }


def test_no_plane_no_tools():
    """No service means the schema tools are not exposed."""
    assert create_schema_tools(None, None, WikiProjectConfig(), service=None) == []


async def test_schema_toolkit_exposes_four_tools(plane_dir):
    """The agent toolkit should expose all four prefixed operations."""
    service = SchemaPlaneService.from_dir(plane_dir, config=SchemaPlaneConfig(), read_only=False)
    toolkit = SchemaPlaneToolkit(service)
    assert {tool.name for tool in toolkit.get_tools()} == {
        "schema_lookup",
        "schema_search",
        "schema_neighbors",
        "schema_sources",
    }
