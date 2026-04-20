"""Test configuration helpers for the parrot codebase."""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
import types
from typing import Any, Dict, List, Optional

# Ensure the project root is importable as ``parrot`` when running tests without
# installing the package.  Several tests import modules directly from the
# source tree, so we add the repository root to ``sys.path`` at collection time.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _install_navconfig_stub() -> None:
    """Provide a lightweight ``navconfig`` implementation for tests."""

    class _Config:
        def get(self, _key: str, fallback=None):  # noqa: D401
            import os
            return os.environ.get(_key, fallback)

        def getint(self, _key: str, fallback: int = 0) -> int:
            import os
            val = os.environ.get(_key)
            return int(val) if val is not None else int(fallback)

        def getboolean(self, _key: str, fallback: bool = False) -> bool:
            import os
            val = os.environ.get(_key)
            if val is None:
                return bool(fallback)
            return val.lower() in ("1", "true", "yes", "on")

    navconfig_module = types.ModuleType("navconfig")
    navconfig_module.config = _Config()
    navconfig_module.BASE_DIR = PROJECT_ROOT

    # Add 'notice' level to standard logging (navconfig extends it)
    NOTICE_LEVEL = 25
    logging.addLevelName(NOTICE_LEVEL, "NOTICE")

    def _notice(self, message, *args, **kwargs):
        if self.isEnabledFor(NOTICE_LEVEL):
            self._log(NOTICE_LEVEL, message, args, **kwargs)

    if not hasattr(logging.Logger, "notice"):
        logging.Logger.notice = _notice

    logging_module = types.ModuleType("navconfig.logging")
    logging_module.logging = logging
    logging_module.Logger = logging.Logger
    navconfig_module.logging = logging_module

    exceptions_module = types.ModuleType("navconfig.exceptions")

    class _ConfigError(Exception):
        pass

    exceptions_module.ConfigError = _ConfigError
    exceptions_module.NavConfigException = _ConfigError

    sys.modules.setdefault("navconfig", navconfig_module)
    sys.modules.setdefault("navconfig.logging", logging_module)
    sys.modules.setdefault("navconfig.exceptions", exceptions_module)


