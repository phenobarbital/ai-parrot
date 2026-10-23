"""Tests for the MS Teams authentication gate, post_login and context sites (FEAT-729)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from botbuilder.dialogs import DialogTurnStatus

from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

NAV_ID = "nav-42"
TEAMS_ID = "teams-user-123"
CONVERSATION_ID = "19:conv@thread"


def _config(**kwargs) -> MSTeamsAgentConfig:
    defaults = {
        "name": "test_bot",
        "chatbot_id": "test_bot_id",
        "client_id": "fake_id",
        "client_secret": "fake_secret",
    }
    defaults.update(kwargs)
    return MSTeamsAgentConfig(**defaults)


@pytest.fixture
def mock_app() -> MagicMock:
    app = MagicMock()
    app.router = MagicMock()
    app.get.return_value = None
    return app


@pytest.fixture
def agent() -> MagicMock:
    bot = MagicMock()
    bot.ask = AsyncMock()
    bot.post_login = AsyncMock()
    bot.clone_for_user = AsyncMock()
    bot.tool_manager = MagicMock()
    bot.tool_manager.list_tools.return_value = []
    return bot


@pytest.fixture
def turn_context() -> MagicMock:
    context = MagicMock()
    context.activity.text = "hello"
    context.activity.value = None
    context.activity.entities = None
    context.activity.conversation.id = CONVERSATION_ID
    context.activity.conversation.conversation_type = "personal"
    context.activity.from_property.id = TEAMS_ID
    context.activity.from_property.aad_object_id = "entra-oid"
    context.activity.from_property.name = "Teams User"
    context.activity.channel_data = SimpleNamespace(tenant=SimpleNamespace(id="tenant-1"))
    context.send_activity = AsyncMock()
    return context


def _orchestrator() -> AsyncMock:
    orchestrator = AsyncMock()
    orchestrator.process_message.return_value = SimpleNamespace(
        has_error=False,
        needs_form=False,
        raw_response=None,
        response_text="ok",
        error=None,
    )
    return orchestrator


def _build(agent, mock_app, **config_kwargs) -> MSTeamsAgentWrapper:
    wrapper = MSTeamsAgentWrapper(agent, _config(**config_kwargs), mock_app)
    wrapper.form_orchestrator = _orchestrator()
    dialog_context = MagicMock()
    dialog_context.continue_dialog = AsyncMock(return_value=SimpleNamespace(status=DialogTurnStatus.Empty))
    wrapper.dialogs = MagicMock()
    wrapper.dialogs.create_context = AsyncMock(return_value=dialog_context)
    wrapper.send_text = AsyncMock()
    wrapper.send_typing = AsyncMock()
    wrapper._remove_mentions = lambda _activity, text: text
    return wrapper


def _authenticate(wrapper: MSTeamsAgentWrapper, turn_context: MagicMock) -> None:
    """Make the (mocked) strategy return an authenticated session for the user."""

    async def ensure(ctx):
        session = await wrapper._session_store.get_or_create(ctx)
        if not session.authenticated:
            session.set_authenticated(NAV_ID, "session-token", email="user@example.com", display_name="Nav User")
        return session

    wrapper._auth.ensure_authenticated = AsyncMock(side_effect=ensure)
    wrapper._auth.send_signin_card = AsyncMock()


def _unauthenticated(wrapper: MSTeamsAgentWrapper) -> None:
    async def ensure(ctx):
        return await wrapper._session_store.get_or_create(ctx)

    wrapper._auth.ensure_authenticated = AsyncMock(side_effect=ensure)
    wrapper._auth.send_signin_card = AsyncMock()


class TestAuthGate:
    @pytest.mark.asyncio
    async def test_fails_closed_when_required(self, agent, mock_app, turn_context):
        """auth_required=True + unauthenticated: card sent, agent never invoked."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=True)
        _unauthenticated(wrapper)

        await wrapper.on_message_activity(turn_context)

        wrapper._auth.send_signin_card.assert_awaited_once_with(turn_context)
        wrapper.form_orchestrator.process_message.assert_not_awaited()
        agent.ask.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_proceeds_when_not_required(self, agent, mock_app, turn_context):
        """auth_required=False: behaviour identical to pre-feature (no card, turn proceeds)."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=False)
        _unauthenticated(wrapper)

        await wrapper.on_message_activity(turn_context)

        wrapper._auth.send_signin_card.assert_not_awaited()
        wrapper.form_orchestrator.process_message.assert_awaited_once()
        context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
        assert context["user_id"] == TEAMS_ID
        agent.post_login.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_gate_runs_after_is_authorized(self, agent, mock_app, turn_context):
        """An unauthorized conversation is refused before any auth work."""
        wrapper = _build(
            agent,
            mock_app,
            navigator_auth_url="https://nav.test/api/v1/login",
            auth_required=True,
            allowed_conversation_ids=["19:other@thread"],
        )
        _unauthenticated(wrapper)

        await wrapper.on_message_activity(turn_context)

        wrapper._auth.ensure_authenticated.assert_not_awaited()
        wrapper._auth.send_signin_card.assert_not_awaited()
        turn_context.send_activity.assert_awaited_once_with("You are not authorized to use this bot.")

    @pytest.mark.asyncio
    async def test_no_strategy_without_auth_url(self, agent, mock_app):
        """No navigator_auth_url: no strategy built and /login not registered."""
        wrapper = _build(agent, mock_app)

        assert wrapper._auth is None
        registered = getattr(wrapper._command_router, "_commands", None)
        if registered is not None:
            assert "/login" not in registered
        assert await wrapper._command_router.try_dispatch("/login", MagicMock()) is False

    @pytest.mark.asyncio
    async def test_login_registered_with_auth_url(self, agent, mock_app):
        """With navigator_auth_url the strategy exists and /login is dispatchable."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login")

        assert wrapper._auth is not None
        wrapper._auth.ensure_authenticated = AsyncMock(
            return_value=SimpleNamespace(authenticated=True, nav_user_id=NAV_ID, nav_email=None, metadata={})
        )
        context = MagicMock()
        context.send_activity = AsyncMock()
        assert await wrapper._command_router.try_dispatch("/login", context) is True


