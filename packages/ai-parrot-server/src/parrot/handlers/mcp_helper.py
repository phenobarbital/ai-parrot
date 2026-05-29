"""MCP Helper HTTP Handler — discovery, activation, and management of MCP servers.

Provides four endpoints under ``/api/v1/agents/chat/{agent_id}/mcp-servers``:

- ``GET  /mcp-servers``          — return the full catalog of pre-built helpers
- ``POST /mcp-servers``          — activate a server on the session ToolManager
- ``GET  /mcp-servers/active``   — list active MCP servers in the session
- ``DELETE /mcp-servers/{name}`` — deactivate a server

Routes are registered by :func:`setup_mcp_helper_routes`.

The activation flow:
1. Validate params via :class:`~parrot.mcp.registry.MCPServerRegistry`.
2. Separate secret params from non-secret params.
3. Encrypt secrets and store in DocumentDB (``user_credentials`` collection).
4. Call the corresponding ``create_*_mcp_server`` factory to build config.
5. Register on the session-scoped ToolManager.
6. Persist non-secret config via :class:`~parrot.handlers.mcp_persistence.MCPPersistenceService`.
"""
from __future__ import annotations

import contextlib
from typing import Any, Dict, List

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from pydantic import ValidationError

from parrot.handlers.mcp_persistence import MCPPersistenceService
from parrot.handlers.vault_utils import (
    delete_vault_credential,
    store_vault_credential,
)
from parrot.mcp.registry import (
    ActivateMCPServerRequest,
    MCPParamType,
    MCPServerRegistry,
    UserMCPServerConfig,
    get_factory_map,
)
from parrot.tools.manager import ToolManager

_registry = MCPServerRegistry()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _get_user_id_from_handler(handler: BaseView) -> str:
    """Extract user_id from a BaseView handler's session.

    Args:
        handler: The :class:`~navigator.views.BaseView` instance.

    Returns:
        User ID string.

    Raises:
        web.HTTPUnauthorized: If the session or user_id is absent.
    """
    session = getattr(handler, '_session', None)
    if not session:
        raise web.HTTPUnauthorized(reason="Session not available.")
    user_id = (
        session.get('session', {}).get('user_id')
        or session.get('user_id')
    )
    if not user_id:
        raise web.HTTPUnauthorized(reason="User ID not found in session.")
    return str(user_id)


async def _get_tool_manager(request: web.Request, agent_id: str) -> ToolManager:
    """Retrieve (or create) the session-scoped ToolManager for an agent.

    Args:
        request: The aiohttp :class:`~aiohttp.web.Request`.
        agent_id: Agent identifier used as the session key prefix.

    Returns:
        The session-scoped :class:`~parrot.tools.manager.ToolManager` instance.
    """
    request_session = None
    with contextlib.suppress(AttributeError):
        request_session = request.session or await get_session(request)

    session_key = f"{agent_id}_tool_manager"

    if request_session is not None:
        tool_manager = request_session.get(session_key)
        if tool_manager is not None and isinstance(tool_manager, ToolManager):
            return tool_manager
        # Create a new ToolManager and persist to session
        tool_manager = ToolManager()
        request_session[session_key] = tool_manager
        return tool_manager

    logger.warning(
        "No session available for agent '%s' — tools registered on this "
        "ToolManager will not persist beyond this request.",
        agent_id,
    )
    return ToolManager()


# ---------------------------------------------------------------------------
# MCPHelperHandler — catalog and activation
# ---------------------------------------------------------------------------


