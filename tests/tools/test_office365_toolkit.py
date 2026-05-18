"""Unit tests for :class:`parrot_tools.o365.oauth_toolkit.Office365Toolkit`.

Validate the per-user credential resolution loop:
- Missing ``_permission_context`` → ``AuthorizationRequired``.
- Resolver returns ``None`` → ``AuthorizationRequired`` carries ``auth_url``.
- Resolver returns a token → toolkit caches it by fingerprint.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.o365_oauth import O365TokenSet
from parrot_tools.o365.oauth_toolkit import Office365Toolkit


class _PermCtx:
    def __init__(self, channel: str, user_id: str) -> None:
        self.channel = channel
        self.user_id = user_id


@pytest.fixture
def fake_resolver():
    resolver = MagicMock()
    resolver.resolve = AsyncMock(return_value=None)
    resolver.get_auth_url = AsyncMock(return_value="https://example.com/authorize?...")
    return resolver


@pytest.fixture
def toolkit(fake_resolver):
    return Office365Toolkit(credential_resolver=fake_resolver, tenant_id="common")


@pytest.mark.asyncio
async def test_pre_execute_no_permission_context_raises(toolkit):
    with pytest.raises(AuthorizationRequired) as info:
        await toolkit._pre_execute("o365_read_inbox")
    assert info.value.provider == "o365"


@pytest.mark.asyncio
async def test_pre_execute_no_user_id_raises(toolkit):
    ctx = _PermCtx(channel="web", user_id=None)
    with pytest.raises(AuthorizationRequired):
        await toolkit._pre_execute("o365_read_inbox", _permission_context=ctx)


@pytest.mark.asyncio
async def test_pre_execute_no_token_raises_with_auth_url(toolkit, fake_resolver):
    ctx = _PermCtx(channel="web", user_id="42")
    with pytest.raises(AuthorizationRequired) as info:
        await toolkit._pre_execute("o365_read_inbox", _permission_context=ctx)

    assert info.value.auth_url == "https://example.com/authorize?..."
    fake_resolver.resolve.assert_awaited_once_with("web", "42")


@pytest.mark.asyncio
async def test_pre_execute_caches_token_by_fingerprint(toolkit, fake_resolver):
    ctx = _PermCtx(channel="web", user_id="42")
    token_a = O365TokenSet(access_token="AAAA" * 8, refresh_token="r", display_name="A")
    fake_resolver.resolve = AsyncMock(return_value=token_a)

    await toolkit._pre_execute("o365_read_inbox", _permission_context=ctx)
    assert "web:42" in toolkit._token_cache
    assert toolkit._current_token is token_a

    # Same token → no re-cache (fingerprint matches).
    await toolkit._pre_execute("o365_read_inbox", _permission_context=ctx)
    assert len(toolkit._token_cache) == 1

    # New token with different fingerprint → re-cache.
    token_b = O365TokenSet(access_token="BBBB" * 8, refresh_token="r2")
    fake_resolver.resolve = AsyncMock(return_value=token_b)
    await toolkit._pre_execute("o365_read_inbox", _permission_context=ctx)
    assert toolkit._token_cache["web:42"][0] is token_b


@pytest.mark.asyncio
async def test_pre_execute_evicts_when_cache_full(fake_resolver):
    toolkit = Office365Toolkit(credential_resolver=fake_resolver, cache_size=2)
    fake_resolver.resolve = AsyncMock(
        side_effect=lambda c, u: O365TokenSet(
            access_token=f"AT-{u}" * 4, refresh_token="r",
        )
    )
    for uid in ("u1", "u2", "u3"):
        ctx = _PermCtx(channel="web", user_id=uid)
        await toolkit._pre_execute("o365_read_inbox", _permission_context=ctx)

    # Oldest (u1) evicted, last two remain.
    assert "web:u1" not in toolkit._token_cache
    assert "web:u2" in toolkit._token_cache
    assert "web:u3" in toolkit._token_cache


def test_toolkit_requires_resolver():
    with pytest.raises(ValueError):
        Office365Toolkit(credential_resolver=None)


def test_toolkit_generates_tools(fake_resolver):
    toolkit = Office365Toolkit(credential_resolver=fake_resolver)
    tools = toolkit.get_tools()
    names = {t.name for t in tools}
    expected = {
        "o365_read_inbox",
        "o365_search_messages",
        "o365_send_email",
        "o365_list_onedrive_files",
        "o365_list_sharepoint_sites",
        "o365_list_upcoming_events",
    }
    assert expected.issubset(names)