class TestPostLogin:
    @pytest.mark.asyncio
    async def test_runs_once_per_session(self, agent, mock_app, turn_context):
        """Two turns, one post_login call."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=True)
        _authenticate(wrapper, turn_context)

        await wrapper.on_message_activity(turn_context)
        await wrapper.on_message_activity(turn_context)

        assert agent.post_login.await_count == 1
        assert wrapper.form_orchestrator.process_message.await_count == 2

    @pytest.mark.asyncio
    async def test_user_context_shape(self, agent, mock_app, turn_context):
        """channel == "msteams", user_id == nav id, email populated."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=True)
        _authenticate(wrapper, turn_context)

        await wrapper.on_message_activity(turn_context)

        user_context = agent.post_login.await_args.args[0]
        assert user_context.channel == "msteams"
        assert user_context.user_id == NAV_ID
        assert user_context.email == "user@example.com"
        assert user_context.session_id == CONVERSATION_ID
        # No token value leaks into the snapshot.
        assert "session-token" not in repr(user_context)

    @pytest.mark.asyncio
    async def test_clone_for_user_when_not_singleton(self, agent, mock_app, turn_context):
        """singleton_agent=False clones the agent and runs post_login on the clone."""
        clone = MagicMock()
        clone.post_login = AsyncMock()
        agent.clone_for_user = AsyncMock(return_value=clone)
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login")
        wrapper.config.singleton_agent = False
        _authenticate(wrapper, turn_context)

        await wrapper.on_message_activity(turn_context)

        agent.clone_for_user.assert_awaited_once()
        clone.post_login.assert_awaited_once()
        agent.post_login.assert_not_awaited()


class TestContextSites:
    @pytest.mark.asyncio
    async def test_text_site_uses_nav_id(self, agent, mock_app, turn_context):
        """The main text path carries the Navigator id once authenticated."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=True)
        _authenticate(wrapper, turn_context)

        await wrapper.on_message_activity(turn_context)

        context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
        assert context["user_id"] == NAV_ID

    @pytest.mark.asyncio
    async def test_voice_site_uses_nav_id(self, agent, mock_app, turn_context):
        """The transcribed-voice path carries the Navigator id once authenticated."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=True)
        _authenticate(wrapper, turn_context)
        await wrapper._auth.ensure_authenticated(turn_context)

        await wrapper._process_transcribed_message(turn_context, "spoken", CONVERSATION_ID)

        context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
        assert context["user_id"] == NAV_ID
        assert context["source"] == "voice_note"

    @pytest.mark.asyncio
    async def test_a2ui_action_site_uses_nav_id(self, agent, mock_app, turn_context):
        """The A2UI native-input submit path carries the Navigator id."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=True)
        _authenticate(wrapper, turn_context)
        await wrapper._auth.ensure_authenticated(turn_context)
        turn_context.activity.value = {"a2ui_action": {"name": "go"}, "surfaceId": "s1"}

        await wrapper._handle_card_submission(turn_context, MagicMock())

        context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
        assert context["user_id"] == NAV_ID

    @pytest.mark.asyncio
    async def test_deeplink_resume_site_uses_nav_id(self, agent, mock_app, turn_context):
        """The deep-link resume closure carries the Navigator id."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login", auth_required=True)
        _authenticate(wrapper, turn_context)
        await wrapper._auth.ensure_authenticated(turn_context)
        turn_context.activity.value = {"a2ui_token": "tok"}

        async def resume(token, inject):
            result = await inject(session_id="sess", user_id="resumed-user", agent_id="a", query="q")
            return {"ok": True, "result": result, "reply": ""}

        helper = MagicMock()
        helper.resume = resume
        wrapper._get_deeplink_resume = MagicMock(return_value=helper)

        await wrapper._handle_card_submission(turn_context, MagicMock())

        context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
        assert context["user_id"] == NAV_ID

    @pytest.mark.asyncio
    async def test_sites_keep_previous_value_when_unauthenticated(self, agent, mock_app, turn_context):
        """Unauthenticated users keep today's Teams-scoped id on every path."""
        wrapper = _build(agent, mock_app, navigator_auth_url="https://nav.test/api/v1/login")
        _unauthenticated(wrapper)

        await wrapper._process_transcribed_message(turn_context, "spoken", CONVERSATION_ID)

        context = wrapper.form_orchestrator.process_message.await_args.kwargs["context"]
        assert context["user_id"] == TEAMS_ID
