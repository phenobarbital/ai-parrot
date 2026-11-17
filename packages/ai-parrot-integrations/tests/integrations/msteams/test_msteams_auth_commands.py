"""Unit tests for the MS Teams Navigator authentication commands."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.token_exchange import REASON_BACKEND_NOT_LOADED, REASON_USER_NOT_FOUND
from parrot.integrations.msteams.commands.auth_commands import register_auth_commands


class _Router:
    """Capture registrations using the MSTeamsCommandRouter.register shape."""

    def __init__(self) -> None:
        """Initialize the handler capture mapping."""
        self.handlers: dict[str, object] = {}

    def register(self, command: str, handler: object) -> None:
        """Capture one command handler.

        Args:
            command: Registered slash command.
            handler: Async handler registered for the command.
        """
        self.handlers[command] = handler


@pytest.fixture
def turn_context() -> MagicMock:
    """Return a minimal context that captures outgoing activities."""
    context = MagicMock()
    context.send_activity = AsyncMock()
    return context


def _session(
    *,
    authenticated: bool = False,
    reason: str | None = None,
    expires_at: datetime | None = None,
) -> SimpleNamespace:
    """Build a session-shaped strategy result without a real token.

    Args:
        authenticated: Whether the session is signed in.
        reason: Optional authentication failure reason.
        expires_at: Optional external credential expiration.

    Returns:
        A session object exposing the command handler's required fields.
    """
    metadata = {"auth_reason": reason} if reason else {}
    return SimpleNamespace(
        authenticated=authenticated,
        nav_user_id="35" if authenticated else None,
        nav_email="user@example.test" if authenticated else None,
        nav_session_token="never-reply-with-this-token",
        external_expires_at=expires_at,
        metadata=metadata,
    )


def _strategy(session: SimpleNamespace) -> MagicMock:
    """Build a strategy stub with independent authentication and store paths.

    Args:
        session: Session returned from authentication and read-only lookup.

    Returns:
        A strategy-shaped mock with its external calls observable.
    """
    strategy = MagicMock()
    strategy.ensure_authenticated = AsyncMock(return_value=session)
    strategy.send_signin_card = AsyncMock()
    strategy.sign_out = AsyncMock()
    strategy.store.get_or_create = AsyncMock(return_value=session)
    strategy.store.is_expired.return_value = False
    return strategy


def _text_from(context: MagicMock) -> str:
    """Return the text of the sole response sent to a test context.

    Args:
        context: Context whose outgoing activity is inspected.

    Returns:
        The user-visible activity text.
    """
    return context.send_activity.await_args.args[0].text


class TestRegistration:
    """Tests for registration of the three Teams commands."""

    def test_registers_three_commands(self) -> None:
        """/login, /logout and /whoami land on the router."""
        router = _Router()

        register_auth_commands(router, _strategy(_session()))

        assert set(router.handlers) == {"/login", "/logout", "/whoami"}


class TestLogin:
    """Tests for the /login handler."""

    @pytest.mark.asyncio
    async def test_success_confirms_navigator_identity(self, turn_context: MagicMock) -> None:
        """A usable token reports the resolved Navigator user id without the token."""
        router = _Router()
        strategy = _strategy(_session(authenticated=True))
        register_auth_commands(router, strategy)

        await router.handlers["/login"](turn_context)

        assert "35" in _text_from(turn_context)
        assert "never-reply-with-this-token" not in _text_from(turn_context)
        strategy.send_signin_card.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_not_found_wording_and_no_card(self, turn_context: MagicMock) -> None:
        """Not provisioned in Navigator is its own message, with no card."""
        router = _Router()
        strategy = _strategy(_session(reason=REASON_USER_NOT_FOUND))
        register_auth_commands(router, strategy)

        await router.handlers["/login"](turn_context)

        assert "not provisioned in Navigator" in _text_from(turn_context)
        assert "administrator" in _text_from(turn_context)
        strategy.send_signin_card.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_backend_not_loaded_uses_operator_wording(self, turn_context: MagicMock) -> None:
        """A missing TokenExchange backend tells the user about operator configuration."""
        router = _Router()
        strategy = _strategy(_session(reason=REASON_BACKEND_NOT_LOADED))
        register_auth_commands(router, strategy)

        await router.handlers["/login"](turn_context)

        assert "not configured" in _text_from(turn_context)
        assert "operator" in _text_from(turn_context)
        strategy.send_signin_card.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_needs_auth_sends_signin_card(self, turn_context: MagicMock) -> None:
        """No token is the normal branch that asks the strategy for a sign-in card."""
        router = _Router()
        strategy = _strategy(_session())
        register_auth_commands(router, strategy)

        await router.handlers["/login"](turn_context)

        strategy.send_signin_card.assert_awaited_once_with(turn_context)
        turn_context.send_activity.assert_not_awaited()


class TestLogout:
    """Tests for the /logout handler."""

    @pytest.mark.asyncio
    async def test_calls_sign_out_once_and_confirms(self, turn_context: MagicMock) -> None:
        """Logout delegates once and confirms the signed-out state."""
        router = _Router()
        strategy = _strategy(_session())
        register_auth_commands(router, strategy)

        await router.handlers["/logout"](turn_context)

        strategy.sign_out.assert_awaited_once_with(turn_context)
        assert "Signed out" in _text_from(turn_context)


class TestWhoAmI:
    """Tests for the read-only /whoami handler."""

    @pytest.mark.asyncio
    async def test_reports_identity_email_and_expiry(self, turn_context: MagicMock) -> None:
        """A signed-in session reports its identity fields without a new exchange."""
        expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
        router = _Router()
        strategy = _strategy(_session(authenticated=True, expires_at=expiry))
        register_auth_commands(router, strategy)

        await router.handlers["/whoami"](turn_context)

        reply = _text_from(turn_context)
        assert "35" in reply
        assert "user@example.test" in reply
        assert str(expiry) in reply
        strategy.ensure_authenticated.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_whoami_triggers_no_exchange(self, turn_context: MagicMock) -> None:
        """/whoami is a report, not an authentication attempt."""
        router = _Router()
        strategy = _strategy(_session())
        register_auth_commands(router, strategy)

        await router.handlers["/whoami"](turn_context)

        assert "not signed in" in _text_from(turn_context)
        strategy.ensure_authenticated.assert_not_awaited()
        strategy.store.get_or_create.assert_awaited_once_with(turn_context)
