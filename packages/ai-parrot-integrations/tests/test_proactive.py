"""
Unit tests for the Teams HITL proactive messaging module (TASK-004 / FEAT-205).

Tests cover:
  - Warm path: cached convref → continue_conversation
  - Cold path: no cache → create_conversation → cache ref
  - TTL + serviceUrl refresh on inbound contact (OQ-4)
  - Cold-create failure propagates as ProactiveDeliveryError
  - ConversationReferenceStore get/set/refresh
  - SentActivityStore get/set/delete
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from botbuilder.schema import (
    ChannelAccount,
    ConversationAccount,
    ConversationReference,
)

from parrot.integrations.msteams.graph import ResolvedTeamsUser
from parrot.integrations.msteams.proactive import (
    ConversationReferenceStore,
    ProactiveDeliveryError,
    ProactiveMessenger,
    SentActivityStore,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_conv_ref(
    email: str = "user@contoso.com",
    service_url: str = "https://smba.trafficmanager.net/",
    aad_object_id: str = "aad-001",
) -> ConversationReference:
    """Build a minimal ConversationReference for testing."""
    return ConversationReference(
        channel_id="msteams",
        service_url=service_url,
        user=ChannelAccount(id=aad_object_id, aad_object_id=aad_object_id),
        bot=ChannelAccount(id="hitl-bot-id"),
        conversation=ConversationAccount(
            id=f"conv-{aad_object_id}",
            is_group=False,
            tenant_id="test-tenant",
        ),
    )


def _make_redis(stored: dict | None = None) -> MagicMock:
    """Build a minimal async Redis mock.

    Args:
        stored: Pre-populated key→value store.

    Returns:
        A mock with async get/setex/expire/delete methods.
    """
    store: dict = stored or {}
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.setex = AsyncMock(
        side_effect=lambda key, ttl, value: store.update({key: value})
    )
    redis.expire = AsyncMock()
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    return redis


def _make_resolved_user(
    email: str = "user@contoso.com",
    aad_object_id: str = "aad-001",
    service_url: str = "https://smba.trafficmanager.net/",
) -> ResolvedTeamsUser:
    return ResolvedTeamsUser(
        aad_object_id=aad_object_id,
        upn=email,
        email=email,
        service_url=service_url,
    )


# ── ConversationReferenceStore ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_convref_store_set_and_get() -> None:
    """Store and retrieve a ConversationReference by email."""
    redis = _make_redis()
    store = ConversationReferenceStore(redis, ttl=100)

    ref = _make_conv_ref()
    await store.set("user@contoso.com", ref)

    retrieved = await store.get("user@contoso.com")
    assert retrieved is not None
    assert retrieved.channel_id == "msteams"
    assert retrieved.service_url == "https://smba.trafficmanager.net/"


@pytest.mark.asyncio
async def test_convref_store_get_miss_returns_none() -> None:
    """Get on a missing key returns None."""
    redis = _make_redis()
    store = ConversationReferenceStore(redis)

    result = await store.get("nobody@contoso.com")
    assert result is None


@pytest.mark.asyncio
async def test_convref_store_set_updates_service_url() -> None:
    """set() with a new service_url updates the ref before storing."""
    redis = _make_redis()
    store = ConversationReferenceStore(redis, ttl=100)

    ref = _make_conv_ref(service_url="https://old-url.com/")
    await store.set("user@contoso.com", ref, service_url="https://new-url.com/")

    retrieved = await store.get("user@contoso.com")
    assert retrieved is not None
    assert retrieved.service_url == "https://new-url.com/"


@pytest.mark.asyncio
async def test_convref_store_refresh_updates_ttl() -> None:
    """refresh() re-stores the ref (renewing TTL) if it exists."""
    redis = _make_redis()
    store = ConversationReferenceStore(redis, ttl=100)

    ref = _make_conv_ref()
    await store.set("user@contoso.com", ref)

    # refresh should call setex again (renewing the TTL)
    await store.refresh("user@contoso.com", service_url="https://refreshed-url.com/")

    redis.setex.assert_called()
    retrieved = await store.get("user@contoso.com")
    assert retrieved is not None
    assert retrieved.service_url == "https://refreshed-url.com/"


@pytest.mark.asyncio
async def test_convref_store_refresh_noop_on_miss() -> None:
    """refresh() does nothing if no entry exists."""
    redis = _make_redis()
    store = ConversationReferenceStore(redis)

    # Should not raise
    await store.refresh("nobody@contoso.com")
    redis.setex.assert_not_called()


# ── SentActivityStore ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sent_activity_store_set_and_get() -> None:
    """Store and retrieve sent-activity metadata."""
    redis = _make_redis()
    store = SentActivityStore(redis)

    ref = _make_conv_ref()
    await store.set("interaction-001", ref, activity_id="act-abc", recipient="user@contoso.com")

    result = await store.get("interaction-001")
    assert result is not None
    assert result["activity_id"] == "act-abc"
    assert result["recipient"] == "user@contoso.com"
    assert result["conversation_reference"] is not None


@pytest.mark.asyncio
async def test_sent_activity_store_get_miss() -> None:
    """Get on missing interaction_id returns None."""
    redis = _make_redis()
    store = SentActivityStore(redis)

    result = await store.get("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_sent_activity_store_delete() -> None:
    """delete() removes the entry."""
    redis = _make_redis()
    store = SentActivityStore(redis)

    ref = _make_conv_ref()
    await store.set("interaction-002", ref, "act-xyz", "user@contoso.com")

    await store.delete("interaction-002")
    redis.delete.assert_called_once()


# ── ProactiveMessenger ─────────────────────────────────────────────────────────

def _make_adapter_with_continue() -> MagicMock:
    """Build a mock adapter that records continue_conversation calls."""
    adapter = MagicMock()
    adapter.continue_conversation = AsyncMock()
    adapter.create_conversation = AsyncMock()
    return adapter


@pytest.mark.asyncio
async def test_warm_path_uses_continue_conversation() -> None:
    """Cached convref → continue_conversation; create_conversation not called."""
    ref = _make_conv_ref()
    redis = _make_redis()
    convref_store = ConversationReferenceStore(redis)
    await convref_store.set("user@contoso.com", ref)

    adapter = _make_adapter_with_continue()

    messenger = ProactiveMessenger(
        adapter=adapter,
        convref_store=convref_store,
        app_id="hitl-app-id",
        tenant_id="test-tenant",
    )

    build_called = []

    async def _build(turn_context):
        build_called.append(True)
        return "activity-id-123"

    with patch(
        "parrot.integrations.msteams.proactive.MicrosoftAppCredentials.trust_service_url"
    ):
        await messenger.send(_make_resolved_user(), _build)

    adapter.continue_conversation.assert_called_once()
    adapter.create_conversation.assert_not_called()


@pytest.mark.asyncio
async def test_cold_path_creates_and_caches_ref() -> None:
    """No convref → create_conversation; reference captured and stored."""
    redis = _make_redis()
    convref_store = ConversationReferenceStore(redis)

    adapter = MagicMock()
    adapter.continue_conversation = AsyncMock()

    # Simulate create_conversation calling the callback with a TurnContext.
    from botbuilder.schema import Activity

    async def _fake_create_conversation(app_id, callback, conv_params, service_url=None):
        # Build a minimal Activity to simulate the bootstrap call.
        activity = Activity(
            type="message",
            channel_id="msteams",
            service_url=service_url or "https://smba.trafficmanager.net/",
            from_property=ChannelAccount(id="hitl-bot-id"),
            recipient=ChannelAccount(id="user-aad"),
            conversation=ConversationAccount(id="new-conv-id", is_group=False, tenant_id="test-tenant"),
        )
        turn_context = MagicMock()
        turn_context.activity = activity
        await callback(turn_context)

    adapter.create_conversation = AsyncMock(side_effect=_fake_create_conversation)

    messenger = ProactiveMessenger(
        adapter=adapter,
        convref_store=convref_store,
        app_id="hitl-app-id",
        tenant_id="test-tenant",
    )

    async def _build(turn_context):
        return "activity-cold-001"

    with patch(
        "parrot.integrations.msteams.proactive.MicrosoftAppCredentials.trust_service_url"
    ):
        with patch(
            "parrot.integrations.msteams.proactive.TurnContext.get_conversation_reference",
            return_value=_make_conv_ref(),
        ):
            result = await messenger.send(_make_resolved_user(), _build)

    adapter.create_conversation.assert_called_once()
    adapter.continue_conversation.assert_not_called()
    assert result == "activity-cold-001"

    # Convref should now be cached.
    cached = await convref_store.get("user@contoso.com")
    assert cached is not None


@pytest.mark.asyncio
async def test_cold_create_failure_propagates() -> None:
    """If create_conversation raises, ProactiveDeliveryError is raised."""
    redis = _make_redis()
    convref_store = ConversationReferenceStore(redis)

    adapter = MagicMock()
    adapter.continue_conversation = AsyncMock()
    adapter.create_conversation = AsyncMock(side_effect=RuntimeError("BotNotInstalled"))

    messenger = ProactiveMessenger(
        adapter=adapter,
        convref_store=convref_store,
        app_id="hitl-app-id",
        tenant_id="test-tenant",
    )

    async def _build(turn_context):
        return "never-reached"

    with pytest.raises(ProactiveDeliveryError, match="BotNotInstalled"):
        with patch(
            "parrot.integrations.msteams.proactive.MicrosoftAppCredentials.trust_service_url"
        ):
            await messenger.send(_make_resolved_user(), _build)


@pytest.mark.asyncio
async def test_ttl_and_serviceurl_refreshed_on_contact() -> None:
    """capture_reference caches the ConversationReference with fresh service_url."""
    redis = _make_redis()
    convref_store = ConversationReferenceStore(redis)

    messenger = ProactiveMessenger(
        adapter=MagicMock(),
        convref_store=convref_store,
        app_id="hitl-app-id",
        tenant_id="test-tenant",
    )

    from botbuilder.schema import Activity

    activity = Activity(
        type="message",
        channel_id="msteams",
        service_url="https://new-service-url.com/",
        from_property=ChannelAccount(id="user-aad"),
        recipient=ChannelAccount(id="hitl-bot"),
        conversation=ConversationAccount(id="conv-1", is_group=False),
    )

    ref = _make_conv_ref()
    with patch(
        "parrot.integrations.msteams.proactive.TurnContext.get_conversation_reference",
        return_value=ref,
    ):
        await messenger.capture_reference(activity, "user@contoso.com")

    cached = await convref_store.get("user@contoso.com")
    assert cached is not None
    assert cached.service_url == "https://new-service-url.com/"
