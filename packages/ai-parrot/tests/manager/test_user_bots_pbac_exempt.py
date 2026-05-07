"""Regression test: user_bots path MUST NOT call enforce_agent_access — FEAT-153 TASK-1055.

The user_bots path (``BotManager.get_user_bot`` →
``_fetch_user_bot_model`` → ``_build_user_bot_instance``) is owner-scoped
by ``(user_id, chatbot_id)`` — that composite key IS the access control.
Agent-level PBAC policies therefore MUST NOT apply to user-owned bots.

This test locks that property in so a future refactor that accidentally
routes user_bots through ``get_bot()`` / ``get_instance()`` will fail here
before hitting production.
"""
from __future__ import annotations

import sys
import types
import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _ensure_navigator_session_stub() -> None:
    """Install a minimal navigator_session stub if not already present.

    get_user_bot() imports get_session lazily (try/except ImportError).
    We install a stub so the import succeeds and the session is provided
    via the request mock's ``.session`` attribute instead.
    """
    if "navigator_session" not in sys.modules:
        stub = types.ModuleType("navigator_session")
        stub.get_session = AsyncMock(return_value=None)
        sys.modules["navigator_session"] = stub


_ensure_navigator_session_stub()


@pytest.mark.asyncio
async def test_user_bot_path_unaffected_by_agent_policies():
    """user_bots are owner-scoped by (user_id, chatbot_id) and MUST NOT be
    subject to agent-level PBAC enforcement.

    Rationale: a user owning their bot is itself the access control — there
    is no need for an additional agent:resolve policy check.  If get_user_bot
    were ever refactored to call get_bot() or get_instance(), the PBAC
    enforcer would fire and potentially deny the owner their own bot.
    This test guards against that regression.

    Verification: the PBAC evaluator's check_access is configured to deny
    ALL access.  If get_user_bot consulted PBAC, it would raise
    AgentAccessDenied and the test would fail.  Instead it succeeds because
    the user_bots code path never calls enforce_agent_access.
    """
    from parrot.manager.manager import BotManager

    cid = str(uuid.uuid4())
    manager = BotManager()
    manager.app = MagicMock()

    # Wire a deny-all PBAC evaluator — if get_user_bot ever calls
    # enforce_agent_access, the check_access call will deny and
    # AgentAccessDenied will be raised.
    mock_evaluator = MagicMock()
    mock_evaluator.check_access.return_value = MagicMock(
        allowed=False,
        matched_policy="deny-all",
        reason="regression-test deny-all",
    )
    manager.registry._evaluator = mock_evaluator

    # Build a fake user-bot instance to be returned by _build_user_bot_instance.
    fake_bot_instance = MagicMock()
    fake_bot_instance.name = f"user_bot_{cid}"

    # Build a fake bot_model to be returned by _fetch_user_bot_model.
    fake_bot_model = MagicMock()

    # Build a fake request with a populated session so get_user_bot
    # doesn't bail out early on missing user_id.
    req = MagicMock()
    req.session = {"user_id": 42, "_user_bots": {}}

    with (
        patch.object(
            manager,
            "_fetch_user_bot_model",
            new=AsyncMock(return_value=fake_bot_model),
        ),
        patch.object(
            manager,
            "_build_user_bot_instance",
            new=AsyncMock(return_value=fake_bot_instance),
        ),
    ):
        bot = await manager.get_user_bot(req, cid)

    # The bot MUST be returned — the user-bot path is exempt from PBAC.
    assert bot is fake_bot_instance, (
        f"Expected the bot instance to be returned, got: {bot!r}"
    )

    # The PBAC evaluator must NEVER have been consulted for this path.
    mock_evaluator.check_access.assert_not_called(), (
        "REGRESSION: get_user_bot consulted the PBAC evaluator — "
        "user_bots must be exempt from agent-level PBAC enforcement."
    )
