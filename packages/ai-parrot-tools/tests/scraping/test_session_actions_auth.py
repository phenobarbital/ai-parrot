"""Tests for session_actions — authenticate + cookies (Module 1, part 1/3).

FEAT-453 TASK-2384.
"""
from unittest.mock import AsyncMock

import pytest
from parrot_tools.scraping.models import Authenticate, GetCookies, SetCookies
from parrot_tools.scraping.session_actions import (
    exec_authenticate,
    exec_get_cookies,
    exec_set_cookies,
)


@pytest.fixture
def mock_driver():
    """An AsyncMock-backed AbstractDriver fake (mirrors test_executor.py)."""
    driver = AsyncMock()
    driver.fill = AsyncMock(return_value=None)
    driver.click = AsyncMock(return_value=None)
    driver.press_key = AsyncMock(return_value=None)
    driver.navigate = AsyncMock(return_value=None)
    driver.wait_for_load_state = AsyncMock(return_value=None)
    driver.execute_script = AsyncMock(return_value="session=abc123; other=xyz")
    driver.current_url = "https://example.test/login"
    return driver


@pytest.fixture
def failing_driver():
    """A driver whose interactive methods raise, simulating a broken page."""
    driver = AsyncMock()
    driver.fill = AsyncMock(side_effect=RuntimeError("element not found"))
    driver.click = AsyncMock(side_effect=RuntimeError("element not found"))
    driver.current_url = "https://example.test/login"
    return driver


class TestExecAuthenticate:
    async def test_form_login_fills_and_submits(self, mock_driver):
        action = Authenticate(username="u", password="p")
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=None) is True
        mock_driver.fill.assert_any_await("#username", "u")
        mock_driver.click.assert_awaited_with(action.submit_selector, timeout=10)

    async def test_enter_on_username_multistep(self, mock_driver):
        action = Authenticate(username="u", password="p", enter_on_username=True)
        await exec_authenticate(mock_driver, action, dispatch_step_fn=None)
        mock_driver.press_key.assert_awaited_with("Enter")

    async def test_never_logs_password(self, mock_driver, caplog):
        await exec_authenticate(
            mock_driver,
            Authenticate(username="u", password="hunter2"),
            dispatch_step_fn=None,
        )
        assert "hunter2" not in caplog.text

    async def test_returns_false_on_failure(self, failing_driver):
        assert await exec_authenticate(
            failing_driver, Authenticate(username="u", password="p"), dispatch_step_fn=None
        ) is False

    async def test_missing_credentials_returns_false(self, mock_driver):
        assert await exec_authenticate(mock_driver, Authenticate(), dispatch_step_fn=None) is False

    async def test_basic_auth_navigates_with_embedded_credentials(self, mock_driver):
        action = Authenticate(method="basic", username="u", password="p")
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=None) is True
        mock_driver.navigate.assert_awaited_once()
        (navigated_url,), _kwargs = mock_driver.navigate.call_args
        assert navigated_url.startswith("https://u:p@example.test/login")

    async def test_custom_method_dispatches_custom_steps(self, mock_driver):
        step_action = Authenticate(method="form", username="a", password="b")
        action = Authenticate(method="custom", custom_steps=[step_action])
        dispatch = AsyncMock(return_value=True)
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=dispatch) is True
        dispatch.assert_awaited_once()

    async def test_custom_method_without_steps_fails_closed(self, mock_driver):
        action = Authenticate(method="custom", custom_steps=None)
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=AsyncMock()) is False

    async def test_oauth_without_dispatch_fn_fails_closed(self, mock_driver):
        step_action = Authenticate(method="form", username="a", password="b")
        action = Authenticate(method="oauth", custom_steps=[step_action])
        assert await exec_authenticate(mock_driver, action, dispatch_step_fn=None) is False

    async def test_credential_resolver_overrides_literals(self, mock_driver):
        resolver = AsyncMock(return_value=("resolved-user", "resolved-pass"))
        action = Authenticate(username="literal-user", password="literal-pass")
        assert await exec_authenticate(
            mock_driver, action, dispatch_step_fn=None, credential_resolver=resolver
        ) is True
        mock_driver.fill.assert_any_await("#username", "resolved-user")

    async def test_credential_resolver_failure_fails_closed(self, mock_driver):
        resolver = AsyncMock(side_effect=RuntimeError("broker down"))
        action = Authenticate(username="u", password="p")
        assert await exec_authenticate(
            mock_driver, action, dispatch_step_fn=None, credential_resolver=resolver
        ) is False


class TestCookies:
    async def test_roundtrip(self, mock_driver):
        result = await exec_get_cookies(mock_driver, GetCookies())
        cookies = result["cookies"]
        assert cookies == [
            {"name": "session", "value": "abc123"},
            {"name": "other", "value": "xyz"},
        ]
        assert await exec_set_cookies(mock_driver, SetCookies(cookies=cookies)) is True

    async def test_get_cookies_filters_by_name(self, mock_driver):
        result = await exec_get_cookies(mock_driver, GetCookies(names=["session"]))
        assert result["cookies"] == [{"name": "session", "value": "abc123"}]

    async def test_get_cookies_failure_returns_empty(self):
        driver = AsyncMock()
        driver.execute_script = AsyncMock(side_effect=RuntimeError("no page"))
        result = await exec_get_cookies(driver, GetCookies())
        assert result == {"cookies": []}

    async def test_set_cookies_failure_returns_false(self):
        driver = AsyncMock()
        driver.execute_script = AsyncMock(side_effect=RuntimeError("no page"))
        assert await exec_set_cookies(driver, SetCookies(cookies=[{"name": "a", "value": "b"}])) is False

    async def test_set_cookies_skips_entries_without_name(self, mock_driver):
        assert await exec_set_cookies(
            mock_driver, SetCookies(cookies=[{"value": "no-name-here"}])
        ) is True
        mock_driver.execute_script.assert_not_awaited()
