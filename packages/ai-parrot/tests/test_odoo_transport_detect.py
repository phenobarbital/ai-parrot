"""Unit tests for the Odoo transport auto-detector."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
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

from parrot.interfaces.odoointerface import OdooConfig  # noqa: E402
from parrot_tools.odoo.transport import (  # noqa: E402
    Json2Transport,
    JsonRpcTransport,
    XmlRpcTransport,
    auto_detect_transport,
    build_transport,
)
from parrot_tools.odoo.transport.detect import _serie_is_json2  # noqa: E402


def _config(**overrides) -> OdooConfig:
    return OdooConfig(
        url=overrides.pop("url", "https://odoo.example.com"),
        database=overrides.pop("database", "testdb"),
        username=overrides.pop("username", "admin"),
        password=overrides.pop("password", "secret"),
        timeout=overrides.pop("timeout", 10),
        verify_ssl=overrides.pop("verify_ssl", False),
    )


def _mock_aiohttp_with_payload(body: dict, status: int = 200):
    """Patch aiohttp.ClientSession to return a mock GET/POST response."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value=body)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=response)
    session.post = MagicMock(return_value=response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    return patch("aiohttp.ClientSession", return_value=session)


# ── Serie classifier ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "serie,expected",
    [
        ("19.0", True),
        ("20.0", True),
        ("18.0", False),
        ("17.0", False),
        ("14.0", False),
        ("", False),
        (None, False),
        ("garbage", False),
    ],
)
def test_serie_is_json2(serie, expected):
    assert _serie_is_json2(serie) is expected


# ── Auto-detect ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_detect_picks_json2_for_v19():
    body = {
        "version": "19.0",
        "version_info": [19, 0, 0, "final", 0, ""],
    }
    with _mock_aiohttp_with_payload(body):
        transport = await auto_detect_transport(_config())
    assert isinstance(transport, Json2Transport)


@pytest.mark.asyncio
async def test_auto_detect_picks_xmlrpc_for_v17():
    body = {
        "version": "17.0",
        "version_info": [17, 0, 0, "final", 0, ""],
    }
    with _mock_aiohttp_with_payload(body):
        transport = await auto_detect_transport(_config())
    assert isinstance(transport, XmlRpcTransport)


@pytest.mark.asyncio
async def test_auto_detect_falls_back_to_xmlrpc_on_probe_failure():
    """Network failure during both probes → XML-RPC fallback."""
    bad_session = MagicMock()
    bad_session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    bad_session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    bad_session.__aenter__ = AsyncMock(return_value=bad_session)
    bad_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=bad_session):
        transport = await auto_detect_transport(_config())
    assert isinstance(transport, XmlRpcTransport)


@pytest.mark.asyncio
async def test_auto_detect_uses_legacy_probe_when_web_version_unavailable():
    legacy_response = AsyncMock()
    legacy_response.status = 200
    legacy_response.json = AsyncMock(
        return_value={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"server_serie": "19.0", "server_version": "19.0+e"},
        }
    )
    legacy_response.__aenter__ = AsyncMock(return_value=legacy_response)
    legacy_response.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("missing"))
    session.post = MagicMock(return_value=legacy_response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=session):
        transport = await auto_detect_transport(_config())
    assert isinstance(transport, Json2Transport)


@pytest.mark.asyncio
async def test_auto_detect_falls_back_on_jsonrpc_error_payload():
    body = {"error": {"code": 500, "message": "x"}}
    with _mock_aiohttp_with_payload(body):
        transport = await auto_detect_transport(_config())
    assert isinstance(transport, XmlRpcTransport)


# ── build_transport ─────────────────────────────────────────────────────────


def test_build_transport_explicit_json2():
    t = build_transport("json2", _config())
    assert isinstance(t, Json2Transport)


def test_build_transport_explicit_jsonrpc_legacy():
    t = build_transport("jsonrpc", _config())
    assert isinstance(t, JsonRpcTransport)


def test_build_transport_explicit_xmlrpc():
    t = build_transport("xmlrpc", _config())
    assert isinstance(t, XmlRpcTransport)


def test_build_transport_auto_returns_none():
    assert build_transport("auto", _config()) is None


def test_build_transport_unknown_raises():
    with pytest.raises(ValueError):
        build_transport("websocket", _config())  # type: ignore[arg-type]