def _install_navigator_stubs() -> None:
    """Install minimal navigator-related modules required during imports."""

    navigator_conf = types.ModuleType("navigator.conf")
    navigator_conf.default_dsn = "postgresql://user:pass@localhost/db"
    navigator_conf.CACHE_HOST = "localhost"
    navigator_conf.CACHE_PORT = 6379
    navigator_module = types.ModuleType("navigator")
    navigator_module.__path__ = []
    sys.modules.setdefault("navigator", navigator_module)
    sys.modules.setdefault("navigator.conf", navigator_conf)
    # navigator.types stub
    navigator_types = types.ModuleType("navigator.types")
    navigator_types.WebApp = type("WebApp", (), {})
    sys.modules.setdefault("navigator.types", navigator_types)

    # navigator.applications stub
    navigator_applications = types.ModuleType("navigator.applications")
    navigator_applications.__path__ = []
    navigator_applications.App = type("App", (), {})
    sys.modules.setdefault("navigator.applications", navigator_applications)
    navigator_applications_base = types.ModuleType("navigator.applications.base")
    navigator_applications_base.BaseApplication = type("BaseApplication", (), {})
    sys.modules.setdefault("navigator.applications.base", navigator_applications_base)

    # navigator.middlewares stub
    navigator_middlewares = types.ModuleType("navigator.middlewares")
    sys.modules.setdefault("navigator.middlewares", navigator_middlewares)

    navigator_auth_module = types.ModuleType("navigator_auth")
    navigator_auth_conf = types.ModuleType("navigator_auth.conf")
    navigator_auth_conf.AUTH_SESSION_OBJECT = None
    navigator_auth_conf.exclude_list = []

    decorators_module = types.ModuleType("navigator_auth.decorators")

    def _user_session(func=None, **__):
        if func is None:
            def wrapper(inner):
                return inner

            return wrapper
        return func

    decorators_module.user_session = _user_session
    decorators_module.is_authenticated = _user_session  # alias for test stubs

    navigator_auth_module.decorators = decorators_module

    sys.modules.setdefault("navigator_auth", navigator_auth_module)
    sys.modules.setdefault("navigator_auth.conf", navigator_auth_conf)
    sys.modules.setdefault("navigator_auth.decorators", decorators_module)

    navigator_views = types.ModuleType("navigator.views")
    base_handler = type("BaseHandler", (), {})
    navigator_views.View = type("View", (), {})
    navigator_views.BaseHandler = base_handler
    navigator_views.ModelView = type("ModelView", (), {})
    navigator_views.BaseView = type("BaseView", (), {
        "query_parameters": staticmethod(lambda req: {}),
        "json_response": lambda self, data, **kw: data,
        "error": lambda self, response, status=400: response,
        "json_data": lambda self: {},
    })
    navigator_views.FormModel = type("FormModel", (), {})

    # AbstractModel stub used by ChatbotHandler
    _abstract_model = type("AbstractModel", (navigator_views.BaseView,), {
        "model": None,
        "get_model": None,
        "on_startup": None,
        "on_shutdown": None,
        "model_kwargs": {},
        "name": "Model",
        "driver": "pg",
        "dsn": None,
        "credentials": None,
        "dbname": "nav.model",
        "pk": None,
        "handler": None,
    })
    navigator_views.AbstractModel = _abstract_model

    # Register navigator.views.abstract submodule
    abstract_module = types.ModuleType("navigator.views.abstract")
    abstract_module.AbstractModel = _abstract_model
    sys.modules.setdefault("navigator.views.abstract", abstract_module)

    sys.modules.setdefault("navigator.views", navigator_views)

    # Ensure navigator.conf has AUTH_SESSION_OBJECT
    navigator_conf.AUTH_SESSION_OBJECT = "user"

    # navigator.connections — required by parrot.scheduler
    navigator_connections = types.ModuleType("navigator.connections")
    navigator_connections.PostgresPool = type("PostgresPool", (), {})
    sys.modules.setdefault("navigator.connections", navigator_connections)

    # asyncdb — required by parrot.scheduler and parrot.scheduler.models
    asyncdb_module = types.ModuleType("asyncdb")
    asyncdb_module.AsyncDB = type("AsyncDB", (), {})
    asyncdb_module.AsyncPool = type("AsyncPool", (), {})
    asyncdb_module.__path__ = []  # make Python treat it as a package
    sys.modules.setdefault("asyncdb", asyncdb_module)

    asyncdb_exceptions = types.ModuleType("asyncdb.exceptions")
    asyncdb_exceptions.__path__ = []  # treat as package to allow sub-imports
    for _exc_name in [
        "NoDataFound", "ProviderError", "DriverError", "UninitializedError",
        "ValidationError", "ConnectionMissing", "ConnectionTimeout", "DataError",
        "DriverError", "EmptyStatement", "ModelError", "NotSupported",
        "StatementError", "TooManyConnections", "UnknownPropertyError",
    ]:
        setattr(asyncdb_exceptions, _exc_name, type(_exc_name, (Exception,), {}))
    # sub-module aliases so "from asyncdb.exceptions.exceptions import X" works
    asyncdb_exc_exc = types.ModuleType("asyncdb.exceptions.exceptions")
    asyncdb_exc_exc.__dict__.update({
        k: v for k, v in asyncdb_exceptions.__dict__.items()
        if isinstance(v, type) and issubclass(v, Exception)
    })
    sys.modules.setdefault("asyncdb.exceptions", asyncdb_exceptions)
    sys.modules.setdefault("asyncdb.exceptions.exceptions", asyncdb_exc_exc)

    asyncdb_models = types.ModuleType("asyncdb.models")
    asyncdb_models.Model = type("Model", (), {})
    asyncdb_models.Field = lambda *a, **kw: None
    sys.modules.setdefault("asyncdb.models", asyncdb_models)

    # querysource.conf — required by parrot.scheduler
    querysource_module = types.ModuleType("querysource")
    querysource_conf = types.ModuleType("querysource.conf")
    querysource_conf.default_dsn = "postgresql://user:pass@localhost/db"
    sys.modules.setdefault("querysource", querysource_module)
    sys.modules.setdefault("querysource.conf", querysource_conf)

    # parrot.notifications — required by parrot.scheduler
    parrot_notifications = types.ModuleType("parrot.notifications")
    parrot_notifications.NotificationMixin = type("NotificationMixin", (), {})
    sys.modules.setdefault("parrot.notifications", parrot_notifications)

    # parrot.conf — required by parrot.scheduler, parrot.memory, parrot.plugins, parrot.tools
    # Use a module subclass that auto-provides any missing attribute as a Path/str default
    # so that deep import chains don't fail on unknown constants.
    class _ParrotConf(types.ModuleType):
        ENVIRONMENT = "test"
        REDIS_HISTORY_URL = "redis://localhost:6379/0"
        PLUGINS_DIR = PROJECT_ROOT / "plugins"
        AGENTS_DIR = PROJECT_ROOT / "agents"
        STATIC_DIR = PROJECT_ROOT / "static"
        BASE_STATIC_URL = "/static"
        PROJECT_ROOT = PROJECT_ROOT

        def __getattr__(self, name: str):
            # Return a sensible default for any other constant
            return None

    parrot_conf = _ParrotConf("parrot.conf")
    sys.modules.setdefault("parrot.conf", parrot_conf)

    # parrot.plugins — required by parrot.tools.__init__
    parrot_plugins = types.ModuleType("parrot.plugins")
    parrot_plugins.setup_plugin_importer = lambda *a, **kw: None
    parrot_plugins.dynamic_import_helper = lambda *a, **kw: None
    sys.modules.setdefault("parrot.plugins", parrot_plugins)


