"""Tests for SlackIdentityResolver (TASK-3207, spec Q3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.devloop.models import Requester  # TASK-3200
from parrot.integrations.slack.devloop.actions import SlackIdentityResolver

_REQ = Requester(transport="slack", tenant_id="T1", user_id="U1")


@pytest.mark.asyncio
async def test_identity_resolver_email_fallback():
    """users.info email → Jira id; missing scope / API error → ("", "") so the service falls back to default_identities."""
    wrapper = MagicMock()
    wrapper._slack_api = AsyncMock(return_value={"user": {"profile": {"email": "a@b.c"}}})
    jira = MagicMock()
    jira.resolve_account_id = AsyncMock(return_value="acc-1")

    resolver = SlackIdentityResolver(wrapper, jira)
    identity = await resolver(_REQ)
    assert identity == ("acc-1", "acc-1")

    # Second call within the TTL must hit the cache, not call the API again.
    wrapper._slack_api.reset_mock()
    identity_again = await resolver(_REQ)
    assert identity_again == ("acc-1", "acc-1")
    wrapper._slack_api.assert_not_called()


@pytest.mark.asyncio
async def test_identity_resolver_no_email_falls_back_to_empty():
    wrapper = MagicMock()
    wrapper._slack_api = AsyncMock(return_value=None)
    resolver = SlackIdentityResolver(wrapper, jira_toolkit=None)

    assert await resolver(_REQ) == ("", "")


@pytest.mark.asyncio
async def test_identity_resolver_email_without_jira_toolkit_uses_email():
    wrapper = MagicMock()
    wrapper._slack_api = AsyncMock(return_value={"user": {"profile": {"email": "a@b.c"}}})
    resolver = SlackIdentityResolver(wrapper, jira_toolkit=None)

    assert await resolver(_REQ) == ("a@b.c", "a@b.c")


@pytest.mark.asyncio
async def test_identity_resolver_jira_failure_falls_back_to_email():
    wrapper = MagicMock()
    wrapper._slack_api = AsyncMock(return_value={"user": {"profile": {"email": "a@b.c"}}})
    jira = MagicMock()
    jira.resolve_account_id = AsyncMock(side_effect=RuntimeError("jira down"))

    resolver = SlackIdentityResolver(wrapper, jira)
    assert await resolver(_REQ) == ("a@b.c", "a@b.c")


@pytest.mark.asyncio
async def test_identity_resolver_ttl_expiry_calls_api_again():
    wrapper = MagicMock()
    wrapper._slack_api = AsyncMock(return_value={"user": {"profile": {"email": "a@b.c"}}})
    resolver = SlackIdentityResolver(wrapper, jira_toolkit=None, ttl_seconds=0.0)

    await resolver(_REQ)
    wrapper._slack_api.reset_mock()
    await resolver(_REQ)
    wrapper._slack_api.assert_awaited_once()
