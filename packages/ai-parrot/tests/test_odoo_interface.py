"""Unit tests for OdooInterface.

All tests use mocked aiohttp responses — no live Odoo instance required.
"""
from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub out heavy/uncompiled project dependencies ────────────────────────────
# parrot.utils.types is a Cython .pyx file that may not be compiled in the test
# environment.  We register a lightweight stub before any parrot imports so the
# import chain parrot.interfaces → rss → http → parrot.utils doesn't fail.

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
else:
    _existing_utils = sys.modules["parrot.utils"]
    if not hasattr(_existing_utils, "SafeDict"):
        _existing_utils.SafeDict = dict  # type: ignore[attr-defined]
    if not hasattr(_existing_utils, "cPrint"):
        _existing_utils.cPrint = lambda *a, **kw: None  # type: ignore[attr-defined]

# ─────────────────────────────────────────────────────────────────────────────

from parrot.interfaces.odoointerface import (  # noqa: E402
    OdooConnectionError,
    OdooInterface,
    OdooAuthenticationError,
    OdooRPCError,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_odoo(**kwargs: Any) -> OdooInterface:
    """Create an OdooInterface with test defaults."""
    defaults = dict(
        url="https://odoo.example.com",
        database="testdb",
        username="admin",
        password="secret",
        timeout=10,
        verify_ssl=False,
    )
    defaults.update(kwargs)
    return OdooInterface(**defaults)


def mock_response(result: Any = None, error: dict | None = None) -> MagicMock:
    """Build a mock aiohttp response returning a JSON-RPC payload."""
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = AsyncMock(return_value=body)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    return mock_resp


def mock_session(response: MagicMock) -> MagicMock:
    """Build a mock aiohttp.ClientSession with a given response."""
    session = MagicMock()
    session.closed = False
    session.post = MagicMock(return_value=response)
    session.close = AsyncMock()
    return session


# ── Authentication Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authenticate_success() -> None:
    """Mock successful login — uid must be cached."""
    odoo = make_odoo()
    resp = mock_response(result=2)
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        uid = await odoo.authenticate()

    assert uid == 2
    assert odoo.uid == 2


@pytest.mark.asyncio
async def test_authenticate_invalid_credentials() -> None:
    """Mock login returning False — OdooAuthenticationError raised."""
    odoo = make_odoo()
    resp = mock_response(result=False)
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(OdooAuthenticationError):
            await odoo.authenticate()


@pytest.mark.asyncio
async def test_authenticate_returns_none() -> None:
    """Mock login returning None — OdooAuthenticationError raised."""
    odoo = make_odoo()
    resp = mock_response(result=None)
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(OdooAuthenticationError):
            await odoo.authenticate()


@pytest.mark.asyncio
async def test_authenticate_rpc_error() -> None:
    """Mock Odoo returning an RPC error during login — OdooRPCError raised."""
    odoo = make_odoo()
    resp = mock_response(error={"code": 200, "message": "Odoo Session Invalid", "data": {}})
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(OdooRPCError) as exc_info:
            await odoo.authenticate()

    assert "200" in str(exc_info.value)


@pytest.mark.asyncio
async def test_authenticate_network_error() -> None:
    """Mock a connection error — OdooConnectionError raised."""
    import aiohttp as _aiohttp

    odoo = make_odoo()
    session = MagicMock()
    session.closed = False
    broken_resp = MagicMock()
    broken_resp.__aenter__ = AsyncMock(side_effect=_aiohttp.ClientConnectionError("refused"))
    broken_resp.__aexit__ = AsyncMock(return_value=None)
    session.post = MagicMock(return_value=broken_resp)
    session.close = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(OdooConnectionError):
            await odoo.authenticate()


# ── execute_kw Tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_kw_payload_structure() -> None:
    """Verify the correct JSON-RPC 2.0 payload is posted to /jsonrpc."""
    odoo = make_odoo()
    odoo.uid = 1  # pre-auth

    resp = mock_response(result=[1, 2, 3])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.execute_kw("res.partner", "search", [[]])

    assert result == [1, 2, 3]

    # Inspect the call args
    call_kwargs = session.post.call_args
    posted_json = call_kwargs.kwargs["json"]

    assert posted_json["jsonrpc"] == "2.0"
    assert posted_json["method"] == "call"
    params = posted_json["params"]
    assert params["service"] == "object"
    assert params["method"] == "execute_kw"
    args = params["args"]
    assert args[0] == "testdb"       # database
    assert args[1] == 1              # uid
    # args[2] is password — we don't assert its value in the payload,
    # but we check it is NOT exposed via the logger (see security tests)
    assert args[3] == "res.partner"  # model
    assert args[4] == "search"       # method


@pytest.mark.asyncio
async def test_execute_kw_auto_authenticates() -> None:
    """execute_kw without prior auth should auto-authenticate first."""
    odoo = make_odoo()
    assert odoo.uid is None

    auth_resp = mock_response(result=5)
    exec_resp = mock_response(result=[10, 20])

    call_count = 0

    def response_factory(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return auth_resp
        return exec_resp

    session = MagicMock()
    session.closed = False
    session.post = MagicMock(side_effect=response_factory)
    session.close = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.execute_kw("sale.order", "search", [[]])

    assert odoo.uid == 5
    assert result == [10, 20]
    assert call_count == 2  # one auth + one execute_kw


@pytest.mark.asyncio
async def test_execute_kw_rpc_error() -> None:
    """OdooRPCError raised when Odoo returns an error response."""
    odoo = make_odoo()
    odoo.uid = 1

    resp = mock_response(error={"code": 1, "message": "Access Denied", "data": {}})
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        with pytest.raises(OdooRPCError) as exc_info:
            await odoo.execute_kw("res.partner", "search", [[]])

    assert exc_info.value.error_data["code"] == 1


# ── CRUD Method Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search() -> None:
    """search() passes domain in args and optional kwargs."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=[1, 2])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.search("res.partner", domain=[("name", "=", "Bob")], limit=5)

    assert result == [1, 2]
    posted = session.post.call_args.kwargs["json"]
    params = posted["params"]["args"]
    assert params[4] == "search"
    assert params[5] == [[("name", "=", "Bob")]]
    assert posted["params"]["args"][6]["limit"] == 5


@pytest.mark.asyncio
async def test_search_read_with_fields() -> None:
    """search_read() includes fields in kwargs."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=[{"id": 1, "name": "Bob"}])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.search_read(
            "res.partner",
            fields=["name", "email"],
            limit=10,
        )

    assert result[0]["name"] == "Bob"
    posted = session.post.call_args.kwargs["json"]
    kw = posted["params"]["args"][6]
    assert kw["fields"] == ["name", "email"]
    assert kw["limit"] == 10


@pytest.mark.asyncio
async def test_search_read_with_domain() -> None:
    """search_read() forwards domain in args."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=[])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        await odoo.search_read("res.partner", domain=[("is_company", "=", True)])

    posted = session.post.call_args.kwargs["json"]
    domain_arg = posted["params"]["args"][5]
    assert domain_arg == [[("is_company", "=", True)]]


@pytest.mark.asyncio
async def test_read_by_ids() -> None:
    """read() passes ids in args and fields in kwargs."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=[{"id": 42, "name": "Alice"}])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.read("res.partner", ids=[42], fields=["name"])

    assert result[0]["id"] == 42
    posted = session.post.call_args.kwargs["json"]
    assert posted["params"]["args"][5] == [[42]]
    assert posted["params"]["args"][6]["fields"] == ["name"]


@pytest.mark.asyncio
async def test_create_single_record() -> None:
    """create() with a single dict returns an int ID."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=99)
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.create("res.partner", {"name": "Alice", "email": "a@b.com"})

    assert result == 99


@pytest.mark.asyncio
async def test_create_multiple_records() -> None:
    """create() with a list of dicts returns a list of IDs."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=[100, 101])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.create(
            "res.partner",
            [{"name": "A"}, {"name": "B"}],
        )

    assert result == [100, 101]


