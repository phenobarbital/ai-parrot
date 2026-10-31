"""End-to-end integration tests for the O365 device-code CLI flow (FEAT-266).

Exercises the full broker seam without standing up a real LLM-backed bot:

    CLI identity bootstrap (env O365_PRINCIPAL → CanonicalIdentityMapper)
      → PermissionContext(channel="cli", user_id=<canonical>)
        → CredentialBroker.from_config([...o365 device_code cfg...], deps)
          → AbstractTool(credential_provider="o365").execute(_broker=..., _cred_channel=...,
                                                              _cred_user_id=...)
            → O365DeviceCodeCredentialResolver.resolve() → VaultTokenSync o365:*

This mirrors the existing `tests/unit/test_tool_credential_seam.py` pattern
(a minimal `AbstractTool` subclass driving the broker gate directly) rather
than a full `AbstractBot` + LLM harness, since the seam under test is the
credential broker, not LLM orchestration.
"""
import pytest

from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import ProviderCredentialConfig
from parrot.auth.oauth2.workiq_provider import WorkIQOBOCredentialResolver
from parrot.tools.abstract import AbstractTool, ToolResult, current_credential


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeO365Client:
    """Stand-in for `O365Client` — simulates a successful device-code login."""

    tenant_id = "tenant-abc"

    def __init__(self):
        self.calls = 0

    async def interactive_login(self, scopes=None, open_browser=True, device_flow_callback=None, **kwargs):
        self.calls += 1
        if device_flow_callback:
            device_flow_callback({
                "verification_uri": "https://microsoft.com/devicelogin",
                "user_code": "A1B2-C3D4",
                "expires_in": 900,
                "message": "To sign in, use a web browser to open the page "
                           "https://microsoft.com/devicelogin and enter the code A1B2-C3D4.",
            })
        return {
            "access_token": "entra-access-tok",
            "refresh_token": "entra-refresh-tok",
            "expires_in": 3600,
            "scope": "User.Read offline_access",
            "id_token": "entra-id-tok",
        }

    def acquire_token_on_behalf_of(self, user_assertion, scopes=None):
        """Simulates the WorkIQ OBO exchange keyed off the Entra access token."""
        assert user_assertion == "entra-access-tok"
        return {"access_token": "workiq-obo-tok"}


class FakeO365OAuthManager:
    async def refresh_access_token(self, refresh_token):  # pragma: no cover - cache hit path only
        raise PermissionError("not exercised in this test")


class FakeVault:
    """In-memory stand-in for `VaultTokenSync` shared across resolvers."""

    def __init__(self):
        self._store = {}

    async def read_tokens(self, user_id, provider):
        return self._store.get((user_id, provider))

    async def store_tokens(self, user_id, provider, tokens):
        existing = self._store.get((user_id, provider), {})
        existing.update({k: v for k, v in tokens.items() if v is not None})
        self._store[(user_id, provider)] = existing


class O365GatedTool(AbstractTool):
    """Minimal tool gated on `credential_provider="o365"` (mirrors test_tool_credential_seam.py)."""

    name = "o365_gated_tool"
    description = "Needs an o365 token"
    credential_provider = "o365"

    async def _execute(self, **kwargs) -> ToolResult:
        cred = current_credential()
        return ToolResult(
            status="success",
            result=f"got-cred:{cred}",
            metadata={"credential_received": cred is not None},
        )


# ---------------------------------------------------------------------------
# End-to-end: CLI identity → broker → tool → resolver → vault
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_device_code_end_to_end(monkeypatch):

    o365_client = FakeO365Client()
    vault = FakeVault()
    broker = CredentialBroker.from_config(
        [ProviderCredentialConfig(provider="o365", auth="device_code")],
        o365_client=o365_client,
        o365_oauth_manager=FakeO365OAuthManager(),
        vault=vault,
    )

    tool = O365GatedTool()
    result = await tool.execute(
        _broker=broker,
        _cred_channel="cli",
        _cred_user_id="user@corp.com",
    )

    assert result.status == "success"
    assert result.result == "got-cred:entra-access-tok"
    assert o365_client.calls == 1

    # Token landed in the canonical o365:* vault store.
    persisted = vault._store[("user@corp.com", "o365")]
    assert persisted["access_token"] == "entra-access-tok"
    assert persisted["refresh_token"] == "entra-refresh-tok"

    # Second resolve is a cache hit — no second device-code round trip.
    result2 = await tool.execute(
        _broker=broker,
        _cred_channel="cli",
        _cred_user_id="user@corp.com",
    )
    assert result2.status == "success"
    assert result2.result == "got-cred:entra-access-tok"
    assert o365_client.calls == 1  # unchanged — cache hit


@pytest.mark.asyncio
async def test_devicecode_token_consumable_by_workiq_obo(monkeypatch):
    """Proves the canonical-store homologation (spec §1): one Entra sign-in,
    written by device-code, is readable by the existing WorkIQ OBO resolver.
    """

    o365_client = FakeO365Client()
    vault = FakeVault()
    broker = CredentialBroker.from_config(
        [ProviderCredentialConfig(provider="o365", auth="device_code")],
        o365_client=o365_client,
        o365_oauth_manager=FakeO365OAuthManager(),
        vault=vault,
    )

    # Step 1: device-code flow persists the canonical o365:* token set.
    tool = O365GatedTool()
    await tool.execute(
        _broker=broker,
        _cred_channel="cli",
        _cred_user_id="user@corp.com",
    )

    # Step 2: WorkIQOBOCredentialResolver reads the SAME vault instance and
    # performs the OBO exchange using the Entra token device-code wrote.
    workiq_resolver = WorkIQOBOCredentialResolver(
        o365_interface=o365_client,
        o365_oauth_manager=FakeO365OAuthManager(),
        vault_token_sync=vault,
    )
    obo_token = await workiq_resolver.resolve("cli", "user@corp.com")

    assert obo_token == "workiq-obo-tok"
