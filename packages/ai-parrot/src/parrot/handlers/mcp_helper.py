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
from datetime import datetime, timezone
from typing import Any, Dict, List

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from navigator_session import get_session
from pydantic import ValidationError

from parrot.handlers.credentials_utils import decrypt_credential, encrypt_credential
from parrot.handlers.mcp_persistence import MCPPersistenceService
from parrot.interfaces.documentdb import DocumentDb
from parrot.mcp.registry import (
    ActivateMCPServerRequest,
    MCPParamType,
    MCPServerRegistry,
    UserMCPServerConfig,
    get_factory_map,
)
from parrot.tools.manager import ToolManager

try:
    from navigator_session.vault.config import get_active_key_id, load_master_keys
except ImportError:
    get_active_key_id = None  # type: ignore[assignment]
    load_master_keys = None   # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# DocumentDB collection for Vault credential storage (mirrors CredentialsHandler)
_CRED_COLLECTION: str = "user_credentials"

_registry = MCPServerRegistry()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vault helpers (mirrors _load_vault_keys from credentials.py)
# ---------------------------------------------------------------------------

def _load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]:
    """Load vault master keys from environment.

    Returns:
        Tuple of (active_key_id, active_master_key, all_master_keys).

    Raises:
        RuntimeError: If vault keys are not configured.
    """
    if load_master_keys is None or get_active_key_id is None:
        raise RuntimeError(
            "navigator_session.vault.config is not available. "
            "Ensure navigator-session is installed."
        )
    master_keys = load_master_keys()
    active_key_id = get_active_key_id()
    active_key = master_keys[active_key_id]
    return active_key_id, active_key, master_keys


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


async def _store_vault_credential(
    user_id: str,
    vault_name: str,
    secret_params: Dict[str, Any],
) -> None:
    """Encrypt and store secret MCP parameters in the Vault (user_credentials).

    Follows the same pattern as :class:`~parrot.handlers.credentials.CredentialsHandler`
    POST handler.  The credential is stored under a deterministic name so the
    restore hook can retrieve it.

    Args:
        user_id: Owner's user identifier.
        vault_name: Vault credential name (e.g. ``"mcp_perplexity_agent-1"``).
        secret_params: Dict of secret values to encrypt.
    """
    active_key_id, active_key, _ = _load_vault_keys()
    encrypted = encrypt_credential(secret_params, active_key_id, active_key)

    async with DocumentDb() as db:
        existing = await db.read_one(
            _CRED_COLLECTION,
            {"user_id": user_id, "name": vault_name},
        )
        now_str = datetime.now(timezone.utc).isoformat()
        if existing is None:
            doc = {
                "user_id": user_id,
                "name": vault_name,
                "credential": encrypted,
                "created_at": now_str,
                "updated_at": now_str,
            }
            await db.write(_CRED_COLLECTION, doc)
        else:
            await db.update_one(
                _CRED_COLLECTION,
                {"user_id": user_id, "name": vault_name},
                {"$set": {"credential": encrypted, "updated_at": now_str}},
            )


async def _retrieve_vault_credential(
    user_id: str,
    vault_name: str,
) -> Dict[str, Any]:
    """Decrypt and return a secret credential from the Vault.

    Args:
        user_id: Owner's user identifier.
        vault_name: Vault credential name.

    Returns:
        Decrypted dict of secret parameters.

    Raises:
        KeyError: If the credential is not found.
        RuntimeError: If vault keys are unavailable.
    """
    _, _, master_keys = _load_vault_keys()

    async with DocumentDb() as db:
        doc = await db.read_one(
            _CRED_COLLECTION,
            {"user_id": user_id, "name": vault_name},
        )

    if doc is None:
        raise KeyError(f"Vault credential '{vault_name}' not found for user '{user_id}'")

    return decrypt_credential(doc["credential"], master_keys)


async def _delete_vault_credential(user_id: str, vault_name: str) -> None:
    """Hard-delete a Vault credential from DocumentDB.

    Args:
        user_id: Owner's user identifier.
        vault_name: Vault credential name to remove.
    """
    async with DocumentDb() as db:
        await db.delete(
            _CRED_COLLECTION,
            {"user_id": user_id, "name": vault_name},
        )


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

    Attributes:
        COLLECTION: DocumentDB collection name (delegates to MCPPersistenceService).
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
            400 if params validation fails.
            500 on Vault or connection errors.
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

        # Separate secret params from non-secret params
        desc = _registry.get_server(req.server)
        if desc is None:
            return self.error(f"Server '{req.server}' not found.", status=400)

        secret_param_names = {
            p.name for p in desc.params if p.type == MCPParamType.SECRET
        }
        secret_params = {
            k: v for k, v in validated_params.items() if k in secret_param_names
        }
        non_secret_params = {
            k: v for k, v in validated_params.items() if k not in secret_param_names
        }

        # Store secrets in Vault (only if there are any)
        vault_name: str | None = None
        if secret_params:
            vault_name = f"mcp_{req.server}_{agent_id}"
            try:
                await _store_vault_credential(user_id, vault_name, secret_params)
            except RuntimeError as exc:
                logger.error("Vault unavailable for MCP activation: %s", exc)
                return self.error("Encryption service unavailable.", status=500)
            except Exception as exc:
                logger.error("Failed to store MCP secrets in Vault: %s", exc)
                return self.error("Failed to store credentials.", status=500)

        # Build the MCPClientConfig using the factory function
        # Merge non-secret params with decrypted secrets for the factory call
        factory_kwargs = {**non_secret_params, **secret_params}
        factory_fn = get_factory_map().get(req.server)

        if factory_fn is None:
            # genmedia and other servers without a create_* factory
            return self.error(
                f"Server '{req.server}' cannot be activated via this endpoint "
                f"(no factory function available).",
                status=400,
            )

        try:
            mcp_config = factory_fn(**factory_kwargs)
        except Exception as exc:
            logger.error("Factory function failed for '%s': %s", req.server, exc)
            return self.error(f"Failed to build server config: {exc}", status=500)

        # Register on the session ToolManager
        tool_manager = await _get_tool_manager(self.request, agent_id)
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
            await _delete_vault_credential(user_id, vault_name)
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
