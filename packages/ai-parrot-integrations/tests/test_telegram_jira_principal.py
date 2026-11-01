"""Integrations wiring for connection events and the principal resolver (FEAT-773; Telegram commands moved to FEAT-776)."""

from unittest.mock import MagicMock, patch

import pytest

from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher
from parrot.integrations.manager import (
    _build_principal_resolver,
    _connection_publisher,
)


@pytest.fixture(autouse=True)
def _reset_notifier_registry() -> None:
    """Keep the process-global notifier registry isolated between tests."""
    ChannelNotifierRegistry._reset()
    yield
    ChannelNotifierRegistry._reset()


def test_connection_publisher_is_shared_and_registers_channel_notifiers() -> None:
    """The app keeps one publisher; Telegram and Teams register here, Slack from its own wrapper."""
    app: dict[str, object] = {}

    first = _connection_publisher(app)
    second = _connection_publisher(app)

    assert first is second
    assert isinstance(first, ConnectionEventPublisher)
    assert {notifier.channel for notifier in ChannelNotifierRegistry().all()} == {"telegram", "msteams"}


@pytest.mark.asyncio
async def test_connection_publisher_audits_events_without_token_material() -> None:
    """AC-7: the production publisher carries an audit ledger and records every connection event."""
    import time

    from parrot.auth.oauth2.events import ConnectionEvent

    app: dict[str, object] = {}
    publisher = _connection_publisher(app)
    ledger = app["connection_audit_ledger"]
    assert publisher._audit is ledger

    await publisher.publish(
        ConnectionEvent(
            kind="connection.completed",
            user_id="1042",
            provider="jira",
            account_id="acct-1",
            channel="telegram",
            occurred_at=time.time(),
        )
    )

    entries = list(ledger._entries.values())
    assert len(entries) == 1
    assert (entries[0].user_id, entries[0].tool, entries[0].provider, entries[0].channel) == (
        "1042",
        "connections",
        "jira",
        "telegram",
    )


def test_build_principal_resolver_registers_authdb() -> None:
    """An auth database produces and registers the server resolver."""
    db_pool = object()
    resolver = MagicMock()
    with (
        patch(
            "parrot.services.identity_principal.IdentityPrincipalResolver",
            return_value=resolver,
        ) as resolver_cls,
        patch("parrot.integrations.manager.set_principal_resolver") as setter,
    ):
        result = _build_principal_resolver({"authdb": db_pool})

    resolver_cls.assert_called_once_with(db_pool)
    setter.assert_called_once_with(resolver)
    assert result is resolver
