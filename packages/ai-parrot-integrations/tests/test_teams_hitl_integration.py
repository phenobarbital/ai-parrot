"""
Integration tests for the Teams HITL channel (TASK-006 / FEAT-205).

Tests the end-to-end wiring: setup_teams_hitl, dispatch-loop over target_humans,
escalation routing, and late-reply acks.

All external dependencies (adapter, Graph, Redis) are mocked to avoid network calls.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from botbuilder.schema import (
    Activity,
    ActivityTypes,
    ChannelAccount,
    ConversationAccount,
)

from parrot.human.channels.teams import TeamsHitlConfig, TeamsHumanChannel
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
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeConfig:
    app_id = "hitl-app-id"
    app_password = "hitl-secret"
    tenant_id = "test-tenant"
    graph_client_id = "graph-id"
    graph_client_secret = "graph-secret"
    graph_tenant_id = "test-tenant"
    redis_url = "redis://localhost/0"
    route = "/api/teams-hitl/messages"
    convref_ttl = 2_592_000
    app_type = "MultiTenant"


def _make_redis() -> MagicMock:
    store: dict = {}
    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.setex = AsyncMock(side_effect=lambda key, ttl, value: store.update({key: value}))
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    return redis


def _make_resolved_user(email: str = "manager@contoso.com") -> ResolvedTeamsUser:
    return ResolvedTeamsUser(
        aad_object_id="aad-001",
        upn=email,
        email=email,
        service_url="https://smba.trafficmanager.net/",
    )


def _make_channel(
    resolved_user: ResolvedTeamsUser | None = None,
    redis: MagicMock | None = None,
) -> TeamsHumanChannel:
    if redis is None:
        redis = _make_redis()
    gc = MagicMock(spec=GraphClient)
    gc.get_user_by_email = AsyncMock(return_value=resolved_user)
    adapter = MagicMock()
    adapter.continue_conversation = AsyncMock()
    adapter.create_conversation = AsyncMock()
    return TeamsHumanChannel(
        adapter=adapter,
        graph_client=gc,
        redis=redis,
        config=_FakeConfig(),
    )


def _make_interaction(
    interaction_id: str = "itr-001",
    itype: InteractionType = InteractionType.APPROVAL,
    target_humans: list[str] | None = None,
) -> HumanInteraction:
    kwargs: dict = {
        "interaction_id": interaction_id,
        "question": "¿Aprobar?",
        "interaction_type": itype,
        "target_humans": target_humans or ["manager@contoso.com"],
    }
    return HumanInteraction(**kwargs)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_registers_teams_channel() -> None:
    """setup_teams_hitl registers the channel on the manager."""
    from parrot.human.channels.teams import setup_teams_hitl

    manager = MagicMock()
    manager.register_channel = MagicMock()

    # Patch the heavy dependencies so we don't need real services.
    # HitlCloudAdapter and GraphClient are imported lazily inside setup_teams_hitl,
    # so we patch them at their canonical module paths.
    fake_redis = MagicMock()
    fake_adapter = MagicMock()
    fake_gc = MagicMock()

    with (
        patch("parrot.integrations.msteams.hitl_adapter.HitlCloudAdapter", return_value=fake_adapter),
        patch("parrot.integrations.msteams.graph.GraphClient", return_value=fake_gc),
        patch("redis.asyncio.from_url", return_value=fake_redis),
    ):
        config = TeamsHitlConfig(
            app_id="app",
            app_password="pw",
            tenant_id="tenant",
            graph_client_id="gid",
            graph_client_secret="gs",
            graph_tenant_id="gtenant",
            redis_url="redis://localhost/0",
        )
        app = MagicMock()
        app.router = MagicMock()
        app.router.add_post = MagicMock()

        channel = await setup_teams_hitl(app, manager, config)

    manager.register_channel.assert_called_once_with("teams", channel)
    assert isinstance(channel, TeamsHumanChannel)


@pytest.mark.asyncio
async def test_dispatch_loop_over_target_humans() -> None:
    """Sending to multiple target_humans calls send_interaction once per email."""
    channel = _make_channel(resolved_user=_make_resolved_user())
    interaction = _make_interaction(
        target_humans=["a@contoso.com", "b@contoso.com"]
    )

    # Patch the graph client to return a resolved user for any email.
    channel._graph_client.get_user_by_email = AsyncMock(
        side_effect=lambda email: _make_resolved_user(email)
    )

    send_results: list[bool] = []
    send_call_count = [0]

    async def _fake_send(recipient, build_fn):
        send_call_count[0] += 1
        turn_ctx = MagicMock()
        resp = MagicMock()
        resp.id = "act-id"
        turn_ctx.send_activity = AsyncMock(return_value=resp)
        await build_fn(turn_ctx)
        return "act-id"

    with patch.object(channel._messenger, "send", side_effect=_fake_send):
        for human in interaction.target_humans:
            result = await channel.send_interaction(interaction, human)
            send_results.append(result)

    assert send_results == [True, True]
    assert send_call_count[0] == 2


@pytest.mark.asyncio
async def test_escalate_button_routes_to_response_callback() -> None:
    """Submitting ESCALATE_OPTION_KEY → response_callback gets value=ESCALATE_OPTION_KEY."""
    redis = _make_redis()
    channel = _make_channel(redis=redis)

    received: list[HumanResponse] = []

    async def _callback(resp: HumanResponse) -> None:
        received.append(resp)

    await channel.register_response_handler(_callback)

    # Build inbound activity simulating escalate button press.
    value = {
        "hitl": True,
        "interaction_id": "itr-escalate",
        "value": ESCALATE_OPTION_KEY,
    }
    activity = Activity(
        type=ActivityTypes.message,
        channel_id="msteams",
        service_url="https://smba.trafficmanager.net/",
        from_property=ChannelAccount(id="sender-aad", aad_object_id="sender-aad"),
        conversation=ConversationAccount(id="conv-1", is_group=False),
        value=value,
    )
    turn_ctx = MagicMock()
    turn_ctx.activity = activity
    turn_ctx.send_activity = AsyncMock()

    with patch.object(channel._messenger, "capture_reference", new=AsyncMock()):
        await channel.on_turn(turn_ctx)

    assert len(received) == 1
    assert received[0].value == ESCALATE_OPTION_KEY
    assert received[0].interaction_id == "itr-escalate"
    assert received[0].respondent == "sender-aad"


@pytest.mark.asyncio
async def test_late_reply_after_expiry_acks() -> None:
    """Late reply after tombstone → in-thread ack sent, callback NOT invoked."""
    redis = _make_redis()
    channel = _make_channel(redis=redis)

    # Pre-populate tombstone.
    redis.get = AsyncMock(
        side_effect=lambda k: b"1" if k == "hitl:result:late-id" else None
    )

    invoked: list[HumanResponse] = []

    async def _callback(resp: HumanResponse) -> None:
        invoked.append(resp)

    await channel.register_response_handler(_callback)

    activity = Activity(
        type=ActivityTypes.message,
        channel_id="msteams",
        service_url="https://smba.trafficmanager.net/",
        from_property=ChannelAccount(id="user-aad", aad_object_id="user-aad"),
        conversation=ConversationAccount(id="conv-1"),
        value={"hitl": True, "interaction_id": "late-id", "value": "approve"},
    )
    turn_ctx = MagicMock()
    turn_ctx.activity = activity
    turn_ctx.send_activity = AsyncMock()

    with patch.object(channel._messenger, "capture_reference", new=AsyncMock()):
        await channel.on_turn(turn_ctx)

    assert invoked == []
    turn_ctx.send_activity.assert_called_once()


@pytest.mark.asyncio
async def test_send_interaction_false_on_graph_failure() -> None:
    """If Graph resolution fails, send_interaction returns False without crashing."""
    channel = _make_channel(resolved_user=None)  # Graph returns None
    interaction = _make_interaction()
    result = await channel.send_interaction(interaction, "unknown@contoso.com")
    assert result is False


def test_teams_hitl_config_reads_from_env(monkeypatch) -> None:
    """TeamsHitlConfig defaults populate from environment variables."""
    monkeypatch.setenv("MSTEAMS_HITL_APP_ID", "env-app-id")
    monkeypatch.setenv("MSTEAMS_HITL_APP_PASSWORD", "env-pw")
    monkeypatch.setenv("MSTEAMS_TENANT_ID", "env-tenant")

    config = TeamsHitlConfig()
    assert config.app_id == "env-app-id"
    assert config.app_password == "env-pw"
    assert config.tenant_id == "env-tenant"
