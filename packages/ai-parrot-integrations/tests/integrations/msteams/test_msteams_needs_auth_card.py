"""FEAT-775 M6: needs-auth connect cards (AC-8, AC-15, AC-16)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.integrations.msteams import wrapper as wrapper_module
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper


def _payload(provider: str = "jira", **overrides: object) -> AuthRequiredPayload:
    """Build a needs-auth payload with safe defaults."""
    values = {"provider": provider, "auth_url": "https://payload.invalid", "scopes": []}
    values.update(overrides)
    return AuthRequiredPayload(**values)


def _wrapper(*, guard: object = None) -> tuple[MSTeamsAgentWrapper, MagicMock, MagicMock]:
    """Build only the wrapper seams exercised by ``_offer_connections``."""
    wrapper = object.__new__(MSTeamsAgentWrapper)
    connector = MagicMock()
    connector.require_guard = AsyncMock(return_value=guard)
    connector.connect_guarded = AsyncMock()
    wrapper._connector = connector
    wrapper.logger = MagicMock()
    turn_context = MagicMock()
    turn_context.send_activity = AsyncMock()
    return wrapper, connector, turn_context


@pytest.mark.asyncio
async def test_offer_connections_dedupes_and_mints_own_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two OAuth requirements for one provider use one guarded connect call."""
    guard = object()
    wrapper, connector, turn_context = _wrapper(guard=guard)
    monkeypatch.setattr(
        wrapper_module.OAuth2ProviderRegistry,
        "get",
        lambda _registry, _provider: SimpleNamespace(display_name="Jira"),
    )

    await wrapper._offer_connections(
        turn_context,
        [_payload(scopes=["write"]), _payload(auth_url="https://must-not-be-used", scopes=["read"])],
    )

    connector.connect_guarded.assert_awaited_once_with(turn_context, guard, "jira", scopes=["read", "write"])
    turn_context.send_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_connect_scope_union_and_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scope union is sorted and passed to the connector for grant upgrade."""
    wrapper, connector, turn_context = _wrapper(guard=object())
    monkeypatch.setattr(
        wrapper_module.OAuth2ProviderRegistry,
        "get",
        lambda _registry, _provider: SimpleNamespace(display_name="Jira"),
    )

    await wrapper._offer_connections(
        turn_context,
        [_payload(scopes=["b", "a"]), _payload(scopes=["a", "c"])],
    )

    assert connector.connect_guarded.await_args.kwargs["scopes"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_offer_connections_device_code_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """A complete device challenge renders a card without starting OAuth."""
    wrapper, connector, turn_context = _wrapper(guard=object())
    card = {"type": "AdaptiveCard"}
    card_builder = MagicMock(return_value=card)
    send_card = AsyncMock()
    monkeypatch.setattr(wrapper_module, "device_code_card", card_builder)
    monkeypatch.setattr(wrapper_module, "send_adaptive_card", send_card)
    monkeypatch.setattr(
        wrapper_module.OAuth2ProviderRegistry,
        "get",
        lambda _registry, _provider: SimpleNamespace(display_name="Jira"),
    )

    await wrapper._offer_connections(
        turn_context,
        [_payload(auth_kind="device_code", user_code="ABCD", verification_uri="https://verify", expires_in=90)],
    )

    card_builder.assert_called_once_with("Jira", "ABCD", "https://verify", 90)
    send_card.assert_awaited_once_with(turn_context, card)
    connector.connect_guarded.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_code_challenges_not_mixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A code-only payload cannot contribute fields to a complete challenge."""
    wrapper, connector, turn_context = _wrapper(guard=object())
    send_card = AsyncMock()
    card_builder = MagicMock()
    monkeypatch.setattr(wrapper_module, "device_code_card", card_builder)
    monkeypatch.setattr(wrapper_module, "send_adaptive_card", send_card)
    monkeypatch.setattr(
        wrapper_module.OAuth2ProviderRegistry,
        "get",
        lambda _registry, _provider: SimpleNamespace(display_name="Jira"),
    )

    await wrapper._offer_connections(
        turn_context,
        [
            _payload(auth_kind="device_code", user_code="ONLY-CODE"),
            _payload(auth_kind="device_code", verification_uri="https://verify"),
        ],
    )

    card_builder.assert_not_called()
    send_card.assert_not_awaited()
    turn_context.send_activity.assert_awaited_once_with("Couldn't start Jira sign-in — please try again.")
    connector.connect_guarded.assert_not_awaited()


@pytest.mark.asyncio
async def test_conflicting_auth_kinds_safe_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conflicting auth kinds produce one safe reply and no card or service call."""
    wrapper, connector, turn_context = _wrapper(guard=object())
    monkeypatch.setattr(
        wrapper_module.OAuth2ProviderRegistry,
        "get",
        lambda _registry, _provider: SimpleNamespace(display_name="Jira"),
    )

    await wrapper._offer_connections(turn_context, [_payload(), _payload(auth_kind="device_code")])

    turn_context.send_activity.assert_awaited_once_with("Couldn't start Jira sign-in — please try again.")
    connector.connect_guarded.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_type", ["group", "channel", None])
async def test_automatic_cards_share_personal_guard(conversation_type: str | None) -> None:
    """The connector guard rejects non-personal turns before any offer branch."""
    wrapper, connector, turn_context = _wrapper(guard=None)
    turn_context.activity.conversation.conversation_type = conversation_type

    await wrapper._offer_connections(turn_context, [_payload(), _payload(auth_kind="device_code")])

    connector.require_guard.assert_awaited_once_with(turn_context)
    connector.connect_guarded.assert_not_awaited()


@pytest.mark.asyncio
async def test_automatic_cards_require_live_principal() -> None:
    """A failed live-principal guard emits no automatic connection action."""
    wrapper, connector, turn_context = _wrapper(guard=None)

    await wrapper._offer_connections(turn_context, [_payload(auth_kind="device_code", user_code="secret")])

    connector.require_guard.assert_awaited_once_with(turn_context)
    connector.connect_guarded.assert_not_awaited()
    turn_context.send_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_tool_needs_auth_card() -> None:
    """The response sender can offer a card only after the response has completed."""
    wrapper, _connector, turn_context = _wrapper(guard=object())
    wrapper._offer_connections = AsyncMock()
    events: list[str] = []
    wrapper.send_text = AsyncMock(side_effect=lambda _text, _turn: events.append("response"))
    result = SimpleNamespace(has_error=False, needs_form=False, raw_response=None, response_text="Done")

    with wrapper_module.collect_auth_requirements() as pending:
        pending.append(_payload())
        await wrapper.send_text(result.response_text, turn_context)
    await wrapper._offer_connections(turn_context, pending)

    assert events == ["response"]
    wrapper._offer_connections.assert_awaited_once_with(turn_context, pending)
