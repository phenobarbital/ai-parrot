"""Unit tests for WebhookBackend.

TASK-1275 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

import json

import pytest
from aiohttp import web

from parrot.human.actions.backends import WebhookBackend, WebhookBackendError
from parrot.human.models import EscalationActionType, EscalationTier, HumanInteraction


@pytest.fixture
def interaction():
    return HumanInteraction(
        question="Need to talk to someone now",
        source_agent="support-agent",
    )


@pytest.fixture
def tier_with_url(tmp_path):
    # URL will be replaced per-test
    return EscalationTier(
        level=3,
        name="LiveChat Tier",
        action_type=EscalationActionType.NOTIFY,
        action_metadata={
            "kind": "webhook",
            "url": "http://placeholder",
        },
    )


async def _make_webhook_server(aiohttp_server, response_body, status=200):
    async def handler(request):
        return web.Response(
            text=json.dumps(response_body),
            content_type="application/json",
            status=status,
        )

    app = web.Application()
    app.router.add_post("/escalate", handler)
    server = await aiohttp_server(app)
    return server


class TestWebhookBackend:
    async def test_post_returns_deep_link(self, aiohttp_server, interaction):
        """Successful POST returns dict with deep_link in message."""
        deep_link = "https://livechat.example.com/session/abc123"
        server = await _make_webhook_server(
            aiohttp_server,
            {"deep_link": deep_link},
        )
        tier = EscalationTier(
            level=3,
            name="LiveChat",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={
                "kind": "webhook",
                "url": str(server.make_url("/escalate")),
            },
        )
        backend = WebhookBackend()
        result = await backend.execute(interaction, tier)

        assert result["deep_link"] == deep_link
        assert deep_link in result["message"]
        assert "[escalated:live_chat]" in result["message"]

    async def test_payload_shape(self, aiohttp_server, interaction):
        """Backend POSTs the documented payload shape."""
        captured = []

        async def handler(request):
            captured.append(await request.json())
            return web.Response(
                text=json.dumps({"deep_link": "http://x.com/s/1"}),
                content_type="application/json",
                status=200,
            )

        app = web.Application()
        app.router.add_post("/hook", handler)
        server = await aiohttp_server(app)

        tier = EscalationTier(
            level=3,
            name="LiveChat",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={
                "kind": "webhook",
                "url": str(server.make_url("/hook")),
            },
        )
        backend = WebhookBackend()
        await backend.execute(interaction, tier)

        assert captured
        payload = captured[0]
        assert "interaction_id" in payload
        assert "question" in payload
        assert "severity" in payload
        assert "user_id" in payload
        assert payload["question"] == interaction.question
        assert payload["user_id"] == "support-agent"

    async def test_http_502_raises_typed_exception(self, aiohttp_server, interaction):
        """HTTP 502 raises WebhookBackendError."""
        server = await _make_webhook_server(
            aiohttp_server,
            {"error": "bad gateway"},
            status=502,
        )
        tier = EscalationTier(
            level=3,
            name="LiveChat",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={
                "kind": "webhook",
                "url": str(server.make_url("/escalate")),
            },
        )
        backend = WebhookBackend()
        with pytest.raises(WebhookBackendError, match="HTTP 502"):
            await backend.execute(interaction, tier)

    async def test_missing_deep_link_raises(self, aiohttp_server, interaction):
        """Response without 'deep_link' raises WebhookBackendError."""
        server = await _make_webhook_server(
            aiohttp_server,
            {"status": "ok"},  # no deep_link
        )
        tier = EscalationTier(
            level=3,
            name="LiveChat",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={
                "kind": "webhook",
                "url": str(server.make_url("/escalate")),
            },
        )
        backend = WebhookBackend()
        with pytest.raises(WebhookBackendError, match="deep_link"):
            await backend.execute(interaction, tier)

    async def test_no_url_raises(self, interaction):
        """Missing 'url' in action_metadata and no default raises WebhookBackendError."""
        tier = EscalationTier(
            level=3,
            name="LiveChat",
            action_type=EscalationActionType.NOTIFY,
            action_metadata={"kind": "webhook"},
        )
        backend = WebhookBackend()  # no default_url
        with pytest.raises(WebhookBackendError, match="no 'url'"):
            await backend.execute(interaction, tier)
