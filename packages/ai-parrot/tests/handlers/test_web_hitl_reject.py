"""Tests for the reject-button (escalate) route in HITLResponseHandler.

TASK-1285 — FEAT-194 hitl-escalation-tier

Verifies that a POST with value="__escalate__" calls
manager.advance_chain(cause="reject") and returns 2xx, while normal
values continue through manager.receive_response unchanged.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.web_hitl import HITLResponseHandler, HITLResponseBody
from parrot.human import set_default_human_manager, get_default_human_manager
from parrot.human.channels.base import ESCALATE_OPTION_KEY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

INTERACTION_ID = "iid-1285"
RESPONDENT = "user:42"


@pytest.fixture(autouse=True)
def reset_default_manager():
    """Restore the global default manager between tests."""
    original = get_default_human_manager()
    yield
    set_default_human_manager(original)


@pytest.fixture
def mock_manager():
    """Mock HumanInteractionManager with advance_chain and receive_response."""
    mgr = AsyncMock()
    mgr.is_valid_respondent = AsyncMock(return_value=True)
    mgr.advance_chain = AsyncMock()
    mgr.receive_response = AsyncMock()
    mgr.get_result = AsyncMock(return_value=MagicMock())
    mgr._pending_futures = {INTERACTION_ID: MagicMock()}
    return mgr


def _make_request(body_dict: dict, user_id: str = RESPONDENT) -> MagicMock:
    """Build a minimal mock aiohttp request."""
    request = MagicMock()
    request.json = AsyncMock(return_value=body_dict)
    request.session = {"user_id": user_id}
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEscalateRoute:

    @pytest.mark.asyncio
    async def test_escalate_value_routes_to_advance_chain(self, mock_manager):
        """value=ESCALATE_OPTION_KEY calls advance_chain(cause='reject') and returns 200."""
        set_default_human_manager(mock_manager)
        request = _make_request(
            {"interaction_id": INTERACTION_ID, "value": ESCALATE_OPTION_KEY}
        )
        handler = HITLResponseHandler(request)
        response = await handler.post()

        assert response.status == 200
        raw = response.body
        if isinstance(raw, bytes):
            raw = raw.decode()
        elif hasattr(raw, "decode"):
            raw = raw.decode()
        else:
            raw = str(raw)
        data = json.loads(raw)
        assert data.get("status") == "escalated"
        mock_manager.advance_chain.assert_awaited_once_with(INTERACTION_ID, cause="reject")
        mock_manager.receive_response.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_normal_value_routes_to_receive_response(self, mock_manager):
        """Regular value skips advance_chain and calls receive_response."""
        set_default_human_manager(mock_manager)
        request = _make_request(
            {"interaction_id": INTERACTION_ID, "value": "approved"}
        )
        handler = HITLResponseHandler(request)
        response = await handler.post()

        assert response.status == 200
        mock_manager.receive_response.assert_awaited_once()
        mock_manager.advance_chain.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unauthorised_user_blocked_on_escalate(self, mock_manager):
        """Unauthorised respondent gets 403 even when sending the escalate value."""
        mock_manager.is_valid_respondent = AsyncMock(return_value=False)
        set_default_human_manager(mock_manager)
        request = _make_request(
            {"interaction_id": INTERACTION_ID, "value": ESCALATE_OPTION_KEY},
            user_id="intruder:99",
        )
        handler = HITLResponseHandler(request)
        response = await handler.post()

        assert response.status == 403
        mock_manager.advance_chain.assert_not_awaited()
        mock_manager.receive_response.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_interaction_returns_404(self, mock_manager):
        """Escalate for unknown/expired interaction returns 404 (same as normal responses)."""
        mock_manager._pending_futures = {}
        mock_manager.get_result = AsyncMock(return_value=None)
        set_default_human_manager(mock_manager)
        request = _make_request(
            {"interaction_id": "no-such-id", "value": ESCALATE_OPTION_KEY}
        )
        handler = HITLResponseHandler(request)
        response = await handler.post()

        assert response.status == 404
        mock_manager.advance_chain.assert_not_awaited()
