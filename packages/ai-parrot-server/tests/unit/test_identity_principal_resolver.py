"""Tests for the server-side identity principal resolver."""

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from parrot.services.identity_principal import IdentityPrincipalResolver


class StubIdentityStore:
    """Small in-memory substitute for navigator-auth's ``IdentityStore``."""

    def __init__(self) -> None:
        """Initialize calls and known channel identities."""
        self.find_calls: list[tuple[str, str]] = []
        self.get_calls: list[tuple[Any, str]] = []
        self.fail_find = False
        self.fail_get = False

    async def find_user_by_provider_account(self, provider: str, provider_user_id: str) -> Optional[Any]:
        """Return the Navigator id for one linked Telegram account."""
        self.find_calls.append((provider, provider_user_id))
        if self.fail_find:
            raise RuntimeError("database unavailable")
        identities = {
            ("telegram", "88123"): 1042,
            ("telegram", "empty-nav-id"): "",
            ("msteams", "entra-oid"): 2042,
        }
        return identities.get((provider, provider_user_id))

    async def get_by_provider(self, user_id: Any, provider: str) -> Optional[Any]:
        """Return secondary identity data for known Navigator ids."""
        self.get_calls.append((user_id, provider))
        if self.fail_get:
            raise RuntimeError("secondary lookup unavailable")
        identities = {
            (1042, "telegram"): SimpleNamespace(email="JLara@Example.COM", provider_user_id="88123"),
            (2042, "msteams"): SimpleNamespace(email="ignored@example.com", provider_user_id="entra-oid"),
        }
        return identities.get((user_id, provider))


@pytest.mark.asyncio
async def test_identity_principal_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve linked Telegram, reject unknown users, and pass web ids through."""
    store = StubIdentityStore()
    resolver = IdentityPrincipalResolver(db_pool=object())
    monkeypatch.setattr(resolver, "_store", lambda: store)

    linked = await resolver.resolve("telegram", "88123")
    unknown = await resolver.resolve("telegram", "unknown")
    web = await resolver.resolve("web", "1042")

    assert linked is not None
    assert linked.user_id == "1042"
    assert linked.canonical_identity == "jlara@example.com"
    assert linked.channel == "telegram"
    assert linked.channel_user_id == "88123"
    assert unknown is None
    assert web is not None
    assert web.user_id == "1042"
    assert web.channel == "web"
    assert web.channel_user_id == "1042"
    assert store.find_calls == [("telegram", "88123"), ("telegram", "unknown")]


@pytest.mark.asyncio
async def test_msteams_uses_provider_user_id_as_canonical_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the Entra OID, rather than e-mail, as the Teams canonical identity."""
    store = StubIdentityStore()
    resolver = IdentityPrincipalResolver(db_pool=object())
    monkeypatch.setattr(resolver, "_store", lambda: store)

    principal = await resolver.resolve("msteams", "entra-oid")

    assert principal is not None
    assert principal.user_id == "2042"
    assert principal.canonical_identity == "entra-oid"


@pytest.mark.asyncio
async def test_secondary_identity_failure_keeps_resolved_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return the principal without a canonical identity when its row cannot be reread."""
    store = StubIdentityStore()
    store.fail_get = True
    resolver = IdentityPrincipalResolver(db_pool=object())
    monkeypatch.setattr(resolver, "_store", lambda: store)

    principal = await resolver.resolve("telegram", "88123")

    assert principal is not None
    assert principal.user_id == "1042"
    assert principal.canonical_identity is None


@pytest.mark.asyncio
async def test_database_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return ``None`` rather than leaking a provider lookup error."""
    store = StubIdentityStore()
    store.fail_find = True
    resolver = IdentityPrincipalResolver(db_pool=object())
    monkeypatch.setattr(resolver, "_store", lambda: store)

    assert await resolver.resolve("telegram", "88123") is None


@pytest.mark.asyncio
async def test_empty_navigator_user_id_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject an identity lookup that returns no usable Navigator id."""
    store = StubIdentityStore()
    resolver = IdentityPrincipalResolver(db_pool=object())
    monkeypatch.setattr(resolver, "_store", lambda: store)

    assert await resolver.resolve("telegram", "empty-nav-id") is None
    assert store.get_calls == []


@pytest.mark.asyncio
async def test_a2a_email_fails_closed_without_email_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not treat an a2a e-mail address as a provider account id."""
    store = StubIdentityStore()
    resolver = IdentityPrincipalResolver(db_pool=object())
    monkeypatch.setattr(resolver, "_store", lambda: store)

    assert await resolver.resolve("a2a", "jlara@example.com") is None
    assert store.find_calls == []
