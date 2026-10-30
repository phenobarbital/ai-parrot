"""Unit tests for delegated connection principal resolution (FEAT-773)."""
from __future__ import annotations

from typing import Optional

import pytest

from parrot.auth.principal import (
    Principal,
    WebPrincipalResolver,
    get_principal_resolver,
    resolve_principal,
    set_principal_resolver,
)


@pytest.fixture(autouse=True)
def _reset_resolver() -> None:
    """Restore the module-level resolver between tests."""
    set_principal_resolver(None)
    yield
    set_principal_resolver(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "slack", "msteams", "a2a", "cli"])
async def test_principal_resolver_default_web_only(channel: str) -> None:
    """The default resolver maps only web sessions to Navigator principals."""
    assert await WebPrincipalResolver().resolve(channel, "42") is None
    web = await WebPrincipalResolver().resolve("web", "1042")
    assert web == Principal(user_id="1042", channel="web", channel_user_id="1042")
    assert await WebPrincipalResolver().resolve("web", "") is None
    assert isinstance(get_principal_resolver(), WebPrincipalResolver)


@pytest.mark.asyncio
async def test_resolve_principal_fail_closed() -> None:
    """Registered resolvers returning no principal never trigger a web fallback."""

    class _Nope:
        async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
            return None

    set_principal_resolver(_Nope())
    assert await resolve_principal("web", "1042") is None
    assert await resolve_principal("", "") is None
