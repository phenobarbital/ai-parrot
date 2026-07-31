"""
AgentTalk - HTTP Handler for Agent Conversations
=================================================
Provides a flexible HTTP interface for talking with agents/bots using the ask() method
with support for multiple output modes and MCP server integration.
"""
from __future__ import annotations
import contextlib
import json
from typing import Dict, Any, List, Optional, Tuple, Union, TYPE_CHECKING
import tempfile
import os
import time
import inspect
import uuid
import asyncio
from aiohttp import web
import pandas as pd
from pydantic import BaseModel
from datamodel.parsers.json import json_encoder  # noqa  pylint: disable=E0611
from rich.panel import Panel
from navconfig.logging import logging
from navigator_session import get_session
from navigator_auth.decorators import is_authenticated, user_session
try:
    from navigator_auth.abac.decorators import requires_permission
    from navigator_auth.abac.policies.resources import ResourceType
    _PBAC_DECORATORS_AVAILABLE = True
except ImportError:
    _PBAC_DECORATORS_AVAILABLE = False
    requires_permission = None
    ResourceType = None
from navigator.views import BaseView
from ..bots.abstract import AbstractBot
from ..bots.search import WebSearchAgent
from ..models.responses import AIMessage, AgentResponse
from ..outputs import OutputMode, OutputFormatter
from ..mcp.integration import MCPServerConfig
from ..memory import RedisConversation
from ..interfaces.documentdb import DocumentDb
from ..tools.manager import ToolManager
from .user_objects import UserObjectsHandler
from ..mcp.registry import get_factory_map as _get_factory_map
from .mcp_persistence import MCPPersistenceService as _MCPPersistenceService
from .credentials_utils import decrypt_credential as _decrypt_credential
from ..auth.exceptions import AuthorizationRequired
from parrot.auth.oauth2.models import AuthRequiredEnvelope
# FEAT-204: HumanInteractionInterrupt lives in core.exceptions (no parrot.human dependency)
from parrot.core.exceptions import HumanInteractionInterrupt
if TYPE_CHECKING:
    from ..manager import BotManager

# FEAT-146: Web HITL ContextVar helpers
from .web_hitl import set_current_web_session, reset_current_web_session


# ---------------------------------------------------------------------------
# FEAT-204: PausedEnvelope — structured HTTP-200 reply for HITL suspend
# ---------------------------------------------------------------------------

#: Default TTL (seconds) for a suspended HITL interaction when neither the
#: HITL manager nor the interaction object is available.
#: 7200s = HumanToolInput default timeout (2h) + 60s buffer.
_DEFAULT_HITL_SUSPEND_TTL: int = 7260

class PausedEnvelope(BaseModel):
    """HTTP-200 structured reply returned by AgentTalk when a SUSPEND tool raises
    HumanInteractionInterrupt.

    Modelled on AuthRequiredEnvelope — the frontend detects ``status == "paused"``
    and renders the appropriate HITL widget for the interaction type.

    Attributes:
        status: Discriminator literal — always ``"paused"``.
        turn_id: Correlation ID wrapping interaction_id (shared with resume path).
        interaction_id: UUID of the pending HumanInteraction in Redis.
        interaction_type: Interaction type string (e.g. ``"single_choice"``).
        question: The question posed to the human.
        context: Optional short background shown above the question.
        options: For choice-type interactions — list of option dicts.
        form_schema: For form-type interactions — JSON Schema dict.
        default_response: Default value if the human does not respond in time.
        deadline: ISO-8601 absolute expiry derived from the interaction TTL.
        source_agent: Name of the agent that raised the interrupt.
    """

    status: str = "paused"
    turn_id: str
    interaction_id: str
    interaction_type: str
    question: str
    context: Optional[str] = None
    options: Optional[list] = None
    form_schema: Optional[Dict[str, Any]] = None
    default_response: Any = None
    deadline: Optional[str] = None
    source_agent: Optional[str] = None


