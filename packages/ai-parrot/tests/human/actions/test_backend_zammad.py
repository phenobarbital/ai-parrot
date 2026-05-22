"""Unit tests for ZammadBackend.

TASK-1275 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

import json

import pytest
from aiohttp import web

from parrot.human.actions.backends import ZammadBackend, ZammadBackendError
from parrot.human.models import EscalationActionType, EscalationTier, HumanInteraction


@pytest.fixture
def interaction():
    return HumanInteraction(
        question="Can you approve this data migration?",
        context="Production migration pending.",
        source_agent="ops-agent",
    )


@pytest.fixture
def tier():
    return EscalationTier(
        level=2,
        name="Zammad Tier",
        action_type=EscalationActionType.TICKET,
        action_metadata={
            "kind": "zammad",
            "queue": "OPS",
            "title_template": "HITL: {question}",
        },
    )


async def _make_zammad_server(aiohttp_server, response_body, status=200):
    """Helper to create a stub Zammad server."""
    async def handler(request):
        return web.Response(
            text=json.dumps(response_body),
            content_type="application/json",
            status=status,
        )

    app = web.Application()
    app.router.add_post("/api/v1/tickets", handler)
    server = await aiohttp_server(app)
    return server


class TestZammadBackend:
    async def test_create_ticket_returns_id_and_url(self, aiohttp_server, interaction, tier):
        """Successful ticket creation returns dict with ticket_id and url in message."""
        server = await _make_zammad_server(
            aiohttp_server,
            {"id": 42, "title": "HITL: test"},
        )
        backend = ZammadBackend(
            base_url=str(server.make_url("")),
            api_token="test-token",
        )
        result = await backend.execute(interaction, tier)

        assert "ticket_id" in result
        assert result["ticket_id"] == 42
        assert "url" in result
        assert "42" in result["url"]
        assert "message" in result
        assert "42" in result["message"]

    async def test_http_500_raises_typed_exception(self, aiohttp_server, interaction, tier):
        """HTTP 500 response raises ZammadBackendError."""
        server = await _make_zammad_server(
            aiohttp_server,
            {"error": "internal server error"},
            status=500,
        )
        backend = ZammadBackend(
            base_url=str(server.make_url("")),
            api_token="test-token",
        )
        with pytest.raises(ZammadBackendError, match="HTTP 500"):
            await backend.execute(interaction, tier)

    async def test_http_401_raises_typed_exception(self, aiohttp_server, interaction, tier):
        """HTTP 401 response raises ZammadBackendError."""
        server = await _make_zammad_server(
            aiohttp_server,
            {"error": "unauthorized"},
            status=401,
        )
        backend = ZammadBackend(
            base_url=str(server.make_url("")),
            api_token="wrong-token",
        )
        with pytest.raises(ZammadBackendError, match="HTTP 401"):
            await backend.execute(interaction, tier)

    async def test_uses_queue_from_metadata(self, aiohttp_server, interaction, tier):
        """The queue in action_metadata is used as the group."""
        captured_requests = []

        async def handler(request):
            captured_requests.append(await request.json())
            return web.Response(
                text=json.dumps({"id": 99, "title": "test"}),
                content_type="application/json",
                status=201,
            )

        app = web.Application()
        app.router.add_post("/api/v1/tickets", handler)
        server = await aiohttp_server(app)

        backend = ZammadBackend(
            base_url=str(server.make_url("")),
            api_token="test-token",
        )
        await backend.execute(interaction, tier)

        assert captured_requests[0]["group"] == "OPS"
