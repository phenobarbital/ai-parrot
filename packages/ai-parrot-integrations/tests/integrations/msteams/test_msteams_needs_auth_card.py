"""FEAT-775 M6: needs-auth connect cards (AC-8, AC-15, AC-16)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from botbuilder.dialogs import DialogTurnStatus

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.pending import record_auth_requirement
from parrot.integrations.msteams.auth import MSTeamsUserSession
from parrot.integrations.msteams.commands.connect_commands import LOGIN_FIRST, PERSONAL_ONLY, TeamsConnector
from parrot.integrations.msteams.models import MSTeamsAgentConfig
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


def _real_connector(*, principal: object | None = object(), authenticated: bool = True) -> tuple[TeamsConnector, MagicMock]:
    """Build a real ``TeamsConnector`` whose principal source is faked, so the real guard logic runs."""
    session = MSTeamsUserSession(
        user_key="aad-oid",
        teams_user_id="29:teams-user",
        aad_object_id="aad-oid",
        tenant_id="tenant-1",
        nav_user_id="nav-42",
        authenticated=authenticated,
    )
    source = MagicMock()
    source.session_for_turn = AsyncMock(return_value=session)
    source.principal_for_turn = AsyncMock(return_value=principal)
    service = MagicMock()
    connector = TeamsConnector(
        principal_source=source,
        service_factory=lambda: service,
        provider_ids=lambda: ["jira"],
        bot_app_id="app",
        auth_enabled=True,
    )
    return connector, service


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_type", ["groupChat", "channel", None])
async def test_automatic_cards_share_personal_guard(conversation_type: str | None) -> None:
    """The real connector guard rejects non-personal turns: one notice, no service call, no card."""
    wrapper, _mock_connector, turn_context = _wrapper()
    connector, service = _real_connector()
    wrapper._connector = connector
    connector.connect_guarded = AsyncMock()
    turn_context.activity.conversation.conversation_type = conversation_type

    await wrapper._offer_connections(turn_context, [_payload(), _payload(auth_kind="device_code")])

    turn_context.send_activity.assert_awaited_once_with(PERSONAL_ONLY)
    connector.connect_guarded.assert_not_awaited()
    assert service.method_calls == []


@pytest.mark.asyncio
async def test_automatic_cards_require_live_principal() -> None:
    """A personal turn without a resolvable principal gets the login prompt and no connection action."""
    wrapper, _mock_connector, turn_context = _wrapper()
    connector, service = _real_connector(principal=None)
    connector.connect_guarded = AsyncMock()
    wrapper._connector = connector
    turn_context.activity.conversation.conversation_type = "personal"

    await wrapper._offer_connections(turn_context, [_payload(auth_kind="device_code", user_code="secret")])

    turn_context.send_activity.assert_awaited_once_with(LOGIN_FIRST)
    connector.connect_guarded.assert_not_awaited()
    assert service.method_calls == []


def _live_wrapper(needs_form: bool = False) -> tuple[MSTeamsAgentWrapper, list[str], MagicMock]:
    """Build a real wrapper whose orchestrator records a needs-auth requirement during the turn."""
    app = MagicMock()
    app.get.return_value = None
    agent = MagicMock()
    agent.tool_manager.list_tools.return_value = []
    config = MSTeamsAgentConfig(
        name="test_bot", chatbot_id="test_bot_id", client_id="fake_id", client_secret="fake_secret"
    )
    wrapper = MSTeamsAgentWrapper(agent, config, app)
    events: list[str] = []

    async def process_message(**_kwargs: object) -> SimpleNamespace:
        record_auth_requirement(_payload())
        return SimpleNamespace(
            has_error=False,
            needs_form=needs_form,
            raw_response=None,
            response_text="Done",
            context_message=None,
            form=None,
            error=None,
        )

    wrapper.form_orchestrator = MagicMock()
    wrapper.form_orchestrator.process_message = AsyncMock(side_effect=process_message)
    dialog_context = MagicMock()
    dialog_context.continue_dialog = AsyncMock(return_value=SimpleNamespace(status=DialogTurnStatus.Empty))
    wrapper.dialogs = MagicMock()
    wrapper.dialogs.create_context = AsyncMock(return_value=dialog_context)
    wrapper.send_typing = AsyncMock()
    wrapper._start_form_dialog = AsyncMock()
    wrapper._remove_mentions = lambda _activity, text: text
    wrapper._remember_conversation = AsyncMock()
    wrapper.send_text = AsyncMock(side_effect=lambda text, _turn: events.append(f"response:{text}"))
    connector, _service = _real_connector()
    connector.connect_guarded = AsyncMock(side_effect=lambda *_a, **_k: events.append("card"))
    wrapper._connector = connector
    turn_context = MagicMock()
    turn_context.activity.text = "hello"
    turn_context.activity.value = None
    turn_context.activity.entities = None
    turn_context.activity.conversation.id = "19:conv"
    turn_context.activity.conversation.conversation_type = "personal"
    turn_context.activity.from_property.id = "29:teams-user"
    turn_context.activity.from_property.aad_object_id = "aad-oid"
    turn_context.activity.from_property.name = "Teams User"
    turn_context.activity.channel_data = SimpleNamespace(tenant=SimpleNamespace(id="tenant-1"))
    turn_context.send_activity = AsyncMock()
    return wrapper, events, turn_context


@pytest.mark.asyncio
async def test_teams_tool_needs_auth_card() -> None:
    """A tool's needs-auth requirement recorded during a real turn yields the response first, then one card."""
    wrapper, events, turn_context = _live_wrapper()

    await wrapper.on_message_activity(turn_context)

    assert events == ["response:Done", "card"]
    wrapper._connector.connect_guarded.assert_awaited_once()
    assert wrapper._connector.connect_guarded.await_args.args[2] == "jira"