def _install_parrot_stubs() -> None:
    """Install lightweight stand-ins for heavy parrot dependencies."""

    # Stub ToolManager used by AgentCrew during initialisation
    class _ToolManager:
        def __init__(self, *_, **__):
            self._tools: Dict[str, Any] = {}

        def add_tool(self, tool: Any, tool_name: Optional[str] = None) -> None:
            name = tool_name or getattr(tool, "name", str(tool))
            self._tools[name] = tool

        def register_tools(self, tools: List[Any]) -> None:
            for tool in tools:
                self.add_tool(tool)

        def get_tool(self, name: Optional[str]) -> Any:
            return self._tools.get(name or "")

        def list_tools(self) -> List[str]:
            return list(self._tools.keys())

        def tool_count(self) -> int:
            return len(self._tools)

        def get_tool_schemas(self, provider_format=None) -> List[Dict[str, Any]]:
            return []

        def all_tools(self) -> List[Any]:
            return list(self._tools.values())




    # Basic AbstractBot / BasicAgent definitions
    class _AbstractBot:
        def __init__(self, name: str = "Agent", **_):
            self.name = name
            self.tool_manager = _ToolManager()
            self.use_llm = None
            self.llm = None
            self._llm = None

    bots_abstract_module = types.ModuleType("parrot.bots.abstract")
    bots_abstract_module.AbstractBot = _AbstractBot
    bots_abstract_module.OutputMode = type("OutputMode", (), {})
    sys.modules.setdefault("parrot.bots.abstract", bots_abstract_module)

    class _BasicAgent(_AbstractBot):
        async def configure(self):
            self.is_configured = True

        def agent_tools(self):
            return []

    bots_agent_module = types.ModuleType("parrot.bots.agent")
    bots_agent_module.BasicAgent = _BasicAgent
    bots_agent_module.Agent = _BasicAgent
    sys.modules.setdefault("parrot.bots.agent", bots_agent_module)

    # clients_base_module = types.ModuleType("parrot.clients.base")
    # clients_base_module.AbstractClient = type("AbstractClient", (), {})
    # sys.modules.setdefault("parrot.clients.base", clients_base_module)

    # Lightweight AgentContext used by AgentCrew
    @dataclass
    class _AgentContext:
        user_id: str
        session_id: str
        original_query: str
        shared_data: Dict[str, Any] = field(default_factory=dict)
        agent_results: Dict[str, Any] = field(default_factory=dict)

    tools_agent_module = types.ModuleType("parrot.tools.agent")
    tools_agent_module.AgentContext = _AgentContext

    class _AgentTool:
        def __init__(self, agent, **kwargs):
            self.agent = agent
            self.name = getattr(agent, "name", "Agent")
        
        async def run(self, *args, **kwargs):
            # Simple mock implementation invoking the agent or returning a dummy response
            if hasattr(self.agent, "arun"):
                 return await self.agent.arun(*args, **kwargs)
            return "Agent executed"

    tools_agent_module.AgentTool = _AgentTool
    sys.modules.setdefault("parrot.tools.agent", tools_agent_module)

    # Minimal response types with ``content`` attribute
    @dataclass
    class _AIMessage:
        def __init__(self, content: Optional[str] = None, **kwargs):
            self.content = content or kwargs.get('output')
            for k, v in kwargs.items():
                setattr(self, k, v)

    @dataclass
    class _AgentResponse:
        content: str
        output: Optional[str] = None
        response: Optional[_AIMessage] = None
        provider: Optional[str] = None
        model: Optional[str] = None
        tool_calls: Optional[List[Any]] = None

    models_responses_module = types.ModuleType("parrot.models.responses")
    models_responses_module.AIMessage = _AIMessage
    models_responses_module.AgentResponse = _AgentResponse
    models_responses_module.SourceDocument = object
    models_responses_module.AIMessageFactory = object
    models_responses_module.MessageResponse = object
    models_responses_module.StreamChunk = object
    sys.modules.setdefault("parrot.models.responses", models_responses_module)

    @dataclass
    class _AgentExecutionInfo:
        agent_id: str
        agent_name: str
        execution_time: float = 0.0
        status: str = "pending"
        error: Optional[str] = None

    @dataclass
    class _CrewResult:
        output: Any
        responses: Dict[str, Any] = field(default_factory=dict)
        summary: str = ""
        results: List[Any] = field(default_factory=list)
        agent_ids: List[str] = field(default_factory=list)
        agents: List[_AgentExecutionInfo] = field(default_factory=list)
        execution_log: List[Dict[str, Any]] = field(default_factory=list)
        total_time: float = 0.0
        status: str = "completed"
        errors: Dict[str, str] = field(default_factory=dict)
        metadata: Dict[str, Any] = field(default_factory=dict)

        @property
        def content(self) -> Any:
            return self.output

        @property
        def final_result(self) -> Any:
            return self.output

        @property
        def agent_results(self) -> Dict[str, Any]:
            return {
                agent_id: self.results[idx]
                for idx, agent_id in enumerate(self.agent_ids)
                if idx < len(self.results)
            }

        @property
        def completed(self) -> List[str]:
            return [info.agent_id for info in self.agents if info.status == "completed"]

        @property
        def failed(self) -> List[str]:
            return [info.agent_id for info in self.agents if info.status == "failed"]

        @property
        def total_execution_time(self) -> float:
            return self.total_time

        def __getitem__(self, item: str) -> Any:
            mapping = {
                "output": self.output,
                "content": self.content,
                "final_result": self.output,
                "results": self.agent_results,
                "agent_results": self.agent_results,
                "agent_ids": self.agent_ids,
                "errors": self.errors,
                "execution_log": self.execution_log,
                "total_time": self.total_time,
                "total_execution_time": self.total_time,
                "status": self.status,
                "response": self.responses,
                "completed": self.completed,
                "failed": self.failed,
            }
            if item not in mapping:
                raise KeyError(item)
            return mapping[item]

    def _determine_run_status(success_count: int, failure_count: int) -> str:
        if failure_count == 0:
            return "completed"
        return "failed" if success_count == 0 else "partial"

    def _build_agent_metadata(
        agent_id: str,
        agent: Optional[_AbstractBot],
        response: Optional[Any],
        output: Optional[Any],
        execution_time: float,
        status: str,
        error: Optional[str] = None,
    ) -> _AgentExecutionInfo:
        name = getattr(agent, "name", agent_id) if agent else agent_id
        return _AgentExecutionInfo(
            agent_id=agent_id,
            agent_name=name,
            execution_time=execution_time,
            status=status,
            error=error,
        )

    @dataclass
    class _AgentResult:
        agent_id: str
        agent_name: str
        task: str
        result: Any
        ai_message: Optional[Any] = None
        metadata: Dict[str, Any] = field(default_factory=dict)
        execution_time: float = 0.0
        timestamp: Any = None
        parent_execution_id: Optional[str] = None
        execution_id: str = ""

        def to_text(self) -> str:
            return f"Agent: {self.agent_name}\nResult: {self.result}"

    class _VectorStoreProtocol:
        """Stub protocol for vector store."""
        def encode(self, texts):
            return []

    models_crew_module = types.ModuleType("parrot.models.crew")
    models_crew_module.CrewResult = _CrewResult
    models_crew_module.AgentResult = _AgentResult
    models_crew_module.AgentExecutionInfo = _AgentExecutionInfo
    models_crew_module.VectorStoreProtocol = _VectorStoreProtocol
    models_crew_module.build_agent_metadata = _build_agent_metadata
    models_crew_module.determine_run_status = _determine_run_status
    sys.modules.setdefault("parrot.models.crew", models_crew_module)


