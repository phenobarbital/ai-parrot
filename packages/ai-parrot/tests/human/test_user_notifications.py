"""Tests for originator (requesting-user) escalation notifications.

Covers ``HumanInteractionManager._notify_originator`` (both the
in-conversation HumanChannel path and the out-of-band async-notify path) and
the user-facing status messages emitted while a case is escalated tier to tier.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from parrot.human.manager import HumanInteractionManager
from parrot.human.models import (
    EscalationActionType,
    EscalationPolicy,
    EscalationTier,
    HumanInteraction,
    InteractionStatus,
)


# notify_log fixture is provided by tests/human/conftest.py

# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeChannel:
    """Minimal HumanChannel double recording send_notification calls."""

    channel_type = "web"

    def __init__(self):
        self.notifications: list = []
        self.fail = False

    async def send_interaction(self, interaction, recipient):
        return True

    async def send_notification(self, recipient, message):
        if self.fail:
            raise RuntimeError("channel down")
        self.notifications.append((recipient, message))

    async def cancel_interaction(self, interaction_id, recipient):
        return True

    async def register_response_handler(self, callback):
        pass

    async def register_cancel_handler(self, callback):
        pass


def _mock_redis():
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.publish = AsyncMock()
    redis.close = AsyncMock()
    return redis


# ── _notify_originator ────────────────────────────────────────────────────────

class TestNotifyOriginator:
    async def test_in_conversation_channel(self):
        channel = FakeChannel()
        mgr = HumanInteractionManager(channels={"web": channel})
        mgr._redis = _mock_redis()
        interaction = HumanInteraction(
            question="q", notify_channel="web", notify_recipient="sess-1"
        )

        await mgr._notify_originator(interaction, "su caso fue escalado")
        assert channel.notifications == [("sess-1", "su caso fue escalado")]

    async def test_falls_back_to_originator_recipient(self):
        channel = FakeChannel()
        mgr = HumanInteractionManager(channels={"web": channel})
        mgr._redis = _mock_redis()
        interaction = HumanInteraction(
            question="q", notify_channel="web", originator="user-9"
        )

        await mgr._notify_originator(interaction, "hi")
        assert channel.notifications == [("user-9", "hi")]

    async def test_async_notify_out_of_band(self, notify_log):
        mgr = HumanInteractionManager(channels={})
        mgr._redis = _mock_redis()
        interaction = HumanInteraction(
            question="q", notify_channel="email", notify_recipient="user@corp.com"
        )

        await mgr._notify_originator(interaction, "via email")
        assert notify_log and notify_log[0]["provider"] == "email"
        assert notify_log[0]["message"] == "via email"

    async def test_noop_without_notify_channel(self):
        channel = FakeChannel()
        mgr = HumanInteractionManager(channels={"web": channel})
        mgr._redis = _mock_redis()
        # No notify_channel set → nothing happens, no error.
        await mgr._notify_originator(HumanInteraction(question="q"), "x")
        assert channel.notifications == []

    async def test_channel_failure_swallowed(self):
        channel = FakeChannel()
        channel.fail = True
        mgr = HumanInteractionManager(channels={"web": channel})
        mgr._redis = _mock_redis()
        interaction = HumanInteraction(
            question="q", notify_channel="web", notify_recipient="s"
        )
        # Must not raise even though the channel raises.
        await mgr._notify_originator(interaction, "x")


# ── message builder ───────────────────────────────────────────────────────────

class TestUserEscalationMessage:
    def test_interact_message_names_tier(self):
        mgr = HumanInteractionManager()
        tier = EscalationTier(
            level=2, name="Gerente B",
            action_type=EscalationActionType.INTERACT, target_humans=["b@x.com"],
        )
        msg = mgr._build_user_escalation_message(HumanInteraction(question="q"), tier, "interact")
        assert "Gerente B" in msg

    def test_notify_message_default(self):
        mgr = HumanInteractionManager()
        tier = EscalationTier(
            level=3, name="Finanzas", action_type=EscalationActionType.NOTIFY,
            action_metadata={"kind": "notify", "to": ["a@x.com"]},
        )
        msg = mgr._build_user_escalation_message(HumanInteraction(question="q"), tier, "notify")
        assert "responsables" in msg

    def test_notify_message_override(self):
        mgr = HumanInteractionManager()
        tier = EscalationTier(
            level=3, name="Finanzas", action_type=EscalationActionType.NOTIFY,
            action_metadata={"kind": "notify", "to": ["a@x.com"],
                             "user_message": "Custom user text"},
        )
        msg = mgr._build_user_escalation_message(HumanInteraction(question="q"), tier, "notify")
        assert msg == "Custom user text"

    def test_exhausted_message(self):
        mgr = HumanInteractionManager()
        msg = mgr._build_user_escalation_message(HumanInteraction(question="q"), None, "exhausted")
        assert "pendiente" in msg


# ── escalation hooks ──────────────────────────────────────────────────────────

class TestEscalationNotifiesUser:
    async def test_interact_escalation_notifies_user(self):
        channel = FakeChannel()
        mgr = HumanInteractionManager(channels={"web": channel})
        mgr._redis = _mock_redis()
        mgr._update_status = AsyncMock()
        mgr._dispatch_to_channel = AsyncMock()
        mgr._handle_timeout = AsyncMock()  # avoid real sleeps

        policy = EscalationPolicy(policy_id="p", name="P", tiers=[
            EscalationTier(level=1, name="Mgr A", channel_type="web",
                           action_type=EscalationActionType.INTERACT,
                           target_humans=["a@x.com"], timeout=60),
            EscalationTier(level=2, name="Mgr B", channel_type="web",
                           action_type=EscalationActionType.INTERACT,
                           target_humans=["b@x.com"], timeout=60),
        ])
        interaction = HumanInteraction(
            question="q", policy=policy, policy_id="p", current_tier_level=1,
            notify_channel="web", notify_recipient="emp",
        )

        await mgr._escalate_to_next_tier(interaction, "web", cause="timeout")
        # Give the fire-and-forget notification task a chance to run.
        await asyncio.sleep(0)

        msgs = [m for (r, m) in channel.notifications if r == "emp"]
        assert msgs and "Mgr B" in msgs[0]

    async def test_notify_escalation_notifies_user(self, notify_log):
        channel = FakeChannel()
        mgr = HumanInteractionManager(channels={"web": channel})
        mgr._redis = _mock_redis()
        mgr._update_status = AsyncMock()
        mgr._persist_result = AsyncMock()
        mgr._trigger_rehydration = AsyncMock()

        policy = EscalationPolicy(policy_id="p", name="P", tiers=[
            EscalationTier(level=1, name="Mgr A", channel_type="web",
                           action_type=EscalationActionType.INTERACT,
                           target_humans=["a@x.com"], timeout=60),
            EscalationTier(level=2, name="Finance Email",
                           action_type=EscalationActionType.NOTIFY, timeout=60,
                           action_metadata={"kind": "notify", "provider": "email",
                                            "to": ["a@x.com"], "cc_originator": True}),
        ])
        interaction = HumanInteraction(
            question="q", policy=policy, policy_id="p", current_tier_level=1,
            originator="emp@corp.com", notify_channel="web", notify_recipient="emp",
        )

        await mgr._escalate_to_next_tier(interaction, "web", cause="timeout")
        await asyncio.sleep(0)

        msgs = [m for (r, m) in channel.notifications if r == "emp"]
        assert msgs and "responsables" in msgs[0]
        # The NOTIFY email actually went out to the manager, CC'ing the user.
        email_sends = [s for s in notify_log if s["provider"] == "email"]
        assert email_sends