@pytest.mark.asyncio
async def test_needs_form_turn_skips_connection_offer() -> None:
    """A turn that starts a form dialog does not interleave a connection card."""
    wrapper, events, turn_context = _live_wrapper(needs_form=True)

    await wrapper.on_message_activity(turn_context)

    wrapper._start_form_dialog.assert_awaited_once()
    wrapper._connector.connect_guarded.assert_not_awaited()
    assert "card" not in events


@pytest.mark.asyncio
async def test_voice_and_resume_call_sites_pass_permission_context() -> None:
    """The real voice-transcript and deep-link-resume sites hand the PBAC context to the orchestrator."""
    wrapper, _events, turn_context = _live_wrapper()
    source = MagicMock()
    source.session_for_turn = AsyncMock(
        return_value=MSTeamsUserSession(
            user_key="aad-oid",
            teams_user_id="29:teams-user",
            aad_object_id="aad-oid",
            tenant_id="tenant-1",
            nav_user_id="nav-42",
            authenticated=True,
        )
    )
    wrapper._principal_source = source
    wrapper._auth = object()  # auth lane configured: PBAC context is built for authenticated sessions
    wrapper._effective_user_id = AsyncMock(return_value="nav-42")

    await wrapper._process_transcribed_message(turn_context, "spoken", "19:conv")
    voice_context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
    assert voice_context["permission_context"].channel == "msteams"
    assert voice_context["permission_context"].user_id == "nav-42"

    turn_context.activity.value = {"a2ui_token": "tok"}

    async def resume(_token: str, inject: object) -> dict:
        result = await inject(session_id="sess", user_id="resumed-user", agent_id="a", query="q")
        return {"ok": True, "result": result, "reply": ""}

    helper = MagicMock()
    helper.resume = resume
    wrapper._get_deeplink_resume = MagicMock(return_value=helper)
    wrapper.form_orchestrator.process_message.reset_mock()
    await wrapper._handle_card_submission(turn_context, MagicMock())
    resume_context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
    assert resume_context["permission_context"].channel == "msteams"
