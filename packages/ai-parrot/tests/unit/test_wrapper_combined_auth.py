"""Integration-level unit tests for TelegramAgentWrapper combined auth
(FEAT-108 / TASK-763).

These tests exercise:
* `_init_post_auth_providers` registration logic
* `_is_combined_payload` detection
* `_build_next_auth_url` URL construction
* `_handle_combined_auth` orchestration (all branches)
* `BasicAuthStrategy.build_login_keyboard` ``next_auth_url`` wiring
* Backward compatibility when ``post_auth_actions`` is absent

Heavy aiogram plumbing (Bot, Router) is mocked; we focus on the
authentication state machine.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from parrot.integrations.telegram.auth import (
    BasicAuthStrategy,
    TelegramUserSession,
)
from parrot.integrations.telegram.models import (
    PostAuthAction,
    TelegramAgentConfig,
)
from parrot.integrations.telegram.post_auth import PostAuthRegistry


# ----------------------------------------------------------------------
# BasicAuthStrategy.build_login_keyboard URL wiring
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_keyboard_without_post_auth_is_unchanged():
    """No next_auth_url → URL keeps only the auth_url param (backward compat)."""
    strat = BasicAuthStrategy(
        auth_url="https://auth.example.com/api/login",
        login_page_url="https://auth.example.com/login",
    )
    config = TelegramAgentConfig(name="t", chatbot_id="t")
    kb = await strat.build_login_keyboard(config, state="x")
    url = kb.keyboard[0][0].web_app.url
    qs = parse_qs(urlparse(url).query)
    assert qs.get("auth_url") == ["https://auth.example.com/api/login"]
    assert "next_auth_url" not in qs


@pytest.mark.asyncio
async def test_login_keyboard_with_next_auth_url():
    """next_auth_url / next_auth_required flow through to the URL."""
    strat = BasicAuthStrategy(
        auth_url="https://auth.example.com/api/login",
        login_page_url="https://auth.example.com/login",
    )
    config = TelegramAgentConfig(name="t", chatbot_id="t")
    kb = await strat.build_login_keyboard(
        config,
        state="x",
        next_auth_url="https://auth.atlassian.com/authorize?client_id=xxx",
        next_auth_required=True,
    )
    url = kb.keyboard[0][0].web_app.url
    qs = parse_qs(urlparse(url).query)
    assert qs["next_auth_url"] == [
        "https://auth.atlassian.com/authorize?client_id=xxx"
    ]
    assert qs["next_auth_required"] == ["true"]


@pytest.mark.asyncio
async def test_login_keyboard_required_false():
    strat = BasicAuthStrategy(
        auth_url="https://a/login",
        login_page_url="https://a/page",
    )
    config = TelegramAgentConfig(name="t", chatbot_id="t")
    kb = await strat.build_login_keyboard(
        config, state="x",
        next_auth_url="https://foo/auth",
        next_auth_required=False,
    )
    qs = parse_qs(urlparse(kb.keyboard[0][0].web_app.url).query)
    assert qs["next_auth_required"] == ["false"]


# ----------------------------------------------------------------------
# Wrapper fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def wrapper_cls():
    """Return the wrapper class after neutralizing heavy __init__ side effects."""
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
    return TelegramAgentWrapper


def _blank_wrapper(cls, config: TelegramAgentConfig, app=None):
    """Build a wrapper *without* calling the full __init__ chain.

    We only need the FEAT-108 surface area; the rest of aiogram wiring
    is irrelevant here. ``app`` mimics the aiohttp application that would
    normally carry ``jira_oauth_manager`` / ``authdb`` / ``redis``.
    """
    w = cls.__new__(cls)
    w.config = config
    w.app = app
    w.agent = MagicMock()
    w.bot = MagicMock()
    w.logger = MagicMock()
    w._user_sessions = {}
    w._auth_strategy = MagicMock()
    w._post_auth_registry = PostAuthRegistry()
    return w


def _make_app(**services):
    """Return a dict-like aiohttp app stand-in populated with the given
    service keys. Using a plain dict keeps the test free of aiohttp setup
    while matching the ``app.get(key)`` interface the wrapper uses.
    """
    return dict(services)


@pytest.fixture
def basic_config():
    return TelegramAgentConfig(
        name="bot", chatbot_id="bot",
        auth_url="https://a/api/login",
        login_page_url="https://a/page",
    )


@pytest.fixture
def config_with_jira(basic_config):
    basic_config.post_auth_actions = [
        PostAuthAction(provider="jira", required=True)
    ]
    return basic_config


# ----------------------------------------------------------------------
# _init_post_auth_providers
# ----------------------------------------------------------------------


class TestInitPostAuthProviders:
    def test_no_actions_leaves_registry_empty(self, wrapper_cls, basic_config):
        w = _blank_wrapper(wrapper_cls, basic_config)
        w._init_post_auth_providers()
        assert len(w._post_auth_registry) == 0

    def test_jira_registered_when_services_available(
        self, wrapper_cls, config_with_jira
    ):
        app = _make_app(
            jira_oauth_manager=MagicMock(),
            authdb=MagicMock(),
            redis=MagicMock(),
        )
        w = _blank_wrapper(wrapper_cls, config_with_jira, app=app)
        w._init_post_auth_providers()
        assert "jira" in w._post_auth_registry

    def test_jira_registered_when_db_key_is_database(
        self, wrapper_cls, config_with_jira
    ):
        """Some deployments publish the pool as ``app['database']`` — the
        wrapper must accept it as a fallback for ``app['authdb']``."""
        app = _make_app(
            jira_oauth_manager=MagicMock(),
            database=MagicMock(),
            redis=MagicMock(),
        )
        w = _blank_wrapper(wrapper_cls, config_with_jira, app=app)
        w._init_post_auth_providers()
        assert "jira" in w._post_auth_registry

    def test_jira_skipped_when_app_missing(
        self, wrapper_cls, config_with_jira
    ):
        # No aiohttp app wired — combined flow disabled.
        w = _blank_wrapper(wrapper_cls, config_with_jira, app=None)
        w._init_post_auth_providers()
        assert "jira" not in w._post_auth_registry

    def test_jira_skipped_if_oauth_manager_missing(
        self, wrapper_cls, config_with_jira
    ):
        # App present but no jira_oauth_manager registered on it.
        app = _make_app(authdb=MagicMock(), redis=MagicMock())
        w = _blank_wrapper(wrapper_cls, config_with_jira, app=app)
        w._init_post_auth_providers()
        assert "jira" not in w._post_auth_registry

    def test_jira_skipped_if_db_pool_missing(
        self, wrapper_cls, config_with_jira
    ):
        app = _make_app(jira_oauth_manager=MagicMock(), redis=MagicMock())
        w = _blank_wrapper(wrapper_cls, config_with_jira, app=app)
        w._init_post_auth_providers()
        assert "jira" not in w._post_auth_registry

    def test_unknown_provider_logged_and_skipped(
        self, wrapper_cls, basic_config
    ):
        basic_config.post_auth_actions = [
            PostAuthAction(provider="mystery", required=False)
        ]
        app = _make_app(
            jira_oauth_manager=MagicMock(),
            authdb=MagicMock(),
            redis=MagicMock(),
        )
        w = _blank_wrapper(wrapper_cls, basic_config, app=app)
        w._init_post_auth_providers()
        assert len(w._post_auth_registry) == 0


# ----------------------------------------------------------------------
# _is_combined_payload
# ----------------------------------------------------------------------


class TestIsCombinedPayload:
    def test_jira_key_present(self, wrapper_cls, config_with_jira):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        assert w._is_combined_payload({"jira": {"code": "c", "state": "s"}})

    def test_no_post_auth_actions(self, wrapper_cls, basic_config):
        w = _blank_wrapper(wrapper_cls, basic_config)
        # Even if data contains "jira" key, with no post_auth_actions
        # configured we treat it as standard.
        assert not w._is_combined_payload({"jira": {"code": "c"}})

    def test_provider_value_must_be_dict(self, wrapper_cls, config_with_jira):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        # A non-dict value for the provider is ignored.
        assert not w._is_combined_payload({"jira": "not-a-dict"})

    def test_basic_auth_only_payload(self, wrapper_cls, config_with_jira):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        assert not w._is_combined_payload({
            "user_id": "u", "token": "t",
        })


# ----------------------------------------------------------------------
# _build_next_auth_url
# ----------------------------------------------------------------------


class TestBuildNextAuthUrl:
    @pytest.mark.asyncio
    async def test_returns_provider_url(self, wrapper_cls, config_with_jira):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.build_auth_url = AsyncMock(
            return_value="https://auth.atlassian.com/authorize?x=1"
        )
        w._post_auth_registry.register(fake_provider)
        session = TelegramUserSession(telegram_id=123)
        url, required = await w._build_next_auth_url(session)
        assert url == "https://auth.atlassian.com/authorize?x=1"
        assert required is True

    @pytest.mark.asyncio
    async def test_returns_none_when_no_provider_registered(
        self, wrapper_cls, config_with_jira
    ):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        session = TelegramUserSession(telegram_id=123)
        url, required = await w._build_next_auth_url(session)
        assert url is None

    @pytest.mark.asyncio
    async def test_exception_in_provider_returns_none(
        self, wrapper_cls, config_with_jira
    ):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.build_auth_url = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        w._post_auth_registry.register(fake_provider)
        session = TelegramUserSession(telegram_id=123)
        url, required = await w._build_next_auth_url(session)
        assert url is None
        # required flag still honored
        assert required is True


# ----------------------------------------------------------------------
# _handle_combined_auth (the main orchestration test)
# ----------------------------------------------------------------------


def _make_message():
    """A minimal aiogram Message stand-in with an async `.answer`."""
    msg = MagicMock()
    msg.answer = AsyncMock()
    return msg


class TestHandleCombinedAuthSuccess:
    @pytest.mark.asyncio
    async def test_basic_and_jira_both_succeed(
        self, wrapper_cls, config_with_jira
    ):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        w._auth_strategy.handle_callback = AsyncMock(return_value=True)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.handle_result = AsyncMock(return_value=True)
        w._post_auth_registry.register(fake_provider)

        msg = _make_message()
        session = TelegramUserSession(
            telegram_id=1, nav_user_id="u", nav_display_name="John"
        )
        session.set_authenticated("u", "tok", "John", "j@e")
        data = {
            "basic_auth": {"user_id": "u", "token": "t"},
            "jira": {"code": "c", "state": "s"},
        }
        await w._handle_combined_auth(msg, data, session)

        # BasicAuth callback got the basic_auth sub-dict.
        call = w._auth_strategy.handle_callback.await_args
        assert call.args[0] == {"user_id": "u", "token": "t"}
        fake_provider.handle_result.assert_awaited_once()
        # Final "full success" message mentions the connected provider.
        msg.answer.assert_called_once()
        text = msg.answer.call_args.args[0]
        assert "jira" in text
        assert session.authenticated  # not rolled back

    @pytest.mark.asyncio
    async def test_basic_auth_fallback_when_no_basic_auth_key(
        self, wrapper_cls, config_with_jira
    ):
        """If payload has no `basic_auth` sub-dict, top-level keys (excluding
        provider keys) are used as the BasicAuth payload."""
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        w._auth_strategy.handle_callback = AsyncMock(return_value=True)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.handle_result = AsyncMock(return_value=True)
        w._post_auth_registry.register(fake_provider)

        msg = _make_message()
        session = TelegramUserSession(telegram_id=1)
        session.set_authenticated("u", "tok", "John", "j@e")
        data = {
            "user_id": "u", "token": "t", "display_name": "John",
            "jira": {"code": "c", "state": "s"},
        }
        await w._handle_combined_auth(msg, data, session)

        basic_data = w._auth_strategy.handle_callback.await_args.args[0]
        # 'jira' key stripped, rest kept.
        assert "jira" not in basic_data
        assert basic_data["user_id"] == "u"


class TestHandleCombinedAuthFailures:
    @pytest.mark.asyncio
    async def test_basic_auth_fails(self, wrapper_cls, config_with_jira):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        w._auth_strategy.handle_callback = AsyncMock(return_value=False)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.handle_result = AsyncMock(return_value=True)
        w._post_auth_registry.register(fake_provider)

        msg = _make_message()
        session = TelegramUserSession(telegram_id=1)
        data = {
            "basic_auth": {"user_id": "u", "token": "t"},
            "jira": {"code": "c", "state": "s"},
        }
        await w._handle_combined_auth(msg, data, session)

        # jira provider NOT called when BasicAuth fails.
        fake_provider.handle_result.assert_not_called()
        text = msg.answer.call_args.args[0]
        assert "Login failed" in text

    @pytest.mark.asyncio
    async def test_jira_fails_required_rolls_back(
        self, wrapper_cls, config_with_jira
    ):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        w._auth_strategy.handle_callback = AsyncMock(return_value=True)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.handle_result = AsyncMock(return_value=False)
        w._post_auth_registry.register(fake_provider)

        msg = _make_message()
        session = TelegramUserSession(telegram_id=1)
        session.set_authenticated("u", "tok", "John", "j@e")
        assert session.authenticated
        data = {
            "basic_auth": {"user_id": "u", "token": "t"},
            "jira": {"code": "c", "state": "s"},
        }
        await w._handle_combined_auth(msg, data, session)

        assert not session.authenticated  # rollback
        text = msg.answer.call_args.args[0]
        assert "requires authorization" in text.lower()

    @pytest.mark.asyncio
    async def test_jira_fails_optional_partial_success(
        self, wrapper_cls, basic_config
    ):
        basic_config.post_auth_actions = [
            PostAuthAction(provider="jira", required=False)
        ]
        w = _blank_wrapper(wrapper_cls, basic_config)
        w._auth_strategy.handle_callback = AsyncMock(return_value=True)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.handle_result = AsyncMock(return_value=False)
        w._post_auth_registry.register(fake_provider)

        msg = _make_message()
        session = TelegramUserSession(telegram_id=1)
        session.set_authenticated("u", "tok", "John", "j@e")
        data = {
            "basic_auth": {"user_id": "u", "token": "t"},
            "jira": {"code": "c", "state": "s"},
        }
        await w._handle_combined_auth(msg, data, session)

        assert session.authenticated  # NOT rolled back
        text = msg.answer.call_args.args[0]
        # Partial-success branch mentions which provider failed.
        assert "Could not connect" in text or "⚠" in text

    @pytest.mark.asyncio
    async def test_provider_raises_treated_as_failure(
        self, wrapper_cls, config_with_jira
    ):
        w = _blank_wrapper(wrapper_cls, config_with_jira)
        w._auth_strategy.handle_callback = AsyncMock(return_value=True)
        fake_provider = MagicMock()
        fake_provider.provider_name = "jira"
        fake_provider.handle_result = AsyncMock(
            side_effect=RuntimeError("kaboom")
        )
        w._post_auth_registry.register(fake_provider)

        msg = _make_message()
        session = TelegramUserSession(telegram_id=1)
        session.set_authenticated("u", "tok", "John", "j@e")
        data = {
            "basic_auth": {"user_id": "u", "token": "t"},
            "jira": {"code": "c", "state": "s"},
        }
        await w._handle_combined_auth(msg, data, session)
        # required=True + failure → rollback
        assert not session.authenticated
