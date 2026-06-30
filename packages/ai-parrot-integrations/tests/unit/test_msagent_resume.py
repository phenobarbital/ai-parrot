"""Unit tests for TASK-1674: MSAgentSDK suspend + proactive resume.

Tests:
- On CredentialRequired with stores configured: SuspendedExecution saved
- On CredentialRequired with stores configured: MsaConversationReference saved
- For static_key: nonce is appended to auth_url
- signin/verifyState triggers proactive resume for the user
- signin/tokenExchange triggers proactive resume for the user
- resume_by_nonce() re-runs ask() proactively (static-key callback)
- Original question is replayed — no user re-typing
- No resume when stores not configured (backward compat)
"""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to avoid the Cython chain triggered by parrot.utils.helpers
# ---------------------------------------------------------------------------

def _make_parrot_utils_stub() -> ModuleType:
    stub = ModuleType("parrot.utils.helpers")
    stub.RequestContext = MagicMock(return_value=MagicMock())
    return stub


def _make_parrot_utils_types_stub() -> ModuleType:
    stub = ModuleType("parrot.utils.types")
    stub.SafeDict = dict
    return stub


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeActivity:
    """Minimal activity double."""

    def __init__(
        self,
        text: str = "get my tasks",
        user_id: str = "user-abc",
        conversation_id: str = "conv-001",
        service_url: str = "https://smba.trafficmanager.net/amer/",
        channel_id: str = "msteams",
    ) -> None:
        self.text = text
        self.conversation = MagicMock()
        self.conversation.id = conversation_id
        self.service_url = service_url
        self.channel_id = channel_id
        from_prop = MagicMock()
        from_prop.aad_object_id = user_id
        from_prop.aadObjectId = None
        from_prop.id = user_id
        from_prop.email = None
        from_prop.name = "Test User"
        self.from_property = from_prop
        self.value = None


class FakeTurnContext:
    def __init__(self, activity: FakeActivity) -> None:
        self.activity = activity
        self._sent: list[Any] = []

    async def send_activity(self, activity: Any) -> None:
        self._sent.append(activity)

    @property
    def sent(self) -> list[Any]:
        return self._sent


class FakeAdapter:
    """Minimal CloudAdapter double for proactive-send tests."""

    def __init__(self) -> None:
        self._calls: list[tuple[str, Any, Any]] = []
        self._turn_context = MagicMock()
        self._turn_context.send_activity = AsyncMock()

    async def continue_conversation(
        self,
        agent_app_id: str,
        continuation_activity: Any,
        callback: Any,
    ) -> None:
        self._calls.append((agent_app_id, continuation_activity, callback))
        # Actually invoke the callback with the fake turn context.
        await callback(self._turn_context)


