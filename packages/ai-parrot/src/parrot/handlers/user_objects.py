"""
UserObjectsHandler - Session-Scoped User Object Management
===========================================================
Manages session-scoped ToolManager and DatasetManager instances for users.

Extracted from AgentTalk to reduce complexity and centralize user object
configuration logic.
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional, Union, TYPE_CHECKING
from pydantic import ValidationError
from navconfig.logging import logging
from ..tools.manager import ToolManager
from ..tools.dataset_manager import DatasetManager
from ..models import ToolConfig
from ..mcp.integration import MCPServerConfig
from ..integrations.oauth2.registry import OAuth2ProviderRegistry
from ..integrations.oauth2.persistence import list_user_agent_toolkits
from ..auth.credentials import OAuthCredentialResolver

if TYPE_CHECKING:
    from ..bots.data import PandasAgent


class UserObjectsHandler:
    """
    Manages session-scoped ToolManager and DatasetManager instances.

    Provides centralized logic for:
    - Creating and retrieving session-scoped ToolManager instances
    - Creating and retrieving session-scoped DatasetManager instances
    - Copying agent configurations to user-specific instances

    Usage:
        handler = UserObjectsHandler(logger=my_logger)
        tool_manager, mcp_servers = await handler.configure_tool_manager(
            data, request_session, agent_name="my-agent"
        )
        dataset_manager = await handler.configure_dataset_manager(
            request_session, agent, agent_name="my-agent"
        )
    """

    def __init__(self, logger: logging.Logger = None):
        """
        Initialize UserObjectsHandler.

        Args:
            logger: Optional logger instance. If not provided, creates one.
        """
        self.logger = logger or logging.getLogger(__name__)

    def get_session_key(self, agent_name: str, manager_type: str) -> str:
        """
        Generate session key for a manager type.

        Args:
            agent_name: Name of the agent (can be None or empty)
            manager_type: Type of manager (e.g., 'tool_manager', 'dataset_manager')

        Returns:
            Session key string like '{agent_name}_{manager_type}' or just '{manager_type}'
        """
        prefix = f"{agent_name}_" if agent_name else ""
        return f"{prefix}{manager_type}"

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
                self.logger.error(f"Failed to add MCP server to ToolManager: {e}")

    async def configure_tool_manager(
        self,
        data: Dict[str, Any],
        request_session: Any,
        agent_name: str = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> tuple[Union[ToolManager, None], List[Dict[str, Any]]]:
        """
        Configure a ToolManager from request payload or session.

        This method handles:
        1. Extracting tool configuration from request data
        2. Creating or retrieving existing ToolManager from session
        3. Registering tools and MCP servers
        4. Persisting the ToolManager back to session
        5. Cold-session hydration from DocumentDB when user_id and agent_id
           are provided and no ToolManager exists in the session.

        Args:
            data: Request body data (will be mutated - tool_config, tools,
                  mcp_servers keys will be popped)
            request_session: Session object for storing/retrieving ToolManager
            agent_name: Agent name used to namespace the session key
            user_id: Authenticated user identifier used for cold-session
                hydration (optional; hydration skipped when absent).
            agent_id: Agent identifier used to query ``user_agent_toolkits``
                (optional; hydration skipped when absent).

        Returns:
            Tuple of (ToolManager or None, remaining mcp_servers list)

        Raises:
            ValueError: If tool_config is not a valid object or configuration is invalid
        """
        session_key = self.get_session_key(agent_name, "tool_manager")
        config_key = self.get_session_key(agent_name, "tool_config")

        tool_config_payload = data.pop('tool_config', None)
        tools_payload = data.pop('tools', None)
        mcp_servers = data.pop('mcp_servers', [])
        tool_manager = None

        if tool_config_payload is not None or tools_payload is not None:
            if tool_config_payload is not None and not isinstance(tool_config_payload, dict):
                raise ValueError("tool_config must be an object.")

            config_payload = {}
            if isinstance(tool_config_payload, dict):
                config_payload.update(tool_config_payload)
            if tools_payload is not None:
                config_payload['tools'] = tools_payload
            if mcp_servers:
                config_payload.setdefault('mcp_servers', mcp_servers)

            try:
                tool_config = ToolConfig(**config_payload)
            except ValidationError as exc:
                raise ValueError(f"Invalid tool configuration: {exc}") from exc

            # Check if there's an existing tool_manager in session to extend
            if request_session is not None:
                existing_tm = request_session.get(session_key)
                # Note: Use 'is not None' because ToolManager.__bool__
                # returns False when empty (no tools registered)
                if existing_tm is not None and isinstance(existing_tm, ToolManager):
                    tool_manager = existing_tm
                else:
                    tool_manager = ToolManager(debug=True)
            else:
                tool_manager = ToolManager(debug=True)

            if tool_config.tools:
                tool_manager.register_tools(tool_config.tools)
            if tool_config.mcp_servers:
                await self._add_mcp_servers_to_tool_manager(
                    tool_manager, tool_config.mcp_servers
                )

            if request_session is not None:
                request_session[session_key] = tool_manager
                request_session[config_key] = tool_config.dict()

            return tool_manager, []

        if request_session:
            tool_manager = request_session.get(session_key)

        # Cold-session hydration: re-add OAuth toolkits that were persisted in
        # DocumentDB but are missing from the (empty/new) session.
        if tool_manager is None and user_id and agent_id:
            tool_manager = await self._hydrate_oauth_toolkits(
                user_id, agent_id, session_key, request_session
            )

        return tool_manager, mcp_servers

    async def _hydrate_oauth_toolkits(
        self,
        user_id: str,
        agent_id: str,
        session_key: str,
        request_session: Any,
    ) -> Optional[ToolManager]:
        """Re-populate OAuth toolkits from DocumentDB on a cold session.

        Reads ``user_agent_toolkits`` rows for the given ``(user_id, agent_id)``
        pair and registers each enabled toolkit via the provider's
        :meth:`~parrot.integrations.oauth2.registry.OAuth2Provider.toolkit_factory`.

        The resulting :class:`~parrot.tools.manager.ToolManager` is persisted
        back to *request_session* under *session_key* so subsequent requests
        benefit from the warm session.

        Returns:
            A populated :class:`~parrot.tools.manager.ToolManager`, or ``None``
            if DocumentDB returned no enablements or an error occurred.
        """
        try:
            enablements = await list_user_agent_toolkits(user_id, agent_id)
            if not enablements:
                return None

            tool_manager = ToolManager(debug=True)
            registry = OAuth2ProviderRegistry()
            for row in enablements:
                provider = registry.get(row.provider)
                if provider is None:
                    self.logger.warning(
                        "Unknown OAuth provider %r in user_agent_toolkits "
                        "(user=%s agent=%s) — skipping",
                        row.provider, user_id, agent_id,
                    )
                    continue
                # Skip if toolkit already registered (idempotency guard).
                if tool_manager.get_tool(row.toolkit_id) is not None:
                    continue
                resolver = OAuthCredentialResolver(provider.manager)
                toolkit = provider.toolkit_factory(resolver)
                tool_manager.register_toolkit(toolkit)
                self.logger.debug(
                    "Hydrated toolkit %r for user=%s agent=%s",
                    row.toolkit_id, user_id, agent_id,
                )

            if request_session is not None:
                request_session[session_key] = tool_manager

            return tool_manager
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Failed to hydrate OAuth toolkits for user=%s agent=%s — "
                "proceeding without hydration",
                user_id, agent_id,
            )
            return None

    async def configure_dataset_manager(
        self,
        request_session: Any,
        agent: "PandasAgent",
        agent_name: str = None
    ) -> DatasetManager:
        """
        Get or create a session-scoped DatasetManager for the user.

        This method handles:
        1. Checking for existing DatasetManager in session
        2. Creating a new DatasetManager if not found
        3. Copying datasets from agent's DatasetManager to user's instance
        4. Persisting the DatasetManager to session

        Args:
            request_session: Session object for storing/retrieving DatasetManager
            agent: PandasAgent instance that may have a DatasetManager with datasets
            agent_name: Agent name used to namespace the session key.
                        If not provided, uses agent.name

        Returns:
            DatasetManager instance (either existing from session or newly created)
        """
        session_key = self.get_session_key(
            agent_name or getattr(agent, 'name', None),
            "dataset_manager"
        )

        # Check for existing DatasetManager in session
        if request_session is not None:
            existing_dm = request_session.get(session_key)
            if existing_dm and isinstance(existing_dm, DatasetManager):
                self.logger.debug(
                    "Using existing DatasetManager from session: %s",
                    session_key
                )
                return existing_dm

        # Create new DatasetManager inheriting config from the agent's DM
        agent_dm = getattr(agent, '_dataset_manager', None)
        user_dm = DatasetManager(
            df_prefix=getattr(agent_dm, 'df_prefix', 'df') if agent_dm else 'df',
            generate_guide=getattr(agent_dm, 'generate_guide', False) if agent_dm else False,
            auto_detect_types=getattr(agent_dm, 'auto_detect_types', True) if agent_dm else True,
        )
        self.logger.debug("Created new DatasetManager for session: %s", session_key)

        # Copy ALL dataset entries from agent's DatasetManager — including
        # unloaded table sources.  Only copying loaded DataFrames (the old
        # behaviour) caused fetch_dataset on table sources to operate on the
        # original DM while the sync callback read from the user DM, leading
        # to missing variables in the REPL namespace.
        if agent_dm:
            try:
                for name, entry in agent_dm._datasets.items():
                    # Share the same DatasetEntry reference — the entry
                    # holds a source object (TableSource, InMemorySource, …)
                    # and optionally a loaded DataFrame.  Sharing the entry
                    # means fetches in the user DM see the same cache/source.
                    user_dm._datasets[name] = entry
                    self.logger.debug(
                        "Copied dataset entry '%s' (%s, loaded=%s) "
                        "from agent to user DatasetManager",
                        name,
                        type(entry.source).__name__,
                        entry.loaded,
                    )
            except Exception as e:
                self.logger.warning(
                    "Failed to copy datasets from agent DatasetManager: %s", e
                )

        # Save to session
        if request_session is not None:
            request_session[session_key] = user_dm
            self.logger.debug("Saved DatasetManager to session: %s", session_key)

        return user_dm