@is_authenticated()
@user_session()
class AgentTalk(BaseView):
    """
    AgentTalk Handler - Universal agent conversation interface.

    Endpoints:
        PATCH /api/v1/agents/chat/{agent_id} - Configure tools/MCP servers (session-scoped)
        POST /api/v1/agents/chat/{agent_id} - Main chat endpoint with format negotiation

    Features:
    - POST to /api/v1/agents/chat/{agent_id} to interact with agents
    - PATCH to /api/v1/agents/chat/{agent_id} to configure tools/MCP servers
    - Uses BotManager to retrieve the agent
    - Supports multiple output formats (JSON, HTML, Markdown, Terminal)
    - Session-scoped ToolManager: PATCH persists tools under '{agent_id}_tool_manager'
    - POST temporarily swaps user's ToolManager onto the agent and restores it after
    - Leverages OutputMode for consistent formatting
    - Session-based conversation management
    """
    _logger_name: str = "Parrot.AgentTalk"
    _user_objects_handler: UserObjectsHandler = None

    @property
    def user_objects_handler(self) -> UserObjectsHandler:
        """Lazy-initialized UserObjectsHandler for session-scoped managers."""
        if self._user_objects_handler is None:
            logger = getattr(self, 'logger', None)
            self._user_objects_handler = UserObjectsHandler(logger=logger)
        return self._user_objects_handler

    def post_init(self, *args, **kwargs):
        self.logger = logging.getLogger(self._logger_name)
        self.logger.setLevel(logging.DEBUG)

    async def _check_pbac_agent_access(
        self,
        agent_id: str,
        action: str = "agent:chat",
    ) -> web.Response:
        """Check PBAC policy for agent access. Returns 403 response if denied.

        Uses ``PolicyEvaluator.check_access()`` from the PDP for real-time
        policy evaluation.  Returns ``None`` if access is allowed or if PBAC
        is not configured (graceful degradation — fail open).

        Args:
            agent_id: The agent identifier extracted from the URL route.
            action: The PBAC action string (e.g. ``"agent:chat"``).

        Returns:
            ``None`` if access is allowed, or a :class:`web.Response` with
            HTTP 403 status if access is denied.
        """
        guardian = self.request.app.get('security')
        if guardian is None:
            # PBAC not configured — allow access (backward compatible)
            return None

        try:
            pdp = self.request.app.get('abac')
            if pdp is None:
                return None
            evaluator = getattr(pdp, '_evaluator', None)
            if evaluator is None:
                return None

            if not _PBAC_DECORATORS_AVAILABLE:
                return None

            eval_ctx = await self._build_eval_context()
            if eval_ctx is None:
                return None

            from navigator_auth.abac.policies.environment import Environment
            result = evaluator.check_access(
                ctx=eval_ctx,
                resource_type=ResourceType.AGENT,
                resource_name=agent_id,
                action=action,
                env=Environment(),
            )
            if not result.allowed:
                userinfo = eval_ctx.store.get('userinfo', {}) or {}
                username = (
                    userinfo.get('username', '')
                    if isinstance(userinfo, dict)
                    else ''
                ) or getattr(eval_ctx.store.get('user'), 'username', '')
                self.logger.warning(
                    "PBAC agent access DENIED: agent=%s user=%s action=%s policy=%s reason=%s",
                    agent_id,
                    username,
                    action,
                    result.matched_policy,
                    result.reason,
                )
                return self.json_response(
                    {
                        "error": "Access Denied",
                        "reason": result.reason or f"Policy denied access to agent:{agent_id}",
                    },
                    status=403,
                )
        except Exception as exc:
            self.logger.warning(
                "PBAC agent access check failed (fail-open): %s", exc
            )
        return None

    async def _filter_tools_for_user(self, tool_manager: "ToolManager") -> None:
        """Filter tools in-place using PBAC policies for the current user.

        Retrieves ``app['security']`` (Guardian) and calls
        ``Guardian.filter_resources()`` (navigator-auth >= 0.19.0) or falls
        back to ``PolicyEvaluator.filter_resources()`` for backward
        compatibility.  Denied tools are removed from *tool_manager*.
        If PBAC is not configured, no filtering is performed.

        Args:
            tool_manager: Session-scoped ToolManager to filter in-place.
        """
        guardian = self.request.app.get('security')
        if guardian is None:
            return  # PBAC not configured, skip filtering

        tool_names = tool_manager.list_tools()
        if not tool_names:
            return

        try:
            if hasattr(guardian, 'filter_resources') and _PBAC_DECORATORS_AVAILABLE:
                # navigator-auth >= 0.19.0 with Guardian.filter_resources()
                filtered = await guardian.filter_resources(
                    resources=tool_names,
                    request=self.request,
                    resource_type=ResourceType.TOOL,
                    action="tool:execute",
                )
            else:
                # Fallback: use PolicyEvaluator.filter_resources() directly
                pdp = self.request.app.get('abac')
                if pdp is None:
                    return
                evaluator = getattr(pdp, '_evaluator', None)
                if evaluator is None:
                    return
                from navigator_auth.abac.policies.environment import Environment
                eval_ctx = await self._build_eval_context()
                if eval_ctx is None:
                    return
                filtered = evaluator.filter_resources(
                    ctx=eval_ctx,
                    resource_type=ResourceType.TOOL,
                    resource_names=tool_names,
                    action="tool:execute",
                    env=Environment(),
                )
            if filtered.denied:
                self.logger.info(
                    "PBAC filtered %d tools for user",
                    len(filtered.denied),
                )
                self.logger.debug("PBAC denied tools: %s", filtered.denied)
                for tool_name in filtered.denied:
                    tool_manager.remove_tool(tool_name)
        except Exception as exc:
            self.logger.error("PBAC tool filtering failed (fail-open): %s", exc)
            # Fail open — tools remain visible

    async def _filter_datasets_for_user(self, dataset_manager: Any) -> None:
        """Filter datasets in-place using PBAC policies for the current user.

        Uses ``ResourceType.DATASET`` (requires navigator-auth >= 0.19.0).
        Falls back gracefully if PBAC or DATASET type is not available.

        Args:
            dataset_manager: DatasetManager instance to filter in-place.
        """
        guardian = self.request.app.get('security')
        if guardian is None:
            return  # PBAC not configured

        if not _PBAC_DECORATORS_AVAILABLE:
            return

        # ResourceType.DATASET requires navigator-auth >= 0.19.0
        try:
            dataset_resource_type = ResourceType.__members__.get('DATASET')
        except Exception:
            dataset_resource_type = None

        if dataset_resource_type is None:
            self.logger.debug(
                "PBAC: ResourceType.DATASET not available — skipping dataset filtering."
            )
            return

        dataset_names = list(dataset_manager.list_dataframes().keys())
        if not dataset_names:
            return

        try:
            if hasattr(guardian, 'filter_resources'):
                filtered = await guardian.filter_resources(
                    resources=dataset_names,
                    request=self.request,
                    resource_type=dataset_resource_type,
                    action="dataset:query",
                )
            else:
                pdp = self.request.app.get('abac')
                if pdp is None:
                    return
                evaluator = getattr(pdp, '_evaluator', None)
                if evaluator is None:
                    return
                from navigator_auth.abac.policies.environment import Environment
                eval_ctx = await self._build_eval_context()
                if eval_ctx is None:
                    return
                filtered = evaluator.filter_resources(
                    ctx=eval_ctx,
                    resource_type=dataset_resource_type,
                    resource_names=dataset_names,
                    action="dataset:query",
                    env=Environment(),
                )
            if filtered.denied:
                self.logger.info(
                    "PBAC filtered %d datasets for user",
                    len(filtered.denied),
                )
                self.logger.debug("PBAC denied datasets: %s", filtered.denied)
                for ds_name in filtered.denied:
                    try:
                        await dataset_manager.remove_dataset(ds_name)
                    except Exception as remove_exc:
                        self.logger.warning(
                            "PBAC: Failed to remove dataset '%s': %s",
                            ds_name,
                            remove_exc,
                        )
        except Exception as exc:
            self.logger.error("PBAC dataset filtering failed (fail-open): %s", exc)

    async def _filter_mcp_servers_for_user(self, mcp_server_configs: list) -> list:
        """Filter MCP server configs using PBAC policies for the current user.

        Returns the subset of *mcp_server_configs* that the current user is
        allowed to access. Denied MCP servers are excluded so their tools are
        never registered in the ToolManager.

        Args:
            mcp_server_configs: List of MCP server config objects (each must
                have a ``.name`` attribute).

        Returns:
            Filtered list containing only allowed MCP server configs.
        """
        guardian = self.request.app.get('security')
        if guardian is None:
            return mcp_server_configs  # PBAC not configured, allow all

        if not mcp_server_configs or not _PBAC_DECORATORS_AVAILABLE:
            return mcp_server_configs

        server_names = [
            cfg.name if hasattr(cfg, 'name') else cfg.get('name', '')
            for cfg in mcp_server_configs
        ]

        try:
            if hasattr(guardian, 'filter_resources'):
                filtered = await guardian.filter_resources(
                    resources=server_names,
                    request=self.request,
                    resource_type=ResourceType.MCP,
                    action="tool:execute",
                )
            else:
                pdp = self.request.app.get('abac')
                if pdp is None:
                    return mcp_server_configs
                evaluator = getattr(pdp, '_evaluator', None)
                if evaluator is None:
                    return mcp_server_configs
                from navigator_auth.abac.policies.environment import Environment
                eval_ctx = await self._build_eval_context()
                if eval_ctx is None:
                    return mcp_server_configs
                filtered = evaluator.filter_resources(
                    ctx=eval_ctx,
                    resource_type=ResourceType.MCP,
                    resource_names=server_names,
                    action="tool:execute",
                    env=Environment(),
                )
            if filtered.denied:
                self.logger.info(
                    "PBAC filtered %d MCP servers for user",
                    len(filtered.denied),
                )
                self.logger.debug("PBAC denied MCP servers: %s", filtered.denied)
            allowed_names = set(filtered.allowed)
            return [
                cfg for cfg in mcp_server_configs
                if (cfg.name if hasattr(cfg, 'name') else cfg.get('name', '')) in allowed_names
            ]
        except Exception as exc:
            self.logger.error(
                "PBAC MCP server filtering failed (fail-open): %s", exc
            )
            return mcp_server_configs

    async def _build_eval_context(self) -> Any:
        """Build an EvalContext from the current request session.

        Returns an :class:`~navigator_auth.abac.context.EvalContext` or
        ``None`` if the session is unavailable or EvalContext cannot be
        imported.
        """
        try:
            from navigator_auth.abac.context import EvalContext
            from navigator_auth.conf import AUTH_SESSION_OBJECT
        except ImportError:
            return None

        try:
            session = self.request.session if hasattr(self.request, 'session') else None
            if session is None:
                session = await get_session(self.request)
            if session is None:
                return None
            userinfo = session.get(AUTH_SESSION_OBJECT, {}) if hasattr(session, 'get') else {}
            user = session.decode('user') if hasattr(session, 'decode') else None
            if user is None and isinstance(userinfo, dict) and userinfo:
                user = userinfo
            return EvalContext(
                request=self.request,
                user=user,
                userinfo=userinfo,
                session=session,
            )
        except Exception as exc:
            self.logger.warning("PBAC: Failed to build EvalContext: %s", exc)
            return None

    def _get_output_format(
        self,
        data: Dict[str, Any],
        qs: Dict[str, Any]
    ) -> str:
        """
        Determine the output format from request.

        Priority:
        1. Explicit 'output_format' in request body or query string
        2. Content-Type header from Accept header
        3. Default to 'json'

        Args:
            data: Request body data
            qs: Query string parameters

        Returns:
            Output format string: 'json', 'html', 'markdown', or 'text'
        """
        # Check explicit output_format parameter
        if output_format := data.pop('output_format', None) or qs.get('output_format'):
            return output_format.lower()

        # Check Accept header - prioritize JSON
        accept_header = self.request.headers.get('Accept', 'application/json')

        if 'application/json' in accept_header:
            return 'json'
        elif 'text/html' in accept_header:
            return 'html'
        elif 'text/markdown' in accept_header:
            return 'markdown'
        elif 'text/plain' in accept_header:
            return 'text'
        else:
            return 'json'

    def _get_output_mode(self, request: web.Request) -> OutputMode:
        """
        Determine output mode from request headers and parameters.

        Priority:
        1. Query parameter 'output_mode'
        2. Content-Type header
        3. Accept header
        4. Default to OutputMode.DEFAULT
        """
        # Check query parameters first
        qs = self.query_parameters(request)
        if 'output_mode' in qs:
            mode = qs['output_mode'].lower()
            if mode in ['json', 'html', 'terminal', 'markdown', 'default']:
                return OutputMode(mode if mode != 'markdown' else 'default')

        # Check Content-Type header
        content_type = request.headers.get('Content-Type', '').lower()
        if 'application/json' in content_type:
            return OutputMode.JSON
        elif 'text/html' in content_type:
            return OutputMode.HTML

        # Check Accept header
        accept = request.headers.get('Accept', '').lower()
        if 'application/json' in accept:
            return OutputMode.JSON
        elif 'text/html' in accept:
            return OutputMode.HTML
        elif 'text/plain' in accept:
            return OutputMode.DEFAULT

        return OutputMode.DEFAULT

    def _format_to_output_mode(self, format_str: str) -> OutputMode:
        """
        Convert format string to OutputMode enum.

        Args:
            format_str: Format string (json, html, markdown, text, terminal)

        Returns:
            OutputMode enum value
        """
        format_map = {
            'json': OutputMode.JSON,
            'html': OutputMode.HTML,
            'markdown': OutputMode.DEFAULT,
            'text': OutputMode.DEFAULT,
            'terminal': OutputMode.TERMINAL,
            'default': OutputMode.DEFAULT
        }
        return format_map.get(format_str.lower(), OutputMode.DEFAULT)

    def _prepare_response(
        self,
        ai_message: AIMessage,
        output_mode: OutputMode,
        format_kwargs: Dict[str, Any] = None
    ):
        """
        Format and return the response based on output mode.

        Args:
            ai_message: The AIMessage response from the agent
            output_mode: The desired output format
            format_kwargs: Additional formatting options
        """
        formatter = OutputFormatter()

        if output_mode == OutputMode.JSON:
            usage = getattr(ai_message, 'usage', None)
            response_data = {
                "content": ai_message.content,
                "metadata": {
                    "session_id": getattr(ai_message, 'session_id', None),
                    "user_id": getattr(ai_message, 'user_id', None),
                    "timestamp": getattr(ai_message, 'timestamp', None),
                    "model": getattr(ai_message, 'model', None),
                    "provider": getattr(ai_message, 'provider', None),
                    "usage": usage.model_dump() if usage is not None else None,
                    "response_time": getattr(ai_message, 'response_time', None),
                    "finish_reason": getattr(ai_message, 'finish_reason', None),
                    "stop_reason": getattr(ai_message, 'stop_reason', None),
                },
                "tool_calls": getattr(ai_message, 'tool_calls', []),
                "sources": getattr(ai_message, 'documents', []) if hasattr(ai_message, 'documents') else []
            }

            if hasattr(ai_message, 'error') and ai_message.error:
                response_data['error'] = ai_message.error
                return self.json_response(response_data, status=400)

            return self.json_response(response_data)

        elif output_mode == OutputMode.HTML:
            # Return formatted HTML
            formatted_content = formatter.format(
                mode=output_mode,
                data=ai_message,
                **(format_kwargs or {})
            )

            # Create complete HTML page
            html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Response</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            max-width: 900px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.6;
            background-color: #f5f5f5;
        }}
        .response-container {{
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .metadata {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #eee;
        }}
        .content {{
            color: #333;
        }}
        .sources {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 0.9em;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        pre {{
            background: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
    </style>
</head>
<body>
    <div class="response-container">
        <div class="metadata">
            <strong>Agent Response</strong>
        </div>
        <div class="content">
            {formatted_content}
        </div>
    </div>
</body>
</html>
            """
            return web.Response(
                text=html_template,
                content_type='text/html',
                charset='utf-8'
            )

        else:
            # Return markdown/plain text
            formatted_content = formatter.format(ai_message, **(format_kwargs or {}))
            return web.Response(
                text=str(formatted_content),
                content_type='text/plain',
                charset='utf-8'
            )

    async def _add_mcp_servers(self, agent: AbstractBot, mcp_configs: list):
        """
        Add MCP servers to the agent if it supports MCP.

        Args:
            agent: The agent instance
            mcp_configs: List of MCP server configurations
        """
        if not hasattr(agent, 'add_mcp_server'):
            self.logger.warning(
                f"Agent {agent.name} does not support MCP servers. "
                "Ensure BasicAgent has MCPEnabledMixin."
            )
            return

        for config_dict in mcp_configs:
            try:
                # Create MCPServerConfig from dict
                config = MCPServerConfig(
                    name=config_dict.get('name'),
                    url=config_dict.get('url'),
                    auth_type=config_dict.get('auth_type'),
                    auth_config=config_dict.get('auth_config', {}),
                    headers=config_dict.get('headers', {}),
                    allowed_tools=config_dict.get('allowed_tools'),
                    blocked_tools=config_dict.get('blocked_tools'),
                )

                tools = await agent.add_mcp_server(config)
                self.logger.info(
                    f"Added MCP server '{config.name}' with {len(tools)} tools to agent {agent.name}"
                )
            except Exception as e:
                self.logger.error("Failed to add MCP server: %s", e)

    async def _add_mcp_servers_to_tool_manager(
        self,
        tool_manager: ToolManager,
        mcp_configs: list
    ) -> None:
        """
        Add MCP servers directly to a ToolManager instance.

        Args:
            tool_manager: ToolManager instance to configure
            mcp_configs: List of MCP server configurations
        """
        for config_dict in mcp_configs:
            try:
                config = MCPServerConfig(
                    name=config_dict.get('name'),
                    url=config_dict.get('url'),
                    auth_type=config_dict.get('auth_type'),
                    auth_config=config_dict.get('auth_config', {}),
                    headers=config_dict.get('headers', {}),
                    allowed_tools=config_dict.get('allowed_tools'),
                    blocked_tools=config_dict.get('blocked_tools'),
                )
                tools = await tool_manager.add_mcp_server(config)
                self.logger.info(
                    "Added MCP server '%s' with %s tools to ToolManager",
                    config.name,
                    len(tools)
                )
            except Exception as e:
                self.logger.error("Failed to add MCP server to ToolManager: %s", e)

    async def _configure_tool_manager(
        self,
        data: Dict[str, Any],
        request_session: Any,
        agent_name: str = None
    ) -> tuple[Union[ToolManager, None], List[Dict[str, Any]]]:
        """
        Configure a ToolManager from request payload or session.

        Delegates to UserObjectsHandler.configure_tool_manager().

        Args:
            data: Request body data (will be mutated)
            request_session: Session object for storing/retrieving ToolManager
            agent_name: Agent name used to namespace the session key

        Returns:
            Tuple of (ToolManager or None, remaining mcp_servers list)
        """
        return await self.user_objects_handler.configure_tool_manager(
            data, request_session, agent_name
        )

    def _check_methods(self, bot: AbstractBot, method_name: str):
        """Check if the method exists in the bot and is callable."""
        forbidden_methods = {
            '__init__', '__del__', '__getattribute__', '__setattr__',
            'configure', '_setup_database_tools', 'save', 'delete',
            'update', 'insert', '__dict__', '__class__', 'retrieval',
            '_define_prompt', 'configure_llm', 'configure_store', 'default_tools'
        }
        if not method_name:
            return None
        if method_name.startswith('_') or method_name in forbidden_methods:
            raise AttributeError(
                f"Method {method_name} error, not found or forbidden."
            )
        if not hasattr(bot, method_name):
            raise AttributeError(
                f"Method {method_name} error, not found or forbidden."
            )
        method = getattr(bot, method_name)
        if not callable(method):
            raise TypeError(
                f"Attribute {method_name} is not callable in bot {bot.name}."
            )
        return method

    @staticmethod
    def _sync_session_pandas(agent, session_tool, dm):
        """Sync callback for session-scoped PythonPandasTool."""
        active_dfs = dm.get_active_dataframes()
        alias_map = dm._get_alias_map()
        session_tool.register_dataframes(active_dfs, alias_map=alias_map)
        # Also update agent-level state for ProphetForecastTool etc.
        agent.dataframes = active_dfs
        agent.df_metadata = {
            name: agent._build_metadata_entry(name, df)
            for name, df in active_dfs.items()
        }
        agent._sync_prophet_tool()
        agent._define_prompt()

    async def _execute_agent_method(
        self,
        bot: AbstractBot,
        method_name: str,
        data: Dict[str, Any],
        attachments: Dict[str, Any],
        use_background: bool,
    ) -> web.Response:
        """Resolve and invoke an agent method safely."""
        try:
            method = self._check_methods(bot, method_name)
        except (AttributeError, TypeError) as exc:
            self.logger.error("Method %s not available: %s", method_name, exc)
            return self.json_response(
                {"error": f"Method {method_name} not available."},
                status=400,
            )

        sig = inspect.signature(method)
        method_params: Dict[str, Any] = {}
        missing_required: List[str] = []
        remaining_kwargs = dict(data)

        for param_name, param in sig.parameters.items():
            if param_name in ['self', 'kwargs']:
                continue

            if param.kind == inspect.Parameter.VAR_POSITIONAL:
                continue
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                continue

            if param_name in remaining_kwargs:
                method_params[param_name] = remaining_kwargs.pop(param_name)
            elif param.default == inspect.Parameter.empty:
                missing_required.append(param_name)

            if param_name in attachments:
                method_params[param_name] = attachments[param_name]
                remaining_kwargs.pop(param_name, None)

        if missing_required:
            return self.json_response(
                {
                    "message": (
                        "Required parameters missing: "
                        f"{', '.join(missing_required)}"
                    ),
                    "required_params": [
                        p for p in sig.parameters.keys() if p != 'self'
                    ],
                },
                status=400,
            )

        final_kwargs = method_params | remaining_kwargs
        try:
            if use_background:
                self.request.app.loop.create_task(method(**final_kwargs))
                return self.json_response(
                    {"message": "Request is being processed in the background."}
                )

            response = await method(**final_kwargs)
            if isinstance(response, web.Response):
                return response

            return self.json_response(
                {
                    "message": (
                        f"Method {method_name} was executed successfully."
                    ),
                    "response": str(response),
                }
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                f"Error calling method {method_name}: {exc}",
                exc_info=True,
            )
            return self.json_response(
                {"error": f"Error calling method {method_name}: {exc}"},
                status=500,
            )

    def _get_agent_name(self, data: dict) -> Union[str, None]:
        """
        Extract agent_name from request data or query string.

        Priority:
        1. Explicit 'agent_name' in request body
        2. 'agent_id' from URL path
        3. 'agent_name' in query string

        Args:
            data: Request body data

        Returns:
            agent_name or None
        """
        agent_name = self.request.match_info.get('agent_id', None)
        if not agent_name:
            agent_name = data.pop('agent_name', None)
        if not agent_name:
            qs = self.query_parameters(self.request)
            agent_name = qs.get('agent_name')
        return agent_name

    async def _notify_ws_channel(
        self,
        channel_id: str,
        message_id: Union[str, None],
        session_id: str
    ):
        """Notify WebSocket channel that answer is ready."""
        try:
            ws_manager = self.request.app.get('user_socket_manager')
            if ws_manager:
                from datetime import datetime, timezone
                await ws_manager.notify_channel(
                    channel_id,
                    {
                        'type': 'answer_ready',
                        'session_id': session_id,
                        'message_id': message_id,
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    }
                )
        except Exception as e:
            self.logger.error("Error notifying WebSocket channel: %s", e)

    async def _get_user_session(self, data: dict) -> tuple[Union[str, None], Union[str, None]]:
        """
        Extract user_id and session_id from data or request context.

        Priority for session_id:
        1. Explicit 'session_id' in request body (conversation-specific)
        2. Generate new UUID (for new conversations)
        Note: We intentionally do NOT use browser session as it causes history mixing

        Priority for user_id:
        1. Explicit 'user_id' in request body
        2. From authenticated user session context

        Args:
            data: Request body data

        Returns:
            Tuple of (user_id, session_id)
        """
        user_id = data.pop('user_id', None) or self.request.get('user_id', None)
        session_id = data.pop('session_id', None)
        # Try to get user_id from request session if not provided
        with contextlib.suppress(AttributeError):
            request_session = self.request.session or await get_session(self.request)
            if not user_id:
                user_id = request_session.get('user_id')
        # Generate new session_id if not provided by client (never use browser session)
        if not session_id:
            session_id = uuid.uuid4().hex
        return user_id, session_id

    async def _get_agent(self, data: Dict[str, Any]) -> Union[AbstractBot, web.Response]:
        """
        Get the agent instance from BotManager.

        Resolution order:
          1. Per-user bot — session cache (set by UserAgentHandler) or DB
             lookup via ``BotManager.get_user_bot``.
          2. System bot — registry / DB via ``BotManager.get_bot``.

        On success returns the bot instance.  The caller can detect a
        user-bot result by checking ``agent.chatbot_id`` against the
        session's ``BotManager.USER_BOTS_SESSION_KEY`` map (see
        :meth:`_resolve_bot`).
        """
        bot, _is_user = await self._resolve_bot(data)
        if isinstance(bot, web.Response):
            return bot
        if bot is None:
            agent_name = self._get_agent_name(data) or "<unknown>"
            return self.error(f"Agent '{agent_name}' not found.", status=404)
        return bot

    async def _resolve_bot(
        self,
        data: Dict[str, Any],
    ) -> Tuple[Optional[AbstractBot], bool]:
        """Resolve a bot, preferring user-defined bots, falling back to system bots.

        Returns ``(bot, is_user_bot)``.  ``bot`` may also be a ``web.Response``
        when an early-return error condition is hit (e.g. BotManager missing).
        """
        manager: BotManager = self.request.app.get('bot_manager')
        if not manager:
            return self.json_response(
                {"error": "BotManager is not installed."}, status=500,
            ), False

        agent_name = self._get_agent_name(data)
        if not agent_name:
            return self.error("Missing Agent Name", status=400), False

        # 1. Per-user bot — session cache or DB lookup.
        try:
            user_bot = await manager.get_user_bot(self.request, agent_name)
        except Exception:  # noqa: BLE001
            user_bot = None
        if user_bot is not None:
            return user_bot, True

        # 2. System bot.
        try:
            agent: AbstractBot = await manager.get_bot(agent_name)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Error retrieving agent %s: %s", agent_name, exc)
            return self.error(f"Error retrieving agent: {exc}", status=500), False
        return agent, False

    async def _setup_agent_tools(
        self,
        agent: AbstractBot,
        data: Dict[str, Any],
        request_session: Any
    ) -> Union[web.Response, None]:
        """
        Configure tool manager and MCP servers from request data.

        Used by PATCH to persist a user's ToolManager into the session.
        The resulting ToolManager is saved under '{agent_name}_tool_manager'.
        """
        try:
            tool_manager, mcp_servers = await self._configure_tool_manager(
                data,
                request_session,
                agent_name=agent.name
            )
        except ValueError as exc:
            return self.error(str(exc), status=400)

        if tool_manager:
            if tool_manager.tool_count() > 0:
                self.logger.info(
                    "Configured ToolManager for agent '%s' with %d tools (session-scoped).",
                    agent.name,
                    tool_manager.tool_count()
                )

        # Add MCP servers directly to the agent if provided standalone
        # PBAC MCP filtering — remove denied MCP servers before registration
        if mcp_servers and isinstance(mcp_servers, list):
            mcp_servers = await self._filter_mcp_servers_for_user(mcp_servers)
            if mcp_servers:
                await self._add_mcp_servers(agent, mcp_servers)

        # Optional MCP server restore.  Agents that set enable_mcp_restore=True
        # have previously-saved MCP server configurations automatically
        # re-connected on every new session (PATCH).
        if getattr(agent, "enable_mcp_restore", False):
            await self._restore_user_mcp_servers(
                tool_manager=tool_manager,
                request_session=request_session,
                agent_name=agent.name,
            )

        # Optional Jira OAuth 2.0 (3LO) session bootstrap.  Agents that want
        # per-user Jira tokens expose ``jira_credential_resolver`` (and an
        # optional ``jira_toolkit_factory``).  When present, we register
        # either the full toolkit (tokens already on file) or the
        # ``JiraConnectTool`` placeholder (user has not authorised yet).
        await self._bootstrap_jira_oauth_session(
            agent=agent,
            tool_manager=tool_manager,
            request_session=request_session,
        )

        return tool_manager

    async def _bootstrap_jira_oauth_session(
        self,
        agent: AbstractBot,
        tool_manager: Any,
        request_session: Any,
    ) -> None:
        """Register Jira OAuth 2.0 (3LO) tools on the session's ToolManager.

        Opt-in: this only runs when the agent exposes a
        ``jira_credential_resolver`` attribute (e.g., an
        ``OAuthCredentialResolver`` wrapping a ``JiraOAuthManager``).  It is
        safe to call unconditionally — agents without the attribute are
        left untouched.
        """
        resolver = getattr(agent, "jira_credential_resolver", None)
        if resolver is None or tool_manager is None:
            return

        user_id = None
        for attr in ("user_id", "id", "username"):
            if hasattr(request_session, attr):
                user_id = getattr(request_session, attr)
                break
        if not user_id:
            self.logger.debug(
                "Jira OAuth bootstrap skipped: no user_id on request_session",
            )
            return

        from ..tools.jira_connect_tool import setup_jira_oauth_session

        try:
            await setup_jira_oauth_session(
                tool_manager,
                resolver,
                channel="agentalk",
                user_id=str(user_id),
                build_full_toolkit=getattr(
                    agent, "jira_toolkit_factory", None,
                ),
            )
        except Exception:  # noqa: BLE001 - must never break session setup
            self.logger.exception(
                "Failed to bootstrap Jira OAuth session for user %s", user_id,
            )

    async def _restore_user_mcp_servers(
        self,
        tool_manager: Any,
        request_session: Any,
        agent_name: str,
    ) -> None:
        """Restore previously-saved MCP server configurations from persistence.

        Runs during :meth:`_setup_agent_tools` for agents that opt in by setting
        ``enable_mcp_restore = True``.  For each saved :class:`UserMCPServerConfig`:

        1. Retrieves the Vault credential (if any) from DocumentDB.
        2. Calls the appropriate ``create_*`` factory function.
        3. Registers the resulting config on the session ToolManager.

        Failures are logged as ``WARNING`` and do **not** abort the PATCH — the
        restore is best-effort.  If ``tool_manager`` is ``None`` or the user ID
        cannot be extracted, the method is a no-op.

        Args:
            tool_manager: Session-scoped ToolManager to register tools on.
                If ``None``, the method returns immediately.
            request_session: The authenticated session object.  Used to extract
                the ``user_id``.
            agent_name: Agent name used as the session key prefix (also the
                ``agent_id`` for persisted configs).
        """
        if tool_manager is None:
            return

        # Extract user_id from session (same pattern as _bootstrap_jira_oauth_session)
        user_id = None
        for attr in ("user_id", "id", "username"):
            if hasattr(request_session, attr):
                user_id = getattr(request_session, attr)
                break

        if not user_id:
            self.logger.debug(
                "MCP restore skipped: no user_id on request_session",
            )
            return

        user_id = str(user_id)

        # Load saved configs from DocumentDB
        persistence = _MCPPersistenceService()
        try:
            saved_configs = await persistence.load_user_mcp_configs(
                user_id=user_id,
                agent_id=agent_name,
            )
        except Exception as exc:
            self.logger.warning(
                "MCP restore: failed to load configs for user='%s' agent='%s': %s",
                user_id,
                agent_name,
                exc,
            )
            return

        if not saved_configs:
            return

        _restore_factory_map = _get_factory_map()

        # Load vault keys once for all secrets retrieval
        try:
            from navigator_session.vault.config import load_master_keys
            master_keys = load_master_keys()
        except Exception as exc:
            self.logger.warning(
                "MCP restore: vault unavailable, skipping restore: %s", exc
            )
            return

        for config in saved_configs:
            try:
                factory_fn = _restore_factory_map.get(config.server_name)
                if factory_fn is None:
                    self.logger.debug(
                        "MCP restore: no factory for server '%s', skipping",
                        config.server_name,
                    )
                    continue

                # Retrieve and decrypt secrets from Vault if needed
                secret_params: Dict[str, Any] = {}
                if config.vault_credential_name:
                    try:
                        async with DocumentDb() as db:
                            doc = await db.read_one(
                                "user_credentials",
                                {
                                    "user_id": user_id,
                                    "name": config.vault_credential_name,
                                },
                            )
                        if doc is None:
                            self.logger.warning(
                                "MCP restore: Vault credential '%s' missing "
                                "for server '%s', skipping",
                                config.vault_credential_name,
                                config.server_name,
                            )
                            continue
                        secret_params = _decrypt_credential(doc["credential"], master_keys)
                    except Exception as exc:
                        self.logger.warning(
                            "MCP restore: failed to decrypt Vault credential "
                            "'%s' for server '%s': %s",
                            config.vault_credential_name,
                            config.server_name,
                            exc,
                        )
                        continue

                # Build MCP config and register on ToolManager
                factory_kwargs = {**config.params, **secret_params}
                mcp_config = factory_fn(**factory_kwargs)
                tools = await tool_manager.add_mcp_server(mcp_config)
                self.logger.info(
                    "MCP restore: restored '%s' with %d tool(s) for user='%s'",
                    config.server_name,
                    len(tools),
                    user_id,
                )

            except Exception as exc:
                self.logger.warning(
                    "MCP restore: failed to restore server '%s' for user='%s': %s",
                    config.server_name,
                    user_id,
                    exc,
                )
                # Continue with remaining servers — never fail the PATCH

    async def _handle_attachments(
        self,
        bot: AbstractBot,
        agent: AbstractBot,
        attachments: Dict[str, Any]
    ) -> web.Response:
        """
        Manage file uploaded into a internal private method.
        """
        if attachments:
            # Handle file uploads without a query
            try:
                added_files = await bot.handle_files(attachments)
                return self.json_response({
                    "message": "Files uploaded successfully",
                    "added_files": added_files,
                    "agent": agent.name
                })
            except Exception as e:
                self.logger.error("Error handling files: %s", e, exc_info=True)
                return self.json_response(
                    {"error": f"Error handling files: {str(e)}"},
                    status=500
                )
        return self.json_response(
            {"error": "query is required"},
            status=400
        )

    async def _handle_hitl_resume(
        self,
        hitl_response: dict,
        agent: Any,
        session_id: Optional[str],
        user_id: Optional[str],
        request_session: Any,
    ) -> web.Response:
        """Handle a HITL resume request (FEAT-204).

        Called when ``AgentTalk.post`` detects a ``hitl_response`` tag in the
        request body.  Validates the respondent, performs the three-state
        TTL/tombstone check, routes the answer through the manager, loads the
        suspended tool-loop state, and calls ``agent.resume()`` to continue
        the agent run to a final ``success`` response.

        Args:
            hitl_response: The ``hitl_response`` body dict with keys
                ``turn_id`` (interaction_id), ``value``, and optionally
                ``response_type``.
            agent: The resolved ``AbstractBot`` for this request.
            session_id: The user's session identifier.
            user_id: The authenticated user ID.
            request_session: The request session object (for respondent lookup).

        Returns:
            An HTTP 200 JSON response — either the resumed ``success`` reply
            or an informational ``expired``/``already_answered`` envelope.
        """
        # ── 0. Set current_web_session ContextVar ────────────────────────
        # Ensures that chained multi-turn HITL (a second ask_human during
        # resume) can resolve the web session correctly via the ContextVar.
        # Cleared in the finally block below.
        _resume_hitl_token = set_current_web_session(session_id)
        try:
            return await self._handle_hitl_resume_inner(
                hitl_response=hitl_response,
                agent=agent,
                session_id=session_id,
                user_id=user_id,
                request_session=request_session,
            )
        finally:
            reset_current_web_session(_resume_hitl_token)

    async def _handle_hitl_resume_inner(
        self,
        hitl_response: dict,
        agent: Any,
        session_id: Optional[str],
        user_id: Optional[str],
        request_session: Any,
    ) -> web.Response:
        """Inner implementation of _handle_hitl_resume (ContextVar already set)."""
        # Lazy imports — keep module-level free of parrot.human dependency.
        from parrot.human import get_default_human_manager as _gm  # noqa: PLC0415
        from parrot.human.models import HumanResponse, InteractionType  # noqa: PLC0415
        from parrot.human.suspended_store import SuspendedExecutionStore  # noqa: PLC0415

        # ── 1. Parse hitl_response body ──────────────────────────────────
        turn_id: str = hitl_response.get("turn_id", "")
        value = hitl_response.get("value")
        response_type_raw: Optional[str] = hitl_response.get("response_type")
        # OQ-1: turn_id == interaction_id (one correlation contract)
        interaction_id: str = turn_id

        if not interaction_id:
            return web.json_response(
                {"status": "error", "message": "hitl_response.turn_id is required"},
                status=400,
            )

        # ── 2. Respondent from authenticated session only ─────────────────
        respondent: str = "unknown"
        try:
            if request_session:
                respondent = request_session.get("user_id", "unknown")
        except AttributeError:
            pass
        if respondent == "unknown" or not respondent:
            self.logger.warning(
                "AgentTalk resume: unauthenticated resume attempt for %s",
                interaction_id,
            )
            return web.json_response(
                {"status": "error", "message": "unauthenticated"},
                status=403,
            )

        # ── 3. Manager lookup ─────────────────────────────────────────────
        hitl_manager = _gm()
        if hitl_manager is None:
            return web.json_response(
                {"status": "error", "message": "HITL service unavailable"},
                status=503,
            )

        # ── 4. Three-state TTL/tombstone check (BEFORE respondent gate) ─────
        #   - hitl:result exists  → already answered (idempotency tombstone)
        #   - hitl:interaction exists, no result → alive → proceed to gate
        #   - neither exists → expired (fast informational reply)
        # Checking TTL first lets expired interactions return "expired" rather
        # than "forbidden" (which would be misleading when the key just expired).
        existing_result = await hitl_manager.get_result(interaction_id)
        if existing_result is not None:
            self.logger.info(
                "AgentTalk resume: interaction %s already answered (tombstone)",
                interaction_id,
            )
            return web.json_response(
                {"status": "already_answered", "interaction_id": interaction_id},
                status=200,
            )

        interaction_alive = await hitl_manager._load_interaction(interaction_id)
        if interaction_alive is None:
            self.logger.info(
                "AgentTalk resume: interaction %s expired (no key in Redis)",
                interaction_id,
            )
            return web.json_response(
                {"status": "expired", "interaction_id": interaction_id},
                status=200,
            )

        # ── 5. is_valid_respondent gate (after TTL check, before write) ───
        if not await hitl_manager.is_valid_respondent(interaction_id, respondent):
            self.logger.warning(
                "AgentTalk resume: respondent '%s' rejected for interaction %s",
                respondent,
                interaction_id,
            )
            return web.json_response(
                {"status": "error", "message": "forbidden: not the intended respondent"},
                status=403,
            )

        # ── 6. Record the response in the HITL ledger ─────────────────────
        response_type: "InteractionType" = (
            interaction_alive.interaction_type
        )
        if response_type_raw:
            try:
                response_type = InteractionType(response_type_raw)
            except ValueError:
                response_type = InteractionType.FREE_TEXT

        human_response = HumanResponse(
            interaction_id=interaction_id,
            respondent=respondent,
            response_type=response_type,
            value=value,
        )
        await hitl_manager.receive_response(human_response)
        self.logger.info(
            "AgentTalk resume: recorded response for interaction %s by %s",
            interaction_id,
            respondent,
        )

        # ── 7. Load suspended state and resume the agent ──────────────────
        redis_client = await hitl_manager._get_redis()
        sus_store = SuspendedExecutionStore(redis_client)
        suspended = await sus_store.load(interaction_id)
        if suspended is None:
            self.logger.error(
                "AgentTalk resume: SuspendedExecution missing for %s — "
                "cannot resume tool-loop",
                interaction_id,
            )
            return web.json_response(
                {"status": "error", "message": "suspended state not found"},
                status=500,
            )

        resume_state = {
            "session_id": suspended.session_id,
            "messages": suspended.messages,
            "tool_call_id": suspended.tool_call_id,
            "agent_name": suspended.agent_name,
        }

        self.logger.info(
            "AgentTalk resume: calling agent.resume for session %s "
            "(interaction=%s, tool_call_id=%s)",
            suspended.session_id,
            interaction_id,
            suspended.tool_call_id,
        )

        # Delete the suspended-state blob BEFORE calling agent.resume().
        # If resume raises, the tombstone prevents a duplicate resume attempt —
        # which is the correct conservative behaviour (one-shot guarantee).
        await sus_store.delete(interaction_id)

        try:
            async with agent.session(
                session_id=suspended.session_id,
                user_id=suspended.user_id or user_id,
            ) as bot:
                ai_message = await bot.resume(
                    session_id=suspended.session_id,
                    user_input=str(value) if value is not None else "",
                    state=resume_state,
                )
        except HumanInteractionInterrupt:
            # A second ask_human during resume → let the TASK-1382 catch handle it
            # by re-raising (the caller AgentTalk.post except block will catch it).
            raise
        except Exception as exc:
            self.logger.exception(
                "AgentTalk resume: agent.resume failed for session %s: %s",
                suspended.session_id,
                exc,
            )
            return web.json_response(
                {"status": "error", "message": f"resume failed: {exc}"},
                status=500,
            )

        # Return the resumed response as a normal success reply.
        return self._format_response(
            ai_message,
            "json",
            {},
            user_id=suspended.user_id or user_id,
            user_session=session_id,
            response_time_ms=None,
            agent_name=suspended.agent_name or (agent.name if agent else ""),
            session_id=session_id,
            client_message_id=None,
        )

    async def post(self):
        """
        POST handler for agent interaction. PBAC-guarded via requires_permission.

        Endpoint: POST /api/v1/agents/chat/{agent_id}

        Access is checked against PBAC policies for ``agent:chat`` action.
        If PBAC is not configured, access is allowed (backward compatible).

        Request body::

            {
                "agent_name": "my_agent",
                "query": "What is the weather like?",
                "session_id": "optional-session-id",
                "user_id": "optional-user-id",
                "stream": false,
                "output_mode": "json|html|markdown|terminal|default",
                "search_type": "similarity",
                "use_vector_context": true,
                "format_kwargs": {
                    "show_metadata": true,
                    "show_sources": true
                }
            }

        If the user's session contains a ToolManager (configured via PATCH),
        it will temporarily replace the agent's built-in ToolManager for the
        duration of this request and be restored afterwards.

        .. deprecated::
            Passing ``tools``, ``mcp_servers``, or ``tool_config`` inline in
            POST is deprecated.  Use ``PATCH /api/v1/agents/chat/{agent_id}``
            to configure tools and MCP servers instead.

        Returns:
        - JSON response if output_mode is 'json' or Accept header is application/json
        - HTML page if output_mode is 'html' or Accept header is text/html
        - Markdown/plain text otherwise
        - When ``stream=true``: HTTP chunked ``text/plain`` response.  Text
          chunks arrive progressively; the final chunk (after a ``\\n\\x00``
          separator) is a JSON object with the AIMessage metadata envelope.
        """
        qs = self.query_parameters(self.request)
        app = self.request.app
        method_name = self.request.match_info.get('method_name', None)

        # PBAC agent access guard — real-time policy evaluation (agent:chat)
        agent_id_param = self.request.match_info.get('agent_id', '*')
        pbac_denied = await self._check_pbac_agent_access(
            agent_id=agent_id_param,
            action="agent:chat",
        )
        if pbac_denied is not None:
            return pbac_denied

        try:
            attachments, data = await self.handle_upload()
        except web.HTTPUnsupportedMediaType:
            # if no file is provided, then is a JSON request:
            data = await self.request.json()
            attachments = {}

        # Method for extract session and user information:
        user_id, user_session = await self._get_user_session(data)
        request_session = None
        with contextlib.suppress(AttributeError):
            request_session = self.request.session or await get_session(self.request)

        # conversation (session_id) — already extracted by _get_user_session()
        session_id = user_session
        # Support method invocation via body or query parameter in addition to the
        # /{agent_id}/{method_name} route so clients don't need to construct a
        # different URL for maintenance operations like refresh_data.
        method_name = (
            method_name or data.pop('method_name', None) or qs.get('method_name')
        )
        # Get the agent — user bots win over system bots when both could match.
        agent_or_response, is_user_bot = await self._resolve_bot(data)
        if isinstance(agent_or_response, web.Response):
            return agent_or_response
        if agent_or_response is None:
            agent_name = self._get_agent_name(data) or "<unknown>"
            return self.error(f"Agent '{agent_name}' not found.", status=404)
        agent: AbstractBot = agent_or_response

        # Load user's tool_manager from session (configured via PATCH).
        # User-defined bots own their own ToolManager in the session cache
        # (built when the bot was instantiated from the DB row), so the
        # per-system-bot ToolManager swap is not applicable to them.
        user_tool_manager = None
        if request_session and not is_user_bot:
            session_key = f"{agent.name}_tool_manager"
            user_tool_manager = request_session.get(session_key)

        # PBAC tool filtering — filter session-scoped ToolManager by policy
        # Only modify the session-scoped clone, never the agent's original
        if user_tool_manager is not None and isinstance(user_tool_manager, ToolManager):
            await self._filter_tools_for_user(user_tool_manager)

        # Deprecation: strip inline tool config from POST body to prevent
        # leaking into **kwargs, but warn that PATCH should be used instead.
        for _dep_key in ('tools', 'mcp_servers', 'tool_config'):
            if _dep_key in data:
                data.pop(_dep_key)
                self.logger.warning(
                    "POST with '%s' is deprecated. Use PATCH /api/v1/agents/chat/%s "
                    "to configure tools and MCP servers.",
                    _dep_key,
                    agent.name,
                )

        query = data.pop('query', None)
        # task background:
        use_background = data.pop('background', False)
        # Chunked HTTP streaming (no SSE/WS/NDJSON):
        use_stream = data.pop('stream', False)

        # Determine output mode
        # output_mode = self._get_output_mode(self.request)
        # Determine output format
        output_format = self._get_output_format(data, qs)
        # Coerce the request's output_mode to a valid OutputMode enum member.
        # Unknown values (e.g. a frontend mode the backend doesn't implement)
        # fall back to DEFAULT instead of leaking a raw string into bot.ask(),
        # which would crash the renderer dispatch with "No renderer registered".
        output_mode = data.pop('output_mode', OutputMode.DEFAULT)
        if isinstance(output_mode, str):
            try:
                output_mode = OutputMode(output_mode.lower())
            except ValueError:
                self.logger.warning(
                    "Unknown output_mode '%s' in request; falling back to DEFAULT.",
                    output_mode,
                )
                output_mode = OutputMode.DEFAULT

        # Extract parameters for ask()
        search_type = data.pop('search_type', 'similarity')
        return_sources = data.pop('return_sources', True)
        use_vector_context = data.pop('use_vector_context', True)
        use_conversation_history = data.pop('use_conversation_history', True)
        # Client-generated message ID — used as turn_id in ChatStorage
        # so frontend and backend share the same identifier for dedup.
        client_message_id = data.pop('message_id', None)
        followup_turn_id = data.pop('turn_id', None)
        followup_data = data.pop('data', None)
        # FEAT-249 Mode B: opt-in backend bifurcation.  When True and a FULL
        # mode session is active, structured outputs are published via the Redis
        # transport to the /ws/userinfo channel keyed by session_id.  Default
        # False — frontend-driven path is unchanged when this flag is absent.
        avatar_bifurcate: bool = bool(data.pop('avatar_bifurcate', False))

        # FEAT-204: HITL resume branch — detect hitl_response tag in the body.
        # Shape: {"hitl_response": {"turn_id": "<interaction_id>", "value": ...,
        #                           "response_type": "<optional>"}}
        # Handled BEFORE bot.ask() so the resume can run to a success reply
        # on the same request that carries the human's answer.
        hitl_response = data.pop('hitl_response', None)
        if hitl_response is not None:
            return await self._handle_hitl_resume(
                hitl_response=hitl_response,
                agent=agent,
                session_id=session_id,
                user_id=user_id,
                request_session=request_session,
            )

        # FEAT-197: Infographic mode is not compatible with streaming — the
        # final envelope must carry the signed URL atomically.
        if output_mode in (OutputMode.INFOGRAPHIC, OutputMode.INTERACTIVE):
            # These modes attach an artifact (signed URL) that must be delivered
            # atomically in the final envelope — incompatible with streaming.
            use_stream = False  # force-disable streaming for these modes

        # Prepare ask() parameters
        format_kwargs = data.pop('format_kwargs', {})
        response = None

        # Extract Custom LLM
        if llm := data.pop('llm', None):
            # TODO: check if is a supported LLM and configure it for the agent
            pass

        # Extract ws_channel_id for notification
        ws_channel_id = data.pop('ws_channel_id', None)

        # FEAT-146: Set the current_web_session ContextVar so WebHumanTool can
        # resolve the active WebSocket channel without being passed it explicitly.
        # Reset in the finally block below to ensure clean teardown.
        _hitl_token = set_current_web_session(ws_channel_id or session_id)
        start_time = time.perf_counter()  # safe default; overwritten inside try

        # --- WebSearchAgent-specific flags ---
        _ws_originals = {}  # saved originals for restore
        if isinstance(agent, WebSearchAgent):
            _ws_flag_keys = {
                'contrastive_search': bool,
                'contrastive_prompt': str,
                'synthesize': bool,
                'synthesize_prompt': str,
            }
            for key, expected_type in _ws_flag_keys.items():
                if key in data:
                    value = data.pop(key)
                    _ws_originals[key] = getattr(agent, key, None)
                    setattr(agent, key, expected_type(value))
            if _ws_originals:
                self.logger.info(
                    "WebSearchAgent '%s': applied per-request flags: %s",
                    agent.name,
                    list(_ws_originals.keys()),
                )

        # Use RedisConversation for history management if session_id is present
        memory = None
        if user_id and session_id:
            try:
                memory = RedisConversation()
            except Exception as ex:
                self.logger.warning(
                    f"Failed to initialize RedisConversation: {ex}"
                )

        # Temporarily swap in user's ToolManager if configured via PATCH
        original_tool_manager = agent.tool_manager
        original_enable_tools = agent.enable_tools
        if user_tool_manager:
            agent.tool_manager = user_tool_manager
            if user_tool_manager.tool_count() > 0:
                agent.enable_tools = True
            with contextlib.suppress(Exception):
                agent.sync_tools()
            self.logger.debug(
                "Swapped agent '%s' tool_manager with user's session ToolManager (%d tools).",
                agent.name,
                user_tool_manager.tool_count(),
            )

        # Configure session-scoped DatasetManager for PandasAgent
        original_dataset_manager = None
        user_dataset_manager = None
        # Import PandasAgent here to avoid circular imports
        from ..bots.data import PandasAgent
        if isinstance(agent, PandasAgent):
            original_dataset_manager = getattr(agent, '_dataset_manager', None)
            user_dataset_manager = await self.user_objects_handler.configure_dataset_manager(
                request_session,
                agent,
                agent_name=agent.name
            )
            if user_dataset_manager:
                # PBAC dataset filtering — remove denied datasets before agent receives them
                await self._filter_datasets_for_user(user_dataset_manager)
                agent.attach_dm(user_dataset_manager)
                # Evict table source DataFrames from the previous turn.
                # Table sources hold query-specific data (columns/filters vary
                # per SQL) so the LLM must call fetch_dataset again with a
                # fresh SQL appropriate to the new question.
                evicted = user_dataset_manager.evict_table_sources()
                self.logger.debug(
                    "Attached session DatasetManager to agent '%s' "
                    "(%d datasets, evicted %d stale table sources).",
                    agent.name,
                    len(user_dataset_manager.list_dataframes()),
                    evicted,
                )

        # Create session-isolated PythonPandasTool so concurrent requests
        # don't share/overwrite each other's DataFrames in locals/globals.
        original_pandas_tool = None
        session_pandas_tool = None
        if isinstance(agent, PandasAgent):
            original_pandas_tool = agent._get_python_pandas_tool()
            if original_pandas_tool:
                dm = user_dataset_manager or getattr(agent, '_dataset_manager', None)
                session_pandas_tool = original_pandas_tool.create_session_clone(
                    dataset_manager=dm,
                )
                # Swap in the ToolManager
                agent.tool_manager._tools[session_pandas_tool.name] = session_pandas_tool
                # Point the sync callback and repl_locals at the session tool
                if dm:
                    dm.set_on_change(
                        lambda: self._sync_session_pandas(agent, session_pandas_tool, dm)
                    )
                    dm.set_repl_locals_getter(lambda: session_pandas_tool.locals)
                self.logger.debug(
                    "Created session-isolated PythonPandasTool for agent '%s'.",
                    agent.name,
                )

        try:
            async with agent.session(request=self.request, app=app, user_id=user_id, session_id=user_session) as bot:
                if method_name:
                    return await self._execute_agent_method(
                        bot=bot,
                        method_name=method_name,
                        data=data,
                        attachments=attachments,
                        use_background=use_background,
                    )
                if not query:
                    return await self._handle_attachments(bot, agent, attachments)
                if use_stream:
                    return await self._handle_stream_response(
                        bot=bot,
                        query=query,
                        session_id=session_id,
                        user_id=user_id,
                        search_type=search_type,
                        return_sources=return_sources,
                        use_vector_context=use_vector_context,
                        use_conversation_history=use_conversation_history,
                        output_mode=output_mode,
                        format_kwargs=format_kwargs,
                        memory=memory,
                        llm=llm,
                        agent_name=agent.name,
                        client_message_id=client_message_id,
                        avatar_bifurcate=avatar_bifurcate,
                        **data,
                    )
                if followup_turn_id and followup_data is not None:
                    start_time = time.perf_counter()
                    response: AIMessage = await bot.followup(
                        question=query,
                        turn_id=followup_turn_id,
                        data=followup_data,
                        session_id=session_id,
                        user_id=user_id,
                        llm=llm,
                        use_conversation_history=use_conversation_history,
                        output_mode=output_mode,
                        format_kwargs=format_kwargs,
                        memory=memory,
                        **data,
                    )
                else:
                    start_time = time.perf_counter()
                    # NOTE (FEAT-249 Mode B): avatar_bifurcate is intentionally
                    # a no-op on this non-streaming path.  FULL mode always
                    # streams, so structured-output publishing via Redis only
                    # happens inside _handle_stream_response above.
                    response: AIMessage = await bot.ask(
                        question=query,
                        session_id=session_id,
                        user_id=user_id,
                        search_type=search_type,
                        return_sources=return_sources,
                        use_vector_context=use_vector_context,
                        use_conversation_history=use_conversation_history,
                        output_mode=output_mode,
                        format_kwargs=format_kwargs,
                        memory=memory,
                        llm=llm,
                        **data,
                    )
        except AuthorizationRequired as exc:
            # Translate the exception into a structured envelope so the web
            # frontend can render a "Connect" pill.  HTTP 200 — the chat call
            # succeeded; the envelope IS the agent's reply.
            envelope = AuthRequiredEnvelope(
                provider=exc.provider,
                tool_name=exc.tool_name,
                auth_url=exc.auth_url,
                scopes=exc.scopes or [],
                message=str(exc),
            )
            return web.json_response(envelope.model_dump(), status=200)
        except HumanInteractionInterrupt as exc:
            # FEAT-204: SUSPEND path — the agent's SuspendingWebHumanTool raised
            # this interrupt instead of blocking.  Persist the tool-loop state,
            # rehydrate the interaction, and return a structured paused envelope.
            # HTTP 200 — the paused envelope IS the agent's turn.
            interaction_id = exc.interaction_id or ""
            _agent_name = exc.agent_name or (agent.name if agent else "") or ""
            self.logger.info(
                "AgentTalk: HITL suspend for interaction %s (agent=%s)",
                interaction_id,
                _agent_name,
            )
            # Initialise defaults in case manager/interaction are unavailable.
            interaction_type_str = "free_text"
            question = exc.prompt or ""
            context = None
            options = None
            form_schema = None
            default_response = None
            deadline = None
            try:
                # Lazy imports to avoid module-level dependency on parrot.human
                # (which would prevent agent.py from loading in environments
                # where the worktree parrot.human is not first on sys.path).
                from parrot.human import get_default_human_manager as _get_manager  # noqa: PLC0415
                from parrot.human.suspended_store import (  # noqa: PLC0415
                    SuspendedExecution, SuspendedExecutionStore
                )
                hitl_manager = _get_manager()
                if hitl_manager is not None and interaction_id:
                    # 1. Build and persist the SuspendedExecution blob.
                    redis_client = await hitl_manager._get_redis()
                    sus_store = SuspendedExecutionStore(redis_client)
                    suspended = SuspendedExecution(
                        interaction_id=interaction_id,
                        session_id=session_id or "",
                        user_id=user_id or "",
                        agent_name=_agent_name,
                        tool_call_id=exc.tool_call_id or "",
                        messages=exc.messages or [],
                    )
                    # 2. Rehydrate the HumanInteraction for type/options/schema.
                    interaction_obj = await hitl_manager._load_interaction(interaction_id)
                    ttl = _DEFAULT_HITL_SUSPEND_TTL  # default fallback (2h + 60s)
                    if interaction_obj is not None:
                        ttl = hitl_manager._compute_ttl(interaction_obj)
                        interaction_type_str = interaction_obj.interaction_type.value
                        question = interaction_obj.question
                        context = interaction_obj.context
                        if interaction_obj.options:
                            options = [
                                o.model_dump() if hasattr(o, "model_dump") else dict(o)
                                for o in interaction_obj.options
                            ]
                        form_schema = interaction_obj.form_schema
                        default_response = interaction_obj.default_response
                        import datetime as _dt
                        # Use the same TTL value already computed for Redis
                        # (which includes the 60s buffer and policy-chain logic)
                        # so the deadline is aligned with actual key expiry.
                        deadline = (
                            _dt.datetime.now(_dt.timezone.utc)
                            + _dt.timedelta(seconds=ttl)
                        ).isoformat()
                    await sus_store.save(suspended, ttl=ttl)
                    self.logger.info(
                        "AgentTalk: persisted SuspendedExecution %s (ttl=%ds)",
                        interaction_id,
                        ttl,
                    )
                else:
                    self.logger.warning(
                        "AgentTalk: no HITL manager or interaction_id — "
                        "PausedEnvelope will have minimal data"
                    )
            except Exception as inner_exc:
                self.logger.exception(
                    "AgentTalk: error persisting/rehydrating suspend state "
                    "for interaction %s: %s",
                    interaction_id,
                    inner_exc,
                )
                # A broken PausedEnvelope (empty question, no options) would
                # leave the frontend in an irrecoverable state.  Return HTTP 500
                # so the client can surface a meaningful error.
                return web.json_response(
                    {
                        "status": "error",
                        "message": (
                            f"Failed to persist suspend state for interaction "
                            f"{interaction_id}: {inner_exc}"
                        ),
                    },
                    status=500,
                )
            # 3. Build and return the PausedEnvelope.
            #    turn_id == interaction_id (OQ-1: shared correlation contract).
            paused = PausedEnvelope(
                turn_id=interaction_id,
                interaction_id=interaction_id,
                interaction_type=interaction_type_str,
                question=question,
                context=context,
                options=options,
                form_schema=form_schema,
                default_response=default_response,
                deadline=deadline,
                source_agent=_agent_name or None,
            )
            return web.json_response(paused.model_dump(), status=200)
        finally:
            # Restore session-isolated PythonPandasTool
            if original_pandas_tool and session_pandas_tool:
                agent.tool_manager._tools[original_pandas_tool.name] = original_pandas_tool
                self.logger.debug(
                    "Restored agent '%s' original PythonPandasTool.",
                    agent.name,
                )
            # Restore agent's original tool_manager
            if user_tool_manager:
                agent.tool_manager = original_tool_manager
                agent.enable_tools = original_enable_tools
                with contextlib.suppress(Exception):
                    agent.sync_tools()
                self.logger.debug(
                    "Restored agent '%s' original tool_manager.",
                    agent.name,
                )
            # Restore agent's original DatasetManager for PandasAgent
            if user_dataset_manager and original_dataset_manager is not None:
                agent.attach_dm(original_dataset_manager)
                self.logger.debug(
                    "Restored agent '%s' original DatasetManager.",
                    agent.name,
                )
            # Restore WebSearchAgent flags
            for key, original_value in _ws_originals.items():
                setattr(agent, key, original_value)
            # FEAT-146: Reset the current_web_session ContextVar
            reset_current_web_session(_hitl_token)
        response_time_ms = int((time.perf_counter() - start_time) * 1000)

        # Notify WebSocket channel if requested
        if ws_channel_id:
            await self._notify_ws_channel(
                ws_channel_id,
                message_id=getattr(response, 'turn_id', None) if response else None,
                session_id=session_id or getattr(response, 'session_id', None)
            )

        # FEAT-242: non-streaming path — speak the full reply through an active
        # avatar session in the background (the streaming path speaks
        # per-sentence in _handle_stream_response). Best-effort; never blocks
        # or fails the text reply.
        if response is not None:
            await self._speak_text_to_avatar(
                session_id, getattr(response, 'response', None) or ''
            )

        # Return formatted response
        return self._format_response(
            response,
            output_format,
            format_kwargs,
            user_id=user_id,
            user_session=user_session,
            response_time_ms=response_time_ms if response else None,
            agent_name=agent.name,
            session_id=session_id,
            client_message_id=client_message_id,
        )

    async def patch(self):
        """
        PATCH /api/v1/agents/chat/{agent_id} — PBAC-guarded via agent:configure.

        Configures the agent's tool manager and/or refreshes agent data.
        Access is checked against PBAC policies for the ``agent:configure``
        action.  If PBAC is not configured, access is allowed (backward
        compatible).

        Tool configuration request body::

            {
                "tools": [...],
                "mcp_servers": [
                    {
                        "name": "weather_api",
                        "url": "https://api.example.com/mcp",
                        "auth_type": "api_key",
                        "auth_config": {"api_key": "xxx"},
                        "headers": {"User-Agent": "AI-Parrot/1.0"}
                    }
                ]
            }

        The resulting ``ToolManager`` is stored in the user's session under
        the key ``{agent_id}_tool_manager`` and will be used by subsequent
        POST requests for this agent.

        If no tool/MCP configuration keys are present, falls through to
        the existing ``refresh_data`` logic.
        """
        agent_name = self.request.match_info.get('agent_id', None)
        if not agent_name:
            return self.error("Missing Agent Name.", status=400)

        # PBAC agent access guard — agent:configure action
        pbac_denied = await self._check_pbac_agent_access(
            agent_id=agent_name,
            action="agent:configure",
        )
        if pbac_denied is not None:
            return pbac_denied

        manager: BotManager = self.request.app.get('bot_manager')
        if not manager:
            return self.json_response(
                {"error": "BotManager is not installed."},
                status=500
            )

        try:
            data = await self.request.json()
        except Exception:
            data = {}

        try:
            agent: AbstractBot = await manager.get_bot(agent_name)
            if not agent:
                return self.error(f"Agent '{agent_name}' not found.", status=404)
        except Exception as e:
            self.logger.error("Error retrieving agent %s: %s", agent_name, e)
            return self.error(f"Error retrieving agent: {e}", status=500)

        # --- Tool / MCP configuration branch ---
        has_tool_config = any(
            key in data for key in ('tools', 'mcp_servers', 'tool_config')
        )
        if has_tool_config:
            request_session = None
            with contextlib.suppress(AttributeError):
                request_session = self.request.session or await get_session(self.request)

            result = await self._setup_agent_tools(agent, data, request_session)
            if isinstance(result, web.Response):
                return result

            # Build summary for the response
            tool_manager = result
            summary: Dict[str, Any] = {
                "agent": agent_name,
                "message": "Tool configuration saved to session.",
                "session_key": f"{agent_name}_tool_manager",
            }
            if tool_manager and isinstance(tool_manager, ToolManager):
                summary["tool_count"] = tool_manager.tool_count()
                summary["tools"] = list(tool_manager.list_tools())

            return self.json_response(summary, status=200)

        # --- Refresh data branch (original behaviour) ---
        try:
            if not hasattr(agent, 'refresh_data') or not callable(agent.refresh_data):
                return self.json_response(
                    {"message": "Agent doesn't have 'Refresh' method."},
                    status=200
                )

            result = await agent.refresh_data()

            if not result:
                return web.Response(status=204)

            response_data = {}
            if isinstance(result, dict):
                for name, df in result.items():
                    if hasattr(df, 'shape'):
                        response_data[name] = {
                            "rows": df.shape[0],
                            "columns": df.shape[1]
                        }
                    else:
                        response_data[name] = "Refreshed"

            return self.json_response(
                {
                    "message": "Agent data refreshed successfully.",
                    "refreshed_data": response_data
                },
                status=200
            )
        except Exception as e:
            self.logger.error("Error refreshing agent %s: %s", agent_name, e)
            return self.error(f"Error refreshing agent: {e}", status=500)

    async def put(self):
        """
        PUT /api/v1/agents/chat/{agent_id}

        Uploads data (Excel) or adds queries (slug) to the agent.
        """
        agent_name = self.request.match_info.get('agent_id', None)
        if not agent_name:
            return self.error("Missing Agent Name.", status=400)

        manager: BotManager = self.request.app.get('bot_manager')
        if not manager:
            return self.json_response(
                {"error": "BotManager is not installed."},
                status=500
            )

        try:
            agent: AbstractBot = await manager.get_bot(agent_name)
            if not agent:
                return self.error(f"Agent '{agent_name}' not found.", status=404)

            # Check if request is multipart (file upload)
            if self.request.content_type.startswith('multipart/'):
                reader = await self.request.multipart()
                file_field = await reader.next()

                if not file_field:
                    return self.error("No file provided.", status=400)

                filename = file_field.filename
                if not filename.endswith(('.xlsx', '.xls')):
                    return self.error(
                        "Only Excel files (.xlsx, .xls) are allowed.",
                        status=400
                    )

                # Save temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
                    while True:
                        chunk = await file_field.read_chunk()
                        if not chunk:
                            break
                        tmp.write(chunk)
                    tmp_path = tmp.name

                try:
                    # Read Excel
                    df = pd.read_excel(tmp_path)

                    # Check method
                    if not hasattr(agent, 'add_dataframe') or not callable(agent.add_dataframe):
                        return self.error(
                            "Agent does not support adding dataframes.",
                            status=400
                        )

                    # Add to agent
                    await agent.add_dataframe(df)

                    return self.json_response(
                        {"message": f"Successfully uploaded {filename}", "rows": len(df)},
                        status=202
                    )
                except Exception as e:
                    self.logger.error("Error processing excel upload: %s", e)
                    return self.error(f"Failed to process file: {str(e)}", status=500)
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

            else:
                # JSON/Form data for Query Slug
                try:
                    data = await self.request.json()
                except Exception:
                    data = await self.request.post()

                slug = data.get('slug')
                if not slug:
                    return self.error("Missing 'slug' in payload.", status=400)

                if not hasattr(agent, 'add_query') or not callable(agent.add_query):
                    return self.error("Agent does not support adding queries.", status=400)

                await agent.add_query(slug)
                return self.json_response(
                    {"message": f"Successfully added query slug: {slug}"},
                    status=202
                )

        except Exception as e:
            self.logger.error("Error in PUT %s: %s", agent_name, e, exc_info=True)
            return self.error(
                f"Operation failed: {str(e)}",
                status=400
            )

    async def get(self):
        """
        GET /api/v1/agents/chat/

        Returns information about the AgentTalk endpoint.
        """
        method_name = self.request.match_info.get('method_name', None)
        if method_name == 'debug':
            agent_name = self.request.match_info.get('agent_id', None)
            if not agent_name:
                return self.error(
                    "Missing Agent Name for debug.",
                    status=400
                )
            manager = self.request.app.get('bot_manager')
            if not manager:
                return self.json_response(
                    {"error": "BotManager is not installed."},
                    status=500
                )
            try:
                agent: AbstractBot = await manager.get_bot(agent_name)
                if not agent:
                    return self.error(
                        f"Agent '{agent_name}' not found.",
                        status=404
                    )
            except Exception as e:
                self.logger.error("Error retrieving agent %s: %s", agent_name, e)
                return self.error(
                    f"Error retrieving agent: {e}",
                    status=500
                )
            debug_info = await self.debug_agent(agent)
            return self.json_response(debug_info)

        if method_name == 'mcp_servers':
            agent_name = self.request.match_info.get('agent_id', None)
            if not agent_name:
                return self.error("Missing Agent Name.", status=400)

            # Load session ToolManager
            request_session = None
            with contextlib.suppress(AttributeError):
                request_session = self.request.session or await get_session(self.request)

            mcp_servers_list: list = []
            if request_session:
                session_key = f"{agent_name}_tool_manager"
                tool_manager = request_session.get(session_key)
                if tool_manager and isinstance(tool_manager, ToolManager):
                    # Build serializable list from _mcp_configs
                    for name, config in getattr(tool_manager, '_mcp_configs', {}).items():
                        entry = {
                            "name": name,
                            "url": getattr(config, 'url', None),
                            "transport": getattr(config, 'transport', 'auto'),
                            "auth_type": getattr(config, 'auth_type', None),
                            "headers": getattr(config, 'headers', {}),
                            "allowed_tools": getattr(config, 'allowed_tools', None),
                            "blocked_tools": getattr(config, 'blocked_tools', None),
                            "description": getattr(config, 'description', None),
                        }
                        # Add runtime info if available
                        client = tool_manager.get_mcp_client(name)
                        if client:
                            entry["connected"] = getattr(client, '_connected', False)
                            entry["tool_count"] = len(tool_manager.get_mcp_tools(name))
                        else:
                            entry["connected"] = False
                            entry["tool_count"] = 0
                        mcp_servers_list.append(entry)

            return self.json_response({
                "agent": agent_name,
                "mcp_servers": mcp_servers_list,
            })

        return self.json_response({
            "message": "AgentTalk - Universal Agent Conversation Interface",
            "version": "1.0",
            "usage": {
                "method": "POST",
                "endpoint": "/api/v1/agents/chat/",
                "required_fields": ["agent_name", "query"],
                "optional_fields": [
                    "session_id",
                    "user_id",
                    "output_mode",
                    "format_kwargs",
                    "mcp_servers",
                    "ask_kwargs"
                ],
                "output_modes": ["json", "html", "markdown", "terminal", "default"]
            }
        })

    async def _maybe_start_avatar_speaker(
        self, session_id: Optional[str]
    ) -> Optional[Any]:
        """Return an entered ``AvatarTurnSpeaker`` if an avatar session is live.

        Looks up an active avatar session (created by
        ``POST /api/v1/agents/avatar/{agent}/start``) for ``session_id`` and the
        shared voice provider on the app.  When both are present, opens an
        :class:`AvatarTurnSpeaker` that streams this turn's reply to the avatar.

        Returns ``None`` (and incurs zero overhead) for ordinary chat, when the
        avatar stack is not installed, or if the speaker fails to start —
        avatar speech is strictly best-effort and never breaks the text reply.

        Args:
            session_id: The AgentChat session ID (shared with the avatar
                ``/start`` call and the LiveKit room).

        Returns:
            An entered ``AvatarTurnSpeaker`` ready for ``feed()``/``finish()``,
            or ``None``.
        """
        if not session_id:
            return None
        app = self.request.app
        record = (app.get('avatar_sessions') or {}).get(session_id)
        if not record:
            return None
        provider = app.get('avatar_voice_provider')
        handle = record.get('handle') if isinstance(record, dict) else None
        # FEAT-256 avatar-OFF sessions store a direct-audio RoomAudioPublisher
        # under "publisher" (no LiveAvatar handle) — route the reply into the
        # LiveKit room track instead of the LiveAvatar WS.
        publisher = record.get('publisher') if isinstance(record, dict) else None
        if provider is None or (handle is None and publisher is None):
            return None
        try:
            from parrot.integrations.liveavatar import AvatarTurnSpeaker

            speaker = AvatarTurnSpeaker(
                handle, provider.synthesize_pcm, room_publisher=publisher
            )
            await speaker.__aenter__()
            self.logger.info(
                "AgentTalk: streaming reply to active avatar session %s",
                session_id,
            )
            return speaker
        except Exception:  # noqa: BLE001 - avatar speech is best-effort
            self.logger.warning(
                "AgentTalk: could not start avatar speaker for session %s; "
                "continuing text-only.",
                session_id,
                exc_info=True,
            )
            return None

    async def _speak_text_to_avatar(
        self, session_id: Optional[str], text: str
    ) -> None:
        """Speak a full reply through an active avatar session (non-stream path).

        Opens an :class:`AvatarTurnSpeaker` for an active session, feeds the
        whole reply (the flattener segments it into sentences) and lets the
        speaker synthesize/push the audio **in the background** so the HTTP JSON
        reply returns immediately.  A no-op when no avatar session is active.

        Args:
            session_id: The AgentChat session ID (shared with the avatar).
            text: The full speakable reply (``AIMessage.response``).
        """
        if not text or not text.strip():
            return
        speaker = await self._maybe_start_avatar_speaker(session_id)
        if speaker is None:
            return

        async def _run() -> None:
            try:
                speaker.feed(text)
                await speaker.finish()
            except Exception:  # noqa: BLE001 - avatar speech is best-effort
                self.logger.warning(
                    "Avatar full-text speak failed for session %s",
                    session_id, exc_info=True,
                )
            finally:
                await speaker.aclose()

        task = asyncio.get_running_loop().create_task(_run())
        # Surface unexpected failures instead of swallowing them on GC.
        task.add_done_callback(
            lambda t: self.logger.warning(
                "Avatar speak task errored for session %s: %s",
                session_id, t.exception(),
            ) if not t.cancelled() and t.exception() else None
        )

    async def _push_voice_answer_audio(
        self, session_id: Optional[str], speaker: Any
    ) -> None:
        """Push the turn's synthesized audio to the front for replay (play button).

        Reuses the exact PCM the speaker already generated for the room/avatar
        (no re-synthesis), WAV-wraps it (24 kHz mono 16-bit) and sends it on the
        session's WS channel as ``voice_answer_audio``. Strictly best-effort.
        """
        if not session_id:
            return
        try:
            pcm = speaker.collected_pcm()
            if not pcm:
                self.logger.info(
                    "voice_answer_audio: no PCM collected for session %s "
                    "(nothing to replay)", session_id,
                )
                return
            ws_manager = self.request.app.get('user_socket_manager')
            if ws_manager is None:
                self.logger.warning(
                    "voice_answer_audio: no user_socket_manager — cannot push "
                    "replay audio for session %s", session_id,
                )
                return
            import io
            import wave

            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm)
            wav_bytes = buf.getvalue()
            # A multi-MB WAV is far too large for a single WebSocket frame, so
            # store it on the session and let the browser fetch it over HTTP
            # (GET .../voice-answer). The WS only carries a tiny "ready" ping.
            sessions = self.request.app.get('avatar_sessions') or {}
            rec = sessions.get(session_id)
            if isinstance(rec, dict):
                rec['last_answer_wav'] = wav_bytes
            self.logger.info(
                "voice_answer_audio: stored %d-byte WAV for session %s; notifying",
                len(wav_bytes), session_id,
            )
            await ws_manager.notify_channel(
                session_id,
                {'type': 'voice_answer_audio', 'session_id': session_id},
            )
        except Exception:  # noqa: BLE001 - replay audio is best-effort
            self.logger.warning(
                "Could not push voice answer audio for session %s",
                session_id, exc_info=True,
            )

    def _detach_avatar_finish(
        self, speaker: Any, agent_name: str, session_id: Optional[str] = None
    ) -> None:
        """Drain + close an avatar speaker in the background (FEAT-242).

        The text + metadata are already on the wire by the time the stream
        ends, so flushing the avatar's trailing audio MUST NOT gate the HTTP
        response.  ``finish()`` waits for the per-sentence synthesis/send
        consumer to drain (each ``send_audio_frame`` can wait on the avatar
        "connected" gate), which is exactly the work that previously wedged
        the request.  We hand it to a detached task so ``write_eof`` returns
        immediately; avatar speech stays strictly best-effort.

        Args:
            speaker: The entered ``AvatarTurnSpeaker`` to flush and close.
            agent_name: Agent name, for log context only.
        """
        async def _run() -> None:
            try:
                await speaker.finish()
                # Reuse the audio we just synthesized → front replay (play button).
                await self._push_voice_answer_audio(session_id, speaker)
            except Exception:  # noqa: BLE001 - avatar speech is best-effort
                self.logger.warning(
                    "Avatar speak finish failed for agent '%s'",
                    agent_name, exc_info=True,
                )
            finally:
                await speaker.aclose()

        task = asyncio.get_running_loop().create_task(_run())
        task.add_done_callback(
            lambda t: self.logger.warning(
                "Avatar finish task errored for agent '%s': %s",
                agent_name, t.exception(),
            ) if not t.cancelled() and t.exception() else None
        )

    async def _maybe_publish_bifurcated_output(
        self,
        ai_message: Any,
        session_id: str,
        turn_id: Optional[str],
    ) -> None:
        """Publish structured output via the Redis transport for Mode B bifurcation.

        Thin delegating wrapper around ``avatar_fullmode.publish_bifurcated_
        output`` — the shared implementation (code-review follow-up on
        FEAT-247) also used directly by the OpenAI-compat endpoint
        (``handlers/openai_compat.py``), so the bifurcation logic lives in
        exactly one place. Kept as an instance method here (rather than
        inlining the import at each call site) purely for call-site
        compatibility with existing callers/tests
        (``tests/handlers/test_fullmode_bifurcation.py``).

        Best-effort — any import or publish error is logged and swallowed so it
        never breaks the text reply path.

        Args:
            ai_message: The final ``AIMessage`` from the turn.
            session_id: The conversation ID (Redis channel key).
            turn_id: Optional turn identifier for deduplication.
        """
        from parrot.handlers.avatar_fullmode import publish_bifurcated_output

        await publish_bifurcated_output(
            self.request, self.logger, ai_message, session_id, turn_id,
        )

    async def _handle_stream_response(
        self,
        bot: AbstractBot,
        query: str,
        session_id: Optional[str],
        user_id: Optional[str],
        search_type: str,
        return_sources: bool,
        use_vector_context: bool,
        use_conversation_history: bool,
        output_mode: OutputMode,
        format_kwargs: Dict[str, Any],
        memory: Optional[Any],
        llm: Optional[Any],
        agent_name: str = '',
        client_message_id: Optional[str] = None,
        avatar_bifurcate: bool = False,
        **kwargs,
    ) -> web.StreamResponse:
        """Stream bot response via HTTP chunked transfer encoding.

        Text chunks are written as-is.  The final yielded element from
        ``bot.ask_stream`` is an ``AIMessage``; its JSON representation is
        appended after an ``\\n\\x00`` separator so the client can split
        text from metadata deterministically.

        When ``avatar_bifurcate=True`` and a FULL mode avatar session is active
        for ``session_id``, structured outputs (``is_structured``, ``data``,
        ``code``, ``tool_calls``) in the final ``AIMessage`` are published as a
        ``StructuredOutputMessage`` via the Redis transport so they reach the
        browser's ``/ws/userinfo`` channel regardless of which gunicorn worker
        holds the WebSocket connection.  ``avatar_bifurcate`` is a no-op for
        non-streaming callers (``bot.ask`` path) — FULL mode always streams.
        """
        stream_resp = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'text/plain; charset=utf-8',
                'Transfer-Encoding': 'chunked',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Parrot-Stream': 'chunked-aimessage',
                'X-Accel-Buffering': 'no',
            },
        )
        await stream_resp.prepare(self.request)
        start_time = time.perf_counter()
        ai_message: Optional[AIMessage] = None
        # FEAT-242 Phase A: if an avatar session is active for this session_id,
        # speak the streamed reply through it. Returns None (zero overhead) for
        # ordinary chat. feed() is non-blocking — synthesis happens in a
        # background task so the text stream is never stalled by TTS.
        avatar_speaker = await self._maybe_start_avatar_speaker(session_id)
        try:
            async for chunk in bot.ask_stream(
                question=query,
                session_id=session_id,
                user_id=user_id,
                search_type=search_type,
                return_sources=return_sources,
                use_vector_context=use_vector_context,
                use_conversation_history=use_conversation_history,
                output_mode=output_mode,
                memory=memory,
                llm=llm,
                **kwargs,
            ):
                if isinstance(chunk, AIMessage):
                    ai_message = chunk
                else:
                    await stream_resp.write(chunk.encode('utf-8'))
                    await stream_resp.drain()
                    if avatar_speaker is not None:
                        avatar_speaker.feed(chunk)

            response_time_ms = int((time.perf_counter() - start_time) * 1000)

            if ai_message is not None:
                envelope = {
                    'input': ai_message.input,
                    'output': ai_message.response or str(ai_message.output),
                    'metadata': {
                        'model': getattr(ai_message, 'model', None),
                        'provider': getattr(ai_message, 'provider', None),
                        'session_id': str(getattr(ai_message, 'session_id', '') or ''),
                        'turn_id': str(getattr(ai_message, 'turn_id', '') or ''),
                        'user_id': (
                            str(ai_message.user_id) if ai_message.user_id is not None else None
                        ),
                        'response_time': response_time_ms,
                        'usage': (
                            ai_message.usage.model_dump()
                            if ai_message.usage is not None else None
                        ),
                        'finish_reason': getattr(ai_message, 'finish_reason', None),
                        'stop_reason': getattr(ai_message, 'stop_reason', None),
                    },
                    'sources': [
                        s if isinstance(s, dict) else s.to_dict()
                        for s in getattr(ai_message, 'source_documents', [])
                    ] if format_kwargs.get('include_sources', True) else [],
                    'tool_calls': [
                        {
                            'name': getattr(t, 'name', 'unknown'),
                            'status': getattr(t, 'status', 'completed'),
                            'output': getattr(t, 'output', None),
                            'arguments': getattr(t, 'arguments', None),
                        }
                        for t in getattr(ai_message, 'tool_calls', [])
                    ] if format_kwargs.get('include_tool_calls', True) else [],
                }
                # FEAT-273: envelope-complete per output — carry the A2UI envelope in
                # the final stream dict only (defensive getattr for legacy messages).
                a2ui_envelope = getattr(ai_message, 'a2ui_envelope', None)
                if a2ui_envelope is not None:
                    envelope['a2ui_envelope'] = a2ui_envelope
                separator = b'\n\x00'
                await stream_resp.write(
                    separator + json_encoder(envelope).encode('utf-8')
                )
                await stream_resp.drain()

            # Persist chat turn via ChatStorage
            try:
                chat_storage = self.request.app.get('chat_storage')
                if chat_storage and user_id and session_id and ai_message:
                    loop = asyncio.get_running_loop()
                    _task = loop.create_task(
                        chat_storage.save_turn(
                            turn_id=client_message_id,
                            user_id=user_id,
                            session_id=session_id,
                            agent_id=agent_name,
                            user_message=ai_message.input or '',
                            assistant_response=ai_message.response or '',
                            output=ai_message.response or str(ai_message.output),
                            output_mode=str(output_mode),
                            data=ai_message.data,
                            code=str(ai_message.code) if ai_message.code else None,
                            model=getattr(ai_message, 'model', None),
                            provider=getattr(ai_message, 'provider', None),
                            response_time_ms=response_time_ms,
                            tool_calls=[
                                {
                                    'name': getattr(t, 'name', 'unknown'),
                                    'status': getattr(t, 'status', 'completed'),
                                    'output': getattr(t, 'output', None),
                                    'arguments': getattr(t, 'arguments', None),
                                }
                                for t in getattr(ai_message, 'tool_calls', [])
                            ],
                            sources=[
                                s if isinstance(s, dict) else s.to_dict()
                                for s in getattr(ai_message, 'source_documents', [])
                            ],
                        )
                    )
                    # Log any exception raised inside the background save so it is
                    # not silently swallowed when the task is garbage-collected.
                    _task.add_done_callback(
                        lambda t: self.logger.warning(
                            "Streamed chat-turn save failed for agent '%s': %s",
                            agent_name, t.exception(),
                        ) if not t.cancelled() and t.exception() else None
                    )
            except Exception as ex:
                self.logger.warning("Error scheduling streamed chat turn save: %s", ex)

            # FEAT-249 Mode B: publish structured outputs via the Redis transport
            # when avatar_bifurcate is enabled and a FULL session is active.
            if avatar_bifurcate and ai_message is not None and session_id:
                await self._maybe_publish_bifurcated_output(
                    ai_message=ai_message,
                    session_id=session_id,
                    turn_id=client_message_id,
                )

            # Flush the final sentence and the avatar's playback buffer in the
            # BACKGROUND. Text + metadata are already on the wire; draining the
            # avatar audio must never gate write_eof (finish() waits on the
            # per-sentence consumer + the avatar "connected" gate, which is
            # what previously wedged the request). Hand off and clear the local
            # ref so the finally-block below does not also close it.
            if avatar_speaker is not None:
                self._detach_avatar_finish(avatar_speaker, agent_name, session_id)
                avatar_speaker = None

        except asyncio.CancelledError:
            self.logger.info("Stream cancelled by client for agent '%s'.", agent_name)
        except Exception as e:
            error_payload = json_encoder({'error': str(e)})
            await stream_resp.write(
                f'\n\x00{error_payload}'.encode('utf-8')
            )
            self.logger.error("Error in stream response for agent '%s': %s", agent_name, e)
        finally:
            if avatar_speaker is not None:
                await avatar_speaker.aclose()
            await stream_resp.write_eof()
        return stream_resp

    def _format_response(
        self,
        response: Union[AIMessage, AgentResponse],
        output_format: str,
        format_kwargs: Dict[str, Any],
        user_id: str = None,
        user_session: str = None,
        response_time_ms: int = None,
        agent_name: str = None,
        session_id: str = None,
        client_message_id: str = None,
    ) -> web.Response:
        """
        Format the response based on the requested output format.

        Args:
            response: AIMessage from agent
            output_format: Requested format
            format_kwargs: Additional formatting options
            response_time_ms: Response time in milliseconds (measured externally)

        Returns:
            web.Response with appropriate content type
        """

        if isinstance(response, AgentResponse):
            response = response.response

        # FEAT-273: A2UI mode — surface the declarative envelope in the JSON response.
        if getattr(response, "output_mode", None) == OutputMode.A2UI:
            return self.json_response(
                {
                    "input": getattr(response, "input", None),
                    "output": response.response or "",
                    "output_mode": OutputMode.A2UI.value,
                    "a2ui_envelope": getattr(response, "a2ui_envelope", None),
                }
            )

        # FEAT-197: Infographic mode — return the documented JSON envelope
        # (or text/html for Accept: text/html / ?format=html requests).
        if getattr(response, "output_mode", None) == OutputMode.INFOGRAPHIC:
            return self._format_infographic_response(
                response=response,
                format_kwargs=format_kwargs,
                user_id=user_id,
                user_session=user_session,
                response_time_ms=response_time_ms,
                agent_name=agent_name,
                session_id=session_id,
                client_message_id=client_message_id,
            )

        output = response.output
        if output_format == 'json':
            # Return structured JSON response
            if isinstance(output, pd.DataFrame):
                # Convert DataFrame to dict
                output = output.to_dict(orient='records')
            elif isinstance(output, Panel):
                # Extract text from Panel or stringify it to avoid serialization error
                # Ideally we want the raw content, but output might be just the visual container
                try:
                    # Try to get the renderable content if it's Syntax (JSON)
                    if hasattr(output.renderable, 'code'):
                        output = output.renderable.code
                    else:
                        output = str(output.renderable) if hasattr(output, 'renderable') else str(output)
                except Exception:
                    output = str(output)
            elif isinstance(output, BaseModel):
                # Preserve the full structured payload (e.g. QueryResponse from
                # DatabaseAgent) so the frontend can render dedicated artifacts.
                # Previously this branch collapsed the model to ``.explanation``
                # alone, throwing away ``.query``, ``.data``, etc.
                output = output.model_dump(mode="json")
            elif hasattr(output, 'explanation'):
                output = output.explanation
            # Safety net: ensure output is JSON-serializable
            if not isinstance(output, (str, dict, list, int, float, bool, type(None))):
                # Use response.response (already serialized HTML) if available
                output = response.response if isinstance(response.response, str) else str(output)
            output_mode = response.output_mode or 'json'
            usage = getattr(response, 'usage', None)
            created_at = getattr(response, 'created_at', None)
            obj_response = {
                "input": response.input,
                "output": output,
                "data": response.data,
                "response": response.response,
                "output_mode": output_mode,
                "code": str(response.code) if response.code else None,
                "metadata": {
                    "model": getattr(response, 'model', None),
                    "provider": getattr(response, 'provider', None),
                    "session_id": str(getattr(response, 'session_id', '')),
                    "turn_id": str(getattr(response, 'turn_id', '')),
                    "user_id": (
                        str(getattr(response, 'user_id', ''))
                        if getattr(response, 'user_id', None) is not None else None
                    ),
                    "response_time": response_time_ms,
                    "usage": usage.model_dump() if usage is not None else None,
                    "finish_reason": getattr(response, 'finish_reason', None),
                    "stop_reason": getattr(response, 'stop_reason', None),
                    "created_at": created_at.isoformat() if created_at is not None else None,
                },
                "sources": [
                    source if isinstance(source, dict) else source.to_dict()
                    for source in getattr(response, 'source_documents', [])
                ] if format_kwargs.get('include_sources', True) else [],
                "tool_calls": [
                    {
                        "name": getattr(tool, 'name', 'unknown'),
                        "status": getattr(tool, 'status', 'completed'),
                        "output": getattr(tool, 'output', None),
                        'arguments': getattr(tool, 'arguments', None)
                    }
                    for tool in getattr(response, 'tool_calls', [])
                ] if format_kwargs.get('include_tool_calls', True) else []
            }
            # self.logger.debug('Agent response: %s', obj_response)

            # Persist chat turn via ChatStorage (hot + cold)
            try:
                chat_storage = self.request.app.get('chat_storage')
                if chat_storage and user_id and session_id:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        chat_storage.save_turn(
                            turn_id=client_message_id,
                            user_id=user_id,
                            session_id=session_id,
                            agent_id=agent_name or '',
                            user_message=response.input or '',
                            assistant_response=response.response or '',
                            output=output,
                            output_mode=output_mode,
                            data=response.data,
                            code=str(response.code) if response.code else None,
                            model=getattr(response, 'model', None),
                            provider=getattr(response, 'provider', None),
                            response_time_ms=response_time_ms,
                            tool_calls=[
                                {
                                    'name': getattr(t, 'name', 'unknown'),
                                    'status': getattr(t, 'status', 'completed'),
                                    'output': getattr(t, 'output', None),
                                    'arguments': getattr(t, 'arguments', None),
                                }
                                for t in getattr(response, 'tool_calls', [])
                            ],
                            sources=[
                                s if isinstance(s, dict) else s.to_dict()
                                for s in getattr(response, 'source_documents', [])
                            ],
                        )
                    )
            except Exception as ex:
                self.logger.warning("Error scheduling chat turn save: %s", ex)

            # FEAT-103: Auto-save data artifact if response includes structured data.
            # FEAT-224 (G5): Extended to recognise structured_* modes and persist the
            # artifact definition (the presentation config), not response.data (the rows).
            try:
                artifact_store = self.request.app.get('artifact_store')
                if artifact_store and user_id and session_id:
                    from datetime import datetime as _dt, timezone as _tz
                    from parrot.storage.models import (  # noqa: E501 pylint: disable=import-outside-toplevel
                        Artifact,
                        ArtifactType,
                        ArtifactCreator,
                    )
                    import uuid as _uuid

                    # Legacy type map (chart / dataframe / export — rows path).
                    _legacy_type_map = {
                        'chart': ArtifactType.CHART,
                        'dataframe': ArtifactType.DATAFRAME,
                        'export': ArtifactType.EXPORT,
                    }
                    # FEAT-224: structured_* type map (config path).
                    _structured_type_map = {
                        'structured_chart': ArtifactType.CHART,
                        'structured_map':   ArtifactType.MAP,
                        'structured_table': ArtifactType.TABLE,
                    }
                    _type_map = {**_legacy_type_map, **_structured_type_map}

                    _is_structured = output_mode in _structured_type_map
                    _is_legacy = (
                        output_mode in _legacy_type_map
                        and response.data is not None
                    )

                    if _is_structured and getattr(response, 'artifacts', None):
                        # FEAT-224 path: persist the envelope definition (config),
                        # not response.data (rows), and reuse the agent-minted id.
                        _env = next(
                            (a for a in response.artifacts if a.get("definition")),
                            None,
                        )
                        if _env is not None:
                            _now = _dt.now(_tz.utc)
                            # Prefer the id the agent already minted (stable across
                            # envelope + persistence; avoids double id divergence).
                            _art_id = (
                                getattr(response, 'artifact_id', None)
                                or _env.get("artifactId")
                                or f"{output_mode}-{_uuid.uuid4().hex[:8]}"
                            )
                            _definition = _env["definition"]  # config, NOT rows
                            _atype = _structured_type_map[output_mode]
                            _artifact = Artifact(
                                artifact_id=_art_id,
                                artifact_type=_atype,
                                title=f"{output_mode.title()} — {(getattr(response, 'input', None) or '')[:60]}",
                                created_at=_now,
                                updated_at=_now,
                                source_turn_id=client_message_id,
                                created_by=ArtifactCreator.AGENT,
                                definition=_definition,
                            )
                            asyncio.get_running_loop().create_task(
                                artifact_store.save_artifact(
                                    user_id=user_id,
                                    agent_id=agent_name or '',
                                    session_id=session_id,
                                    artifact=_artifact,
                                )
                            )

                    elif _is_legacy:
                        # Legacy path (chart / dataframe / export): persist response.data.
                        _now = _dt.now(_tz.utc)
                        _art_id = f"{output_mode}-{_uuid.uuid4().hex[:8]}"
                        _definition = (
                            response.data if isinstance(response.data, dict)
                            else {"raw": str(response.data)[:10000]}
                        )
                        _artifact = Artifact(
                            artifact_id=_art_id,
                            artifact_type=_type_map.get(output_mode, ArtifactType.EXPORT),
                            title=f"{output_mode.title()} — {(getattr(response, 'input', None) or '')[:60]}",
                            created_at=_now,
                            updated_at=_now,
                            source_turn_id=client_message_id,
                            created_by=ArtifactCreator.AGENT,
                            definition=_definition,
                        )
                        asyncio.get_running_loop().create_task(
                            artifact_store.save_artifact(
                                user_id=user_id,
                                agent_id=agent_name or '',
                                session_id=session_id,
                                artifact=_artifact,
                            )
                        )
            except Exception as ex:
                self.logger.warning("Error scheduling artifact auto-save: %s", ex)

            return web.json_response(
                obj_response, dumps=json_encoder, content_type='application/json'
            )

        elif output_format == 'html':
            interactive = format_kwargs.get('interactive', False)
            if interactive:
                return self._serve_panel_dashboard(response)

            # Return HTML response
            html_content = response.response
            if isinstance(html_content, str):
                html_str = html_content
            elif hasattr(html_content, '_repr_html_'):
                # Panel/IPython displayable object (for HTML mode)
                html_str = html_content._repr_html_()
            elif hasattr(html_content, '__str__'):
                # Other objects with string representation
                html_str = str(html_content)
            else:
                html_str = str(html_content)

            return web.Response(
                text=html_str,
                content_type='text/html',
                charset='utf-8'
            )

        else:  # markdown or text
            # Return plain text/markdown response
            content = response.content

            # Ensure it's a string
            if not isinstance(content, str):
                content = str(content)

            # Optionally append sources
            if format_kwargs.get('include_sources', False) and getattr(response, 'source_documents', []):
                content += "\n\n## Sources\n"
                for idx, source in enumerate(response.source_documents, 1):
                    src_content = source.get('source', '') if isinstance(source, dict) else getattr(source, 'source', '')
                    content += f"\n{idx}. {src_content[:200]}...\n"

            return web.Response(
                text=content,
                content_type='text/plain' if output_format == 'text' else 'text/markdown',
                charset='utf-8'
            )

        return output

    @staticmethod
    def _extract_infographic_explanation(response: "AIMessage") -> str:
        """Pull the LLM's narrative explanation for the infographic envelope.

        Prefers ``response.response`` (where ``PandasAgent`` stores the parsed
        ``explanation``), falling back to ``response.content``.  When the value
        is still a raw structured-output JSON string (e.g. Gemini emits
        ``{"explanation": "..."}``), the ``explanation`` field is unwrapped.

        Args:
            response: The agent's ``AIMessage``.

        Returns:
            The explanation text, or an empty string when none is available.
        """
        raw = getattr(response, "response", None) or getattr(response, "content", None)
        if raw is None:
            return ""
        if not isinstance(raw, str):
            return str(raw)
        stripped = raw.strip()
        if stripped.startswith("{") and '"explanation"' in stripped:
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                return raw
            if isinstance(parsed, dict) and parsed.get("explanation"):
                return str(parsed["explanation"])
        return raw

    def _format_infographic_response(
        self,
        response: "AIMessage",
        format_kwargs: Dict[str, Any],
        user_id: str = None,
        user_session: str = None,
        response_time_ms: int = None,
        agent_name: str = None,
        session_id: str = None,
        client_message_id: str = None,
    ) -> web.Response:
        """Return the INFOGRAPHIC JSON envelope or text/html for Accept: text/html.

        JSON envelope shape:
        ```json
        {
            "input": "...",
            "output": "<html_url or html_inline>",
            "output_mode": "infographic",
            "artifact_id": "...",
            "data": [ ... List[DatasetResult] ... ],
            "metadata": {
                "html_url": "...",
                "html_inline_omitted": false,
                "enhanced": false,
                "template_name": "...",
                "theme": "...",
                ...
            }
        }
        ```
        ``Accept: text/html`` or ``?format=html`` returns the raw HTML body.
        """
        # Accept: text/html content-negotiation
        accept_header = self.request.headers.get("Accept", "")
        fmt_param = self.request.query.get("format", "")
        want_html = accept_header.startswith("text/html") or fmt_param == "html"

        if want_html:
            # Serve the artifact HTML directly.
            html_body = (
                response.output
                if isinstance(response.output, str)
                else str(response.output or "")
            )
            from parrot.handlers.csp import build_csp_headers, frame_ancestors_from_env
            from parrot.models.infographic import JSBundle
            meta = dict(getattr(response, "metadata", None) or {})
            raw_bundles = meta.get("js_bundles", [])
            bundles = [JSBundle.model_validate(b) if isinstance(b, dict) else b for b in raw_bundles]
            csp_headers = build_csp_headers(js_bundles=bundles, frame_ancestors=frame_ancestors_from_env())
            return web.Response(
                text=html_body,
                content_type="text/html",
                charset="utf-8",
                headers=csp_headers,
            )

        # Default: structured JSON envelope
        metadata = dict(getattr(response, "metadata", None) or {})
        artifact_id = getattr(response, "artifact_id", None)

        # Surface the LLM's narrative explanation.  The infographic post-loop
        # branch in PandasAgent returns early (bypassing the formatter), so the
        # explanation only survives on ``response.response``/``response.content``
        # — never in ``output`` (which carries the HTML URL or inline HTML).
        # Without this the frontend loses the textual summary entirely.
        explanation = self._extract_infographic_explanation(response)

        obj_response = {
            "input": response.input,
            "output": response.output,
            "response": explanation,
            "output_mode": "infographic",
            "artifact_id": artifact_id,
            "data": response.data,
            "metadata": {
                **metadata,
                "model": getattr(response, "model", None),
                "provider": getattr(response, "provider", None),
                "session_id": str(getattr(response, "session_id", "") or ""),
                "turn_id": str(getattr(response, "turn_id", "") or ""),
                "response_time": response_time_ms,
            },
            "sources": [],
            "tool_calls": [],
        }
        return web.json_response(
            obj_response, dumps=json_encoder, content_type="application/json",
        )

    def _serve_panel_dashboard(self, response: AIMessage) -> web.Response:
        """
        Serve an interactive Panel dashboard.

        This converts the Panel object to a standalone HTML application
        with embedded JavaScript for interactivity.

        Args:
            response: AIMessage with Panel object in .content

        Returns:
            web.Response with interactive HTML
        """
        try:
            panel_obj = response.response
            # Create temporary file for the Panel HTML
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.html',
                delete=False
            ) as tmp:
                tmp_path = tmp.name

            try:
                # Save Panel to HTML with all resources embedded
                panel_obj.save(
                    tmp_path,
                    embed=True,  # Embed all JS/CSS resources
                    title=f"AI Agent Response - {response.session_id[:8] if response.session_id else 'interactive'}",
                    resources='inline'  # Inline all resources
                )

                # Read the HTML content
                with open(tmp_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                # Return as HTML response
                return web.Response(
                    text=html_content,
                    content_type='text/html',
                    charset='utf-8'
                )

            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception as e:
                        self.logger.warning("Failed to delete temp file %s: %s", tmp_path, e)

        except ImportError:
            self.logger.error(
                "Panel library not available for interactive dashboards"
            )
            # Fallback to static HTML
            return web.Response(
                text=str(response.content),
                content_type='text/html',
                charset='utf-8'
            )
        except Exception as e:
            self.logger.error("Error serving Panel dashboard: %s", e, exc_info=True)
            # Fallback to error response
            return self.error(
                f"Error rendering interactive dashboard: {e}",
                status=500
            )

    async def debug_agent(self, agent):
        debug_info = {}

        # Safely get dataframes if available
        if hasattr(agent, 'dataframes') and agent.dataframes:
            debug_info["dataframes"] = list(agent.dataframes.keys())
        else:
            debug_info["dataframes"] = []

        # Safely get df_metadata if available
        if hasattr(agent, 'df_metadata') and agent.df_metadata:
            debug_info["df_metadata"] = {k: v['shape'] for k, v in agent.df_metadata.items()}
        else:
            debug_info["df_metadata"] = {}

        # Safely get pandas_tool if available
        if hasattr(agent, '_get_python_pandas_tool'):
            pandas_tool = agent._get_python_pandas_tool()
            debug_info["pandas_tool"] = {
                "exists": pandas_tool is not None,
                "dataframes": list(pandas_tool.dataframes.keys()) if pandas_tool else []
            }
        else:
            debug_info["pandas_tool"] = {"exists": False, "dataframes": []}

        # Safely get metadata_tool if available
        if hasattr(agent, '_get_metadata_tool'):
            metadata_tool = agent._get_metadata_tool()
            debug_info["metadata_tool"] = {
                "exists": metadata_tool is not None,
                "dataframes": list(metadata_tool.dataframes.keys()) if metadata_tool else [],
                "metadata": list(metadata_tool.metadata.keys()) if metadata_tool else []
            }
        else:
            debug_info["metadata_tool"] = {"exists": False, "dataframes": [], "metadata": []}

        return debug_info
