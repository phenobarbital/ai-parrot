"""Tests for session_actions — wait actions + HumanChannel injection
(Module 1, part 2/3).

FEAT-453 TASK-2385.
"""

from unittest.mock import AsyncMock

import pytest
from parrot.human.channels.base import HumanChannel
from parrot_tools.scraping import session_actions
from parrot_tools.scraping.models import AwaitBrowserEvent, AwaitHuman, AwaitKeyPress
from parrot_tools.scraping.session_actions import (
    exec_await_browser_event,
    exec_await_human,
    exec_await_keypress,
)


class FakeHumanChannel(HumanChannel):
    """Minimal concrete HumanChannel for tests — records outbound calls."""

    def __init__(self, deliver: bool = True):
        self.notifications: list[tuple[str, str]] = []
        self.interactions: list[tuple[object, str]] = []
        self._deliver = deliver
        self.response_handler = None

    async def send_interaction(self, interaction, recipient):
        self.interactions.append((interaction, recipient))
        return self._deliver

    async def send_notification(self, recipient, message):
        self.notifications.append((recipient, message))

    async def cancel_interaction(self, interaction_id, recipient):
        return True

    async def register_response_handler(self, callback):
        self.response_handler = callback


@pytest.fixture
def mock_driver():
    """An AsyncMock-backed AbstractDriver fake whose selector check is
    satisfied on the first poll (element count = 1)."""
    driver = AsyncMock()
    driver.execute_script = AsyncMock(return_value=1)
    driver.evaluate = AsyncMock(return_value="Dashboard")
    driver.current_url = "https://example.test/dashboard"
    return driver


@pytest.fixture
def never_ready_driver():
    """A driver whose checks never succeed — used to exercise timeouts."""
    driver = AsyncMock()
    driver.execute_script = AsyncMock(return_value=0)
    driver.evaluate = AsyncMock(return_value="")
    driver.current_url = "https://example.test/login"
    return driver


@pytest.fixture
def fake_channel():
    return FakeHumanChannel()


class TestAwaitHuman:
    async def test_manual_without_channel_fails_closed(self, mock_driver):
        action = AwaitHuman(condition_type="manual", timeout=300)
        # must NOT block for 300s
        assert await exec_await_human(mock_driver, action, channel=None) is False

    async def test_selector_condition_notifies_channel(self, mock_driver, fake_channel):
        action = AwaitHuman(condition_type="selector", target="#done")
        assert await exec_await_human(mock_driver, action, channel=fake_channel) is True
        assert fake_channel.notifications, "operator was never told the browser is waiting"

    async def test_timeout_returns_false(self, never_ready_driver):
        action = AwaitHuman(condition_type="selector", target="#never", timeout=1)
        assert await exec_await_human(never_ready_driver, action) is False

    async def test_url_contains_condition(self, mock_driver):
        action = AwaitHuman(condition_type="url_contains", target="dashboard", timeout=5)
        assert await exec_await_human(mock_driver, action) is True

    async def test_title_contains_condition(self, mock_driver):
        action = AwaitHuman(condition_type="title_contains", target="Dashboard", timeout=5)
        assert await exec_await_human(mock_driver, action) is True

    async def test_no_target_returns_false_immediately(self, mock_driver):
        action = AwaitHuman(condition_type="selector", target=None)
        assert await exec_await_human(mock_driver, action) is False

    async def test_manual_with_channel_waits_for_response(self, mock_driver, fake_channel):
        action = AwaitHuman(condition_type="manual", timeout=5, message="Please confirm")
        assert fake_channel.response_handler is None

        # Resolve the response as soon as the handler is registered.
        import asyncio

        async def _resolve_soon():
            while fake_channel.response_handler is None:
                await asyncio.sleep(0.01)
            await fake_channel.response_handler(object())

        task = asyncio.create_task(_resolve_soon())
        result = await exec_await_human(mock_driver, action, channel=fake_channel)
        await task
        assert result is True
        assert fake_channel.interactions

    async def test_manual_with_channel_delivery_failure(self, mock_driver):
        channel = FakeHumanChannel(deliver=False)
        action = AwaitHuman(condition_type="manual", timeout=1)
        assert await exec_await_human(mock_driver, action, channel=channel) is False

    async def test_manual_with_channel_timeout(self, mock_driver, fake_channel):
        action = AwaitHuman(condition_type="manual", timeout=1)
        assert await exec_await_human(mock_driver, action, channel=fake_channel) is False


class TestAwaitKeypress:
    async def test_returns_true_on_expected_key(self, mock_driver, monkeypatch):
        monkeypatch.setattr(session_actions.select, "select", lambda *a, **kw: ([True], [], []))
        monkeypatch.setattr(session_actions.sys.stdin, "readline", lambda: "go\n")
        action = AwaitKeyPress(expected_key="go", timeout=5)
        assert await exec_await_keypress(mock_driver, action) is True

    async def test_any_key_when_expected_key_unset(self, mock_driver, monkeypatch):
        monkeypatch.setattr(session_actions.select, "select", lambda *a, **kw: ([True], [], []))
        monkeypatch.setattr(session_actions.sys.stdin, "readline", lambda: "anything\n")
        action = AwaitKeyPress(expected_key=None, timeout=5)
        assert await exec_await_keypress(mock_driver, action) is True

    async def test_timeout_returns_false(self, mock_driver, monkeypatch):
        monkeypatch.setattr(session_actions.select, "select", lambda *a, **kw: ([], [], []))
        action = AwaitKeyPress(timeout=1)
        assert await exec_await_keypress(mock_driver, action) is False


class TestAwaitBrowserEvent:
    async def test_returns_true_when_flag_already_set(self, mock_driver):
        # execute_script always returns 1 (truthy) -> ready on first check.
        action = AwaitBrowserEvent(timeout=5)
        assert await exec_await_browser_event(mock_driver, action) is True

    async def test_timeout_returns_false(self, never_ready_driver):
        action = AwaitBrowserEvent(timeout=1)
        assert await exec_await_browser_event(never_ready_driver, action) is False

    async def test_string_target_used_as_key_combo(self, mock_driver):
        action = AwaitBrowserEvent(target="alt_shift_s", timeout=5)
        assert await exec_await_browser_event(mock_driver, action) is True
