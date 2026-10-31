"""FEAT-776 M7 notifier tests."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEvent
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.integrations.telegram.connection_notifier import (
    TelegramConnectionNotifier,
    get_or_create_telegram_notifier,
)


class FakeBot:
    """Record Telegram sends and optionally fail them."""

    def __init__(self) -> None:
        self.messages: List[Dict[str, Any]] = []
        self.error: OptionalException = None

    async def send_message(self, **kwargs: Any) -> None:
        """Record one send or raise the configured error."""
        if self.error is not None:
            raise self.error
        self.messages.append(kwargs)


class OptionalException(Exception):
    """Test-only exception used to exercise defensive notifier paths."""


class FakeIdentityService:
    """Return a configured identity row while recording lookups."""

    def __init__(self, identity: Dict[str, Any] | None) -> None:
        self.identity = identity
        self.calls: List[Tuple[str, str]] = []
        self.error: OptionalException | None = None

    async def get_identity(self, nav_user_id: str, auth_provider: str) -> Dict[str, Any] | None:
        """Return the configured identity row."""
        self.calls.append((nav_user_id, auth_provider))
        if self.error is not None:
            raise self.error
        return self.identity


class FakeProvider:
    """Minimal provider metadata consumed by the notifier."""

    provider_id = "jira"
    display_name = "Jira Cloud"


@pytest.fixture(autouse=True)
def reset_registries() -> None:
    """Keep singleton registries isolated between tests."""
    ChannelNotifierRegistry._reset()
    OAuth2ProviderRegistry._reset()
    yield
    ChannelNotifierRegistry._reset()
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def fake_bot() -> FakeBot:
    """Return a Telegram bot test double."""
    return FakeBot()


@pytest.fixture
def fake_identity_service() -> FakeIdentityService:
    """Return an identity service mapped to Telegram user 456."""
    return FakeIdentityService({"provider_user_id": "456"})


def make_event(kind: str, *, occurred_at: float = 1.0, display_name: str = "Ada") -> ConnectionEvent:
    """Build a connection event for notifier tests."""
    return ConnectionEvent(
        kind=kind,
        user_id="42",
        provider="jira",
        display_name=display_name,
        channel="telegram",
        occurred_at=occurred_at,
    )


@pytest.mark.asyncio
async def test_notifier_targets_state_chat_then_identity_row(
    fake_bot: FakeBot,
    fake_identity_service: FakeIdentityService,
) -> None:
    notifier = TelegramConnectionNotifier(identity_service=fake_identity_service)
    fallback_bot = FakeBot()
    notifier.attach("state-bot", fake_bot)
    notifier.attach("fallback-bot", fallback_bot)
    notifier.record_connect_bot("42", "fallback-bot")

    await notifier.notify(make_event("connection.completed"), {"extra": {"chat_id": "123", "bot_id": "state-bot"}})

    assert fake_bot.messages == [{"chat_id": 123, "text": "jira connected as Ada.", "parse_mode": None}]
    assert fake_identity_service.calls == []

    await notifier.notify(make_event("connection.revoked", occurred_at=2.0), {})

    assert fallback_bot.messages == [{"chat_id": 456, "text": "jira disconnected.", "parse_mode": None}]
    assert fake_identity_service.calls == [("42", "telegram")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("connection.completed", "Jira Cloud connected as Ada."),
        ("connection.revoked", "Jira Cloud disconnected."),
        ("connection.refresh_failed", "Jira Cloud access expired — /connect jira to reconnect."),
    ],
)
async def test_notifier_texts_per_kind_plain_text(fake_bot: FakeBot, kind: str, expected: str) -> None:
    OAuth2ProviderRegistry().register(FakeProvider())  # type: ignore[arg-type]
    notifier = TelegramConnectionNotifier()
    notifier.attach("bot", fake_bot)

    await notifier.notify(make_event(kind), {"extra": {"chat_id": 123, "bot_id": "bot"}})

    assert fake_bot.messages == [{"chat_id": 123, "text": expected, "parse_mode": None}]


@pytest.mark.asyncio
async def test_notifier_never_raises(fake_bot: FakeBot, fake_identity_service: FakeIdentityService) -> None:
    fake_identity_service.error = OptionalException("identity lookup failed")
    notifier = TelegramConnectionNotifier(identity_service=fake_identity_service)
    await notifier.notify(make_event("connection.completed"), {})

    fake_bot.error = OptionalException("send failed")
    notifier.attach("bot", fake_bot)
    await notifier.notify(
        make_event("connection.completed", occurred_at=2.0),
        {"extra": {"chat_id": 123, "bot_id": "bot"}},
    )

    def broken_hook(telegram_id: int, event: ConnectionEvent) -> None:
        """Raise from a session hook."""
        raise OptionalException(f"hook failed for {telegram_id}:{event.provider}")

    fake_bot.error = None
    notifier.register_session_hook("jira", on_completed=broken_hook)
    await notifier.notify(
        make_event("connection.completed", occurred_at=3.0),
        {"extra": {"chat_id": 123, "bot_id": "bot"}},
    )

    assert len(fake_bot.messages) == 1


@pytest.mark.asyncio
async def test_jira_session_hook_stamps_and_clears(fake_bot: FakeBot) -> None:
    calls: List[Tuple[str, int, ConnectionEvent]] = []

    async def stamp(telegram_id: int, event: ConnectionEvent) -> None:
        calls.append(("stamp", telegram_id, event))

    def clear(telegram_id: int, event: ConnectionEvent) -> None:
        calls.append(("clear", telegram_id, event))

    notifier = TelegramConnectionNotifier()
    notifier.attach("bot", fake_bot)
    notifier.register_session_hook("jira", on_completed=stamp, on_revoked=clear)
    completed = make_event("connection.completed")
    revoked = make_event("connection.revoked", occurred_at=2.0)
    refresh_failed = make_event("connection.refresh_failed", occurred_at=3.0)

    for event in (completed, revoked, refresh_failed):
        await notifier.notify(event, {"extra": {"chat_id": "123", "bot_id": "bot"}})

    assert calls == [
        ("stamp", 123, completed),
        ("clear", 123, revoked),
        ("clear", 123, refresh_failed),
    ]


@pytest.mark.asyncio
async def test_duplicate_event_is_sent_once(fake_bot: FakeBot) -> None:
    notifier = TelegramConnectionNotifier()
    notifier.attach("bot", fake_bot)
    event = make_event("connection.completed")
    state = {"extra": {"chat_id": 123, "bot_id": "bot"}}

    await notifier.notify(event, state)
    await notifier.notify(event, state)

    assert len(fake_bot.messages) == 1


def test_get_or_create_notifier_is_idempotent(fake_identity_service: FakeIdentityService) -> None:
    app: Dict[str, Any] = {}

    first = get_or_create_telegram_notifier(app, identity_service=fake_identity_service)
    second = get_or_create_telegram_notifier(app)

    assert second is first
    assert app["telegram_connection_notifier"] is first
    assert ChannelNotifierRegistry().get("telegram") is first
