"""Unit tests for BigQuery, InfluxDB, Elasticsearch, and DocumentDB toolkits."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from parrot.bots.database.toolkits.bigquery import BigQueryToolkit  # noqa: E402
from parrot.bots.database.toolkits.influx import InfluxDBToolkit  # noqa: E402
from parrot.bots.database.toolkits.elastic import ElasticToolkit  # noqa: E402
from parrot.bots.database.toolkits.documentdb import DocumentDBToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------

class TestBigQueryToolkit:
    def test_explain_prefix(self):
        tk = BigQueryToolkit(project_id="my-project")
        assert "DRY RUN" in tk._get_explain_prefix()

    def test_asyncdb_driver(self):
        tk = BigQueryToolkit(project_id="my-project")
        assert tk._get_asyncdb_driver() == "bigquery"

    def test_database_type(self):
        tk = BigQueryToolkit(project_id="my-project")
        assert tk.database_type == "bigquery"

    def test_tool_methods(self):
        tk = BigQueryToolkit(project_id="my-project")
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_schema" in tool_names
        assert "execute_query" in tool_names

    def test_no_primary_keys(self):
        tk = BigQueryToolkit(project_id="my-project")
        sql, _ = tk._get_primary_keys_query("dataset", "table")
        assert "FALSE" in sql  # returns empty


# ---------------------------------------------------------------------------
# InfluxDB
# ---------------------------------------------------------------------------

class TestInfluxDBToolkit:
    def test_asyncdb_driver(self):
        tk = InfluxDBToolkit(dsn="influxdb://test")
        assert tk._get_asyncdb_driver() == "influx"

    def test_database_type(self):
        tk = InfluxDBToolkit(dsn="influxdb://test")
        assert tk.database_type == "influxdb"

    def test_tool_methods(self):
        tk = InfluxDBToolkit(dsn="influxdb://test")
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_schema" in tool_names
        assert "execute_query" in tool_names
        assert "search_measurements" in tool_names
        assert "generate_flux_query" in tool_names
        assert "execute_flux_query" in tool_names
        assert "explore_buckets" in tool_names

    def test_exclude_tools(self):
        tk = InfluxDBToolkit(dsn="influxdb://test")
        tool_names = [t.name for t in tk.get_tools()]
        assert "start" not in tool_names
        assert "stop" not in tool_names

    @pytest.mark.asyncio
    async def test_generate_flux_query(self):
        tk = InfluxDBToolkit(dsn="influxdb://test", allowed_schemas=["metrics"])
        result = await tk.generate_flux_query("CPU usage last hour", bucket="metrics")
        assert "metrics" in result
        assert "CPU" in result


# ---------------------------------------------------------------------------
# Elasticsearch
# ---------------------------------------------------------------------------

class TestElasticToolkit:
    def test_asyncdb_driver(self):
        tk = ElasticToolkit(dsn="http://localhost:9200")
        assert tk._get_asyncdb_driver() == "elasticsearch"

    def test_database_type(self):
        tk = ElasticToolkit(dsn="http://localhost:9200")
        assert tk.database_type == "elasticsearch"

    def test_tool_methods(self):
        tk = ElasticToolkit(dsn="http://localhost:9200")
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_schema" in tool_names
        assert "execute_query" in tool_names
        assert "search_indices" in tool_names
        assert "generate_dsl_query" in tool_names
        assert "run_aggregation" in tool_names

    @pytest.mark.asyncio
    async def test_execute_invalid_json(self):
        tk = ElasticToolkit(dsn="http://localhost:9200")
        result = await tk.execute_query("not json")
        assert not result.success
        assert "Invalid JSON" in result.error_message


# ---------------------------------------------------------------------------
# DocumentDB
# ---------------------------------------------------------------------------

class TestDocumentDBToolkit:
    def test_asyncdb_driver(self):
        tk = DocumentDBToolkit(dsn="mongodb://test")
        assert tk._get_asyncdb_driver() == "motor"

    def test_database_type(self):
        tk = DocumentDBToolkit(dsn="mongodb://test")
        assert tk.database_type == "documentdb"

    def test_tool_methods(self):
        tk = DocumentDBToolkit(dsn="mongodb://test")
        tool_names = [t.name for t in tk.get_tools()]
        assert "search_schema" in tool_names
        assert "execute_query" in tool_names
        assert "search_collections" in tool_names
        assert "generate_mql_query" in tool_names
        assert "explore_collection" in tool_names

    @pytest.mark.asyncio
    async def test_generate_mql_query(self):
        tk = DocumentDBToolkit(dsn="mongodb://test", database_name="mydb")
        result = await tk.generate_mql_query("find all users", collection="users")
        assert "users" in result
        assert "mydb" in result
