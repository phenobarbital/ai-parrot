"""Unit tests for the XmlRpcTransport.

All tests mock ``xmlrpc.client.ServerProxy`` — no live Odoo required.
"""
from __future__ import annotations

import sys
import types
import xmlrpc.client
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy parrot.utils dependencies (Cython modules may be uncompiled) ──

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
    OdooConnectionError,
    OdooRPCError,
)
from parrot_tools.odoo.transport.xmlrpc import XmlRpcTransport  # noqa: E402


def _config(**overrides) -> OdooConfig:
    return OdooConfig(
        url=overrides.pop("url", "https://odoo.example.com"),
        database=overrides.pop("database", "testdb"),
        username=overrides.pop("username", "admin"),
        password=overrides.pop("password", "secret"),
        timeout=overrides.pop("timeout", 10),
        verify_ssl=overrides.pop("verify_ssl", False),
    )


@pytest.fixture
def proxies(monkeypatch):
    """Patch the ServerProxy factory so two distinct mocks back common/object."""
    common = MagicMock(name="common_proxy")
    object_ = MagicMock(name="object_proxy")
    proxies_iter = iter([common, object_])

    def _factory(*args, **kwargs):
        return next(proxies_iter)

    monkeypatch.setattr(
        "parrot_tools.odoo.transport.xmlrpc._build_proxy", _factory
    )
    return common, object_


# ── Authentication ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authenticate_success(proxies):
    common, _ = proxies
    common.authenticate.return_value = 7
    transport = XmlRpcTransport(_config())

    uid = await transport.authenticate()

    assert uid == 7
    assert transport.uid == 7
    common.authenticate.assert_called_once_with("testdb", "admin", "secret", {})


@pytest.mark.asyncio
async def test_authenticate_invalid_credentials(proxies):
    common, _ = proxies
    common.authenticate.return_value = False
    transport = XmlRpcTransport(_config())

    with pytest.raises(OdooAuthenticationError):
        await transport.authenticate()


@pytest.mark.asyncio
async def test_authenticate_xmlrpc_fault_maps_to_rpc_error(proxies):
    common, _ = proxies
    common.authenticate.side_effect = xmlrpc.client.Fault(2, "Access Denied")
    transport = XmlRpcTransport(_config())

    with pytest.raises(OdooRPCError):
        await transport.authenticate()


@pytest.mark.asyncio
async def test_authenticate_network_error_maps_to_connection_error(proxies):
    common, _ = proxies
    common.authenticate.side_effect = OSError("connection refused")
    transport = XmlRpcTransport(_config())

    with pytest.raises(OdooConnectionError):
        await transport.authenticate()


# ── execute_kw ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_kw_passes_correct_args(proxies):
    common, object_ = proxies
    common.authenticate.return_value = 11
    object_.execute_kw.return_value = [{"id": 1, "name": "Acme"}]
    transport = XmlRpcTransport(_config())

    rows = await transport.execute_kw(
        "res.partner", "search_read", [[]], {"fields": ["name"], "limit": 5}
    )

    assert rows == [{"id": 1, "name": "Acme"}]
    object_.execute_kw.assert_called_once_with(
        "testdb", 11, "secret",
        "res.partner", "search_read",
        [[]], {"fields": ["name"], "limit": 5},
    )


@pytest.mark.asyncio
async def test_execute_kw_validates_model_name(proxies):
    common, _ = proxies
    common.authenticate.return_value = 11
    transport = XmlRpcTransport(_config())

    with pytest.raises(ValueError):
        await transport.execute_kw("BAD MODEL", "search", [[]], {})


@pytest.mark.asyncio
async def test_execute_kw_fault_maps_to_rpc_error(proxies):
    common, object_ = proxies
    common.authenticate.return_value = 11
    object_.execute_kw.side_effect = xmlrpc.client.Fault(1, "boom")
    transport = XmlRpcTransport(_config())

    with pytest.raises(OdooRPCError):
        await transport.execute_kw("res.partner", "read", [[1]], {})


@pytest.mark.asyncio
async def test_version_returns_dict(proxies):
    common, _ = proxies
    common.version.return_value = {"server_serie": "17.0", "protocol_version": 1}
    transport = XmlRpcTransport(_config())

    info = await transport.version()

    assert info == {"server_serie": "17.0", "protocol_version": 1}


# ── Build-proxy SSL handling ────────────────────────────────────────────────


def test_build_proxy_disables_ssl_when_requested(monkeypatch):
    """Verify _build_proxy passes an unverified context for verify_ssl=False."""
    captured: dict = {}

    def fake_proxy(url, allow_none=True, context=None):
        captured["url"] = url
        captured["context"] = context
        return MagicMock()

    monkeypatch.setattr(xmlrpc.client, "ServerProxy", fake_proxy)
    from parrot_tools.odoo.transport.xmlrpc import _build_proxy

    _build_proxy("https://x.example.com/xmlrpc/2/common", verify_ssl=False)

    assert captured["url"] == "https://x.example.com/xmlrpc/2/common"
    assert captured["context"] is not None  # unverified context provided