@pytest.mark.asyncio
async def test_write_records() -> None:
    """write() forwards ids and values."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=True)
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.write("res.partner", [1, 2], {"name": "New Name"})

    assert result is True
    posted = session.post.call_args.kwargs["json"]
    assert posted["params"]["args"][5] == [[1, 2], {"name": "New Name"}]


@pytest.mark.asyncio
async def test_unlink_records() -> None:
    """unlink() forwards ids."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=True)
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.unlink("res.partner", [5, 6])

    assert result is True
    posted = session.post.call_args.kwargs["json"]
    assert posted["params"]["args"][5] == [[5, 6]]


@pytest.mark.asyncio
async def test_search_count() -> None:
    """search_count() returns integer count."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=42)
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.search_count("res.partner", domain=[("active", "=", True)])

    assert result == 42
    posted = session.post.call_args.kwargs["json"]
    assert posted["params"]["args"][4] == "search_count"
    assert posted["params"]["args"][5] == [[("active", "=", True)]]


@pytest.mark.asyncio
async def test_fields_get() -> None:
    """fields_get() forwards attributes and returns dict."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result={"name": {"type": "char", "string": "Name"}})
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await odoo.fields_get("res.partner", attributes=["string", "type"])

    assert "name" in result
    assert result["name"]["type"] == "char"
    posted = session.post.call_args.kwargs["json"]
    assert posted["params"]["args"][6]["attributes"] == ["string", "type"]


