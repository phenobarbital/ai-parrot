"""Unit tests for the Odoo JSON-2 transport."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub heavy parrot.utils dependencies ────────────────────────────────────

if "parrot.utils.types" not in sys.modules:
    _utils_types_stub = types.ModuleType("parrot.utils.types")
    _utils_types_stub.SafeDict = dict
    _utils_types_stub.cPrint = lambda *a, **kw: None
    sys.modules["parrot.utils.types"] = _utils_types_stub

if "parrot.utils" not in sys.modules:
    _utils_stub = types.ModuleType("parrot.utils")
    _utils_stub.SafeDict = dict
    _utils_stub.cPrint = lambda *a, **kw: None
    sys.modules["parrot.utils"] = _utils_stub

# ─────────────────────────────────────────────────────────────────────────────

from parrot.interfaces.odoointerface import (  # noqa: E402
    OdooAuthenticationError,
    OdooConfig,
    OdooRPCError,
)
from parrot_tools.odoo.transport.json2 import Json2Transport  # noqa: E402


def _config(**overrides) -> OdooConfig:
    return OdooConfig(
        url=overrides.pop("url", "https://odoo.example.com"),
        database=overrides.pop("database", "testdb"),
        username=overrides.pop("username", "admin"),
        password=overrides.pop("password", "api-key"),
        timeout=overrides.pop("timeout", 10),
        verify_ssl=overrides.pop("verify_ssl", False),
    )


def _mock_aiohttp_response(body, status: int = 200):
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=body)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.closed = False
    session.post = MagicMock(return_value=response)
    session.get = MagicMock(return_value=response)
    session.close = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_authenticate_uses_context_get_with_bearer_api_key():
    session = _mock_aiohttp_response({"uid": 42, "lang": "en_US"})
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        uid = await transport.authenticate()

    assert uid == 42
    session.post.assert_called_once()
    url = session.post.call_args.args[0]
    kwargs = session.post.call_args.kwargs
    assert url == "https://odoo.example.com/json/2/res.users/context_get"
    assert kwargs["headers"]["Authorization"] == "bearer api-key"
    assert kwargs["headers"]["X-Odoo-Database"] == "testdb"
    assert kwargs["json"] == {}


@pytest.mark.asyncio
async def test_execute_kw_search_read_maps_to_json2_named_body():
    session = _mock_aiohttp_response([{"id": 1, "name": "Acme"}])
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        result = await transport.execute_kw(
            "res.partner",
            "search_read",
            [[("is_company", "=", True)]],
            {"fields": ["name"], "limit": 5, "offset": 0},
        )

    assert result == [{"id": 1, "name": "Acme"}]
    url = session.post.call_args.args[0]
    body = session.post.call_args.kwargs["json"]
    assert url == "https://odoo.example.com/json/2/res.partner/search_read"
    assert body == {
        "domain": [("is_company", "=", True)],
        "fields": ["name"],
        "limit": 5,
        "offset": 0,
    }


@pytest.mark.asyncio
async def test_execute_kw_read_maps_ids_and_fields():
    session = _mock_aiohttp_response([{"id": 7, "name": "Acme"}])
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        await transport.execute_kw("res.partner", "read", [[7]], {"fields": ["name"]})

    assert session.post.call_args.kwargs["json"] == {"ids": [7], "fields": ["name"]}


@pytest.mark.asyncio
async def test_execute_kw_create_maps_values_to_vals_list():
    session = _mock_aiohttp_response(99)
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        await transport.execute_kw("res.partner", "create", [{"name": "Acme"}], None)

    assert session.post.call_args.kwargs["json"] == {"vals_list": {"name": "Acme"}}


@pytest.mark.asyncio
async def test_execute_kw_write_maps_ids_and_vals():
    session = _mock_aiohttp_response(True)
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        await transport.execute_kw("res.partner", "write", [[7], {"name": "Acme"}], None)

    assert session.post.call_args.kwargs["json"] == {
        "ids": [7],
        "vals": {"name": "Acme"},
    }


@pytest.mark.asyncio
async def test_execute_kw_unsupported_positional_args_raise_rpc_error():
    transport = Json2Transport(_config())

    with pytest.raises(OdooRPCError):
        await transport.execute_kw("res.partner", "custom_method", ["x"], None)


@pytest.mark.asyncio
async def test_version_uses_web_version_endpoint_and_normalizes_response():
    session = _mock_aiohttp_response({"version": "19.0", "version_info": [19, 0, 0, "final", 0, ""]})
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        info = await transport.version()

    assert session.get.call_args.args[0] == "https://odoo.example.com/web/version"
    assert info["server_serie"] == "19.0"
    assert info["server_version"] == "19.0"


@pytest.mark.asyncio
async def test_json2_unauthorized_maps_to_authentication_error():
    session = _mock_aiohttp_response({"message": "Invalid apikey"}, status=401)
    transport = Json2Transport(_config())

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(OdooAuthenticationError):
            await transport.authenticate()
