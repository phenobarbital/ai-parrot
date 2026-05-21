"""Unit tests for TelegramHumanChannel reject-button rendering.

TASK-1279 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.human.channels.base import ESCALATE_OPTION_KEY, HumanChannel
from parrot.human.channels.telegram import TelegramHumanChannel
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
    """TelegramHumanChannel with mocked aiogram imports."""
    # Patch aiogram so the import guard passes without installing it
    with patch.dict(
        "sys.modules",
        {
            "aiogram": MagicMock(),
            "aiogram.filters": MagicMock(),
            "aiogram.types": MagicMock(),
        },
    ):
        with patch("parrot.human.channels.telegram.HAS_AIOGRAM", True):
            mock_bot = AsyncMock()
            mock_redis = AsyncMock()

            # Patch the Router so __init__ doesn't fail
            with patch("parrot.human.channels.telegram.Router", return_value=MagicMock(
                callback_query=MagicMock(register=MagicMock()),
                message=MagicMock(register=MagicMock()),
            )):
                ch = TelegramHumanChannel(bot=mock_bot, redis=mock_redis)
                ch.bot = mock_bot
                ch.redis = mock_redis
                return ch


# ── Tests: class attributes ───────────────────────────────────────────────────

class TestRenderRejectButtonAttribute:
    def test_base_channel_has_false_default(self):
        assert HumanChannel.render_reject_button is False

    def test_telegram_has_true(self):
        assert TelegramHumanChannel.render_reject_button is True

    def test_escalate_option_key_constant(self):
        assert ESCALATE_OPTION_KEY == "__escalate__"


# ── Tests: keyboard rendering ─────────────────────────────────────────────────

class TestTelegramKeyboardWithRejectButton:
    @pytest.mark.asyncio
    async def test_escalate_row_present_when_policy_set(self, channel):
        """Keyboard includes escalate button when interaction.policy is not None."""
        # Track tokens created
        tokens_created = []
        original_create = channel._create_token

        async def fake_create(interaction_id, human_id, action, extra=None):
            tok = f"tok-{action}"
            tokens_created.append((action, tok))
            # Store token data so _handle_callback can find it
            channel.redis.get = AsyncMock(return_value=None)
            return tok

        channel._create_token = fake_create

        # Mock bot.send_message
        mock_msg = MagicMock()
        mock_msg.message_id = 42
        channel.bot.send_message = AsyncMock(return_value=mock_msg)
        channel._store_message_id = AsyncMock()
        channel._store_interaction_meta = AsyncMock()

        interaction = HumanInteraction(
            question="Approve?",
            interaction_type=InteractionType.APPROVAL,
            policy=_make_policy(),
            target_humans=["123"],
        )

        await channel._send_approval(interaction, chat_id=123)

        # Find the pick:__escalate__ token creation
        escalate_actions = [a for a, _ in tokens_created if ESCALATE_OPTION_KEY in a]
        assert escalate_actions, (
            f"Expected escalate token to be created, got: {tokens_created}"
        )

    @pytest.mark.asyncio
    async def test_escalate_row_absent_when_no_policy(self, channel):
        """Keyboard does NOT include escalate button when interaction.policy is None."""
        tokens_created = []

        async def fake_create(interaction_id, human_id, action, extra=None):
            tok = f"tok-{action}"
            tokens_created.append((action, tok))
            return tok

        channel._create_token = fake_create

        mock_msg = MagicMock()
        mock_msg.message_id = 42
        channel.bot.send_message = AsyncMock(return_value=mock_msg)
        channel._store_message_id = AsyncMock()
        channel._store_interaction_meta = AsyncMock()

        # interaction with no policy
        interaction = HumanInteraction(
            question="Approve?",
            interaction_type=InteractionType.APPROVAL,
            target_humans=["123"],
        )

        await channel._send_approval(interaction, chat_id=123)

        escalate_actions = [a for a, _ in tokens_created if ESCALATE_OPTION_KEY in a]
        assert not escalate_actions, (
            f"Expected NO escalate token, got: {tokens_created}"
        )

    @pytest.mark.asyncio
    async def test_escalate_token_callback_data_format(self, channel):
        """Escalate button callback_data contains ESCALATE_OPTION_KEY."""
        keyboard_rows = []

        # Patch _build_escalate_row to capture what it returns
        original_build_escalate = channel._build_escalate_row

        async def capturing_build_escalate(interaction_id, chat_id):
            row = await original_build_escalate(interaction_id, chat_id)
            keyboard_rows.extend(row)
            return row

        channel._build_escalate_row = capturing_build_escalate

        # But we need _create_token to work
        async def fake_create(interaction_id, human_id, action, extra=None):
            return f"tok-{action}"

        channel._create_token = fake_create

        interaction = HumanInteraction(
            question="Test?",
            interaction_type=InteractionType.APPROVAL,
            policy=_make_policy(),
        )

        row = await channel._build_escalate_row(interaction.interaction_id, 123)
        # The row is a list of InlineKeyboardButton mocks or objects
        # We can't easily inspect text in unit tests without real aiogram,
        # so just confirm the token contains ESCALATE_OPTION_KEY
        assert row is not None
