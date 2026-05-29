"""
Unit tests for TeamsHumanChannel (TASK-005 / FEAT-205).

Covers:
  - send_interaction returns False on resolution failure.
  - Inbound demux builds a correct HumanResponse (respondent from activity).
  - respondent always comes from activity.from_property, not payload.
  - cancel_interaction calls update_activity; idempotent on no-record.
  - ChannelRegistry registers "teams" at import.
  - _LAZY_EXPORTS entry resolves to TeamsHumanChannel.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from botbuilder.schema import Activity, ActivityTypes, ChannelAccount, ConversationAccount

from parrot.human.channels.base import ESCALATE_OPTION_KEY
from parrot.human.models import (
    ChoiceOption,
    HumanInteraction,
    HumanResponse,
    InteractionType,
)
from parrot.integrations.msteams.graph import GraphClient, ResolvedTeamsUser
from parrot.integrations.msteams.proactive import (
    ConversationReferenceStore,
    ProactiveDeliveryError,
    ProactiveMessenger,
    SentActivityStore,
)
from parrot.human.channels.teams import TeamsHumanChannel


# ── Config stub ───────────────────────────────────────────────────────────────

class _Config:
    app_id = "hitl-app-id"
    app_password = "hitl-secret"
    tenant_id = "test-tenant"
    graph_client_id = "graph-id"
    graph_client_secret = "graph-secret"
    graph_tenant_id = "test-tenant"
    redis_url = "redis://localhost/0"
    route = "/api/teams-hitl/messages"
    convref_ttl = 2_592_000


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_redis() -> MagicMock:
    store: dict = {}
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.setex = AsyncMock(side_effect=lambda key, ttl, value: store.update({key: value}))
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    return redis


def _make_graph_client(resolved: ResolvedTeamsUser | None = None) -> GraphClient:
    gc = MagicMock(spec=GraphClient)
    gc.get_user_by_email = AsyncMock(return_value=resolved)
    return gc


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.continue_conversation = AsyncMock()
    adapter.create_conversation = AsyncMock()
    adapter.process_activity = AsyncMock(return_value=None)
    return adapter


def _make_channel(
    resolved_user: ResolvedTeamsUser | None = None,
    redis: MagicMock | None = None,
) -> TeamsHumanChannel:
    if redis is None:
        redis = _make_redis()
    gc = _make_graph_client(resolved_user)
    adapter = _make_adapter()
    return TeamsHumanChannel(
        adapter=adapter,
        graph_client=gc,
        redis=redis,
        config=_Config(),
    )


def _make_resolved_user(email: str = "manager@contoso.com") -> ResolvedTeamsUser:
    return ResolvedTeamsUser(
        aad_object_id="aad-001",
        upn=email,
        email=email,
        service_url="https://smba.trafficmanager.net/",
    )


def _make_basic_interaction(
    itype: InteractionType = InteractionType.FREE_TEXT,
) -> HumanInteraction:
    kwargs: dict = {
        "interaction_id": "test-interaction-001",
        "question": "¿Confirmas?",
        "interaction_type": itype,
    }
    if itype in (InteractionType.SINGLE_CHOICE, InteractionType.MULTI_CHOICE, InteractionType.POLL):
        kwargs["options"] = [ChoiceOption(key="a", label="A"), ChoiceOption(key="b", label="B")]
    return HumanInteraction(**kwargs)


# ── send_interaction ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_interaction_false_on_resolve_fail() -> None:
    """Unresolved recipient → send_interaction returns False."""
    channel = _make_channel(resolved_user=None)
    interaction = _make_basic_interaction()
    result = await channel.send_interaction(interaction, "nobody@contoso.com")
    assert result is False


@pytest.mark.asyncio
async def test_send_interaction_false_on_delivery_fail() -> None:
    """ProactiveDeliveryError → send_interaction returns False (never raises)."""
    channel = _make_channel(resolved_user=_make_resolved_user())

    with patch.object(
        channel._messenger,
        "send",
        side_effect=ProactiveDeliveryError("BotNotInstalled"),
    ):
        result = await channel.send_interaction(
            _make_basic_interaction(), "manager@contoso.com"
        )
    assert result is False


@pytest.mark.asyncio
async def test_send_interaction_true_on_success() -> None:
    """Successful proactive send → True."""
    channel = _make_channel(resolved_user=_make_resolved_user())

    async def _fake_send(recipient, build_fn):
        turn_ctx = MagicMock()
        resp = MagicMock()
        resp.id = "activity-123"
        turn_ctx.send_activity = AsyncMock(return_value=resp)
        await build_fn(turn_ctx)
        return "activity-123"

    with patch.object(channel._messenger, "send", side_effect=_fake_send):
        result = await channel.send_interaction(
            _make_basic_interaction(), "manager@contoso.com"
        )
    assert result is True


# ── on_turn / inbound demux ───────────────────────────────────────────────────

def _make_turn_context(
    aad_object_id: str = "sender-aad-001",
    value: dict | None = None,
    activity_type: str = ActivityTypes.message,
) -> MagicMock:
    """Build a minimal TurnContext mock for on_turn tests."""
    activity = Activity(
        type=activity_type,
        channel_id="msteams",
        service_url="https://smba.trafficmanager.net/",
        from_property=ChannelAccount(
            id=aad_object_id,
            aad_object_id=aad_object_id,
        ),
        conversation=ConversationAccount(id="conv-001", is_group=False),
        value=value or {},
    )
    turn_ctx = MagicMock()
    turn_ctx.activity = activity
    turn_ctx.send_activity = AsyncMock()
    turn_ctx.update_activity = AsyncMock()
    return turn_ctx


@pytest.mark.asyncio
async def test_inbound_demux_builds_human_response() -> None:
    """activity.value.hitl=True → correct HumanResponse built and callback called."""
    channel = _make_channel()
    received: list[HumanResponse] = []

    async def _callback(response: HumanResponse) -> None:
        received.append(response)

    await channel.register_response_handler(_callback)

    value = {
        "hitl": True,
        "interaction_id": "test-interaction-001",
        "value": "approve",
    }
    turn_ctx = _make_turn_context(aad_object_id="sender-aad-001", value=value)

    with patch.object(
        channel._messenger, "capture_reference", new=AsyncMock()
    ):
        await channel.on_turn(turn_ctx)

    assert len(received) == 1
    resp = received[0]
    assert resp.interaction_id == "test-interaction-001"
    assert resp.respondent == "sender-aad-001"
    assert resp.value is True  # "approve" parsed to bool True


@pytest.mark.asyncio
async def test_respondent_from_activity_not_payload() -> None:
    """Respondent is always from activity.from_property.aad_object_id, not payload."""
    channel = _make_channel()
    received: list[HumanResponse] = []

    async def _callback(response: HumanResponse) -> None:
        received.append(response)

    await channel.register_response_handler(_callback)

    # Payload tries to inject a different respondent.
    value = {
        "hitl": True,
        "interaction_id": "test-002",
        "value": "reject",
        "forged_respondent": "attacker@evil.com",  # must be ignored
    }
    turn_ctx = _make_turn_context(aad_object_id="real-aad-id", value=value)

    with patch.object(
        channel._messenger, "capture_reference", new=AsyncMock()
    ):
        await channel.on_turn(turn_ctx)

    assert received[0].respondent == "real-aad-id"


@pytest.mark.asyncio
async def test_late_reply_after_expiry_acks_not_crashes() -> None:
    """Late reply after tombstone → sends in-thread ack, no callback invoked."""
    redis = _make_redis()
    channel = _make_channel(redis=redis)

    # Pre-populate tombstone.
    tombstone_key = "hitl:result:expired-interaction"
    redis.get = AsyncMock(
        side_effect=lambda key: (
            b"1" if key == tombstone_key else None
        )
    )

    received: list[HumanResponse] = []

    async def _callback(response: HumanResponse) -> None:
        received.append(response)

    await channel.register_response_handler(_callback)

    value = {
        "hitl": True,
        "interaction_id": "expired-interaction",
        "value": "approve",
    }
    turn_ctx = _make_turn_context(value=value)

    with patch.object(
        channel._messenger, "capture_reference", new=AsyncMock()
    ):
        await channel.on_turn(turn_ctx)

    # No response dispatched; in-thread ack sent.
    assert received == []
    turn_ctx.send_activity.assert_called_once()


@pytest.mark.asyncio
async def test_non_hitl_activity_ignored() -> None:
    """Activity without hitl=True is silently ignored."""
    channel = _make_channel()
    received: list[HumanResponse] = []

    async def _callback(response: HumanResponse) -> None:
        received.append(response)

    await channel.register_response_handler(_callback)

    value = {"some_other": "data"}
    turn_ctx = _make_turn_context(value=value)

    with patch.object(
        channel._messenger, "capture_reference", new=AsyncMock()
    ):
        await channel.on_turn(turn_ctx)

    assert received == []


# ── cancel_interaction ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_updates_activity_idempotent() -> None:
    """cancel_interaction returns False when no sent record exists (idempotent)."""
    channel = _make_channel()
    # No sent record in the store.
    result = await channel.cancel_interaction("nonexistent-id", "user@contoso.com")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_updates_activity_when_record_exists() -> None:
    """cancel_interaction calls update_activity when sent record exists."""
    redis = _make_redis()
    channel = _make_channel(redis=redis)

    from botbuilder.schema import ConversationReference, ConversationAccount, ChannelAccount as CA
    ref = ConversationReference(
        channel_id="msteams",
        service_url="https://smba.trafficmanager.net/",
        user=CA(id="user-aad"),
        bot=CA(id="bot-id"),
        conversation=ConversationAccount(id="conv-1", is_group=False),
    )
    await channel._sent_store.set("cancel-test-id", ref, "activity-to-cancel", "user@contoso.com")

    update_called = []

    async def _fake_send(recipient, build_fn):
        turn_ctx = MagicMock()
        turn_ctx.update_activity = AsyncMock()
        update_called.append(True)
        await build_fn(turn_ctx)
        return ""

    with patch.object(channel._messenger, "send", side_effect=_fake_send):
        result = await channel.cancel_interaction("cancel-test-id", "user@contoso.com")

    assert result is True
    assert update_called


# ── Registry ──────────────────────────────────────────────────────────────────

def test_registry_registers_teams() -> None:
    """ChannelRegistry should have a 'teams' entry after importing the channel."""
    from parrot.human.channels import ChannelRegistry
    # Import the teams module (should have registered already via module-level code)
    import parrot.human.channels.teams  # noqa: F401 — import for side effect

    # Check registry has 'teams'
    assert "teams" in ChannelRegistry._channels, (
        f"'teams' not in ChannelRegistry._channels; "
        f"registered: {list(ChannelRegistry._channels)!r}"
    )
    assert ChannelRegistry._channels["teams"] is TeamsHumanChannel


def test_lazy_export_resolves() -> None:
    """from parrot.human import TeamsHumanChannel resolves lazily."""
    import parrot.human as ph
    cls = ph.TeamsHumanChannel
    assert cls is TeamsHumanChannel
