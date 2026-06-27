"""Integration tests for the Fireflies MCP static-key vertical over the A2A bridge.

FEAT-263 / TASK-1648 (Group B — Fireflies MCP vertical).

OQ#6 resolved: Fireflies.ai accepts exclusively a static API key.
No OAuth flow. The key is captured OOB and stored per-user in vault.

Validates:
  - Fireflies tool (credential_provider="fireflies") routes through the bridge.
  - Missing API key → INPUT_REQUIRED + OOB capture link (no secret in payload).
  - Resolved API key → tool runs + AuditLedger entry with key_fingerprint.
  - No secret appears in the task payload (INVARIANT: audit has fingerprint only).
  - No service-identity fallback for fireflies.

A ``FakeVaultTokenSync`` simulates the VaultTokenSync contract
(``read_tokens`` / ``store_tokens``) so no real vault connection is needed.
``FakeFirefliesResolver`` directly subclasses ``FirefliesCredentialResolver``
and swaps the vault for the in-memory fake.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.models import Message, TaskState
from parrot.a2a.server import A2AServer
from parrot.integrations.mcp.fireflies_a2a import FirefliesCredentialResolver
from parrot.security.audit_ledger import AuditLedger, LocalHMACSigner


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

OOB_CAPTURE_URL = "https://app.example.com/auth/fireflies/capture"
FAKE_API_KEY = "ff-sk-test-abc123def456"


class FakeVaultTokenSync:
    """In-memory stand-in for VaultTokenSync that uses a plain dict."""

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

    def grant(self, user_id: str, provider: str, api_key: str) -> None:
        """Helper: pre-populate an API key as if the user had already submitted it."""
        self.store_tokens_sync(user_id, provider, {"api_key": api_key})

    def store_tokens_sync(
        self, user_id: str, provider: str, tokens: Dict[str, Any]
    ) -> None:
        self._store.setdefault(user_id, {}).setdefault(provider, {}).update(tokens)


class FakeFirefliesTool:
    """Minimal duck-typed Fireflies tool declaring provider='fireflies'."""

    name = "fireflies_search"
    description = "Search Fireflies.ai meeting transcripts."
    credential_provider = "fireflies"

    async def _execute(self, query: str = "", **kwargs: Any) -> str:
        return f"fireflies-results: {query}"


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


def _make_fireflies_server(
    vault: FakeVaultTokenSync,
    store: FakeSuspendedStore,
    ledger: AuditLedger,
) -> A2AServer:
    """Build an A2AServer wired with the Fireflies resolver and a fake tool."""
    agent = MagicMock()
    agent.name = "FirefliesAgent"
    agent.ask = AsyncMock(return_value="agent-response")
    agent.resume = AsyncMock(return_value="fireflies-resume")
    agent.tool_manager = None
    agent.tools = [FakeFirefliesTool()]

    resolver = FirefliesCredentialResolver(
        vault_token_sync=vault,
        oob_capture_url=OOB_CAPTURE_URL,
    )

    server = A2AServer(agent, suspended_store=store, audit_ledger=ledger)
    server.wire_fireflies_resolver(resolver)
    return server, resolver


def _fireflies_tool_message(user_id: str, query: str = "last week meetings") -> Message:
    """Build an A2A message requesting the fireflies_search tool."""
    msg = Message.user("", metadata={"user_id": user_id})
    msg.parts[0].data = {
        "tool": "fireflies_search",
        "params": {"query": query},
    }
    msg.parts[0].text = None
    return msg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFirefliesVertical:
    """End-to-end tests for the Fireflies MCP static-key vertical."""

    @pytest.mark.asyncio
    async def test_fireflies_missing_key_suspends(self):
        """Missing Fireflies API key → INPUT_REQUIRED with OOB capture link."""
        vault = FakeVaultTokenSync()
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"fireflies-test"))
        server, _ = _make_fireflies_server(vault, store, ledger)

        task = await server.process_message(
            _fireflies_tool_message("alice@example.com")
        )

        assert task.status.state == TaskState.INPUT_REQUIRED
        assert len(task.artifacts) == 1
        art = task.artifacts[0]
        assert art.name == "consent_required"
        assert art.metadata["provider"] == "fireflies"
        assert art.metadata["requires_auth"] is True

        # OOB capture link must appear in the consent text
        consent_text = " ".join(
            p.text or "" for p in art.parts
        )
        assert OOB_CAPTURE_URL in consent_text

    @pytest.mark.asyncio
    async def test_fireflies_no_secret_in_payload(self):
        """Fireflies consent payload must not contain any API key / secret."""
        vault = FakeVaultTokenSync()
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"fireflies-test"))
        server, _ = _make_fireflies_server(vault, store, ledger)

        task = await server.process_message(
            _fireflies_tool_message("bob@example.com")
        )

        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert FAKE_API_KEY not in part.text
                    assert "api_key" not in part.text
            for key, val in (art.metadata or {}).items():
                assert FAKE_API_KEY not in str(val)

    @pytest.mark.asyncio
    async def test_fireflies_resolved_key_runs_tool(self):
        """Resolved Fireflies API key → tool executes and task COMPLETES."""
        vault = FakeVaultTokenSync()
        # Pre-populate the user's API key (simulates after OOB capture)
        vault.store_tokens_sync("carol@example.com", "fireflies", {"api_key": FAKE_API_KEY})

        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"fireflies-test"))
        server, _ = _make_fireflies_server(vault, store, ledger)

        task = await server.process_message(
            _fireflies_tool_message("carol@example.com", query="Q3 all-hands")
        )

        assert task.status.state == TaskState.COMPLETED
        # The tool result must appear in some artifact part
        assert any(
            "fireflies-results" in (p.text or "")
            for art in task.artifacts
            for p in art.parts
        )

    @pytest.mark.asyncio
    async def test_fireflies_audit_entry_written(self):
        """Resolved key → AuditLedger entry with key_fingerprint; raw key absent."""
        vault = FakeVaultTokenSync()
        vault.store_tokens_sync("dave@example.com", "fireflies", {"api_key": FAKE_API_KEY})

        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"fireflies-audit"))
        server, _ = _make_fireflies_server(vault, store, ledger)

        await server.process_message(_fireflies_tool_message("dave@example.com"))

        assert ledger.entry_count == 1
        entry = next(iter(ledger._entries.values()))
        assert entry.provider == "fireflies"
        assert entry.user_id == "dave@example.com"
        assert entry.tool == "fireflies_search"
        # Fingerprint must be a SHA-256 hex string (64 chars)
        assert len(entry.key_fingerprint) == 64
        # Raw API key must NEVER appear in the serialised entry
        assert FAKE_API_KEY not in entry.model_dump_json()

    @pytest.mark.asyncio
    async def test_fireflies_store_key_then_resolve(self):
        """store_key() persists the API key; subsequent resolve() returns it."""
        vault = FakeVaultTokenSync()
        resolver = FirefliesCredentialResolver(
            vault_token_sync=vault,
            oob_capture_url=OOB_CAPTURE_URL,
        )

        # Before storing: resolve returns None
        result = await resolver.resolve("a2a:copilot", "eve@example.com")
        assert result is None

        # After store_key: resolve returns the key
        await resolver.store_key("eve@example.com", FAKE_API_KEY)
        result = await resolver.resolve("a2a:copilot", "eve@example.com")
        assert result == FAKE_API_KEY

    @pytest.mark.asyncio
    async def test_fireflies_get_auth_url_returns_oob_url(self):
        """get_auth_url() returns the configured OOB capture URL."""
        vault = FakeVaultTokenSync()
        resolver = FirefliesCredentialResolver(
            vault_token_sync=vault,
            oob_capture_url=OOB_CAPTURE_URL,
        )
        url = await resolver.get_auth_url("a2a:copilot", "frank@example.com")
        assert url == OOB_CAPTURE_URL

    @pytest.mark.asyncio
    async def test_fireflies_wire_resolver_registers_provider(self):
        """wire_fireflies_resolver() registers resolver under 'fireflies'."""
        agent = MagicMock()
        agent.name = "TestAgent"
        agent.tool_manager = None
        agent.tools = []

        server = A2AServer(agent)
        assert "fireflies" not in server._credential_resolvers

        vault = FakeVaultTokenSync()
        resolver = FirefliesCredentialResolver(
            vault_token_sync=vault,
            oob_capture_url=OOB_CAPTURE_URL,
        )
        server.wire_fireflies_resolver(resolver)

        assert "fireflies" in server._credential_resolvers
        assert server._credential_resolvers["fireflies"] is resolver

    @pytest.mark.asyncio
    async def test_fireflies_no_service_identity_fallback(self):
        """Missing API key never runs tool under service identity."""
        vault = FakeVaultTokenSync()  # empty — no key stored
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"fireflies-test"))
        server, _ = _make_fireflies_server(vault, store, ledger)

        task = await server.process_message(
            _fireflies_tool_message("grace@example.com")
        )

        assert task.status.state == TaskState.INPUT_REQUIRED
        assert ledger.entry_count == 0  # tool never ran
        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert "fireflies-results" not in part.text
