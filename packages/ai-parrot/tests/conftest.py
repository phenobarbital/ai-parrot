"""Test configuration helpers for the parrot codebase."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
import types
import importlib.util
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest


def pytest_collection_modifyitems(config, items):  # noqa: D401
    """Skip tests marked real_llm unless PARROT_TEST_REAL_LLM=1 is set."""
    if not os.environ.get("PARROT_TEST_REAL_LLM"):
        skip_real_llm = pytest.mark.skip(reason="Set PARROT_TEST_REAL_LLM=1 to run real LLM tests")
        for item in items:
            if "real_llm" in item.keywords:
                item.add_marker(skip_real_llm)
    _mark_by_directory(items)


_DIRECTORY_MARKERS = {"integration": "integration", "e2e": "e2e"}


def _mark_by_directory(items) -> None:
    """Add ``integration``/``e2e`` markers from the test's directory (FEAT-563).

    Only exact path segments below this ``tests`` directory count, so
    ``integrations/`` (unit tests of integration packages) is never marked.
    """
    base = Path(__file__).resolve().parent
    for item in items:
        try:
            parts = Path(str(item.path)).resolve().relative_to(base).parts[:-1]
        except ValueError:
            continue
        for segment in parts:
            marker = _DIRECTORY_MARKERS.get(segment)
            if marker:
                item.add_marker(getattr(pytest.mark, marker))


@pytest.fixture(autouse=True)
def _reset_injection_engine_singleton():
    """Reset FEAT-439's process-wide injection-engine singleton, repo-wide.

    ``parrot.bots.guardrails.builtin.prompt_injection._resolve_injection_engine()``
    memoizes its result in a module-level ``_RESOLVED_INJECTION_ENGINE``
    (``_UNSET`` sentinel) so N bots share one resolved engine in
    production. Left unreset between tests, whichever test constructs the
    FIRST ``PromptInjectionGuardrail``/bot-with-``injection_detection=True``
    in the whole pytest process "wins" — every later test's construction
    silently reuses that memoized engine/mock regardless of what it
    itself patches, corrupting unrelated suites
    (e.g. ``test_guardrails_input_migration.py``) that never even import
    this module directly. Autouse + defined at the top-level ``tests/``
    conftest so it applies to ``tests/unit/`` AND ``tests/integration/``
    without every test file needing to know this internal exists.
    """
    import parrot.bots.guardrails.builtin.prompt_injection as _pi_module

    _pi_module._RESOLVED_INJECTION_ENGINE = _pi_module._UNSET
    _pi_module._WARMUP_DONE = False
    yield
    _pi_module._RESOLVED_INJECTION_ENGINE = _pi_module._UNSET
    _pi_module._WARMUP_DONE = False


# Ensure the project root is importable as ``parrot`` when running tests without
# installing the package.  Several tests import modules directly from the
# source tree, so we add the repository root to ``sys.path`` at collection time.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Also add the tests directory so shared helper modules (e.g. _crew_test_helpers)
# can be imported directly by test files.
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


def _stub_if_absent(name: str, module: types.ModuleType) -> bool:
    """Register ``module`` under ``name`` only if the real module is unavailable.

    FEAT-617 / issue:c3c59277ef77. The previous ``sys.modules.setdefault(name, stub)``
    asked "is this name already imported?" -- a question about import *order*, not
    availability -- so a stub pre-empted any real module that simply had not been
    imported yet, and its symbols vanished for the rest of the pytest process. The
    tell was ``(unknown location)`` in the resulting ImportError: a ``ModuleType``
    stub has no ``__file__``. That poisoned 14 of 18 collection errors in this tree.

    The stubs' legitimate purpose -- keeping tests importable when an optional
    third-party dependency (navigator, asyncdb, querysource, navconfig) is genuinely
    missing -- is preserved exactly: if the real module cannot be resolved, the stub
    still lands.

    Args:
        name: Fully-qualified module name, e.g. ``"parrot.tools.filemanager"``.
        module: The lightweight stand-in to install if the real module is absent.

    Returns:
        True if the stub was installed, False if the real module won (or the name
        was already present in ``sys.modules``).
    """
    if name in sys.modules:
        # Preserve setdefault's original contract for the already-imported case.
        return False
    try:
        if importlib.util.find_spec(name) is not None:
            # The real module is importable -- never shadow it.
            return False
    except (ImportError, AttributeError, ValueError):
        # find_spec() imports the PARENT package and may raise rather than return
        # None. Any failure means "not resolvable", so fall through and install the
        # stub -- identical to the pre-FEAT-617 fallback for missing optional deps.
        pass
    sys.modules[name] = module
    return True


def _install_navconfig_stub() -> None:
    """Provide a lightweight ``navconfig`` implementation for tests.

    If the real ``navconfig`` package is installed (it ships transitively
    with ``navigator-api``) we use it as-is — Cython modules like
    ``navigator.types`` bind ``DEBUG``/``SETTINGS_DIR``/``loglevel`` at
    import time and the stub keeps drifting out of sync. Only fall back
    to the stub when the package genuinely cannot be imported.
    """
    try:
        import navconfig  # noqa: F401
        import navconfig.logging  # noqa: F401
        import navconfig.exceptions  # noqa: F401

        return
    except ImportError:
        pass

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
    # navigator.types (Cython) does `from navconfig import config, DEBUG`.
    # Honour PARROT_DEBUG / DEBUG env vars so tests can flip it.
    import os as _os

    navconfig_module.DEBUG = _os.environ.get("PARROT_DEBUG", _os.environ.get("DEBUG", "")).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

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
    # navigator.applications.base does `from navconfig.logging import logging, loglevel`.
    logging_module.loglevel = logging.INFO
    logging_module.LOGLEVEL = "INFO"
    navconfig_module.logging = logging_module

    exceptions_module = types.ModuleType("navconfig.exceptions")

    class _ConfigError(Exception):
        pass

    exceptions_module.ConfigError = _ConfigError
    exceptions_module.NavConfigException = _ConfigError

    _stub_if_absent("navconfig", navconfig_module)
    _stub_if_absent("navconfig.logging", logging_module)
    _stub_if_absent("navconfig.exceptions", exceptions_module)


def _install_navigator_stubs() -> None:
    """Install minimal navigator-related modules required during imports."""

    # ── navigator.utils.file stubs ─────────────────────────────────────────
    # FEAT-124 added parrot.interfaces.file and parrot.tools.filemanager that
    # import symbols from navigator.utils.file. The full FileManager interface
    # ships with navigator-api >= 3.0.3 (see pyproject.toml). Install stubs so
    # tests can collect without requiring that version installed.
    import navigator.utils.file as _nuf  # already importable, just missing attrs

    from unittest.mock import AsyncMock

    _FileManagerInterface = type(
        "FileManagerInterface",
        (),
        {
            "__init__": lambda self, *a, **kw: None,
            "__getattr__": lambda self, name: AsyncMock(),
        },
    )
    _FileMetadata = type("FileMetadata", (), {})
    _LocalFileManager = type("LocalFileManager", (_FileManagerInterface,), {})
    _TempFileManager = type("TempFileManager", (_FileManagerInterface,), {})
    _FileManagerFactory = type(
        "FileManagerFactory",
        (),
        {
            "get": staticmethod(lambda *a, **kw: _LocalFileManager()),
            "create": staticmethod(lambda *a, **kw: _LocalFileManager()),
        },
    )

    for _attr, _val in [
        ("FileManagerInterface", _FileManagerInterface),
        ("FileMetadata", _FileMetadata),
        ("LocalFileManager", _LocalFileManager),
        ("TempFileManager", _TempFileManager),
        ("FileManagerFactory", _FileManagerFactory),
    ]:
        if not hasattr(_nuf, _attr):
            setattr(_nuf, _attr, _val)

    # navigator.utils.file.abstract — used by parrot.interfaces.file.abstract
    _nuf_abstract = types.ModuleType("navigator.utils.file.abstract")
    _nuf_abstract.FileManagerInterface = _FileManagerInterface
    _nuf_abstract.FileMetadata = _FileMetadata
    _stub_if_absent("navigator.utils.file.abstract", _nuf_abstract)

    # parrot.interfaces.file shim — avoids re-importing the real module that
    # would fail if navigator doesn't expose these attrs yet.
    _parrot_interfaces_file = types.ModuleType("parrot.interfaces.file")
    _parrot_interfaces_file.FileManagerInterface = _FileManagerInterface
    _parrot_interfaces_file.FileMetadata = _FileMetadata
    _parrot_interfaces_file.LocalFileManager = _LocalFileManager
    _parrot_interfaces_file.TempFileManager = _TempFileManager
    _parrot_interfaces_file.S3FileManager = type("S3FileManager", (_FileManagerInterface,), {})
    _parrot_interfaces_file.GCSFileManager = type("GCSFileManager", (_FileManagerInterface,), {})
    _stub_if_absent("parrot.interfaces.file", _parrot_interfaces_file)

    # parrot.interfaces.file.{abstract,s3,gcs,local,tmp} — concrete submodules
    # used by parrot.storage.overflow / s3_overflow and the backend factory.
    _parrot_interfaces_file_abstract = types.ModuleType("parrot.interfaces.file.abstract")
    _parrot_interfaces_file_abstract.FileManagerInterface = _FileManagerInterface
    _parrot_interfaces_file_abstract.FileMetadata = _FileMetadata
    _stub_if_absent("parrot.interfaces.file.abstract", _parrot_interfaces_file_abstract)
    _parrot_interfaces_file.abstract = _parrot_interfaces_file_abstract

    _parrot_interfaces_file_s3 = types.ModuleType("parrot.interfaces.file.s3")
    _parrot_interfaces_file_s3.S3FileManager = _parrot_interfaces_file.S3FileManager
    _stub_if_absent("parrot.interfaces.file.s3", _parrot_interfaces_file_s3)
    _parrot_interfaces_file.s3 = _parrot_interfaces_file_s3

    _parrot_interfaces_file_gcs = types.ModuleType("parrot.interfaces.file.gcs")
    _parrot_interfaces_file_gcs.GCSFileManager = _parrot_interfaces_file.GCSFileManager
    _stub_if_absent("parrot.interfaces.file.gcs", _parrot_interfaces_file_gcs)
    _parrot_interfaces_file.gcs = _parrot_interfaces_file_gcs

    _parrot_interfaces_file_local = types.ModuleType("parrot.interfaces.file.local")
    _parrot_interfaces_file_local.LocalFileManager = _LocalFileManager
    _stub_if_absent("parrot.interfaces.file.local", _parrot_interfaces_file_local)
    _parrot_interfaces_file.local = _parrot_interfaces_file_local

    _parrot_interfaces_file_tmp = types.ModuleType("parrot.interfaces.file.tmp")
    _parrot_interfaces_file_tmp.TempFileManager = _TempFileManager
    _stub_if_absent("parrot.interfaces.file.tmp", _parrot_interfaces_file_tmp)
    _parrot_interfaces_file.tmp = _parrot_interfaces_file_tmp

    # parrot.tools.filemanager — used by parrot.clients.google.generation
    _parrot_tools_fm = types.ModuleType("parrot.tools.filemanager")
    _parrot_tools_fm.FileManagerFactory = _FileManagerFactory
    _stub_if_absent("parrot.tools.filemanager", _parrot_tools_fm)

    # ── main navigator stubs ───────────────────────────────────────────────
    navigator_conf = types.ModuleType("navigator.conf")
    navigator_conf.default_dsn = "postgresql://user:pass@localhost/db"
    navigator_conf.CACHE_HOST = "localhost"
    navigator_conf.CACHE_PORT = 6379
    navigator_module = types.ModuleType("navigator")
    navigator_module.__path__ = []
    _stub_if_absent("navigator", navigator_module)
    _stub_if_absent("navigator.conf", navigator_conf)
    # navigator.types stub
    navigator_types = types.ModuleType("navigator.types")
    navigator_types.WebApp = type("WebApp", (), {})
    _stub_if_absent("navigator.types", navigator_types)

    # navigator.applications stub
    navigator_applications = types.ModuleType("navigator.applications")
    navigator_applications.__path__ = []
    navigator_applications.App = type("App", (), {})
    _stub_if_absent("navigator.applications", navigator_applications)
    navigator_applications_base = types.ModuleType("navigator.applications.base")
    navigator_applications_base.BaseApplication = type("BaseApplication", (), {})
    _stub_if_absent("navigator.applications.base", navigator_applications_base)

    # navigator.middlewares stub
    navigator_middlewares = types.ModuleType("navigator.middlewares")
    _stub_if_absent("navigator.middlewares", navigator_middlewares)

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

    _stub_if_absent("navigator_auth", navigator_auth_module)
    _stub_if_absent("navigator_auth.conf", navigator_auth_conf)
    _stub_if_absent("navigator_auth.decorators", decorators_module)

    navigator_views = types.ModuleType("navigator.views")
    base_handler = type("BaseHandler", (), {})
    navigator_views.View = type("View", (), {})
    navigator_views.BaseHandler = base_handler
    navigator_views.ModelView = type("ModelView", (), {})
    navigator_views.BaseView = type(
        "BaseView",
        (),
        {
            "query_parameters": staticmethod(lambda req: {}),
            "json_response": lambda self, data, **kw: data,
            "error": lambda self, response, status=400: response,
            "json_data": lambda self: {},
        },
    )
    navigator_views.FormModel = type("FormModel", (), {})

    # AbstractModel stub used by ChatbotHandler
    _abstract_model = type(
        "AbstractModel",
        (navigator_views.BaseView,),
        {
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
        },
    )
    navigator_views.AbstractModel = _abstract_model

    # Register navigator.views.abstract submodule
    abstract_module = types.ModuleType("navigator.views.abstract")
    abstract_module.AbstractModel = _abstract_model
    _stub_if_absent("navigator.views.abstract", abstract_module)

    _stub_if_absent("navigator.views", navigator_views)

    # Ensure navigator.conf has AUTH_SESSION_OBJECT
    navigator_conf.AUTH_SESSION_OBJECT = "user"

    # navigator.connections — required by parrot.scheduler
    navigator_connections = types.ModuleType("navigator.connections")
    navigator_connections.PostgresPool = type("PostgresPool", (), {})
    _stub_if_absent("navigator.connections", navigator_connections)

    # asyncdb — required by parrot.scheduler and parrot.scheduler.models
    asyncdb_module = types.ModuleType("asyncdb")
    asyncdb_module.AsyncDB = type("AsyncDB", (), {})
    asyncdb_module.AsyncPool = type("AsyncPool", (), {})
    asyncdb_module.__path__ = []  # make Python treat it as a package
    _stub_if_absent("asyncdb", asyncdb_module)

    asyncdb_exceptions = types.ModuleType("asyncdb.exceptions")
    asyncdb_exceptions.__path__ = []  # treat as package to allow sub-imports
    for _exc_name in [
        "NoDataFound",
        "ProviderError",
        "DriverError",
        "UninitializedError",
        "ValidationError",
        "ConnectionMissing",
        "ConnectionTimeout",
        "DataError",
        "DriverError",
        "EmptyStatement",
        "ModelError",
        "NotSupported",
        "StatementError",
        "TooManyConnections",
        "UnknownPropertyError",
    ]:
        setattr(asyncdb_exceptions, _exc_name, type(_exc_name, (Exception,), {}))
    # sub-module aliases so "from asyncdb.exceptions.exceptions import X" works
    asyncdb_exc_exc = types.ModuleType("asyncdb.exceptions.exceptions")
    asyncdb_exc_exc.__dict__.update(
        {k: v for k, v in asyncdb_exceptions.__dict__.items() if isinstance(v, type) and issubclass(v, Exception)}
    )
    _stub_if_absent("asyncdb.exceptions", asyncdb_exceptions)
    _stub_if_absent("asyncdb.exceptions.exceptions", asyncdb_exc_exc)

    asyncdb_models = types.ModuleType("asyncdb.models")
    asyncdb_models.Model = type("Model", (), {})
    asyncdb_models.Field = lambda *a, **kw: None
    _stub_if_absent("asyncdb.models", asyncdb_models)

    # querysource.conf — required by parrot.scheduler
    querysource_module = types.ModuleType("querysource")
    querysource_conf = types.ModuleType("querysource.conf")
    querysource_conf.default_dsn = "postgresql://user:pass@localhost/db"
    _stub_if_absent("querysource", querysource_module)
    _stub_if_absent("querysource.conf", querysource_conf)

    # parrot.notifications — required by parrot.scheduler.
    # Prefer the REAL module when it is importable (same policy as
    # parrot.conf below): the stub's empty NotificationMixin has none of
    # the real methods, so once setdefault() wins, every test that
    # exercises NotificationMixin silently skips itself instead of
    # running (tests/notifications/ skipped all 24 cases this way).
    try:
        import parrot.notifications  # noqa: F401
    except Exception:  # noqa: BLE001 — any import failure → stub fallback
        parrot_notifications = types.ModuleType("parrot.notifications")
        parrot_notifications.NotificationMixin = type("NotificationMixin", (), {})
        _stub_if_absent("parrot.notifications", parrot_notifications)

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
        PARROT_SCHEMA = "navigator"

        def __getattr__(self, name: str):
            # Return a sensible default for any other constant
            return None

    # Prefer the REAL parrot.conf when it is importable (same policy as
    # _install_navconfig_stub): the stub's __getattr__ returns None for
    # every constant, which silently breaks suites that read real settings
    # (e.g. dev_loop's ACCEPTANCE_CRITERION_ALLOWLIST / conf.config).
    try:
        import parrot.conf  # noqa: F401
    except Exception:  # noqa: BLE001 — any import failure → stub fallback
        parrot_conf = _ParrotConf("parrot.conf")
        _stub_if_absent("parrot.conf", parrot_conf)

    # parrot.plugins — required by parrot.tools.__init__
    parrot_plugins = types.ModuleType("parrot.plugins")
    parrot_plugins.setup_plugin_importer = lambda *a, **kw: None
    parrot_plugins.dynamic_import_helper = lambda *a, **kw: None
    _stub_if_absent("parrot.plugins", parrot_plugins)


@pytest.fixture
def fake_parrot_bots(monkeypatch):
    """Opt-in fake AbstractBot/Agent stand-ins for lightweight AgentCrew tests.

    Scoped via monkeypatch.setitem so sys.modules is restored automatically at
    fixture teardown, instead of the old sys.modules.setdefault() approach
    (formerly ``_install_parrot_stubs()``, called unconditionally at conftest
    import time) which leaked into unrelated tests needing the REAL
    parrot.bots.abstract / parrot.bots.agent (see FEAT-268 for the bug this
    caused in JiraSpecialist).
    """

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
    monkeypatch.setitem(sys.modules, "parrot.bots.abstract", bots_abstract_module)

    class _BasicAgent(_AbstractBot):
        async def configure(self):
            self.is_configured = True

        def agent_tools(self):
            return []

    bots_agent_module = types.ModuleType("parrot.bots.agent")
    bots_agent_module.BasicAgent = _BasicAgent
    bots_agent_module.Agent = _BasicAgent
    monkeypatch.setitem(sys.modules, "parrot.bots.agent", bots_agent_module)

    yield

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
    monkeypatch.setitem(sys.modules, "parrot.tools.agent", tools_agent_module)

    # Minimal response types with ``content`` attribute
    @dataclass
    class _AIMessage:
        def __init__(self, content: Optional[str] = None, **kwargs):
            self.content = content or kwargs.get("output")
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

    @dataclass
    class _InvokeResult:
        output: Any = None
        model: Optional[str] = None
        provider: Optional[str] = None
        usage: Optional[Any] = None

    models_responses_module = types.ModuleType("parrot.models.responses")
    models_responses_module.AIMessage = _AIMessage
    models_responses_module.AgentResponse = _AgentResponse
    models_responses_module.SourceDocument = object
    models_responses_module.AIMessageFactory = object
    models_responses_module.MessageResponse = object
    models_responses_module.StreamChunk = object
    models_responses_module.InvokeResult = _InvokeResult
    monkeypatch.setitem(sys.modules, "parrot.models.responses", models_responses_module)

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
                agent_id: self.results[idx] for idx, agent_id in enumerate(self.agent_ids) if idx < len(self.results)
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
    monkeypatch.setitem(sys.modules, "parrot.models.crew", models_crew_module)



# ---------------------------------------------------------------------------
# FEAT-617 / issue:c3c59277ef77 — a test module may not keep another's imports
# ---------------------------------------------------------------------------
# Several modules in this tree install stand-ins at MODULE scope and never restore
# them, e.g. tests/integration/test_spatial_transport.py:95-96 does
#
#     sys.modules["aiohttp"] = types.ModuleType("aiohttp")
#
# so the real aiohttp is gone for every file collected afterwards. Delta-debugging
# identified 8 such modules; between them they caused 13 of this tree's 18 collection
# errors ("cannot import name 'FormData' from 'aiohttp' (unknown location)",
# "module 'aiohttp.web' has no attribute 'Application'", and the parrot._imports /
# parrot.registry variants). The tell is always the same: a types.ModuleType stub has
# no __file__.
#
# Rather than rewrite eight modules, scope the damage: snapshot sys.modules around
# each test module's import and put back exactly the real modules that module
# REPLACED. Only genuine module objects are restored (a name the module merely ADDED
# is left in place, since nothing was shadowed), and the original object is restored
# rather than re-imported, so any reference captured meanwhile stays valid.
#
# The polluting modules need their stand-ins only while they load a target by path at
# import time -- they keep direct references afterwards -- so restoring once their
# collection finishes leaves their own tests working.

_MODULE_SNAPSHOTS: Dict[str, Dict[str, Any]] = {}


def _real_module_snapshot() -> Dict[str, Any]:
    """Identity map of every sys.modules entry that is currently a REAL module."""
    snap = {}
    for name, module in list(sys.modules.items()):
        if module is not None and getattr(module, "__file__", None) is not None:
            snap[name] = module
    return snap


def pytest_collectstart(collector):  # noqa: D401
    """Snapshot the real modules in play before a test module is imported."""
    if type(collector).__name__ == "Module":
        _MODULE_SNAPSHOTS[collector.nodeid] = _real_module_snapshot()


def pytest_collectreport(report):  # noqa: D401
    """Undo any real module the just-collected test module replaced with a stub."""
    snapshot = _MODULE_SNAPSHOTS.pop(report.nodeid, None)
    if not snapshot:
        return
    for name, original in snapshot.items():
        current = sys.modules.get(name)
        if current is original or current is None:
            continue
        # The entry changed. Restore only if what replaced it is a bare stand-in --
        # a real re-import (different object, still a real module) is left alone.
        if getattr(current, "__file__", None) is None:
            sys.modules[name] = original

_install_navconfig_stub()
_install_navigator_stubs()
# NOTE (FEAT-268): _install_parrot_stubs() used to be called unconditionally
# here, poisoning sys.modules["parrot.bots.abstract"/"parrot.bots.agent"] for
# the whole pytest process. It is now the opt-in `fake_parrot_bots` fixture
# defined above — request it explicitly in tests that want the lightweight
# stand-ins instead of the real AbstractBot/Agent classes.


# ── Permission System Fixtures ─────────────────────────────────────────────────
# These fixtures support FEAT-014: Granular Permissions System tests.

# ── Dataset Manager Fixtures ────────────────────────────────────────────────
# These fixtures support FEAT-021: DatasetManager Support tests.


@pytest.fixture
def sample_dataframe():
    """Sample DataFrame for testing."""
    return pd.DataFrame(
        {"name": ["Alice", "Bob", "Charlie"], "age": [25, 30, 35], "salary": [50000.0, 60000.0, 70000.0]}
    )


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
        "jira.admin": {"jira.manage", "jira.write", "jira.read"},
        "jira.manage": {"jira.write", "jira.read"},
        "jira.write": {"jira.read"},
        "jira.read": set(),
    }


@pytest.fixture
def simple_hierarchy():
    """Simple role hierarchy for basic permission tests."""
    return {
        "admin": {"write", "read"},
        "write": {"read"},
        "read": set(),
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

    return UserSession(user_id="admin-user", tenant_id="test-tenant", roles=frozenset({"jira.admin"}))


@pytest.fixture
def reader_session():
    """User session with read-only role."""
    from parrot.auth.permission import UserSession

    return UserSession(user_id="reader-user", tenant_id="test-tenant", roles=frozenset({"jira.read"}))


@pytest.fixture
def writer_session():
    """User session with write role."""
    from parrot.auth.permission import UserSession

    return UserSession(user_id="writer-user", tenant_id="test-tenant", roles=frozenset({"jira.write"}))


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