@is_authenticated()
@user_session()
class MCPHelperHandler(BaseView):
    """HTTP handler for MCP server catalog listing and activation.

    Handles two routes:
    - ``GET  /api/v1/agents/chat/{agent_id}/mcp-servers`` — full catalog
    - ``POST /api/v1/agents/chat/{agent_id}/mcp-servers`` — activate server
    """

    async def get(self) -> web.Response:
        """Return the full catalog of pre-built MCP server helpers.

        Returns:
            200 JSON array of :class:`~parrot.mcp.registry.MCPServerDescriptor`
            objects serialized as dicts.
        """
        servers = _registry.list_servers()
        data = [s.model_dump() for s in servers]
        return self.json_response(data)

    async def post(self) -> web.Response:
        """Activate a pre-built MCP server on the session ToolManager.

        Request body (JSON):
            .. code-block:: json

                {"server": "perplexity", "params": {"api_key": "sk-..."}}

        Returns:
            200 JSON with registered tool names.
            400 if params validation fails or server already active.
            502 if the MCP server fails to connect.
            500 on Vault or config-build errors.
        """
        try:
            user_id = _get_user_id_from_handler(self)
        except web.HTTPUnauthorized as exc:
            return self.error(exc.reason, status=401)

        # Parse and validate request body
        try:
            body = await self.request.json()
        except Exception:
            return self.error("Invalid JSON body.", status=400)

        try:
            req = ActivateMCPServerRequest(**body)
        except (ValidationError, TypeError) as exc:
            return self.error(str(exc), status=400)

        # Validate params against registry
        try:
            validated_params = _registry.validate_params(req.server, req.params)
        except ValueError as exc:
            return self.error(str(exc), status=400)

        agent_id = self.request.match_info.get("agent_id", "")

        # --- Duplicate-activation guard ---
        # Fetch the ToolManager early so we can check for an already-active server
        # before spending a Vault write + DB round-trip on a no-op activation.
        tool_manager = await _get_tool_manager(self.request, agent_id)
        if req.server in tool_manager.list_mcp_servers():
            logger.debug(
                "MCP server '%s' already active for agent='%s' — skipping re-activation.",
                req.server,
                agent_id,
            )
            active_tools: List[str] = [
                name for name in tool_manager._tools
                if name.startswith(f"mcp_{req.server}_")
            ]
            return self.json_response({
                "server": req.server,
                "tools": active_tools,
                "tool_count": len(active_tools),
                "message": "Server already active.",
            })

        # Separate secret params from non-secret params
        desc = _registry.get_server(req.server)
        if desc is None:
            # Unreachable in practice — validate_params already raised for unknown servers.
            # Kept as an explicit guard against future registry refactors.
            return self.error(f"Server '{req.server}' not found.", status=400)

        secret_param_names: set[str] = {
            p.name for p in desc.params if p.type == MCPParamType.SECRET
        }
        secret_params: Dict[str, Any] = {
            k: v for k, v in validated_params.items() if k in secret_param_names
        }
        non_secret_params: Dict[str, Any] = {
            k: v for k, v in validated_params.items() if k not in secret_param_names
        }

        # Store secrets in Vault (only if there are any)
        vault_name: str | None = None
        if secret_params:
            vault_name = f"mcp_{req.server}_{agent_id}"
            try:
                await store_vault_credential(user_id, vault_name, secret_params)
            except RuntimeError as exc:
                logger.error("Vault unavailable for MCP activation: %s", exc)
                return self.error("Encryption service unavailable.", status=500)
            except Exception as exc:
                logger.error("Failed to store MCP secrets in Vault: %s", exc)
                return self.error("Failed to store credentials.", status=500)

        # Build the MCPClientConfig using the factory function
        factory_kwargs = {**non_secret_params, **secret_params}
        factory_fn = get_factory_map().get(req.server)

        if factory_fn is None:
            return self.error(
                f"Server '{req.server}' cannot be activated via this endpoint "
                f"(no factory function available).",
                status=400,
            )

        try:
            mcp_config = factory_fn(**factory_kwargs)
        except Exception as exc:
            # Do NOT include exc in the response — factory_kwargs contains secret
            # values and the exception message may echo them back.
            logger.error(
                "Factory function failed for '%s': %s", req.server, exc, exc_info=True
            )
            return self.error(
                f"Failed to build server config for '{req.server}'. "
                "Check server logs for details.",
                status=500,
            )

        # Register on the session ToolManager (already fetched above)
        try:
            tool_names: List[str] = await tool_manager.add_mcp_server(mcp_config)
        except Exception as exc:
            logger.warning(
                "MCP server '%s' connection failed during activation: %s",
                req.server,
                exc,
            )
            return self.error(
                f"MCP server '{req.server}' failed to connect: {exc}",
                status=502,
            )

        # Persist non-secret config
        persistence = MCPPersistenceService()
        config = UserMCPServerConfig(
            server_name=req.server,
            agent_id=agent_id,
            user_id=user_id,
            params=non_secret_params,
            vault_credential_name=vault_name,
            active=True,
        )
        try:
            await persistence.save_user_mcp_config(config)
        except Exception as exc:
            # Persistence failure is non-fatal — server is already active
            logger.warning(
                "Failed to persist MCP config for '%s': %s",
                req.server,
                exc,
            )

        logger.info(
            "Activated MCP server '%s' for user='%s' agent='%s' — %d tool(s)",
            req.server,
            user_id,
            agent_id,
            len(tool_names),
        )

        return self.json_response({
            "server": req.server,
            "tools": tool_names,
            "tool_count": len(tool_names),
        })


