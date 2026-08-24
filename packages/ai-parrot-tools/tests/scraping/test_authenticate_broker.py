"""Tests for broker-backed Authenticate — no credentials in plan JSON
(Module 4, Goal G3).

FEAT-453 TASK-2389.
"""

from typing import Any, Optional, Tuple
from unittest.mock import AsyncMock

import pytest
from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import CredentialResolver
from parrot_tools.scraping.models import Authenticate, lint_literal_credentials
from parrot_tools.scraping.session_actions import exec_authenticate


class _StaticSecret:
    """Minimal credential material — mirrors StaticCredentials shape."""

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password


class _StaticResolver(CredentialResolver):
    """Always resolves to the same secret — mirrors StaticCredentialResolver."""

    def __init__(self, username: str, password: str) -> None:
        self._secret = _StaticSecret(username, password)

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        return self._secret

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        raise NotImplementedError("static credentials do not require authorization")


class _MissingResolver(CredentialResolver):
    """Always misses — simulates a user who has not authorized yet."""

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        return None

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return "https://example.test/authorize"


class _BrokerWrapper:
    """Adapts a CredentialBroker into the session_actions CredentialResolverFn
    shape: ``Callable[[Authenticate], Awaitable[Optional[Tuple[str, str]]]]``.
    """

    def __init__(self, broker: CredentialBroker, provider: str) -> None:
        self.broker = broker
        self.provider = provider

    def as_resolver(self):
        async def _resolve(action: Authenticate) -> Optional[Tuple[Optional[str], Optional[str]]]:
            from parrot.auth.credentials import NeedsAuth

            result = await self.broker.resolve(self.provider, "web-automation", "operator@example.test")
            if isinstance(result, NeedsAuth):
                return None
            secret = result.secret
            return secret.username, secret.password

        return _resolve


@pytest.fixture
def mock_driver():
    driver = AsyncMock()
    driver.fill = AsyncMock(return_value=None)
    driver.click = AsyncMock(return_value=None)
    driver.wait_for_load_state = AsyncMock(return_value=None)
    return driver


@pytest.fixture
def audit_ledger():
    return AsyncMock()


@pytest.fixture
def fake_broker(audit_ledger):
    broker = CredentialBroker(audit_ledger=audit_ledger)
    broker.register("hooba", _StaticResolver("broker-user", "broker-pass"), auth_kind="static_key")
    wrapper = _BrokerWrapper(broker, "hooba")
    wrapper.expected_user = "broker-user"
    wrapper.expected_password = "broker-pass"
    wrapper.audit_ledger = audit_ledger
    return wrapper


@pytest.fixture
def missing_broker():
    broker = CredentialBroker()
    broker.register("hooba", _MissingResolver(), auth_kind="static_key")
    return _BrokerWrapper(broker, "hooba")


class TestBrokerAuth:
    async def test_prefers_broker_over_literals(self, mock_driver, fake_broker):
        action = Authenticate(credential_provider="hooba", username="LITERAL", password="LITERAL")
        result = await exec_authenticate(
            mock_driver,
            action,
            dispatch_step_fn=None,
            credential_resolver=fake_broker.as_resolver(),
        )
        assert result is True
        mock_driver.fill.assert_any_await("#username", fake_broker.expected_user)
        mock_driver.fill.assert_any_await("#password", fake_broker.expected_password)

    async def test_broker_resolution_appends_audit_entry(self, mock_driver, fake_broker):
        action = Authenticate(credential_provider="hooba", username="LITERAL", password="LITERAL")
        await exec_authenticate(
            mock_driver,
            action,
            dispatch_step_fn=None,
            credential_resolver=fake_broker.as_resolver(),
        )
        fake_broker.audit_ledger.append.assert_awaited_once()

    async def test_broker_miss_fails_closed(self, mock_driver, missing_broker):
        action = Authenticate(credential_provider="hooba", username="LITERAL", password="LITERAL")
        assert (
            await exec_authenticate(
                mock_driver,
                action,
                dispatch_step_fn=None,
                credential_resolver=missing_broker.as_resolver(),
            )
            is False
        )
        mock_driver.fill.assert_not_awaited()

    async def test_credential_provider_without_resolver_fails_closed(self, mock_driver):
        action = Authenticate(credential_provider="hooba", username="LITERAL", password="LITERAL")
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=None) is False
        mock_driver.fill.assert_not_awaited()

    async def test_incomplete_broker_credential_fails_closed(self, mock_driver):
        async def _resolver(action):
            return ("only-a-username", None)

        action = Authenticate(credential_provider="hooba", username="LITERAL", password="LITERAL")
        assert (
            await exec_authenticate(mock_driver, action, dispatch_step_fn=None, credential_resolver=_resolver) is False
        )
        mock_driver.fill.assert_not_awaited()

    async def test_never_logs_broker_credential(self, mock_driver, fake_broker, caplog):
        action = Authenticate(credential_provider="hooba", username="LITERAL", password="LITERAL")
        await exec_authenticate(
            mock_driver,
            action,
            dispatch_step_fn=None,
            credential_resolver=fake_broker.as_resolver(),
        )
        assert "broker-pass" not in caplog.text

    async def test_no_provider_still_uses_literals(self, mock_driver):
        # Back-compat: without credential_provider, literals still work
        # (no resolver involved at all).
        action = Authenticate(username="literal-user", password="literal-pass")
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=None) is True
        mock_driver.fill.assert_any_await("#username", "literal-user")


class TestPlansLint:
    def test_flags_literal_password(self):
        steps = [
            {"action": "navigate", "url": "http://x/"},
            {"action": "authenticate", "username": "u", "password": "hunter2"},
        ]
        warnings = lint_literal_credentials(steps)
        assert len(warnings) == 1
        assert "step 1" in warnings[0]
        assert "hunter2" not in warnings[0]

    def test_clean_plan_no_warnings(self):
        steps = [
            {"action": "navigate", "url": "http://x/"},
            {"action": "authenticate", "credential_provider": "hooba"},
        ]
        assert lint_literal_credentials(steps) == []

    def test_ignores_non_authenticate_steps(self):
        steps = [{"action": "fill", "selector": "#x", "value": "password"}]
        assert lint_literal_credentials(steps) == []
