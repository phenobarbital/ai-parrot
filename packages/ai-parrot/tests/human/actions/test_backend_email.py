"""Unit tests for EmailBackend.

TASK-1275 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.human.actions.backends import EmailBackend, EmailBackendError
from parrot.human.models import (
    EscalationActionType,
    EscalationTier,
    HumanInteraction,
)


@pytest.fixture
def backend():
    return EmailBackend(
        host="localhost",
        port=25,
        username="u",
        password="p",
        default_from="bot@parrot.test",
    )


@pytest.fixture
def interaction():
    return HumanInteraction(
        question="Can you approve this request?",
        context="User is requesting budget approval.",
        source_agent="budget-agent",
    )


@pytest.fixture
def tier():
    return EscalationTier(
        level=1,
        name="Email Tier",
        action_type=EscalationActionType.NOTIFY,
        action_metadata={
            "kind": "email",
            "to": ["ops@example.com", "manager@example.com"],
            "subject_template": "HITL: {question}",
        },
    )


class TestEmailBackend:
    async def test_send_returns_message_with_recipients(self, backend, interaction, tier):
        """Successful SMTP send returns a dict with 'message' containing recipients."""
        with patch("aiosmtplib.send", new=AsyncMock()) as mock_send:
            result = await backend.execute(interaction, tier)

        mock_send.assert_called_once()
        assert "message" in result
        assert "ops@example.com" in result["message"]
        assert "manager@example.com" in result["message"]
        assert result["status"] == "sent"
        assert result["to"] == ["ops@example.com", "manager@example.com"]

    async def test_empty_to_raises(self, backend, interaction):
        """Empty 'to' list raises EmailBackendError."""
        tier = EscalationTier(
            level=1,
            name="Email Tier",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={"kind": "email", "to": []},
        )
        with pytest.raises(EmailBackendError, match="empty"):
            await backend.execute(interaction, tier)

    async def test_missing_to_raises(self, backend, interaction):
        """Missing 'to' key raises EmailBackendError."""
        tier = EscalationTier(
            level=1,
            name="Email Tier",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={"kind": "email"},
        )
        with pytest.raises(EmailBackendError, match="empty"):
            await backend.execute(interaction, tier)

    async def test_invalid_email_address_raises(self, backend, interaction):
        """Invalid email address in 'to' raises EmailBackendError."""
        tier = EscalationTier(
            level=1,
            name="Email Tier",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={"kind": "email", "to": ["not-an-email"]},
        )
        with pytest.raises(EmailBackendError, match="invalid email"):
            await backend.execute(interaction, tier)

    async def test_smtp_failure_raises_typed_exception(self, backend, interaction, tier):
        """aiosmtplib exception is wrapped in EmailBackendError."""
        import aiosmtplib
        with patch(
            "aiosmtplib.send",
            new=AsyncMock(side_effect=aiosmtplib.SMTPException("Connection refused")),
        ):
            with pytest.raises(EmailBackendError, match="SMTP send failed"):
                await backend.execute(interaction, tier)

    async def test_message_contains_question(self, backend, interaction, tier):
        """The sent email body contains the interaction question."""
        captured_msgs = []

        async def capture_send(msg, **kwargs):
            captured_msgs.append(msg)

        with patch("aiosmtplib.send", new=capture_send):
            await backend.execute(interaction, tier)

        assert captured_msgs, "aiosmtplib.send was not called"
        msg_body = captured_msgs[0].get_payload(0).get_payload()
        assert "Can you approve this request?" in msg_body

    async def test_password_not_logged(self, backend, interaction, tier, caplog):
        """SMTP credentials are not exposed in logs."""
        import logging
        import aiosmtplib
        with patch(
            "aiosmtplib.send",
            new=AsyncMock(side_effect=aiosmtplib.SMTPException("auth error")),
        ):
            with caplog.at_level(logging.WARNING, logger="parrot.human.actions.backends.email"):
                try:
                    await backend.execute(interaction, tier)
                except EmailBackendError:
                    pass

        for record in caplog.records:
            assert "password" not in record.message.lower()
            assert "p" != record.message  # the password itself
