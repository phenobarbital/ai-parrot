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
            return fallback

        def getint(self, _key: str, fallback: int = 0) -> int:
            return int(fallback)

        def getboolean(self, _key: str, fallback: bool = False) -> bool:
            return bool(fallback)

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
    sys.modules.setdefault("navigator", types.ModuleType("navigator"))
    sys.modules.setdefault("navigator.conf", navigator_conf)

    navigator_auth_module = types.ModuleType("navigator_auth")
    navigator_auth_conf = types.ModuleType("navigator_auth.conf")
    navigator_auth_conf.AUTH_SESSION_OBJECT = None

    decorators_module = types.ModuleType("navigator_auth.decorators")

    def _user_session(func=None, **__):
        if func is None:
            def wrapper(inner):
                return inner

            return wrapper
        return func

    decorators_module.user_session = _user_session

    navigator_auth_module.decorators = decorators_module

    sys.modules.setdefault("navigator_auth", navigator_auth_module)
    sys.modules.setdefault("navigator_auth.conf", navigator_auth_conf)
    sys.modules.setdefault("navigator_auth.decorators", decorators_module)

    navigator_views = types.ModuleType("navigator.views")
    base_handler = type("BaseHandler", (), {})
    navigator_views.View = type("View", (), {})
    navigator_views.BaseHandler = base_handler
    navigator_views.ModelView = type("ModelView", (), {})
    navigator_views.BaseView = type("BaseView", (), {})
    navigator_views.FormModel = type("FormModel", (), {})
    sys.modules.setdefault("navigator.views", navigator_views)


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
        response: Dict[str, Any] = field(default_factory=dict)
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
                "response": self.response,
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

    models_crew_module = types.ModuleType("parrot.models.crew")
    models_crew_module.CrewResult = _CrewResult
    models_crew_module.AgentExecutionInfo = _AgentExecutionInfo
    models_crew_module.build_agent_metadata = _build_agent_metadata
    models_crew_module.determine_run_status = _determine_run_status
    sys.modules.setdefault("parrot.models.crew", models_crew_module)


_install_navconfig_stub()
_install_navigator_stubs()
_install_parrot_stubs()
