"""Integration tests for the Work IQ MCP OBO vertical over the A2A bridge.

FEAT-263 / TASK-1649 (Group B — Work IQ OBO vertical).

OQ#5 resolved: Work IQ IS an MCP server; OBO auth is supported (delegated only;
app-only NOT supported).  Scope: api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask.
One Entra sign-in covers both o365 and work-iq.

Validates:
  - WorkIQTool (credential_provider="workiq") routes through the bridge.
  - No Entra token in vault → INPUT_REQUIRED + Entra sign-in link.
  - Entra token in vault → OBO exchange → Work IQ token → tool runs + COMPLETED.
  - OBO exchange failure → INPUT_REQUIRED (graceful degradation).
  - Cached Work IQ OBO token → tool runs without new OBO exchange.
  - AuditLedger entry with key_fingerprint; raw token absent.
  - No service-identity fallback for work-iq.
  - from parrot.tools.workiq_tool import WorkIQTool works.
  - wire_workiq_resolver() registers OBO resolver under "workiq".

``FakeVaultTokenSync`` simulates VaultTokenSync in-memory.
``FakeO365OAuthManager`` simulates the O365 OAuth manager for auth-URL generation.
``FakeO365Interface`` simulates O365Interface.acquire_token_on_behalf_of.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.models import Message, TaskState
from parrot.a2a.server import A2AServer
from parrot.auth.broker import CredentialBroker
from parrot.auth.oauth2.workiq_provider import (
    WorkIQOAuth2Provider,
    WorkIQOBOCredentialResolver,
    WORKIQ_SCOPE,
    WORKIQ_PROVIDER_ID,
)
from parrot.security.audit_ledger import AuditLedger, LocalHMACSigner
from parrot.tools.workiq_tool import WorkIQTool


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

ENTRA_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
FAKE_ENTRA_TOKEN = "entra-access-token-abc123"
FAKE_WORKIQ_TOKEN = "workiq-obo-token-xyz789"


class FakeVaultTokenSync:
    """In-memory stand-in for VaultTokenSync using a plain dict."""

    def __init__(self) -> None:
        # {user_id: {provider: {field: value}}}
        self._store: Dict[str, Dict[str, Dict[str, Any]]] = {}

    async def read_tokens(
        self, user_id: str, provider: str
    ) -> Optional[Dict[str, Any]]:
        return self._store.get(user_id, {}).get(provider)

    async def store_tokens(
        self, user_id: str, provider: str, tokens: Dict[str, Any]
    ) -> None:
        self._store.setdefault(user_id, {}).setdefault(provider, {}).update(tokens)

    def grant_entra(self, user_id: str, token: str = FAKE_ENTRA_TOKEN) -> None:
        """Pre-populate the user's Entra (o365) access token in vault."""
        self._store.setdefault(user_id, {})["o365"] = {"access_token": token}

    def grant_workiq(self, user_id: str, token: str = FAKE_WORKIQ_TOKEN) -> None:
        """Pre-populate a cached Work IQ OBO token in vault."""
        self._store.setdefault(user_id, {})["workiq"] = {"access_token": token}


class FakeO365OAuthManager:
    """Minimal O365 OAuth manager double for bridge tests."""

    def __init__(self, auth_url: str = ENTRA_AUTH_URL) -> None:
        self._auth_url = auth_url

    async def create_authorization_url(
        self, channel: str, user_id: str
    ):
        return self._auth_url, "state-nonce"


