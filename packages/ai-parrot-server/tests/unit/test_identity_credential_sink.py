"""Unit tests for :class:`IdentityVaultCredentialSink` (FEAT-735 / TASK-4668).

The Identity Vault is the durable owner of a Jira grant; these tests pin the
behaviour that keeps it correct without a database: the Navigator user is
resolved from the Atlassian account id, the refresh re-seals the row with
``update_tokens`` (never ``save_linked_identity``, which would wipe
``auth_data``), and an account with no row is a logged no-op.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from parrot.services.identity_credential_sink import IdentityVaultCredentialSink


def _token(access_token: str = "new-access", account_id: str = "acct-1") -> SimpleNamespace:
    """A ``JiraTokenSet``-shaped object (the sink only reads attributes)."""
    return SimpleNamespace(
        access_token=access_token,
        refresh_token="rt_new",
        expires_at=time.time() + 3600,
        cloud_id="cloud-1",
        site_url="https://x.atlassian.net",
        account_id=account_id,
        display_name="Test User",
        email="test@example.com",
        scopes=["read:jira-work"],
    )


class _FakeStore:
    """Records the IdentityStore calls the sink makes."""

    def __init__(self, nav_user_id: Optional[str] = "42", identity: Any = "identity-row") -> None:
        self._nav_user_id = nav_user_id
        self._identity = identity
        self.update_tokens_calls: list[tuple] = []
        self.save_linked_identity_calls: list[tuple] = []
        self.lookups: list[tuple] = []

    async def find_user_by_provider_account(self, provider: str, provider_user_id: str):
        self.lookups.append((provider, provider_user_id))
        return self._nav_user_id

    async def get_for_provider_account(self, user_id: Any, provider: str, provider_user_id: str):
        return self._identity

    async def update_tokens(self, identity: Any, token: Any):
        self.update_tokens_calls.append((identity, token))
        return identity

    async def save_linked_identity(self, *args: Any, **kwargs: Any):
        self.save_linked_identity_calls.append((args, kwargs))
        return self._identity


@pytest.fixture
def sink_with_store(monkeypatch: pytest.MonkeyPatch):
    """Build a sink whose ``_store()`` returns a fake, parameterised store."""

    def _build(store: _FakeStore) -> IdentityVaultCredentialSink:
        sink = IdentityVaultCredentialSink(db_pool=object())
        monkeypatch.setattr(sink, "_store", lambda: store)
        return sink

    return _build


class TestPersistMinted:
    """TASK-4669 — link time, where the owner row is created."""

    @pytest.mark.asyncio
    async def test_resolves_nav_user_from_state(self, sink_with_store) -> None:
        """AC-4 — the state's Navigator id wins; no account lookup happens."""
        store = _FakeStore(nav_user_id="should-not-be-used")
        sink = sink_with_store(store)

        await sink.persist_minted("telegram", "tg-1", _token(), {"extra": {"nav_user_id": "42"}})

        assert store.lookups == []
        assert len(store.save_linked_identity_calls) == 1
        _args, kwargs = store.save_linked_identity_calls[0]
        assert kwargs["user_id"] == "42"
        assert kwargs["provider"] == "jira"
        assert kwargs["token"].access_token == "new-access"
        assert kwargs["userinfo"]["cloud_id"] == "cloud-1"

    @pytest.mark.asyncio
    async def test_falls_back_to_account_lookup_on_relink(self, sink_with_store) -> None:
        """AC-2 — a channel with no Navigator id can still re-link."""
        store = _FakeStore(nav_user_id="77")
        sink = sink_with_store(store)

        await sink.persist_minted("slack", "team:u1", _token(), {"extra": {}})

        assert store.lookups == [("jira", "acct-1")]
        _args, kwargs = store.save_linked_identity_calls[0]
        assert kwargs["user_id"] == "77"

    @pytest.mark.asyncio
    async def test_without_nav_user_is_a_logged_noop(self, sink_with_store) -> None:
        """AC-5 — a first-ever Slack/Teams link has no owner; never guess one."""
        store = _FakeStore(nav_user_id=None)
        sink = sink_with_store(store)

        await sink.persist_minted("slack", "team:u1", _token(), {"extra": {}})

        assert store.save_linked_identity_calls == []
        assert store.update_tokens_calls == []

    @pytest.mark.asyncio
    async def test_link_uses_save_linked_identity_not_update_tokens(self, sink_with_store) -> None:
        """Link time has userinfo, so the full sealed write is the right call."""
        store = _FakeStore()
        sink = sink_with_store(store)

        await sink.persist_minted("telegram", "tg-1", _token(), {"extra": {"nav_user_id": "42"}})

        assert store.update_tokens_calls == []
        assert len(store.save_linked_identity_calls) == 1

    @pytest.mark.asyncio
    async def test_missing_state_payload_is_tolerated(self, sink_with_store) -> None:
        """An empty payload degrades to the account lookup, never a KeyError."""
        store = _FakeStore(nav_user_id="77")
        sink = sink_with_store(store)

        await sink.persist_minted("slack", "team:u1", _token(), {})

        assert store.lookups == [("jira", "acct-1")]


class TestPersist:
    @pytest.mark.asyncio
    async def test_refresh_reseals_the_owner_row(self, sink_with_store) -> None:
        """AC-2 — the owner's credential becomes the refreshed access token."""
        store = _FakeStore()
        sink = sink_with_store(store)

        await sink.persist("tg", "u1", _token())

        assert store.lookups == [("jira", "acct-1")]
        assert len(store.update_tokens_calls) == 1
        _identity, token_response = store.update_tokens_calls[0]
        assert token_response.access_token == "new-access"
        assert token_response.provider_user_id == "acct-1"
        assert token_response.raw == {"cloud_id": "cloud-1", "site_url": "https://x.atlassian.net"}

    @pytest.mark.asyncio
    async def test_refresh_never_calls_save_linked_identity(self, sink_with_store) -> None:
        """AC-5 — ``save_linked_identity`` would reset auth_data from userinfo."""
        store = _FakeStore()
        sink = sink_with_store(store)

        await sink.persist("tg", "u1", _token())

        assert store.save_linked_identity_calls == []

    @pytest.mark.asyncio
    async def test_unknown_account_is_a_logged_noop(self, sink_with_store) -> None:
        """AC-6 — a user who linked before FEAT-729 has no row to update."""
        store = _FakeStore(nav_user_id=None)
        sink = sink_with_store(store)

        await sink.persist("tg", "u1", _token())

        assert store.update_tokens_calls == []
        assert store.save_linked_identity_calls == []

    @pytest.mark.asyncio
    async def test_missing_identity_row_is_a_noop(self, sink_with_store) -> None:
        """The user resolves but the provider row is gone: still no write."""
        store = _FakeStore(identity=None)
        sink = sink_with_store(store)

        await sink.persist("tg", "u1", _token())

        assert store.update_tokens_calls == []

    @pytest.mark.asyncio
    async def test_token_without_account_id_is_a_noop(self, sink_with_store) -> None:
        """Nothing to resolve on: never guess a user."""
        store = _FakeStore()
        sink = sink_with_store(store)

        await sink.persist("tg", "u1", _token(account_id=""))

        assert store.lookups == []
        assert store.update_tokens_calls == []
