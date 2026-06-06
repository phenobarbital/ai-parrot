"""Tests for SessionManager — FEAT-222 TASK-1451."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.scraping.flow_models import FlowNode
from parrot_tools.scraping.session_manager import SessionManager


def _make_context():
    ctx = MagicMock()
    ctx.close = AsyncMock()
    ctx.new_page = AsyncMock(return_value=MagicMock())
    return ctx


@pytest.fixture
def mock_browser():
    browser = MagicMock()
    # Each new_context() call returns a distinct context mock.
    browser.new_context = AsyncMock(side_effect=lambda **kw: _make_context())
    return browser


class TestGetContext:
    async def test_lazy_create_then_cache(self, mock_browser):
        sm = SessionManager(mock_browser)
        ctx1 = await sm.get_context("default")
        ctx2 = await sm.get_context("default")
        assert ctx1 is ctx2
        assert mock_browser.new_context.call_count == 1

    async def test_distinct_sessions(self, mock_browser):
        sm = SessionManager(mock_browser)
        ctx_a = await sm.get_context("a")
        ctx_b = await sm.get_context("b")
        assert ctx_a is not ctx_b
        assert mock_browser.new_context.call_count == 2

    async def test_default_kwargs_applied(self, mock_browser):
        sm = SessionManager(mock_browser, default_context_kwargs={"locale": "en-US"})
        await sm.get_context("default")
        assert mock_browser.new_context.call_args.kwargs == {"locale": "en-US"}

    async def test_session_config_override(self, mock_browser):
        sm = SessionManager(
            mock_browser,
            default_context_kwargs={"locale": "en-US"},
            session_configs={"auth": {"storage_state": "state.json"}},
        )
        await sm.get_context("auth")
        assert mock_browser.new_context.call_args.kwargs == {
            "locale": "en-US",
            "storage_state": "state.json",
        }


class TestNewPage:
    async def test_new_page_uses_session_context(self, mock_browser):
        sm = SessionManager(mock_browser)
        page = await sm.new_page("s1")
        ctx = await sm.get_context("s1")  # cached
        ctx.new_page.assert_awaited()
        assert page is not None


class TestLastUse:
    def test_precompute_last_use(self):
        sm = SessionManager(MagicMock())
        order = [
            FlowNode(id="n1", plan_ref="p", session="default"),
            FlowNode(id="n2", plan_ref="p", session="auth"),
            FlowNode(id="n3", plan_ref="p", session="default"),
        ]
        last = sm.precompute_last_use(order)
        assert last == {"default": "n3", "auth": "n2"}


class TestCloseIfLast:
    async def test_closes_after_last_node(self, mock_browser):
        sm = SessionManager(mock_browser)
        order = [
            FlowNode(id="n1", plan_ref="p", session="default"),
            FlowNode(id="n2", plan_ref="p", session="default"),
        ]
        sm.precompute_last_use(order)
        ctx = await sm.get_context("default")

        # Not the last node → context stays open.
        await sm.close_if_last("default", "n1")
        ctx.close.assert_not_awaited()

        # Last node → context closed and evicted.
        await sm.close_if_last("default", "n2")
        ctx.close.assert_awaited_once()
        assert "default" not in sm._contexts

    async def test_unknown_session_noop(self, mock_browser):
        sm = SessionManager(mock_browser)
        # No precompute / no context — should not raise.
        await sm.close_if_last("ghost", "x")


class TestCloseAll:
    async def test_close_all(self, mock_browser):
        sm = SessionManager(mock_browser)
        ctx_a = await sm.get_context("a")
        ctx_b = await sm.get_context("b")
        await sm.close_all()
        ctx_a.close.assert_awaited_once()
        ctx_b.close.assert_awaited_once()
        assert sm._contexts == {}

    async def test_close_all_suppresses_errors(self, mock_browser):
        sm = SessionManager(mock_browser)
        ctx = await sm.get_context("a")
        ctx.close = AsyncMock(side_effect=Exception("already closed"))
        # Should not raise despite the close failure.
        await sm.close_all()
        assert sm._contexts == {}