class FakeSuspendedStore:
    """In-memory SuspendedExecutionStore double."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def save(self, record: Any, ttl: int = 3600) -> None:
        self._store[record.interaction_id] = record

    async def load(self, interaction_id: str) -> Any:
        return self._store.get(interaction_id)

    async def delete(self, interaction_id: str) -> None:
        self._store.pop(interaction_id, None)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _make_agent(
    suspended_store=None,
    conv_ref_store=None,
    adapter=None,
    agent_app_id=None,
    broker=None,
):
    """Build a ParrotM365Agent with fakes for suspend/resume stores."""
    from parrot.integrations.msagentsdk.agent import ParrotM365Agent

    parrot_agent = MagicMock()
    parrot_agent.ask = AsyncMock(return_value=MagicMock(content="Here are your tasks."))
    return ParrotM365Agent(
        parrot_agent=parrot_agent,
        suspended_store=suspended_store,
        conv_ref_store=conv_ref_store,
        adapter=adapter,
        agent_app_id=agent_app_id,
        broker=broker,
    )


# ---------------------------------------------------------------------------
# MsaConversationRefStore unit tests (no Cython chain)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conv_ref_store_save_and_load_by_nonce():
    """MsaConversationRefStore.load_by_nonce returns the saved reference."""
    from parrot.integrations.msagentsdk.resume import (
        MsaConversationReference,
        MsaConversationRefStore,
    )

    store = MsaConversationRefStore()
    ref = MsaConversationReference(
        nonce="abc123",
        conversation_id="conv-001",
        service_url="https://smba.trafficmanager.net/amer/",
        user_id="user-abc",
    )
    await store.save(ref)
    loaded = await store.load_by_nonce("abc123")
    assert loaded is not None
    assert loaded.conversation_id == "conv-001"
    assert loaded.user_id == "user-abc"


@pytest.mark.asyncio
async def test_conv_ref_store_save_and_load_by_user():
    """MsaConversationRefStore.load_by_user returns the saved reference."""
    from parrot.integrations.msagentsdk.resume import (
        MsaConversationReference,
        MsaConversationRefStore,
    )

    store = MsaConversationRefStore()
    ref = MsaConversationReference(
        nonce="xyz789",
        conversation_id="conv-002",
        service_url="https://smba.trafficmanager.net/amer/",
        user_id="user-xyz",
    )
    await store.save(ref)
    loaded = await store.load_by_user("user-xyz")
    assert loaded is not None
    assert loaded.nonce == "xyz789"


@pytest.mark.asyncio
async def test_conv_ref_store_delete():
    """MsaConversationRefStore.delete removes both keys."""
    from parrot.integrations.msagentsdk.resume import (
        MsaConversationReference,
        MsaConversationRefStore,
    )

    store = MsaConversationRefStore()
    ref = MsaConversationReference(
        nonce="del001",
        conversation_id="conv-003",
        service_url="https://smba.trafficmanager.net/amer/",
        user_id="user-del",
    )
    await store.save(ref)
    await store.delete(ref)
    assert await store.load_by_nonce("del001") is None
    assert await store.load_by_user("user-del") is None


# ---------------------------------------------------------------------------
# _handle_message suspend-on-CredentialRequired
# (patched to avoid Cython chain)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspend_record_saved_on_credential_required():
    """When CredentialRequired is raised, a SuspendedExecution is saved."""
    from parrot.auth.credentials import CredentialRequired
    from parrot.integrations.msagentsdk.resume import MsaConversationRefStore

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()
    adapter = FakeAdapter()

    _types_stub = _make_parrot_utils_types_stub()
    _helpers_stub = _make_parrot_utils_stub()

    with patch.dict(sys.modules, {
        "parrot.utils.types": _types_stub,
        "parrot.utils.helpers": _helpers_stub,
    }):
        agent = _make_agent(
            suspended_store=suspended,
            conv_ref_store=conv_store,
            adapter=adapter,
            agent_app_id="test-app-id",
        )
        agent.parrot_agent.ask = AsyncMock(
            side_effect=CredentialRequired(
                provider="workiq",
                auth_url="https://auth.example.com/authorize",
                auth_kind="obo",
            )
        )
        activity = FakeActivity(text="summarise my emails")
        ctx = FakeTurnContext(activity)
        with patch.object(agent, "_emit_oauth_card", new_callable=AsyncMock):
            await agent._handle_message(ctx)

    assert len(suspended._store) == 1
    record = list(suspended._store.values())[0]
    assert record.user_id == "user-abc"
    # Original question stored in messages[0]
    assert record.messages[0]["content"] == "summarise my emails"


@pytest.mark.asyncio
async def test_conv_ref_saved_on_credential_required():
    """When CredentialRequired is raised, a MsaConversationReference is saved."""
    from parrot.auth.credentials import CredentialRequired
    from parrot.integrations.msagentsdk.resume import MsaConversationRefStore

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()
    adapter = FakeAdapter()

    _types_stub = _make_parrot_utils_types_stub()
    _helpers_stub = _make_parrot_utils_stub()

    with patch.dict(sys.modules, {
        "parrot.utils.types": _types_stub,
        "parrot.utils.helpers": _helpers_stub,
    }):
        agent = _make_agent(
            suspended_store=suspended,
            conv_ref_store=conv_store,
            adapter=adapter,
            agent_app_id="test-app-id",
        )
        agent.parrot_agent.ask = AsyncMock(
            side_effect=CredentialRequired(
                provider="workiq",
                auth_url="https://auth.example.com/authorize",
                auth_kind="obo",
            )
        )
        activity = FakeActivity(text="summarise my emails")
        ctx = FakeTurnContext(activity)
        with patch.object(agent, "_emit_oauth_card", new_callable=AsyncMock):
            await agent._handle_message(ctx)

    loaded = await conv_store.load_by_user("user-abc")
    assert loaded is not None
    assert loaded.conversation_id == "conv-001"
    assert loaded.service_url == "https://smba.trafficmanager.net/amer/"


@pytest.mark.asyncio
async def test_static_key_nonce_appended_to_auth_url():
    """For static_key: nonce is appended to auth_url so the capture route can call back."""
    from parrot.auth.credentials import CredentialRequired
    from parrot.integrations.msagentsdk.resume import MsaConversationRefStore

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()
    adapter = FakeAdapter()

    _types_stub = _make_parrot_utils_types_stub()
    _helpers_stub = _make_parrot_utils_stub()

    captured_adaptive_card_calls: list[tuple] = []

    with patch.dict(sys.modules, {
        "parrot.utils.types": _types_stub,
        "parrot.utils.helpers": _helpers_stub,
    }):
        agent = _make_agent(
            suspended_store=suspended,
            conv_ref_store=conv_store,
            adapter=adapter,
            agent_app_id="test-app-id",
        )
        agent.parrot_agent.ask = AsyncMock(
            side_effect=CredentialRequired(
                provider="fireflies",
                auth_url="https://app.example.com/auth/fireflies/capture",
                auth_kind="static_key",
            )
        )
        activity = FakeActivity(text="find my meetings")
        ctx = FakeTurnContext(activity)

        async def capture_adaptive(context, url, provider):
            captured_adaptive_card_calls.append((url, provider))

        with patch.object(agent, "_emit_adaptive_card", side_effect=capture_adaptive):
            await agent._handle_message(ctx)

    assert len(captured_adaptive_card_calls) == 1
    url, _ = captured_adaptive_card_calls[0]
    assert "nonce=" in url
    assert url.startswith("https://app.example.com/auth/fireflies/capture")


# ---------------------------------------------------------------------------
# Resume triggers: signin/verifyState and signin/tokenExchange
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signin_verify_triggers_proactive_resume():
    """signin/verifyState invokes _try_resume_by_user which sends the reply proactively."""
    from parrot.integrations.msagentsdk.resume import (
        MsaConversationReference,
        MsaConversationRefStore,
    )

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()
    adapter = FakeAdapter()

    # Pre-populate suspended state
    nonce = "resume-nonce-001"
    conv_ref = MsaConversationReference(
        nonce=nonce,
        conversation_id="conv-001",
        service_url="https://smba.trafficmanager.net/amer/",
        user_id="user-abc",
    )
    await conv_store.save(conv_ref)
    from parrot.human.suspended_store import SuspendedExecution
    suspension = SuspendedExecution(
        interaction_id=nonce,
        session_id="conv-001",
        user_id="user-abc",
        agent_name="FakeAgent",
        tool_call_id=nonce,
        messages=[{"role": "user", "content": "summarise my emails"}],
    )
    await suspended.save(suspension)

    agent = _make_agent(
        suspended_store=suspended,
        conv_ref_store=conv_store,
        adapter=adapter,
        agent_app_id="test-app-id",
    )

    # Build a fake signin/verifyState activity
    verify_activity = FakeActivity(text="")
    verify_activity.value = {"state": "magic123"}
    ctx = FakeTurnContext(verify_activity)

    await agent._handle_signin_verify(ctx)

    # adapter.continue_conversation should have been called once
    assert len(adapter._calls) == 1
    app_id, cont_act, _ = adapter._calls[0]
    assert app_id == "test-app-id"
    assert cont_act.conversation.id == "conv-001"

    # parrot_agent.ask should have been called with the original question
    agent.parrot_agent.ask.assert_awaited_once()
    call_kwargs = agent.parrot_agent.ask.call_args
    assert call_kwargs.kwargs.get("question") == "summarise my emails"

    # Records cleaned up after resume
    assert await conv_store.load_by_user("user-abc") is None
    assert await suspended.load(nonce) is None


@pytest.mark.asyncio
async def test_signin_exchange_triggers_proactive_resume():
    """signin/tokenExchange invokes _try_resume_by_user."""
    from parrot.integrations.msagentsdk.resume import (
        MsaConversationReference,
        MsaConversationRefStore,
    )

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()
    adapter = FakeAdapter()

    nonce = "exchange-nonce-001"
    conv_ref = MsaConversationReference(
        nonce=nonce,
        conversation_id="conv-002",
        service_url="https://smba.trafficmanager.net/amer/",
        user_id="user-abc",
    )
    await conv_store.save(conv_ref)
    from parrot.human.suspended_store import SuspendedExecution
    suspension = SuspendedExecution(
        interaction_id=nonce,
        session_id="conv-002",
        user_id="user-abc",
        agent_name="FakeAgent",
        tool_call_id=nonce,
        messages=[{"role": "user", "content": "create a jira issue"}],
    )
    await suspended.save(suspension)

    agent = _make_agent(
        suspended_store=suspended,
        conv_ref_store=conv_store,
        adapter=adapter,
        agent_app_id="test-app-id",
    )

    exchange_activity = FakeActivity(text="")
    exchange_activity.value = {"connectionName": "graph_sso"}
    ctx = FakeTurnContext(exchange_activity)

    await agent._handle_signin_exchange(ctx)

    assert len(adapter._calls) == 1
    agent.parrot_agent.ask.assert_awaited_once()
    assert agent.parrot_agent.ask.call_args.kwargs.get("question") == "create a jira issue"


# ---------------------------------------------------------------------------
# resume_by_nonce (static-key callback path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_by_nonce_delivers_result():
    """resume_by_nonce() re-runs ask() and proactively delivers the result."""
    from parrot.integrations.msagentsdk.resume import (
        MsaConversationReference,
        MsaConversationRefStore,
    )
    from parrot.human.suspended_store import SuspendedExecution

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()
    adapter = FakeAdapter()

    nonce = "static-key-nonce"
    conv_ref = MsaConversationReference(
        nonce=nonce,
        conversation_id="conv-ff",
        service_url="https://smba.trafficmanager.net/amer/",
        user_id="user-ff",
    )
    await conv_store.save(conv_ref)
    suspension = SuspendedExecution(
        interaction_id=nonce,
        session_id="conv-ff",
        user_id="user-ff",
        agent_name="FakeAgent",
        tool_call_id=nonce,
        messages=[{"role": "user", "content": "find my meetings"}],
    )
    await suspended.save(suspension)

    agent = _make_agent(
        suspended_store=suspended,
        conv_ref_store=conv_store,
        adapter=adapter,
        agent_app_id="test-app-id",
    )

    result = await agent.resume_by_nonce(nonce)

    assert result is True
    assert len(adapter._calls) == 1
    agent.parrot_agent.ask.assert_awaited_once()
    assert agent.parrot_agent.ask.call_args.kwargs.get("question") == "find my meetings"

    # Records cleaned up
    assert await conv_store.load_by_nonce(nonce) is None
    assert await suspended.load(nonce) is None


@pytest.mark.asyncio
async def test_resume_by_nonce_returns_false_when_not_found():
    """resume_by_nonce() returns False when no suspended record exists."""
    from parrot.integrations.msagentsdk.resume import MsaConversationRefStore

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()
    adapter = FakeAdapter()

    agent = _make_agent(
        suspended_store=suspended,
        conv_ref_store=conv_store,
        adapter=adapter,
        agent_app_id="test-app-id",
    )

    result = await agent.resume_by_nonce("nonexistent-nonce")
    assert result is False
    assert len(adapter._calls) == 0


# ---------------------------------------------------------------------------
# Backward compat: no resume when stores not configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_resume_without_stores():
    """Without stores/adapter configured, no suspension occurs (backward compat)."""
    from parrot.auth.credentials import CredentialRequired
    from parrot.integrations.msagentsdk.resume import MsaConversationRefStore

    suspended = FakeSuspendedStore()
    conv_store = MsaConversationRefStore()

    _types_stub = _make_parrot_utils_types_stub()
    _helpers_stub = _make_parrot_utils_stub()

    with patch.dict(sys.modules, {
        "parrot.utils.types": _types_stub,
        "parrot.utils.helpers": _helpers_stub,
    }):
        # No suspended_store / conv_ref_store / adapter
        agent = _make_agent()
        agent.parrot_agent.ask = AsyncMock(
            side_effect=CredentialRequired(
                provider="workiq",
                auth_url="https://auth.example.com/authorize",
                auth_kind="obo",
            )
        )
        activity = FakeActivity(text="summarise my emails")
        ctx = FakeTurnContext(activity)
        with patch.object(agent, "_emit_oauth_card", new_callable=AsyncMock):
            await agent._handle_message(ctx)

    # Nothing was saved in the stores
    assert len(suspended._store) == 0
    assert len(conv_store._mem) == 0
