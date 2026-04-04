"""Unit tests for DatabaseAgent."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

# Now load the agent module from worktree
import importlib, importlib.util, types  # noqa: E402
_HERE = os.path.dirname(os.path.abspath(__file__))
_WT_SRC = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir, "packages", "ai-parrot", "src"))
_agent_file = os.path.join(_WT_SRC, "parrot", "bots", "database", "agent.py")
if os.path.isfile(_agent_file):
    _spec = importlib.util.spec_from_file_location("parrot.bots.database.agent", _agent_file)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["parrot.bots.database.agent"] = _mod
    _spec.loader.exec_module(_mod)
    DatabaseAgent = _mod.DatabaseAgent
else:
    from parrot.bots.database.agent import DatabaseAgent  # type: ignore

import pytest  # noqa: E402
from parrot.models import AIMessage  # noqa: E402
from parrot.bots.database.models import UserRole, OutputComponent, QueryExecutionResponse  # noqa: E402
from parrot.bots.database.toolkits.base import DatabaseToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# Mock toolkit
# ---------------------------------------------------------------------------

class MockToolkit(DatabaseToolkit):
    """Minimal concrete toolkit for agent testing."""

    def __init__(self, db_type: str = "postgresql", schemas=None):
        super().__init__(
            dsn=f"{db_type}://test:test@localhost/test",
            allowed_schemas=schemas or ["public"],
            primary_schema=(schemas or ["public"])[0],
            database_type=db_type,
        )
        self._started = False

    async def start(self):
        self._started = True

    async def stop(self):
        self._started = False

    async def search_schema(self, search_term, schema_name=None, limit=10):
        """Search schema (mock)."""
        return []

    async def execute_query(self, query, limit=1000, timeout=30):
        """Execute query (mock)."""
        return QueryExecutionResponse(
            success=True, row_count=0, execution_time_ms=1.0,
            schema_used=self.primary_schema,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDatabaseAgentInit:
    def test_default_role(self):
        agent = DatabaseAgent(
            toolkits=[MockToolkit()],
            default_user_role=UserRole.DATABASE_ADMIN,
        )
        assert agent.default_user_role == UserRole.DATABASE_ADMIN

    def test_single_toolkit(self):
        agent = DatabaseAgent(toolkits=[MockToolkit()])
        assert len(agent.toolkits) == 1

    def test_multi_toolkit(self):
        agent = DatabaseAgent(toolkits=[
            MockToolkit("postgresql", ["public"]),
            MockToolkit("bigquery", ["analytics"]),
        ])
        assert len(agent.toolkits) == 2

    def test_no_toolkits(self):
        agent = DatabaseAgent(toolkits=[])
        assert len(agent.toolkits) == 0


class TestDatabaseAgentConfigure:
    @pytest.mark.asyncio
    async def test_configure_starts_toolkits(self):
        tk = MockToolkit()
        agent = DatabaseAgent(toolkits=[tk])
        await agent.configure()
        assert tk._started is True

    @pytest.mark.asyncio
    async def test_configure_creates_cache_partitions(self):
        tk = MockToolkit()
        agent = DatabaseAgent(toolkits=[tk])
        await agent.configure()
        assert tk.cache_partition is not None

    @pytest.mark.asyncio
    async def test_configure_creates_router(self):
        agent = DatabaseAgent(toolkits=[MockToolkit()])
        await agent.configure()
        assert agent.query_router is not None

    @pytest.mark.asyncio
    async def test_configure_registers_databases(self):
        agent = DatabaseAgent(toolkits=[
            MockToolkit("postgresql", ["public"]),
            MockToolkit("bigquery", ["analytics"]),
        ])
        await agent.configure()
        assert len(agent.query_router.registered_databases) >= 2


class TestDatabaseAgentAsk:
    @pytest.mark.asyncio
    async def test_ask_not_configured(self):
        agent = DatabaseAgent(toolkits=[MockToolkit()])
        result = await agent.ask("show me orders")
        assert "not configured" in result.content.lower()

    @pytest.mark.asyncio
    async def test_ask_returns_ai_message(self):
        agent = DatabaseAgent(toolkits=[MockToolkit()])
        await agent.configure()
        result = await agent.ask("show me all orders")
        assert isinstance(result, AIMessage)
        assert isinstance(result.content, str)

    @pytest.mark.asyncio
    async def test_ask_with_explicit_role(self):
        agent = DatabaseAgent(
            toolkits=[MockToolkit()],
            default_user_role=UserRole.DATA_ANALYST,
        )
        await agent.configure()
        # Explicit role should be used
        result = await agent.ask(
            "show me orders", user_role=UserRole.BUSINESS_USER
        )
        assert result is not None


class TestDatabaseAgentToolkitSelection:
    @pytest.mark.asyncio
    async def test_selects_first_toolkit_by_default(self):
        agent = DatabaseAgent(toolkits=[
            MockToolkit("postgresql", ["public"]),
            MockToolkit("bigquery", ["analytics"]),
        ])
        await agent.configure()
        tk = agent._select_toolkit(None)
        assert tk.database_type == "postgresql"

    @pytest.mark.asyncio
    async def test_selects_toolkit_by_id(self):
        agent = DatabaseAgent(toolkits=[
            MockToolkit("postgresql", ["public"]),
            MockToolkit("bigquery", ["analytics"]),
        ])
        await agent.configure()
        # Find the bigquery toolkit id
        bq_id = None
        for tk_id, tk in agent._toolkit_map.items():
            if tk.database_type == "bigquery":
                bq_id = tk_id
                break
        assert bq_id is not None
        selected = agent._select_toolkit(bq_id)
        assert selected.database_type == "bigquery"


class TestDatabaseAgentCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_stops_toolkits(self):
        tk = MockToolkit()
        agent = DatabaseAgent(toolkits=[tk])
        await agent.configure()
        assert tk._started is True
        await agent.cleanup()
        assert tk._started is False
