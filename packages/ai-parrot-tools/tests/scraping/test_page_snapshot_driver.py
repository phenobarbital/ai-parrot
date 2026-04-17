"""Tests for snapshot_from_driver against AbstractDriver — TASK-730 / TASK-732."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, PropertyMock

from parrot_tools.scraping.page_snapshot import snapshot_from_driver


class TestSnapshotFromAbstractDriver:
    """Verify snapshot_from_driver uses AbstractDriver methods, not Selenium attrs."""

    @pytest.mark.asyncio
    async def test_uses_get_page_source(self):
        """snapshot_from_driver calls driver.get_page_source() to get HTML."""
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://example.com")
        driver.get_page_source = AsyncMock(
            return_value="<html><body><h1>Hi</h1></body></html>"
        )
        driver.execute_script = AsyncMock(return_value=0)  # _scroll_sweep height

        snap = await snapshot_from_driver(driver, url="https://example.com", scroll_sweep=False)
        driver.get_page_source.assert_awaited_once()
        assert snap is not None

    @pytest.mark.asyncio
    async def test_navigates_when_url_differs(self):
        """snapshot_from_driver calls driver.navigate() when URL differs."""
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://other.com")
        driver.get_page_source = AsyncMock(return_value="<html></html>")
        driver.execute_script = AsyncMock(return_value=0)

        await snapshot_from_driver(
            driver,
            url="https://example.com",
            settle_seconds=0,
            scroll_sweep=False,
        )
        driver.navigate.assert_awaited_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_does_not_navigate_when_url_matches(self):
        """snapshot_from_driver skips navigate() when current URL already matches."""
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://example.com")
        driver.get_page_source = AsyncMock(return_value="<html></html>")
        driver.execute_script = AsyncMock(return_value=0)

        await snapshot_from_driver(
            driver,
            url="https://example.com",
            scroll_sweep=False,
        )
        driver.navigate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_none_on_driver_error(self):
        """snapshot_from_driver returns None and warns when driver raises."""
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(side_effect=RuntimeError("boom"))
        snap = await snapshot_from_driver(driver, url="https://x.com", scroll_sweep=False)
        assert snap is None

    @pytest.mark.asyncio
    async def test_returns_none_on_get_page_source_error(self):
        """snapshot_from_driver returns None when get_page_source raises."""
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://example.com")
        driver.get_page_source = AsyncMock(side_effect=Exception("dead"))
        snap = await snapshot_from_driver(
            driver, url="https://example.com", scroll_sweep=False
        )
        assert snap is None

    @pytest.mark.asyncio
    async def test_no_url_arg_skips_navigation(self):
        """When url=None, snapshot_from_driver does not check or call navigate."""
        driver = AsyncMock()
        driver.get_page_source = AsyncMock(
            return_value="<html><body><p>content</p></body></html>"
        )
        driver.execute_script = AsyncMock(return_value=0)

        snap = await snapshot_from_driver(driver, scroll_sweep=False)
        driver.navigate.assert_not_awaited()
        assert snap is not None

    @pytest.mark.asyncio
    async def test_snapshot_parses_html(self):
        """Returned PageSnapshot has a non-empty title extracted from HTML."""
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://example.com")
        driver.get_page_source = AsyncMock(
            return_value="<html><head><title>My Page</title></head><body><h1>Hello</h1></body></html>"
        )
        driver.execute_script = AsyncMock(return_value=0)

        snap = await snapshot_from_driver(driver, scroll_sweep=False)
        assert snap is not None
        assert snap.title == "My Page"

    @pytest.mark.asyncio
    async def test_scroll_sweep_calls_execute_script(self):
        """When scroll_sweep=True, driver.execute_script is called for scrolling."""
        driver = AsyncMock()
        type(driver).current_url = PropertyMock(return_value="https://example.com")
        driver.get_page_source = AsyncMock(
            return_value="<html><body>ok</body></html>"
        )
        # Return a positive height to trigger actual scroll steps
        driver.execute_script = AsyncMock(return_value=1200)

        await snapshot_from_driver(driver, scroll_sweep=True)
        driver.execute_script.assert_awaited()
