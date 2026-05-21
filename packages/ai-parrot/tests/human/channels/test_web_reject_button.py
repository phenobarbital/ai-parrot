"""Unit tests for WebHumanChannel reject-button rendering.

TASK-1279 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.human.channels.base import ESCALATE_OPTION_KEY
from parrot.human.channels.web import WebHumanChannel
from parrot.human.models import (
    EscalationActionType,
    EscalationPolicy,
    EscalationTier,
    HumanInteraction,
    InteractionType,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_policy():
    return EscalationPolicy(
        policy_id="p1",
        name="Test",
        tiers=[
            EscalationTier(
                level=1,
                name="T1",
                action_type=EscalationActionType.NOTIFY,
                action_metadata={"kind": "email", "to": ["a@b.com"]},
            )
        ],
    )


@pytest.fixture
def channel():
    socket_manager = MagicMock()
    socket_manager.notify_channel = AsyncMock(return_value=True)
    return WebHumanChannel(socket_manager=socket_manager)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestWebRenderRejectButton:
    def test_web_channel_has_true(self):
        assert WebHumanChannel.render_reject_button is True

    def test_payload_includes_escalate_option_when_policy_set(self, channel):
        """Web payload options list contains __escalate__ when policy is set."""
        interaction = HumanInteraction(
            question="Can you approve?",
            interaction_type=InteractionType.FREE_TEXT,
            policy=_make_policy(),
        )
        payload = channel._build_question_payload(interaction)
        keys = [o["key"] for o in (payload.get("options") or [])]
        assert ESCALATE_OPTION_KEY in keys, (
            f"Expected {ESCALATE_OPTION_KEY!r} in options, got: {keys}"
        )

    def test_payload_excludes_escalate_when_no_policy(self, channel):
        """Web payload options list does NOT contain __escalate__ without policy."""
        interaction = HumanInteraction(
            question="Can you approve?",
            interaction_type=InteractionType.FREE_TEXT,
        )
        payload = channel._build_question_payload(interaction)
        keys = [o["key"] for o in (payload.get("options") or [])]
        assert ESCALATE_OPTION_KEY not in keys

    def test_payload_escalate_option_label(self, channel):
        """Escalate option has the expected label."""
        interaction = HumanInteraction(
            question="Test?",
            policy=_make_policy(),
        )
        payload = channel._build_question_payload(interaction)
        escalate = next(
            (o for o in (payload.get("options") or []) if o["key"] == ESCALATE_OPTION_KEY),
            None,
        )
        assert escalate is not None
        assert escalate["label"] == "↑ Escalar"

    def test_payload_with_existing_options_appends_escalate(self, channel):
        """Escalate option is appended AFTER existing options."""
        from parrot.human.models import ChoiceOption

        interaction = HumanInteraction(
            question="Which?",
            interaction_type=InteractionType.SINGLE_CHOICE,
            options=[
                ChoiceOption(key="a", label="Option A"),
                ChoiceOption(key="b", label="Option B"),
            ],
            policy=_make_policy(),
        )
        payload = channel._build_question_payload(interaction)
        keys = [o["key"] for o in payload.get("options", [])]
        assert keys[-1] == ESCALATE_OPTION_KEY
        assert keys[0] == "a"
        assert keys[1] == "b"
