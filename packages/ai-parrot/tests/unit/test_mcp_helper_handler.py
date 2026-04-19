"""Unit tests for parrot.handlers.mcp_helper — MCPHelperHandler endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from parrot.handlers.mcp_helper import (
    MCPActiveHandler,
    MCPHelperHandler,
    MCPServerItemHandler,
    setup_mcp_helper_routes,
)
from parrot.mcp.registry import MCPServerRegistry, get_factory_map


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_request(
    method: str = "GET",
    match_info: dict | None = None,
    body: dict | None = None,
    session: dict | None = None,
) -> MagicMock:
    """Build a lightweight mock aiohttp Request."""
    req = MagicMock()
    req.method = method
    req.match_info = match_info or {"agent_id": "test-agent"}
    req.json = AsyncMock(return_value=body or {})
    req.session = session or {}
    return req


def _make_handler(
    handler_cls,
    request: MagicMock,
    session_data: dict | None = None,
) -> MagicMock:
    """Instantiate a handler-like object with mocked request and session."""
    # Use object() base so __getattr__ returns None rather than Mock
    handler = MagicMock()
    handler.request = request
    # Use a real dict so _get_user_id_from_handler can call .get()
    handler._session = session_data if session_data is not None else {"user_id": "test-user-42"}
    # json_response and error delegate to web.Response for unit tests
    handler.json_response = lambda data, status=200: web.Response(
        status=status, text=str(data), content_type="application/json"
    )
    handler.error = lambda msg, status=400: web.Response(
        status=status, text=str(msg), content_type="application/json"
    )
    return handler


# ---------------------------------------------------------------------------
# Tests: setup_mcp_helper_routes
# ---------------------------------------------------------------------------


class TestSetupMCPHelperRoutes:
    """Tests for the route registration function."""

    def test_importable(self) -> None:
        """setup_mcp_helper_routes is importable and callable."""
        assert callable(setup_mcp_helper_routes)

    def test_registers_routes(self) -> None:
        """Routes are added to the aiohttp app router."""
        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        joined = " ".join(routes)
        assert "mcp-servers" in joined

    def test_base_route_registered(self) -> None:
        """Base /mcp-servers route is registered."""
        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        assert any("mcp-servers" in r and "active" not in r and "server_name" not in r
                   for r in routes)

    def test_active_route_registered(self) -> None:
        """/mcp-servers/active route is registered."""
        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        assert any("active" in r for r in routes)

    def test_server_name_route_registered(self) -> None:
        """/mcp-servers/{server_name} route is registered."""
        app = web.Application()
        setup_mcp_helper_routes(app)

        routes = [r.resource.canonical for r in app.router.routes()
                  if hasattr(r, 'resource')]
        assert any("server_name" in r for r in routes)


# ---------------------------------------------------------------------------
# Tests: MCPHelperHandler.get
# ---------------------------------------------------------------------------


class TestMCPHelperHandlerGet:
    """Tests for GET /mcp-servers (catalog)."""

    @pytest.mark.asyncio
    async def test_get_returns_all_servers(self) -> None:
        """GET returns JSON catalog with all registered servers."""
        req = _make_mock_request(method="GET")
        handler = _make_handler(MCPHelperHandler, req)

        # Call the method directly (bypass auth decorators)
        response = await MCPHelperHandler.get(handler)

        # Should be a successful response
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_get_catalog_contains_perplexity(self) -> None:
        """GET catalog includes perplexity in the response text."""
        req = _make_mock_request(method="GET")
        handler = _make_handler(MCPHelperHandler, req)

        response = await MCPHelperHandler.get(handler)
        assert "perplexity" in response.text

    @pytest.mark.asyncio
    async def test_get_catalog_contains_fireflies(self) -> None:
        """GET catalog includes fireflies in the response text."""
        req = _make_mock_request(method="GET")
        handler = _make_handler(MCPHelperHandler, req)

        response = await MCPHelperHandler.get(handler)
        assert "fireflies" in response.text


# ---------------------------------------------------------------------------
# Tests: MCPHelperHandler.post
# ---------------------------------------------------------------------------


class TestMCPHelperHandlerPost:
    """Tests for POST /mcp-servers (activate)."""

    @pytest.mark.asyncio
    async def test_post_missing_user_id_returns_401(self) -> None:
        """POST returns 401 when session has no user_id."""
        req = _make_mock_request(method="POST", body={"server": "perplexity", "params": {}})
        handler = _make_handler(MCPHelperHandler, req, session_data={})

        response = await MCPHelperHandler.post(handler)
        assert response.status == 401

    @pytest.mark.asyncio
    async def test_post_invalid_json_returns_400(self) -> None:
        """POST returns 400 for invalid JSON."""
        req = _make_mock_request(method="POST")
        req.json = AsyncMock(side_effect=Exception("bad JSON"))
        handler = _make_handler(MCPHelperHandler, req)

        response = await MCPHelperHandler.post(handler)
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_missing_required_param_returns_400(self) -> None:
        """POST returns 400 when required param (api_key) is missing."""
        req = _make_mock_request(
            method="POST",
            body={"server": "perplexity", "params": {}},
        )
        handler = _make_handler(MCPHelperHandler, req)

        response = await MCPHelperHandler.post(handler)
        assert response.status == 400
        assert "api_key" in response.text

    @pytest.mark.asyncio
    async def test_post_unknown_server_returns_400(self) -> None:
        """POST returns 400 for an unknown server slug."""
        req = _make_mock_request(
            method="POST",
            body={"server": "unknown-server", "params": {}},
        )
        handler = _make_handler(MCPHelperHandler, req)

        response = await MCPHelperHandler.post(handler)
        assert response.status == 400

    @pytest.mark.asyncio
    async def test_post_separates_secret_params(self) -> None:
        """POST encrypts secret params (api_key) in Vault, not in non_secret_params."""
        req = _make_mock_request(
            method="POST",
            match_info={"agent_id": "test-agent"},
            body={"server": "perplexity", "params": {"api_key": "sk-test-123"}},
        )
        handler = _make_handler(MCPHelperHandler, req)

        saved_config = {}

        async def mock_save(config):
            saved_config.update(config.model_dump())

        with (
            patch("parrot.handlers.mcp_helper._store_vault_credential", new_callable=AsyncMock) as mock_vault,
            patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm,
            patch("parrot.handlers.mcp_helper.MCPPersistenceService") as mock_ps,
        ):
            mock_tool_manager = AsyncMock()
            mock_tool_manager.add_mcp_server = AsyncMock(return_value=["tool1", "tool2"])
            mock_tm.return_value = mock_tool_manager

            mock_ps_instance = mock_ps.return_value
            mock_ps_instance.save_user_mcp_config = AsyncMock(side_effect=mock_save)

            response = await MCPHelperHandler.post(handler)

        # api_key should NOT appear in non-secret params
        if "params" in saved_config:
            assert "api_key" not in saved_config["params"]

        # Vault store should have been called
        mock_vault.assert_called_once()
        call_kwargs = mock_vault.call_args
        stored_secrets = call_kwargs[0][2]  # positional: (user_id, vault_name, secret_params)
        assert "api_key" in stored_secrets

    @pytest.mark.asyncio
    async def test_post_calls_factory_and_add_mcp_server(self) -> None:
        """POST calls the correct factory and add_mcp_server on ToolManager."""
        req = _make_mock_request(
            method="POST",
            match_info={"agent_id": "a1"},
            body={"server": "perplexity", "params": {"api_key": "sk-x"}},
        )
        handler = _make_handler(MCPHelperHandler, req)

        mock_config = MagicMock()
        mock_factory_fn = MagicMock(return_value=mock_config)
        patched_map = dict(get_factory_map())
        patched_map["perplexity"] = mock_factory_fn

        with (
            patch("parrot.handlers.mcp_helper._store_vault_credential", new_callable=AsyncMock),
            patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm,
            patch("parrot.handlers.mcp_helper.MCPPersistenceService") as mock_ps,
            patch("parrot.handlers.mcp_helper.get_factory_map", return_value=patched_map),
        ):
            mock_tool_manager = AsyncMock()
            mock_tool_manager.add_mcp_server = AsyncMock(return_value=["plex-tool"])
            mock_tm.return_value = mock_tool_manager

            mock_ps.return_value.save_user_mcp_config = AsyncMock()

            response = await MCPHelperHandler.post(handler)

        # Factory was called
        mock_factory_fn.assert_called_once()
        # add_mcp_server was called with the factory result
        mock_tool_manager.add_mcp_server.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_post_persists_config(self) -> None:
        """POST calls MCPPersistenceService.save_user_mcp_config."""
        req = _make_mock_request(
            method="POST",
            match_info={"agent_id": "a1"},
            body={"server": "perplexity", "params": {"api_key": "sk-x"}},
        )
        handler = _make_handler(MCPHelperHandler, req)

        mock_factory_fn = MagicMock(return_value=MagicMock())
        patched_map = {"perplexity": mock_factory_fn}

        with (
            patch("parrot.handlers.mcp_helper._store_vault_credential", new_callable=AsyncMock),
            patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm,
            patch("parrot.handlers.mcp_helper.MCPPersistenceService") as mock_ps,
            patch("parrot.handlers.mcp_helper.get_factory_map", return_value=patched_map),
        ):
            mock_tool_manager = AsyncMock()
            mock_tool_manager.add_mcp_server = AsyncMock(return_value=["tool1"])
            mock_tm.return_value = mock_tool_manager

            mock_save = AsyncMock()
            mock_ps.return_value.save_user_mcp_config = mock_save

            await MCPHelperHandler.post(handler)

        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_returns_tool_names_on_success(self) -> None:
        """POST returns 200 with registered tool names."""
        req = _make_mock_request(
            method="POST",
            match_info={"agent_id": "a1"},
            body={"server": "perplexity", "params": {"api_key": "sk-x"}},
        )
        handler = _make_handler(MCPHelperHandler, req)

        mock_factory_fn = MagicMock(return_value=MagicMock())
        patched_map = {"perplexity": mock_factory_fn}

        with (
            patch("parrot.handlers.mcp_helper._store_vault_credential", new_callable=AsyncMock),
            patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm,
            patch("parrot.handlers.mcp_helper.MCPPersistenceService") as mock_ps,
            patch("parrot.handlers.mcp_helper.get_factory_map", return_value=patched_map),
        ):
            mock_tool_manager = AsyncMock()
            expected_tools = ["perplexity.search", "perplexity.chat"]
            mock_tool_manager.add_mcp_server = AsyncMock(return_value=expected_tools)
            mock_tm.return_value = mock_tool_manager
            mock_ps.return_value.save_user_mcp_config = AsyncMock()

            response = await MCPHelperHandler.post(handler)

        assert response.status == 200
        assert "perplexity" in response.text


# ---------------------------------------------------------------------------
# Tests: MCPActiveHandler.get
# ---------------------------------------------------------------------------


class TestMCPActiveHandlerGet:
    """Tests for GET /mcp-servers/active."""

    @pytest.mark.asyncio
    async def test_get_active_returns_server_list(self) -> None:
        """GET /active returns list of active server names."""
        req = _make_mock_request(match_info={"agent_id": "a1"})
        handler = _make_handler(MCPActiveHandler, req)

        with patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm:
            mock_tool_manager = MagicMock()
            mock_tool_manager.list_mcp_servers.return_value = ["perplexity", "fireflies"]
            mock_tm.return_value = mock_tool_manager

            response = await MCPActiveHandler.get(handler)

        assert response.status == 200
        assert "perplexity" in response.text

    @pytest.mark.asyncio
    async def test_get_active_empty_when_none(self) -> None:
        """GET /active returns empty list when no servers are active."""
        req = _make_mock_request(match_info={"agent_id": "a1"})
        handler = _make_handler(MCPActiveHandler, req)

        with patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm:
            mock_tool_manager = MagicMock()
            mock_tool_manager.list_mcp_servers.return_value = []
            mock_tm.return_value = mock_tool_manager

            response = await MCPActiveHandler.get(handler)

        assert response.status == 200


# ---------------------------------------------------------------------------
# Tests: MCPServerItemHandler.delete
# ---------------------------------------------------------------------------


class TestMCPServerItemHandlerDelete:
    """Tests for DELETE /mcp-servers/{server_name}."""

    @pytest.mark.asyncio
    async def test_delete_missing_user_id_returns_401(self) -> None:
        """DELETE returns 401 when session has no user_id."""
        req = _make_mock_request(
            match_info={"agent_id": "a1", "server_name": "perplexity"}
        )
        handler = _make_handler(MCPServerItemHandler, req, session_data={})

        response = await MCPServerItemHandler.delete(handler)
        assert response.status == 401

    @pytest.mark.asyncio
    async def test_delete_removes_from_toolmanager_and_db(self) -> None:
        """DELETE calls remove_mcp_server and MCPPersistenceService.remove."""
        req = _make_mock_request(
            match_info={"agent_id": "a1", "server_name": "perplexity"}
        )
        handler = _make_handler(MCPServerItemHandler, req)

        with (
            patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm,
            patch("parrot.handlers.mcp_helper.MCPPersistenceService") as mock_ps,
            patch("parrot.handlers.mcp_helper._delete_vault_credential", new_callable=AsyncMock),
        ):
            mock_tool_manager = AsyncMock()
            mock_tool_manager.remove_mcp_server = AsyncMock(return_value=True)
            mock_tm.return_value = mock_tool_manager

            mock_remove = AsyncMock(return_value=True)
            mock_ps.return_value.remove_user_mcp_config = mock_remove

            response = await MCPServerItemHandler.delete(handler)

        assert response.status == 200
        mock_tool_manager.remove_mcp_server.assert_called_once_with("perplexity")
        mock_remove.assert_called_once_with("test-user-42", "a1", "perplexity")

    @pytest.mark.asyncio
    async def test_delete_also_removes_vault_credential(self) -> None:
        """DELETE calls _delete_vault_credential for the Vault cleanup."""
        req = _make_mock_request(
            match_info={"agent_id": "a1", "server_name": "perplexity"}
        )
        handler = _make_handler(MCPServerItemHandler, req)

        with (
            patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm,
            patch("parrot.handlers.mcp_helper.MCPPersistenceService") as mock_ps,
            patch("parrot.handlers.mcp_helper._delete_vault_credential", new_callable=AsyncMock) as mock_del_vault,
        ):
            mock_tool_manager = AsyncMock()
            mock_tool_manager.remove_mcp_server = AsyncMock(return_value=True)
            mock_tm.return_value = mock_tool_manager
            mock_ps.return_value.remove_user_mcp_config = AsyncMock(return_value=True)

            await MCPServerItemHandler.delete(handler)

        mock_del_vault.assert_called_once_with("test-user-42", "mcp_perplexity_a1")

    @pytest.mark.asyncio
    async def test_delete_returns_confirmation(self) -> None:
        """DELETE returns 200 confirmation message."""
        req = _make_mock_request(
            match_info={"agent_id": "a1", "server_name": "perplexity"}
        )
        handler = _make_handler(MCPServerItemHandler, req)

        with (
            patch("parrot.handlers.mcp_helper._get_tool_manager", new_callable=AsyncMock) as mock_tm,
            patch("parrot.handlers.mcp_helper.MCPPersistenceService") as mock_ps,
            patch("parrot.handlers.mcp_helper._delete_vault_credential", new_callable=AsyncMock),
        ):
            mock_tool_manager = AsyncMock()
            mock_tool_manager.remove_mcp_server = AsyncMock(return_value=True)
            mock_tm.return_value = mock_tool_manager
            mock_ps.return_value.remove_user_mcp_config = AsyncMock(return_value=True)

            response = await MCPServerItemHandler.delete(handler)

        assert response.status == 200
        assert "perplexity" in response.text


# ---------------------------------------------------------------------------
# Tests: Factory map
# ---------------------------------------------------------------------------


class TestFactoryMap:
    """Tests for the get_factory_map() dispatch mapping."""

    def test_factory_map_has_all_non_genmedia_servers(self) -> None:
        """Factory map covers all servers with create_* functions."""
        factory_map = get_factory_map()
        expected = {
            "perplexity",
            "fireflies",
            "chrome-devtools",
            "google-maps",
            "alphavantage",
            "quic",
            "websocket",
        }
        assert expected.issubset(set(factory_map.keys()))

    def test_factory_map_values_are_callable(self) -> None:
        """All factory map values are callable functions."""
        factory_map = get_factory_map()
        for name, fn in factory_map.items():
            assert callable(fn), f"Factory for '{name}' is not callable"