@pytest.mark.asyncio
async def test_none_kwargs_omitted() -> None:
    """Optional params with None values must NOT be sent in the kwargs dict."""
    odoo = make_odoo()
    odoo.uid = 1
    resp = mock_response(result=[])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        await odoo.search("res.partner")  # limit=None, order=None

    posted = session.post.call_args.kwargs["json"]
    kw = posted["params"]["args"][6]
    assert "limit" not in kw
    assert "order" not in kw


# ── Context Manager Tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_context_manager() -> None:
    """Session created on __aenter__ and closed on __aexit__."""
    odoo = make_odoo()

    mock_sess = MagicMock()
    mock_sess.closed = False
    mock_sess.close = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=mock_sess) as cls:
        async with odoo:
            assert odoo._session is not None

    mock_sess.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_explicit() -> None:
    """Explicit close() properly closes the session."""
    odoo = make_odoo()

    mock_sess = MagicMock()
    mock_sess.closed = False
    mock_sess.close = AsyncMock()

    with patch("aiohttp.ClientSession", return_value=mock_sess):
        await odoo._get_session()
        await odoo.close()

    mock_sess.close.assert_called_once()
    assert odoo._session is None


# ── Security Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_model_name_rejected() -> None:
    """Model names with special characters raise ValueError."""
    odoo = make_odoo()
    odoo.uid = 1

    with pytest.raises(ValueError, match="Invalid Odoo model name"):
        await odoo.execute_kw("res.partner; DROP TABLE", "search", [[]])

    with pytest.raises(ValueError):
        await odoo.execute_kw("Res.Partner", "search", [[]])

    with pytest.raises(ValueError):
        await odoo.execute_kw("", "search", [[]])


@pytest.mark.asyncio
async def test_password_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    """The password must not appear in any log output."""
    import logging

    odoo = make_odoo(password="super_secret_password_123")
    odoo.uid = 1
    resp = mock_response(result=[1])
    session = mock_session(resp)

    with patch("aiohttp.ClientSession", return_value=session):
        with caplog.at_level(logging.DEBUG, logger="OdooInterface"):
            await odoo.execute_kw("res.partner", "search", [[]])

    full_log = " ".join(caplog.messages)
    assert "super_secret_password_123" not in full_log


# ── Config Tests ──────────────────────────────────────────────────────────────


def test_config_from_kwargs() -> None:
    """Explicit kwargs must populate config correctly."""
    odoo = make_odoo(
        url="https://myodoo.com",
        database="prod",
        username="user",
        password="pass",
        timeout=60,
        verify_ssl=True,
    )
    assert odoo.config.url == "https://myodoo.com"
    assert odoo.config.database == "prod"
    assert odoo.config.username == "user"
    assert odoo.config.timeout == 60
    assert odoo.config.verify_ssl is True


def test_config_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """When kwargs are omitted, parrot.conf fallbacks are used."""
    monkeypatch.setattr("parrot.interfaces.odoointerface.ODOO_URL", "https://env-odoo.com")
    monkeypatch.setattr("parrot.interfaces.odoointerface.ODOO_DATABASE", "envdb")
    monkeypatch.setattr("parrot.interfaces.odoointerface.ODOO_USERNAME", "envuser")
    monkeypatch.setattr("parrot.interfaces.odoointerface.ODOO_PASSWORD", "envpass")
    monkeypatch.setattr("parrot.interfaces.odoointerface.ODOO_TIMEOUT", 45)
    monkeypatch.setattr("parrot.interfaces.odoointerface.ODOO_VERIFY_SSL", False)

    odoo = OdooInterface()
    assert odoo.config.url == "https://env-odoo.com"
    assert odoo.config.database == "envdb"
    assert odoo.config.username == "envuser"
    assert odoo.config.timeout == 45
    assert odoo.config.verify_ssl is False


def test_import_odoo_interface() -> None:
    """OdooInterface must be importable from parrot.interfaces."""
    from parrot.interfaces import OdooInterface as OI  # noqa: F401

    assert OI is OdooInterface