_install_navconfig_stub()
_install_navigator_stubs()
_install_parrot_stubs()


# ── Permission System Fixtures ─────────────────────────────────────────────────
# These fixtures support FEAT-014: Granular Permissions System tests.

import pytest


# ── Dataset Manager Fixtures ────────────────────────────────────────────────
# These fixtures support FEAT-021: DatasetManager Support tests.

import pandas as pd
from io import BytesIO


@pytest.fixture
def sample_dataframe():
    """Sample DataFrame for testing."""
    return pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie'],
        'age': [25, 30, 35],
        'salary': [50000.0, 60000.0, 70000.0]
    })


@pytest.fixture
def sample_excel_file(sample_dataframe):
    """Sample Excel file as BytesIO."""
    buffer = BytesIO()
    sample_dataframe.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer


@pytest.fixture
def sample_csv_file(sample_dataframe):
    """Sample CSV file as BytesIO."""
    buffer = BytesIO()
    sample_dataframe.to_csv(buffer, index=False)
    buffer.seek(0)
    return buffer


@pytest.fixture
def empty_session():
    """Empty session dict."""
    return {}


@pytest.fixture
def dataset_manager_with_data(sample_dataframe):
    """DatasetManager with pre-loaded data."""
    from parrot.tools.dataset_manager import DatasetManager
    dm = DatasetManager()
    dm.add_dataframe("test_df", sample_dataframe)
    return dm