# ---------------------------------------------------------------------------
# MCPActiveHandler — list active MCP servers
# ---------------------------------------------------------------------------


@is_authenticated()
@user_session()
class MCPActiveHandler(BaseView):
    """HTTP handler that returns the currently active MCP servers in the session.

    Handles one route:
    - ``GET /api/v1/agents/chat/{agent_id}/mcp-servers/active``
    """

    async def get(self) -> web.Response:
        """Return the list of active MCP servers from the session ToolManager.

        Returns:
            200 JSON array of active server names.
        """
        agent_id = self.request.match_info.get("agent_id", "")
        tool_manager = await _get_tool_manager(self.request, agent_id)

        servers = tool_manager.list_mcp_servers()
        return self.json_response({
            "agent_id": agent_id,
            "active_servers": servers,
            "count": len(servers),
        })


# ---------------------------------------------------------------------------
# MCPServerItemHandler — deactivate a specific MCP server
# ---------------------------------------------------------------------------


@is_authenticated()
@user_session()
class MCPServerItemHandler(BaseView):
    """HTTP handler for deactivating a specific MCP server.

    Handles one route:
    - ``DELETE /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name}``
    """

    async def delete(self) -> web.Response:
        """Deactivate an MCP server: remove from ToolManager, soft-delete from DB.

        The Vault credential (if any) is also hard-deleted per the spec decision.

        Returns:
            200 JSON confirmation message.
            500 on database errors.
        """
        try:
            user_id = _get_user_id_from_handler(self)
        except web.HTTPUnauthorized as exc:
            return self.error(exc.reason, status=401)

        agent_id = self.request.match_info.get("agent_id", "")
        server_name = self.request.match_info.get("server_name", "")

        # Remove from session ToolManager (best-effort)
        tool_manager = await _get_tool_manager(self.request, agent_id)
        try:
            await tool_manager.remove_mcp_server(server_name)
        except Exception as exc:
            logger.warning(
                "Failed to remove MCP server '%s' from ToolManager: %s",
                server_name,
                exc,
            )

        # Soft-delete from DocumentDB
        persistence = MCPPersistenceService()
        removed = False
        try:
            removed = await persistence.remove_user_mcp_config(
                user_id, agent_id, server_name
            )
        except Exception as exc:
            logger.error(
                "Failed to soft-delete MCP config for '%s': %s",
                server_name,
                exc,
            )

        # Also remove Vault credential (per spec Q&A: Yes, DELETE removes Vault cred)
        vault_name = f"mcp_{server_name}_{agent_id}"
        try:
            await delete_vault_credential(user_id, vault_name)
        except Exception as exc:
            # Non-fatal — the credential may not exist
            logger.debug(
                "Vault cleanup for '%s': %s",
                vault_name,
                exc,
            )

        logger.info(
            "Deactivated MCP server '%s' for user='%s' agent='%s' (persisted=%s)",
            server_name,
            user_id,
            agent_id,
            removed,
        )

        return self.json_response({
            "server": server_name,
            "message": f"MCP server '{server_name}' deactivated.",
            "removed_from_db": removed,
        })


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def setup_mcp_helper_routes(app: web.Application) -> None:
    """Register MCP helper management routes on the aiohttp application.

    Registers four routes:
    - ``GET  /api/v1/agents/chat/{agent_id}/mcp-servers``
      → :class:`MCPHelperHandler` (catalog)
    - ``POST /api/v1/agents/chat/{agent_id}/mcp-servers``
      → :class:`MCPHelperHandler` (activate)
    - ``GET  /api/v1/agents/chat/{agent_id}/mcp-servers/active``
      → :class:`MCPActiveHandler` (list active)
    - ``DELETE /api/v1/agents/chat/{agent_id}/mcp-servers/{server_name}``
      → :class:`MCPServerItemHandler` (deactivate)

    Args:
        app: The aiohttp :class:`~aiohttp.web.Application` instance.
    """
    base = "/api/v1/agents/chat/{agent_id}/mcp-servers"

    # Catalog / activation handler
    app.router.add_route("GET", base, MCPHelperHandler)
    app.router.add_route("POST", base, MCPHelperHandler)

    # Active servers listing — must be registered BEFORE the {server_name} route
    app.router.add_route("GET", f"{base}/active", MCPActiveHandler)

    # Per-server deactivation
    app.router.add_route("DELETE", f"{base}/{{server_name}}", MCPServerItemHandler)
