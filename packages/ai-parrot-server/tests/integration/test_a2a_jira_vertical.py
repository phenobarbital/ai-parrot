"""Integration tests for the Jira tool vertical over the A2A credential bridge.

FEAT-260 / TASK-1647 (Group B — Jira vertical).

Validates:
  - Jira tool (credential_provider="jira") goes through the bridge correctly.
  - Missing credential → Atlassian 3LO consent link (no secret in payload).
  - Resolved credential → tool runs + AuditLedger.append with key_fingerprint.
  - No service-identity fallback for jira (same invariant as stub).

A ``FakeJiraOAuthManager`` simulates the JiraOAuthManager contract
(``get_valid_token`` / ``create_authorization_url``) so no real Atlassian
connection is needed.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.models import Message, TaskState
from parrot.a2a.server import A2AServer
from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import OAuthCredentialResolver
from parrot.security.audit_ledger import AuditLedger, LocalHMACSigner


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeJiraOAuthManager:
    """Minimal JiraOAuthManager double for bridge tests."""

    def __init__(self, auth_url: str = "https://auth.atlassian.com/authorize?client_id=x"):
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self._auth_url = auth_url

    def grant(self, channel: str, user_id: str, token: str = "atlassian-access-token") -> None:
        self._tokens[f"{channel}:{user_id}"] = {"access_token": token}

    async def get_valid_token(self, channel: str, user_id: str) -> Optional[Dict[str, Any]]:
        return self._tokens.get(f"{channel}:{user_id}")

    async def create_authorization_url(self, channel: str, user_id: str):
        return self._auth_url, "jira-state-nonce"


class FakeJiraTool:
    """Minimal duck-typed Jira tool declaring provider='jira'."""
    name = "jira_create_issue"
    description = "Create a Jira issue."
    credential_provider = "jira"

    async def _execute(self, summary: str = "", **kwargs: Any) -> str:
        return f"jira-issue-created: {summary}"


class FakeSuspendedStore:
    def __init__(self):
        self._store: Dict[str, Any] = {}

    async def save(self, record: Any, ttl: int) -> None:
        self._store[record.interaction_id] = record

    async def load(self, interaction_id: str) -> Optional[Any]:
        return self._store.get(interaction_id)

    async def delete(self, interaction_id: str) -> None:
        self._store.pop(interaction_id, None)

    def has(self, interaction_id: str) -> bool:
        return interaction_id in self._store


def _make_jira_server(
    jira_manager: FakeJiraOAuthManager,
    store: FakeSuspendedStore,
    ledger: AuditLedger,
) -> A2AServer:
    agent = MagicMock()
    agent.name = "JiraAgent"
    agent.ask = AsyncMock(return_value="agent-response")
    agent.resume = AsyncMock(return_value="jira-resume")
    agent.tool_manager = None
    agent.tools = [FakeJiraTool()]

    resolver = OAuthCredentialResolver(jira_manager)
    broker = CredentialBroker(audit_ledger=ledger)
    broker.register("jira", resolver)

    server = A2AServer(agent, suspended_store=store, audit_ledger=ledger, broker=broker)
    return server


def _jira_tool_message(user_id: str, summary: str = "Fix auth bug") -> Message:
    msg = Message.user("", metadata={"user_id": user_id})
    msg.parts[0].data = {
        "tool": "jira_create_issue",
        "params": {"summary": summary},
    }
    msg.parts[0].text = None
    return msg


# ---------------------------------------------------------------------------
# TestJiraVertical
# ---------------------------------------------------------------------------


class TestJiraVertical:
    @pytest.mark.asyncio
    async def test_jira_missing_credential_suspends(self):
        """Jira tool: missing credential → INPUT_REQUIRED + consent link."""
        manager = FakeJiraOAuthManager()
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"jira-test"))
        server = _make_jira_server(manager, store, ledger)

        task = await server.process_message(_jira_tool_message("alice@example.com"))

        assert task.status.state == TaskState.INPUT_REQUIRED
        assert len(task.artifacts) == 1
        art = task.artifacts[0]
        assert art.name == "consent_required"
        assert art.metadata["provider"] == "jira"
        assert art.metadata["requires_auth"] is True

        # Consent link should contain the Atlassian auth URL
        assert any(
            "atlassian.com" in (p.text or "")
            for p in art.parts
        )

    @pytest.mark.asyncio
    async def test_jira_no_secret_in_payload(self):
        """Jira consent payload must not contain any token/secret."""
        manager = FakeJiraOAuthManager()
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"jira-test"))
        server = _make_jira_server(manager, store, ledger)

        task = await server.process_message(_jira_tool_message("bob@example.com"))

        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert "access_token" not in part.text
                    assert "atlassian-access-token" not in part.text
            for key, val in (art.metadata or {}).items():
                assert "token" not in str(val).lower() or key in ("provider",)

    @pytest.mark.asyncio
    async def test_jira_resolved_credential_runs_tool(self):
        """Resolved Jira credential → tool executes + COMPLETED."""
        manager = FakeJiraOAuthManager()
        manager.grant("a2a:copilot", "alice@example.com")
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"jira-test"))
        server = _make_jira_server(manager, store, ledger)

        task = await server.process_message(
            _jira_tool_message("alice@example.com", summary="Implement A2A bridge")
        )

        assert task.status.state == TaskState.COMPLETED
        assert any(
            "jira-issue-created" in (p.text or "")
            for art in task.artifacts
            for p in art.parts
        )

    @pytest.mark.asyncio
    async def test_jira_audit_entry_written(self):
        """Resolved Jira credential → AuditLedger entry with key_fingerprint, no secret."""
        manager = FakeJiraOAuthManager()
        manager.grant("a2a:copilot", "carol@example.com", "atlassian-secret-tok")
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"jira-test"))
        server = _make_jira_server(manager, store, ledger)

        await server.process_message(_jira_tool_message("carol@example.com"))

        assert ledger.entry_count == 1
        entry = next(iter(ledger._entries.values()))
        assert entry.provider == "jira"
        assert entry.user_id == "carol@example.com"
        assert entry.tool == "jira_create_issue"
        assert len(entry.key_fingerprint) == 64
        # Raw token must not appear
        assert "atlassian-secret-tok" not in entry.model_dump_json()

    @pytest.mark.asyncio
    async def test_jira_broker_registers_provider(self):
        """CredentialBroker correctly holds the registered jira resolver."""
        manager = FakeJiraOAuthManager()
        resolver = OAuthCredentialResolver(manager)

        broker = CredentialBroker()
        broker.register("jira", resolver)

        assert "jira" in broker._resolvers
        assert isinstance(broker._resolvers["jira"], OAuthCredentialResolver)

        # A2AServer built with the broker uses it for gating.
        agent = MagicMock()
        agent.name = "TestAgent"
        agent.tool_manager = None
        agent.tools = []
        server = A2AServer(agent, broker=broker)
        assert server._broker is broker

    @pytest.mark.asyncio
    async def test_jira_no_service_identity_fallback(self):
        """Jira tool: missing credential never runs under service identity."""
        manager = FakeJiraOAuthManager()  # no tokens
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"jira-test"))
        server = _make_jira_server(manager, store, ledger)

        task = await server.process_message(_jira_tool_message("dave@example.com"))

        assert task.status.state == TaskState.INPUT_REQUIRED
        assert ledger.entry_count == 0  # tool never ran
        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert "jira-issue-created" not in part.text