@pytest.fixture
def mock_pandas_agent(dataset_manager_with_data):
    """Mock PandasAgent with DatasetManager."""
    from unittest.mock import MagicMock
    agent = MagicMock()
    agent.name = "test-pandas-agent"
    agent._dataset_manager = dataset_manager_with_data
    agent.attach_dm = MagicMock()
    return agent


@pytest.fixture
def mock_regular_agent():
    """Mock regular Agent (not PandasAgent)."""
    from unittest.mock import MagicMock
    agent = MagicMock()
    agent.name = "test-agent"
    # No _dataset_manager attribute
    return agent


# ── Permission System Fixtures ─────────────────────────────────────────────────
# These fixtures support FEAT-014: Granular Permissions System tests.


@pytest.fixture
def jira_hierarchy():
    """Role hierarchy for Jira-style permissions."""
    return {
        'jira.admin': {'jira.manage', 'jira.write', 'jira.read'},
        'jira.manage': {'jira.write', 'jira.read'},
        'jira.write': {'jira.read'},
        'jira.read': set(),
    }


@pytest.fixture
def simple_hierarchy():
    """Simple role hierarchy for basic permission tests."""
    return {
        'admin': {'write', 'read'},
        'write': {'read'},
        'read': set(),
    }


@pytest.fixture
def permission_resolver(jira_hierarchy):
    """Default permission resolver with Jira hierarchy."""
    from parrot.auth.resolver import DefaultPermissionResolver
    return DefaultPermissionResolver(role_hierarchy=jira_hierarchy)


@pytest.fixture
def simple_resolver(simple_hierarchy):
    """Permission resolver with simple hierarchy."""
    from parrot.auth.resolver import DefaultPermissionResolver
    return DefaultPermissionResolver(role_hierarchy=simple_hierarchy)


@pytest.fixture
def admin_session():
    """User session with admin role."""
    from parrot.auth.permission import UserSession
    return UserSession(
        user_id="admin-user",
        tenant_id="test-tenant",
        roles=frozenset({'jira.admin'})
    )


@pytest.fixture
def reader_session():
    """User session with read-only role."""
    from parrot.auth.permission import UserSession
    return UserSession(
        user_id="reader-user",
        tenant_id="test-tenant",
        roles=frozenset({'jira.read'})
    )


@pytest.fixture
def writer_session():
    """User session with write role."""
    from parrot.auth.permission import UserSession
    return UserSession(
        user_id="writer-user",
        tenant_id="test-tenant",
        roles=frozenset({'jira.write'})
    )


@pytest.fixture
def admin_context(admin_session):
    """Permission context for admin user."""
    from parrot.auth.permission import PermissionContext
    return PermissionContext(session=admin_session, request_id="test-req-admin")


@pytest.fixture
def reader_context(reader_session):
    """Permission context for reader user."""
    from parrot.auth.permission import PermissionContext
    return PermissionContext(session=reader_session, request_id="test-req-reader")


@pytest.fixture
def writer_context(writer_session):
    """Permission context for writer user."""
    from parrot.auth.permission import PermissionContext
    return PermissionContext(session=writer_session, request_id="test-req-writer")