class FakeO365Interface:
    """Minimal O365Interface double that simulates acquire_token_on_behalf_of."""

    def __init__(self, obo_result: Optional[Dict[str, Any]] = None) -> None:
        """
        Args:
            obo_result: Dict returned by acquire_token_on_behalf_of.
                Pass ``None`` to simulate an OBO exchange failure (raises RuntimeError).
        """
        self._obo_result = obo_result
        self.obo_call_count: int = 0

    def acquire_token_on_behalf_of(
        self,
        user_assertion: str,
        scopes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Simulate OBO exchange.  Raises RuntimeError if configured with None."""
        self.obo_call_count += 1
        if self._obo_result is None:
            raise RuntimeError("Simulated OBO failure")
        return self._obo_result


class FakeSuspendedStore:
    """In-memory suspended execution store."""

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    async def save(self, record: Any, ttl: int) -> None:
        self._store[record.interaction_id] = record

    async def load(self, interaction_id: str) -> Optional[Any]:
        return self._store.get(interaction_id)

    async def delete(self, interaction_id: str) -> None:
        self._store.pop(interaction_id, None)

    def has(self, interaction_id: str) -> bool:
        return interaction_id in self._store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workiq_server(
    vault: FakeVaultTokenSync,
    o365: FakeO365Interface,
    store: FakeSuspendedStore,
    ledger: AuditLedger,
    o365_manager: Optional[FakeO365OAuthManager] = None,
) -> tuple[A2AServer, WorkIQOBOCredentialResolver]:
    """Build an A2AServer wired with the Work IQ OBO resolver and WorkIQTool."""
    if o365_manager is None:
        o365_manager = FakeO365OAuthManager()

    agent = MagicMock()
    agent.name = "WorkIQAgent"
    agent.ask = AsyncMock(return_value="agent-response")
    agent.resume = AsyncMock(return_value="workiq-resume")
    agent.tool_manager = None
    agent.tools = [WorkIQTool()]

    provider = WorkIQOAuth2Provider(
        o365_interface=o365,
        o365_oauth_manager=o365_manager,
        vault_token_sync=vault,
    )
    resolver = provider.credential_resolver()

    broker = CredentialBroker(audit_ledger=ledger)
    broker.register("workiq", resolver)

    server = A2AServer(agent, suspended_store=store, audit_ledger=ledger, broker=broker)
    return server, resolver


def _workiq_tool_message(user_id: str, query: str = "What are my open tasks?") -> Message:
    """Build an A2A message requesting the workiq_ask tool."""
    msg = Message.user("", metadata={"user_id": user_id})
    msg.parts[0].data = {
        "tool": "workiq_ask",
        "params": {"query": query},
    }
    msg.parts[0].text = None
    return msg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkIQVertical:
    """End-to-end tests for the Work IQ MCP OBO vertical over the A2A bridge."""

    @pytest.mark.asyncio
    async def test_workiq_import(self):
        """from parrot.tools.workiq_tool import WorkIQTool works."""
        from parrot.tools.workiq_tool import WorkIQTool as _WorkIQTool
        assert _WorkIQTool.credential_provider == "workiq"
        assert _WorkIQTool.name == "workiq_ask"

    @pytest.mark.asyncio
    async def test_workiq_no_entra_token_suspends(self):
        """No Entra token in vault → INPUT_REQUIRED with Entra sign-in link."""
        vault = FakeVaultTokenSync()  # empty — no Entra or Work IQ token
        o365 = FakeO365Interface(obo_result={"access_token": FAKE_WORKIQ_TOKEN})
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-test"))
        server, _ = _make_workiq_server(vault, o365, store, ledger)

        task = await server.process_message(
            _workiq_tool_message("alice@example.com")
        )

        assert task.status.state == TaskState.INPUT_REQUIRED
        assert len(task.artifacts) == 1
        art = task.artifacts[0]
        assert art.name == "consent_required"
        assert art.metadata["provider"] == "workiq"
        assert art.metadata["requires_auth"] is True

        # Entra sign-in link must appear in the consent text
        consent_text = " ".join(p.text or "" for p in art.parts)
        assert "login.microsoftonline.com" in consent_text

    @pytest.mark.asyncio
    async def test_workiq_no_secret_in_payload(self):
        """Consent payload must not contain any OBO token or Entra token."""
        vault = FakeVaultTokenSync()
        o365 = FakeO365Interface(obo_result=None)
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-test"))
        server, _ = _make_workiq_server(vault, o365, store, ledger)

        task = await server.process_message(
            _workiq_tool_message("bob@example.com")
        )

        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert FAKE_ENTRA_TOKEN not in part.text
                    assert FAKE_WORKIQ_TOKEN not in part.text
                    assert "access_token" not in part.text
            for key, val in (art.metadata or {}).items():
                assert FAKE_WORKIQ_TOKEN not in str(val)
                assert FAKE_ENTRA_TOKEN not in str(val)

    @pytest.mark.asyncio
    async def test_workiq_obo_exchange_success(self):
        """Entra token in vault → OBO exchange → Work IQ token → COMPLETED."""
        vault = FakeVaultTokenSync()
        vault.grant_entra("carol@example.com")  # Entra token available

        o365 = FakeO365Interface(obo_result={"access_token": FAKE_WORKIQ_TOKEN})
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-test"))
        server, _ = _make_workiq_server(vault, o365, store, ledger)

        task = await server.process_message(
            _workiq_tool_message("carol@example.com", query="Summarise my emails")
        )

        assert task.status.state == TaskState.COMPLETED
        # WorkIQTool result should appear in artifacts
        assert any(
            "Work IQ" in (p.text or "")
            for art in task.artifacts
            for p in art.parts
        )
        # OBO was called
        assert o365.obo_call_count == 1

    @pytest.mark.asyncio
    async def test_workiq_obo_covers_o365_and_workiq(self):
        """One Entra sign-in covers both o365 and work-iq (OBO reuses Entra token)."""
        vault = FakeVaultTokenSync()
        # Entra token granted (simulating o365 sign-in completion)
        vault.grant_entra("dave@example.com")

        o365 = FakeO365Interface(obo_result={"access_token": FAKE_WORKIQ_TOKEN})
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-test"))
        server, resolver = _make_workiq_server(vault, o365, store, ledger)

        # Verify: OBO exchange uses the existing Entra token (no new sign-in needed)
        token = await resolver.resolve("a2a:copilot", "dave@example.com")
        assert token == FAKE_WORKIQ_TOKEN
        assert o365.obo_call_count == 1  # One OBO call per first resolution

        # Second resolve uses cached OBO token — no new OBO call
        token2 = await resolver.resolve("a2a:copilot", "dave@example.com")
        assert token2 == FAKE_WORKIQ_TOKEN
        assert o365.obo_call_count == 1  # No extra OBO call

    @pytest.mark.asyncio
    async def test_workiq_obo_failure_suspends(self):
        """OBO exchange failure → INPUT_REQUIRED (graceful degradation)."""
        vault = FakeVaultTokenSync()
        vault.grant_entra("eve@example.com")

        # Simulate OBO failure
        o365 = FakeO365Interface(obo_result=None)
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-test"))
        server, _ = _make_workiq_server(vault, o365, store, ledger)

        task = await server.process_message(
            _workiq_tool_message("eve@example.com")
        )

        assert task.status.state == TaskState.INPUT_REQUIRED
        assert ledger.entry_count == 0  # tool never ran

    @pytest.mark.asyncio
    async def test_workiq_cached_obo_token_runs_tool(self):
        """Cached Work IQ OBO token → tool runs without new OBO exchange."""
        vault = FakeVaultTokenSync()
        vault.grant_workiq("frank@example.com")  # Cached OBO token already present

        o365 = FakeO365Interface(obo_result={"access_token": "should-not-be-used"})
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-test"))
        server, _ = _make_workiq_server(vault, o365, store, ledger)

        task = await server.process_message(
            _workiq_tool_message("frank@example.com")
        )

        assert task.status.state == TaskState.COMPLETED
        assert o365.obo_call_count == 0  # Cached token used, no new OBO

    @pytest.mark.asyncio
    async def test_workiq_audit_entry_written(self):
        """Resolved OBO token → AuditLedger entry with key_fingerprint; raw token absent."""
        vault = FakeVaultTokenSync()
        vault.grant_entra("grace@example.com")

        o365 = FakeO365Interface(obo_result={"access_token": FAKE_WORKIQ_TOKEN})
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-audit"))
        server, _ = _make_workiq_server(vault, o365, store, ledger)

        await server.process_message(_workiq_tool_message("grace@example.com"))

        assert ledger.entry_count == 1
        entry = next(iter(ledger._entries.values()))
        assert entry.provider == "workiq"
        assert entry.user_id == "grace@example.com"
        assert entry.tool == "workiq_ask"
        # Fingerprint must be a SHA-256 hex string (64 chars)
        assert len(entry.key_fingerprint) == 64
        # Raw OBO token must NEVER appear in the serialised entry
        assert FAKE_WORKIQ_TOKEN not in entry.model_dump_json()

    @pytest.mark.asyncio
    async def test_workiq_broker_registers_provider(self):
        """CredentialBroker correctly holds the registered workiq resolver."""
        vault = FakeVaultTokenSync()
        o365 = FakeO365Interface()
        resolver = WorkIQOBOCredentialResolver(
            o365_interface=o365,
            o365_oauth_manager=FakeO365OAuthManager(),
            vault_token_sync=vault,
        )

        broker = CredentialBroker()
        broker.register("workiq", resolver)

        # Broker internal dict has the resolver.
        assert "workiq" in broker._resolvers
        assert broker._resolvers["workiq"] is resolver

        # A2AServer built with the broker uses it for gating.
        agent = MagicMock()
        agent.name = "TestAgent"
        agent.tool_manager = None
        agent.tools = []
        server = A2AServer(agent, broker=broker)
        assert server._broker is broker

    @pytest.mark.asyncio
    async def test_workiq_no_service_identity_fallback(self):
        """Missing credential never runs tool under service identity."""
        vault = FakeVaultTokenSync()  # empty
        o365 = FakeO365Interface(obo_result={"access_token": FAKE_WORKIQ_TOKEN})
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"workiq-test"))
        server, _ = _make_workiq_server(vault, o365, store, ledger)

        task = await server.process_message(
            _workiq_tool_message("henry@example.com")
        )

        assert task.status.state == TaskState.INPUT_REQUIRED
        assert ledger.entry_count == 0  # tool never ran
        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert "Work IQ (via MCP)" not in part.text

    @pytest.mark.asyncio
    async def test_workiq_provider_metadata(self):
        """WorkIQOAuth2Provider has correct provider_id, scope, display_name."""
        provider = WorkIQOAuth2Provider(
            o365_interface=FakeO365Interface(),
            o365_oauth_manager=FakeO365OAuthManager(),
            vault_token_sync=FakeVaultTokenSync(),
        )
        assert provider.provider_id == WORKIQ_PROVIDER_ID
        assert provider.provider_id == "workiq"
        assert WORKIQ_SCOPE in provider.default_scopes
        assert provider.display_name == "Work IQ"

    @pytest.mark.asyncio
    async def test_workiq_provider_toolkit_factory_raises(self):
        """WorkIQOAuth2Provider.toolkit_factory raises NotImplementedError."""
        provider = WorkIQOAuth2Provider(
            o365_interface=FakeO365Interface(),
            o365_oauth_manager=FakeO365OAuthManager(),
            vault_token_sync=FakeVaultTokenSync(),
        )
        with pytest.raises(NotImplementedError):
            provider.toolkit_factory(None)
