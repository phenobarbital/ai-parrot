"""End-to-end integration tests for the A2A credential bridge (FEAT-260 / TASK-1646).

These tests validate the complete v1 happy path through the bridge:

  task → suspend (INPUT_REQUIRED, TEXT consent link, no secret)
       → simulated OAuth callback
       → resume (agent.resume called)
       → second invocation → COMPLETED (audit entry written)

And the negative paths:
  - TTL-expiry → graceful re-prompt.
  - No credential → never executes under service identity.

The ``StubCredentialedTool`` serves as the vehicle for the bridge proof.
No real IdP is needed; a ``FakeResolver`` simulates the credential lifecycle.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.models import Message, TaskState
from parrot.a2a.server import A2AServer
from parrot.security.audit_ledger import AuditLedger, LocalHMACSigner
from parrot.tools.stub_credentialed_tool import StubCredentialedTool


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeResolver:
    """Simulates per-user OAuth credential lifecycle."""

    def __init__(self, auth_url: str = "https://stub-provider.example.com/oauth"):
        self._credentials: Dict[str, str] = {}
        self._auth_url = auth_url

    def grant(self, user_id: str, credential: str = "stub-token-xyz") -> None:
        self._credentials[user_id] = credential

    def revoke(self, user_id: str) -> None:
        self._credentials.pop(user_id, None)

    async def resolve(self, channel: str, user_id: str) -> Optional[str]:
        return self._credentials.get(user_id)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return self._auth_url


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


def _make_server(
    resolver: FakeResolver,
    store: FakeSuspendedStore,
    ledger: AuditLedger,
) -> A2AServer:
    tool = StubCredentialedTool()
    agent = MagicMock()
    agent.name = "BridgeTestAgent"
    agent.ask = AsyncMock(return_value="ask-response")
    agent.resume = AsyncMock(return_value="resume-response")
    agent.tool_manager = None
    agent.tools = [tool]

    return A2AServer(
        agent,
        credential_resolvers={"stub": resolver},
        suspended_store=store,
        audit_ledger=ledger,
    )


def _tool_message(user_id: str, message: str = "hello") -> Message:
    msg = Message.user("", metadata={"user_id": user_id})
    msg.parts[0].data = {"tool": "stub_credentialed", "params": {"message": message}}
    msg.parts[0].text = None
    return msg


# ---------------------------------------------------------------------------
# TestStubEndToEnd — v1 acceptance criteria
# ---------------------------------------------------------------------------


class TestStubEndToEnd:
    @pytest.mark.asyncio
    async def test_stub_end_to_end_suspend_then_resume_and_complete(self):
        """Full happy path: suspend → simulated callback → second call → COMPLETED."""
        resolver = FakeResolver()
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"e2e-test"))
        server = _make_server(resolver, store, ledger)

        # --- Phase 1: first call — credential missing → INPUT_REQUIRED ---
        task1 = await server.process_message(_tool_message("alice@example.com"))
        assert task1.status.state == TaskState.INPUT_REQUIRED

        # Consent artifact must contain link + interaction_id, never a token
        assert len(task1.artifacts) == 1
        art = task1.artifacts[0]
        assert art.name == "consent_required"
        assert art.metadata["requires_auth"] is True
        interaction_id = art.metadata["interaction_id"]
        assert interaction_id

        # Verify no secret in payload
        for part in art.parts:
            if part.text:
                assert "stub-token" not in part.text
        assert "stub-token" not in str(art.metadata)

        # --- Phase 2: simulated OAuth callback persists credential ---
        resolver.grant("alice@example.com", "stub-token-xyz")
        await server.resume_from_oauth_callback(interaction_id, user_input="")

        # Suspended entry cleaned up
        assert not store.has(interaction_id)

        # --- Phase 3: second call — credential resolved → COMPLETED ---
        task2 = await server.process_message(_tool_message("alice@example.com"))
        assert task2.status.state == TaskState.COMPLETED
        # Tool result is in artifacts
        assert any(
            "stub-echo" in (p.text or "")
            for a in task2.artifacts
            for p in a.parts
        )

    @pytest.mark.asyncio
    async def test_audit_entry_written_on_resolved_credential(self):
        """Resolved credential → AuditLedger.append with key_fingerprint, no secret."""
        resolver = FakeResolver()
        resolver.grant("bob@example.com", "super-secret-stub-token")
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"e2e-test"))
        server = _make_server(resolver, store, ledger)

        await server.process_message(_tool_message("bob@example.com"))

        assert ledger.entry_count == 1
        entry = next(iter(ledger._entries.values()))
        assert entry.user_id == "bob@example.com"
        assert entry.provider == "stub"
        assert len(entry.key_fingerprint) == 64
        # Raw secret must NOT appear in any ledger field
        assert "super-secret-stub-token" not in entry.model_dump_json()


# ---------------------------------------------------------------------------
# TestResumeAfterTtlExpiry
# ---------------------------------------------------------------------------


class TestResumeAfterTtlExpiry:
    @pytest.mark.asyncio
    async def test_resume_after_ttl_expiry_does_not_crash(self):
        """Expired suspended entry → graceful re-prompt (no 500 / exception)."""
        resolver = FakeResolver()  # credential still None (not yet granted)
        store = FakeSuspendedStore()  # empty store (simulates TTL expiry)
        ledger = AuditLedger(signer=LocalHMACSigner(b"e2e-test"))
        server = _make_server(resolver, store, ledger)

        # Should not raise
        await server.resume_from_oauth_callback("expired-interaction-id")
        server.agent.resume.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_suspend_stores_entry_with_correct_fields(self):
        """Suspended execution entry has correct user_id and tool_call_id."""
        resolver = FakeResolver()
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"e2e-test"))
        server = _make_server(resolver, store, ledger)

        task = await server.process_message(_tool_message("carol@example.com"))

        interaction_id = task.artifacts[0].metadata["interaction_id"]
        suspended = await store.load(interaction_id)
        assert suspended is not None
        assert suspended.user_id == "carol@example.com"
        assert suspended.tool_call_id == "stub_credentialed"


# ---------------------------------------------------------------------------
# TestNoServiceIdentityFallback (negative, v1 acceptance criterion)
# ---------------------------------------------------------------------------


class TestNoServiceIdentityFallback:
    @pytest.mark.asyncio
    async def test_missing_identity_never_executes_tool(self):
        """Gated tool with no user identity → FAILED, never runs under service identity."""
        resolver = FakeResolver()
        resolver.grant("service@system.internal", "svc-token")  # service token available
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"e2e-test"))
        server = _make_server(resolver, store, ledger)

        # No user_id in message
        msg = Message.user("", metadata={})
        msg.parts[0].data = {"tool": "stub_credentialed", "params": {"message": "test"}}
        msg.parts[0].text = None

        task = await server.process_message(msg)

        assert task.status.state == TaskState.FAILED
        # Audit ledger must be empty — tool never ran
        assert ledger.entry_count == 0
        # No echo result in artifacts
        for art in task.artifacts:
            for part in art.parts:
                if part.text:
                    assert "stub-echo" not in part.text

    @pytest.mark.asyncio
    async def test_no_credential_never_executes_under_service_identity(self):
        """Credential=None → suspend/INPUT_REQUIRED, not COMPLETED under svc identity."""
        resolver = FakeResolver()  # returns None for all users
        store = FakeSuspendedStore()
        ledger = AuditLedger(signer=LocalHMACSigner(b"e2e-test"))
        server = _make_server(resolver, store, ledger)

        task = await server.process_message(_tool_message("dave@example.com"))

        # Must suspend — not run under any fallback identity
        assert task.status.state == TaskState.INPUT_REQUIRED
        # Audit ledger is empty — tool never ran
        assert ledger.entry_count == 0


# ---------------------------------------------------------------------------
# TestStubToolImport — acceptance criterion
# ---------------------------------------------------------------------------


class TestStubToolImport:
    def test_stub_credentialed_tool_importable(self):
        """from parrot.tools.stub_credentialed_tool import StubCredentialedTool works."""
        from parrot.tools.stub_credentialed_tool import StubCredentialedTool as T

        assert T.name == "stub_credentialed"
        assert T.credential_provider == "stub"

    @pytest.mark.asyncio
    async def test_stub_tool_executes(self):
        """StubCredentialedTool._execute returns echo result."""
        tool = StubCredentialedTool()
        result = await tool._execute(message="world")
        assert result == "stub-echo: world"

    @pytest.mark.asyncio
    async def test_stub_tool_with_metadata(self):
        """StubCredentialedTool._execute includes metadata in output."""
        tool = StubCredentialedTool()
        result = await tool._execute(message="ping", metadata="info")
        assert "stub-echo: ping" in result
        assert "info" in result
