"""Unit tests for the async-notify-backed NotifyBackend.

The backend delivers escalation notifications through async-notify so the
delivery channel (email / ses / telegram / …) is a ``provider`` attribute.
async-notify is an optional dependency, so these tests install a lightweight
fake ``notify`` module that records every ``send`` call.
"""
from __future__ import annotations

import sys
import types

import pytest

from parrot.human.models import (
    EscalationActionType,
    EscalationTier,
    HumanInteraction,
)


# ── Fake async-notify ─────────────────────────────────────────────────────────

@pytest.fixture
def notify_log(monkeypatch):
    """Install a fake ``notify`` module and return the captured-send log."""
    log: list = []

    class _Conn:
        def __init__(self, provider, opts):
            self.provider = provider
            self.opts = opts

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send(self, **kwargs):
            log.append({"provider": self.provider, "opts": self.opts, **kwargs})
            return [types.SimpleNamespace(message_id="1")]

    def _notify(provider, **opts):
        return _Conn(provider, opts)

    notify_mod = types.ModuleType("notify")
    notify_mod.Notify = _notify
    models_mod = types.ModuleType("notify.models")

    class Actor:
        def __init__(self, name=None, account=None):
            self.name = name
            self.account = account or {}

    class Chat:
        def __init__(self, chat_id=None):
            self.chat_id = chat_id

    class Channel:
        def __init__(self, channel_id=None):
            self.channel_id = channel_id

    models_mod.Actor = Actor
    models_mod.Chat = Chat
    models_mod.Channel = Channel
    notify_mod.models = models_mod

    monkeypatch.setitem(sys.modules, "notify", notify_mod)
    monkeypatch.setitem(sys.modules, "notify.models", models_mod)
    return log


@pytest.fixture
def interaction():
    return HumanInteraction(
        question="Approve USD 5,000 expense for Alice?",
        context="Quarterly travel budget.",
        source_agent="expense-agent",
        originator="alice@corp.com",
    )


def _tier(action_metadata):
    return EscalationTier(
        level=3,
        name="Finance Email",
        action_type=EscalationActionType.NOTIFY,
        action_metadata=action_metadata,
        timeout=60,
    )


class TestNotifyBackend:
    async def test_email_provider_sends_to_recipients(self, notify_log, interaction):
        from parrot.human.actions.backends import NotifyBackend

        tier = _tier({"kind": "notify", "provider": "email",
                      "to": ["ops@x.com", "mgr@x.com"]})
        result = await NotifyBackend().execute(interaction, tier)

        assert len(notify_log) == 1
        sent = notify_log[0]
        assert sent["provider"] == "email"
        assert {a.account["address"] for a in sent["recipient"]} == {"ops@x.com", "mgr@x.com"}
        assert result["status"] == "sent"
        assert result["to"] == ["ops@x.com", "mgr@x.com"]
        assert "escalated:email" in result["message"]

    async def test_provider_switch_to_telegram_uses_chat(self, notify_log, interaction):
        from parrot.human.actions.backends import NotifyBackend

        tier = _tier({"kind": "notify", "provider": "telegram", "to": ["987654321"]})
        await NotifyBackend().execute(interaction, tier)

        sent = notify_log[0]
        assert sent["provider"] == "telegram"
        assert sent["recipient"][0].chat_id == "987654321"

    async def test_cc_and_cc_originator(self, notify_log, interaction):
        from parrot.human.actions.backends import NotifyBackend

        tier = _tier({
            "kind": "notify", "provider": "email",
            "to": ["a@x.com", "b@x.com"],
            "cc": ["audit@x.com"],
            "cc_originator": True,
        })
        result = await NotifyBackend().execute(interaction, tier)

        cc_addrs = {a.account["address"] for a in notify_log[0]["cc"]}
        assert cc_addrs == {"audit@x.com", "alice@corp.com"}
        assert "alice@corp.com" in result["cc"]

    async def test_cc_originator_not_duplicated_when_already_recipient(
        self, notify_log, interaction
    ):
        from parrot.human.actions.backends import NotifyBackend

        tier = _tier({
            "kind": "notify", "provider": "email",
            "to": ["alice@corp.com"], "cc_originator": True,
        })
        result = await NotifyBackend().execute(interaction, tier)
        assert result["cc"] == []

    async def test_provider_options_merged(self, notify_log, interaction):
        from parrot.human.actions.backends import NotifyBackend

        backend = NotifyBackend(provider_options={"hostname": "smtp.base", "port": 25})
        tier = _tier({
            "kind": "notify", "provider": "email", "to": ["a@x.com"],
            "provider_options": {"port": 587},
        })
        await NotifyBackend.execute(backend, interaction, tier)
        assert notify_log[0]["opts"] == {"hostname": "smtp.base", "port": 587}

    async def test_empty_to_raises(self, notify_log, interaction):
        from parrot.human.actions.backends import NotifyBackend, NotifyBackendError

        tier = _tier({"kind": "notify", "provider": "email", "to": []})
        with pytest.raises(NotifyBackendError, match="empty"):
            await NotifyBackend().execute(interaction, tier)

    async def test_invalid_email_raises(self, notify_log, interaction):
        from parrot.human.actions.backends import NotifyBackend, NotifyBackendError

        tier = _tier({"kind": "notify", "provider": "email", "to": ["not-an-email"]})
        with pytest.raises(NotifyBackendError, match="invalid address"):
            await NotifyBackend().execute(interaction, tier)

    async def test_send_failure_wrapped(self, monkeypatch, interaction):
        from parrot.human.actions.backends import NotifyBackend, NotifyBackendError

        class _Boom:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def send(self, **kwargs):
                raise RuntimeError("provider down")

        notify_mod = types.ModuleType("notify")
        notify_mod.Notify = lambda provider, **opts: _Boom()
        models_mod = types.ModuleType("notify.models")
        models_mod.Actor = type("Actor", (), {"__init__": lambda self, name=None, account=None: None})
        models_mod.Chat = type("Chat", (), {"__init__": lambda self, chat_id=None: None})
        models_mod.Channel = type("Channel", (), {"__init__": lambda self, channel_id=None: None})
        notify_mod.models = models_mod
        monkeypatch.setitem(sys.modules, "notify", notify_mod)
        monkeypatch.setitem(sys.modules, "notify.models", models_mod)

        tier = _tier({"kind": "notify", "provider": "email", "to": ["a@x.com"]})
        with pytest.raises(NotifyBackendError, match="failed"):
            await NotifyBackend().execute(interaction, tier)


class TestEmailBackendCompat:
    """The legacy EmailBackend now routes through async-notify."""

    async def test_email_backend_maps_smtp_to_provider_options(
        self, notify_log, interaction
    ):
        from parrot.human.actions.backends import EmailBackend

        backend = EmailBackend(host="smtp.x", port=587, username="u", password="p")
        tier = _tier({"kind": "email", "to": ["ops@x.com"]})
        await backend.execute(interaction, tier)

        sent = notify_log[0]
        assert sent["provider"] == "email"
        assert sent["opts"]["hostname"] == "smtp.x"
        assert sent["opts"]["port"] == 587
        assert sent["opts"]["username"] == "u"

    async def test_email_backend_message_contains_question(
        self, notify_log, interaction
    ):
        from parrot.human.actions.backends import EmailBackend

        tier = _tier({"kind": "email", "to": ["ops@x.com"]})
        await EmailBackend().execute(interaction, tier)
        assert "Approve USD 5,000 expense for Alice?" in notify_log[0]["message"]
