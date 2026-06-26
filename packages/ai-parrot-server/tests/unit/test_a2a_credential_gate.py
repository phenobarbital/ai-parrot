"""Unit tests for A2A credential gate + suspend (FEAT-260 / TASK-1644).

Tests:
- resolve()==None → SuspendedExecution saved + TEXT consent link returned.
- Consent payload contains link + interaction_id only — never a token.
- Resolved credential → tool runs + AuditLedger.append called.
- Negative: per-user tool with no credential never executes under service identity.
- Tool without credential_provider → legacy path (no gate).
- Missing user_id with gated tool → fails closed.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.models import Message, TaskState
from parrot.a2a.server import A2AServer
from parrot.security.audit_ledger import AuditLedger, LocalHMACSigner


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class FakeResolver:
    """Fake CredentialResolver: returns None until a credential is set."""

    def __init__(self, auth_url: str = "https://auth.example.com/oauth"):
        self._credential: Optional[str] = None
        self._auth_url = auth_url

    def set_credential(self, value: str) -> None:
        self._credential = value

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        return self._credential

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return self._auth_url


class FakeSuspendedStore:
    """In-memory SuspendedExecutionStore double."""

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


class StubCredentialedTool:
    """Minimal tool that declares a credential requirement."""
    name = "stub_tool"
    description = "Stub credentialed tool for testing."
    credential_provider = "stub"

    async def _execute(self, **kwargs) -> str:
        return f"stub-result: {kwargs}"


class PlainTool:
    """Tool without credential_provider — no gate."""
    name = "plain_tool"
    description = "A plain tool."

    async def _execute(self, **kwargs) -> str:
        return "plain-result"


def _make_server(
    resolver: Optional[FakeResolver] = None,
    store: Optional[FakeSuspendedStore] = None,
    ledger: Optional[AuditLedger] = None,
    tools: Optional[list] = None,
) -> A2AServer:
    """Return an A2AServer configured with the given components."""
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.ask = AsyncMock(return_value="agent-response")
    agent.resume = AsyncMock(return_value="resume-response")
    agent.tool_manager = None
    agent.tools = tools or []

    credential_resolvers = {"stub": resolver} if resolver else {}
    server = A2AServer(
        agent,
        credential_resolvers=credential_resolvers,
        suspended_store=store,
        audit_ledger=ledger,
    )
    return server


def _make_message(user_id: Optional[str] = "alice@example.com") -> Message:
    meta = {"user_id": user_id} if user_id else {}
    return Message.user("hello", metadata=meta)


# ---------------------------------------------------------------------------
# TestCredentialGateSuspend
# ---------------------------------------------------------------------------


class TestCredentialGateSuspend:
    @pytest.mark.asyncio
    async def test_resolve_none_triggers_suspend(self):
        """resolve()==None → SuspendedExecution saved + INPUT_REQUIRED task."""
        resolver = FakeResolver()  # returns None by default
        store = FakeSuspendedStore()
        server = _make_server(resolver=resolver, store=store, tools=[StubCredentialedTool()])

        msg = _make_message(user_id="alice@example.com")
        # Direct tool invocation via structured data
        msg.parts[0].data = {"tool": "stub_tool", "params": {}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        assert task.status.state == TaskState.INPUT_REQUIRED
        # Exactly one consent artifact
        assert len(task.artifacts) == 1
        artifact = task.artifacts[0]
        assert artifact.name == "consent_required"
        assert artifact.metadata["requires_auth"] is True
        assert "interaction_id" in artifact.metadata

    @pytest.mark.asyncio
    async def test_no_secret_in_a2a_payload(self):
        """Consent payload contains link + interaction_id — never a token/secret."""
        resolver = FakeResolver(auth_url="https://auth.example.com/oauth?client_id=x")
        store = FakeSuspendedStore()
        server = _make_server(resolver=resolver, store=store, tools=[StubCredentialedTool()])

        msg = _make_message(user_id="alice@example.com")
        msg.parts[0].data = {"tool": "stub_tool", "params": {}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        artifact = task.artifacts[0]
        # No raw credential in any artifact field
        for part in artifact.parts:
            if part.text:
                assert "secret" not in part.text.lower()
                assert "password" not in part.text.lower()
                assert "token" not in part.text.lower()
        # Metadata has provider and interaction_id but never a secret
        meta = artifact.metadata or {}
        assert "token" not in str(meta).lower()

    @pytest.mark.asyncio
    async def test_suspended_execution_persisted_in_store(self):
        """resolve()==None → SuspendedExecution saved to the store."""
        resolver = FakeResolver()
        store = FakeSuspendedStore()
        server = _make_server(resolver=resolver, store=store, tools=[StubCredentialedTool()])

        msg = _make_message(user_id="alice@example.com")
        msg.parts[0].data = {"tool": "stub_tool", "params": {}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        interaction_id = task.artifacts[0].metadata["interaction_id"]
        assert store.has(interaction_id), "SuspendedExecution not persisted"

        suspended = await store.load(interaction_id)
        assert suspended.user_id == "alice@example.com"
        assert suspended.tool_call_id == "stub_tool"

    @pytest.mark.asyncio
    async def test_no_service_identity_fallback(self):
        """Negative: gated tool with no credential never runs under service identity."""
        resolver = FakeResolver()  # always None
        store = FakeSuspendedStore()
        server = _make_server(resolver=resolver, store=store, tools=[StubCredentialedTool()])

        msg = _make_message(user_id="alice@example.com")
        msg.parts[0].data = {"tool": "stub_tool", "params": {}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        # Tool must NOT have run — state is INPUT_REQUIRED, not COMPLETED
        assert task.status.state == TaskState.INPUT_REQUIRED
        # No "stub-result" in any artifact
        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert "stub-result" not in part.text


# ---------------------------------------------------------------------------
# TestCredentialGateResolved
# ---------------------------------------------------------------------------


class TestCredentialGateResolved:
    @pytest.mark.asyncio
    async def test_resolved_credential_runs_tool(self):
        """Resolved credential → tool executes and task completes."""
        resolver = FakeResolver()
        resolver.set_credential("valid-token-abc")
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"test"))
        server = _make_server(
            resolver=resolver, store=store, ledger=ledger,
            tools=[StubCredentialedTool()]
        )

        msg = _make_message(user_id="alice@example.com")
        msg.parts[0].data = {"tool": "stub_tool", "params": {"key": "value"}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        assert task.status.state == TaskState.COMPLETED
        # Tool result is in artifacts
        assert any(
            "stub-result" in (p.text or "")
            for art in task.artifacts
            for p in art.parts
        )

    @pytest.mark.asyncio
    async def test_resolved_credential_triggers_audit(self):
        """Resolved credential → AuditLedger.append called with key_fingerprint."""
        resolver = FakeResolver()
        resolver.set_credential("valid-token-abc")
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"test"))
        server = _make_server(
            resolver=resolver, store=store, ledger=ledger,
            tools=[StubCredentialedTool()]
        )

        msg = _make_message(user_id="alice@example.com")
        msg.parts[0].data = {"tool": "stub_tool", "params": {}}
        msg.parts[0].text = None

        await server.process_message(msg)

        assert ledger.entry_count == 1
        entry = next(iter(ledger._entries.values()))
        assert entry.user_id == "alice@example.com"
        assert entry.tool == "stub_tool"
        assert entry.provider == "stub"
        assert len(entry.key_fingerprint) == 64
        # No raw credential in the entry
        assert "valid-token-abc" not in entry.model_dump_json()


# ---------------------------------------------------------------------------
# TestNoGatePath
# ---------------------------------------------------------------------------


class TestNoGatePath:
    @pytest.mark.asyncio
    async def test_plain_tool_bypasses_gate(self):
        """Tool without credential_provider uses the legacy path (no gate)."""
        server = _make_server(tools=[PlainTool()])  # no resolvers

        msg = _make_message(user_id="alice@example.com")
        msg.parts[0].data = {"tool": "plain_tool", "params": {}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        assert task.status.state == TaskState.COMPLETED

    @pytest.mark.asyncio
    async def test_missing_user_id_with_gated_tool_fails_closed(self):
        """Gated tool with no user identity → fails closed, no execution."""
        resolver = FakeResolver()
        resolver.set_credential("some-token")
        server = _make_server(resolver=resolver, tools=[StubCredentialedTool()])

        # No user_id in metadata
        msg = _make_message(user_id=None)
        msg.parts[0].data = {"tool": "stub_tool", "params": {}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        assert task.status.state == TaskState.FAILED
        # Explicitly no service-identity fallback
        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert "stub-result" not in part.text
