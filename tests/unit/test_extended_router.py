"""Unit tests for Extended SchemaQueryRouter."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from parrot.bots.database.router import SchemaQueryRouter, INTENT_ROLE_MAPPING  # noqa: E402
from parrot.bots.database.models import UserRole, QueryIntent  # noqa: E402


@pytest.fixture
def router():
    r = SchemaQueryRouter(primary_schema="public", allowed_schemas=["public", "sales"])
    r.register_database("bigquery", "bq_toolkit")
    r.register_database("postgres", "pg_toolkit")
    r.register_database("influx", "influx_toolkit")
    return r


class TestRoleInference:
    @pytest.mark.asyncio
    async def test_analyze_data_infers_scientist(self, router):
        # "analyze" triggers ANALYZE_DATA intent → DATA_SCIENTIST
        decision = await router.route("analyze trends in this data")
        assert decision.user_role == UserRole.DATA_SCIENTIST
        assert decision.role_source == "inferred"

    @pytest.mark.asyncio
    async def test_show_data_infers_business(self, router):
        decision = await router.route("show me all orders")
        assert decision.user_role == UserRole.BUSINESS_USER
        assert decision.role_source == "inferred"

    @pytest.mark.asyncio
    async def test_explicit_role_beats_inferred(self, router):
        decision = await router.route(
            "optimize this query", user_role=UserRole.DATA_ANALYST
        )
        assert decision.user_role == UserRole.DATA_ANALYST
        assert decision.role_source == "explicit"

    @pytest.mark.asyncio
    async def test_default_role_when_no_match(self, router):
        # A query that doesn't strongly match any intent pattern falls to default
        decision = await router.route("hello world")
        assert decision.role_source in ("inferred", "default")


class TestDatabaseSelection:
    @pytest.mark.asyncio
    async def test_bigquery_detected(self, router):
        decision = await router.route("query the bigquery analytics table")
        assert decision.target_database == "bq_toolkit"

    @pytest.mark.asyncio
    async def test_postgres_detected(self, router):
        decision = await router.route("check the postgres users table")
        assert decision.target_database == "pg_toolkit"

    @pytest.mark.asyncio
    async def test_explicit_database_beats_detected(self, router):
        decision = await router.route(
            "query the bigquery table", database="pg_toolkit"
        )
        assert decision.target_database == "pg_toolkit"

    @pytest.mark.asyncio
    async def test_no_database_detected(self, router):
        decision = await router.route("show me all orders")
        assert decision.target_database is None


class TestIntentRoleMapping:
    def test_mapping_exists(self):
        assert QueryIntent.OPTIMIZE_QUERY in INTENT_ROLE_MAPPING
        assert QueryIntent.SHOW_DATA in INTENT_ROLE_MAPPING
        assert INTENT_ROLE_MAPPING[QueryIntent.OPTIMIZE_QUERY] == UserRole.DATABASE_ADMIN
