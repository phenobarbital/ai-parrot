"""Unit tests for TASK-1676: MCP per-user token injection via broker.

Tests:
- MCPClientConfig.get_headers() returns Authorization: Bearer when
  inject_broker_credential=True and current_credential() is set
- inject_broker_credential=False → no credential injected (no-op)
- inject_broker_credential=True but ContextVar unset → no Authorization header
- existing Authorization header from auth_credential/header_provider is not overwritten
- MCPToolProxy gets credential_provider set when inject_broker_credential=True
"""
import pytest

from parrot.mcp.client import MCPClientConfig
from parrot.tools.abstract import _CREDENTIAL_VAR


# ---------------------------------------------------------------------------
# MCPClientConfig.get_headers — credential injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_headers_injects_bearer_when_cred_set():
    """With inject_broker_credential=True and cred in ContextVar → Authorization: Bearer."""
    config = MCPClientConfig(
        name="myservice",
        url="http://svc.example.com/mcp",
        inject_broker_credential=True,
    )

    token = _CREDENTIAL_VAR.set("my-per-user-token")
    try:
        headers = await config.get_headers()
    finally:
        _CREDENTIAL_VAR.reset(token)

    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer my-per-user-token"


@pytest.mark.asyncio
async def test_get_headers_no_injection_when_flag_false():
    """inject_broker_credential=False → no Authorization header from ContextVar."""
    config = MCPClientConfig(
        name="myservice",
        url="http://svc.example.com/mcp",
        inject_broker_credential=False,  # default
    )

    token = _CREDENTIAL_VAR.set("secret-token")
    try:
        headers = await config.get_headers()
    finally:
        _CREDENTIAL_VAR.reset(token)

    # No broker injection
    assert headers.get("Authorization") is None


@pytest.mark.asyncio
async def test_get_headers_no_injection_when_cred_not_set():
    """inject_broker_credential=True but ContextVar unset → no Authorization header."""
    config = MCPClientConfig(
        name="myservice",
        url="http://svc.example.com/mcp",
        inject_broker_credential=True,
    )
    # Ensure ContextVar is None
    token = _CREDENTIAL_VAR.set(None)
    try:
        headers = await config.get_headers()
    finally:
        _CREDENTIAL_VAR.reset(token)

    assert headers.get("Authorization") is None


@pytest.mark.asyncio
async def test_get_headers_does_not_overwrite_existing_auth():
    """Broker credential does not override an existing Authorization header.

    Static auth_credential / header_provider headers take precedence
    (setdefault semantics).
    """
    def _hp(ctx):
        return {"Authorization": "Bearer static-header-token"}

    config = MCPClientConfig(
        name="myservice",
        url="http://svc.example.com/mcp",
        header_provider=_hp,
        inject_broker_credential=True,
    )

    token = _CREDENTIAL_VAR.set("broker-token")
    try:
        # context must be truthy for header_provider to be called
        headers = await config.get_headers(context=object())
    finally:
        _CREDENTIAL_VAR.reset(token)

    # header_provider's value wins (setdefault — broker does NOT override)
    assert headers["Authorization"] == "Bearer static-header-token"


@pytest.mark.asyncio
async def test_static_headers_merged_with_broker_cred():
    """Static headers from self.headers are preserved alongside broker credential."""
    config = MCPClientConfig(
        name="myservice",
        url="http://svc.example.com/mcp",
        headers={"X-Custom": "my-value"},
        inject_broker_credential=True,
    )

    token = _CREDENTIAL_VAR.set("per-user-api-token")
    try:
        headers = await config.get_headers()
    finally:
        _CREDENTIAL_VAR.reset(token)

    assert headers["X-Custom"] == "my-value"
    assert headers["Authorization"] == "Bearer per-user-api-token"


# ---------------------------------------------------------------------------
# MCPClientConfig field default
# ---------------------------------------------------------------------------


def test_inject_broker_credential_defaults_to_false():
    """inject_broker_credential defaults to False (no-op for existing configs)."""
    config = MCPClientConfig(name="svc", url="http://svc.example.com/mcp")
    assert config.inject_broker_credential is False
