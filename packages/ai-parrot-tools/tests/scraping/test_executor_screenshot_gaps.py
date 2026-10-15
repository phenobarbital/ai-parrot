"""Regression coverage for typing and screenshot executor artifacts."""

import base64
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot_tools.scraping import executor as executor_module
from parrot_tools.scraping.confine import FILES_ROOT, PathConfinementError
from parrot_tools.scraping.executor import MAX_SCREENSHOT_BASE64_BYTES, execute_plan_steps
from parrot_tools.scraping.models import ACTION_MAP
from parrot_tools.scraping.plan import ScrapingPlan
from parrot_tools.scraping.toolkit_models import DriverConfig


@pytest.fixture
def spy_driver() -> AsyncMock:
    """Return a driver mock with a minimal final document."""
    driver = AsyncMock()
    driver.current_url = "http://x/"
    driver.get_page_source.return_value = "<html></html>"
    driver.screenshot.return_value = b"\x89PNG"
    driver.screenshot_element.return_value = b"\x89PNG"
    return driver


def _plan(*steps: dict) -> ScrapingPlan:
    """Create a plan whose action delays are disabled by the caller."""
    return ScrapingPlan(url="http://x/", objective="test", steps=list(steps))


async def test_type_forwards_all_fields(spy_driver: AsyncMock) -> None:
    """Typing passes every declared model field to the driver."""
    await execute_plan_steps(
        spy_driver,
        plan=_plan({"action": "type", "text": "hello", "selector": "#q", "delay": 7, "clear_first": True}),
        config=DriverConfig(delay_between_actions=0, default_timeout=23),
    )

    spy_driver.type_text.assert_awaited_once_with("hello", selector="#q", delay_ms=7, clear_first=True, timeout=23)


async def test_type_without_selector_uses_default_timeout(spy_driver: AsyncMock) -> None:
    """Focused-element typing preserves ``selector=None``."""
    await execute_plan_steps(
        spy_driver,
        plan=_plan({"action": "type", "text": "focused"}),
        config=DriverConfig(delay_between_actions=0, default_timeout=19),
    )

    spy_driver.type_text.assert_awaited_once_with("focused", selector=None, delay_ms=0, clear_first=False, timeout=19)


async def test_screenshot_passes_full_page_and_records_path(spy_driver: AsyncMock, tmp_path: Path) -> None:
    """Page captures receive the model's full-page flag and report their path."""
    result = await execute_plan_steps(
        spy_driver,
        plan=_plan(
            {
                "action": "screenshot",
                "output_path": str(tmp_path),
                "output_name": "page.png",
                "full_page": True,
            }
        ),
        config=DriverConfig(delay_between_actions=0),
    )

    expected = str(tmp_path / "page.png")
    spy_driver.screenshot.assert_awaited_once_with(expected, full_page=True)
    spy_driver.screenshot_element.assert_not_awaited()
    assert result.extracted_data == {"screenshot": {"path": expected}}


async def test_screenshot_element_uses_element_capture(spy_driver: AsyncMock, tmp_path: Path) -> None:
    """A selector routes a capture through the element-specific driver API."""
    await execute_plan_steps(
        spy_driver,
        plan=_plan(
            {
                "action": "screenshot",
                "selector": "#card",
                "output_path": str(tmp_path),
                "output_name": "card",
                "full_page": True,
                "timeout": 12,
            }
        ),
        config=DriverConfig(delay_between_actions=0),
    )

    spy_driver.screenshot_element.assert_awaited_once_with("#card", str(tmp_path / "card.png"), 12)
    spy_driver.screenshot.assert_not_awaited()


async def test_screenshot_return_base64(spy_driver: AsyncMock, tmp_path: Path) -> None:
    """Screenshot payload base64 decodes to precisely the captured bytes."""
    png = b"\x89PNG\r\ndata"
    spy_driver.screenshot.return_value = png
    result = await execute_plan_steps(
        spy_driver,
        plan=_plan(
            {"action": "screenshot", "output_path": str(tmp_path), "output_name": "encoded", "return_base64": True}
        ),
        config=DriverConfig(delay_between_actions=0),
    )

    payload = result.extracted_data["screenshot"]
    assert base64.b64decode(payload["base64"]) == png
    assert "base64_omitted" not in payload
    assert "size_bytes" not in payload


@pytest.mark.parametrize(
    ("size", "expect_base64"),
    [(MAX_SCREENSHOT_BASE64_BYTES, True), (MAX_SCREENSHOT_BASE64_BYTES + 1, False)],
)
async def test_screenshot_base64_cap(spy_driver: AsyncMock, tmp_path: Path, size: int, expect_base64: bool) -> None:
    """The raw-byte cap includes exactly two MiB and excludes one byte above it."""
    spy_driver.screenshot.return_value = b"x" * size
    result = await execute_plan_steps(
        spy_driver,
        plan=_plan(
            {"action": "screenshot", "output_path": str(tmp_path), "output_name": str(size), "return_base64": True}
        ),
        config=DriverConfig(delay_between_actions=0),
    )

    payload = result.extracted_data["screenshot"]
    assert ("base64" in payload) is expect_base64
    if not expect_base64:
        assert payload["base64_omitted"] is True
        assert payload["size_bytes"] == size


async def test_screenshot_key_and_path_collisions_use_first_free_suffix(spy_driver: AsyncMock, tmp_path: Path) -> None:
    """Repeated captures retain all artifacts without replacing a file or key."""
    (tmp_path / "same.png").write_bytes(b"old")
    (tmp_path / "same_2.png").write_bytes(b"old")
    result = await execute_plan_steps(
        spy_driver,
        plan=_plan(
            {"action": "screenshot", "name": "capture", "output_path": str(tmp_path), "output_name": "same"},
            {"action": "screenshot", "name": "capture", "output_path": str(tmp_path), "output_name": "same"},
        ),
        config=DriverConfig(delay_between_actions=0),
    )

    assert result.extracted_data["capture"]["path"] == str(tmp_path / "same_3.png")
    assert result.extracted_data["capture_2"]["path"] == str(tmp_path / "same_4.png")
    assert (tmp_path / "same.png").read_bytes() == b"old"
    assert (tmp_path / "same_2.png").read_bytes() == b"old"


async def test_screenshot_custom_name_key_and_failed_capture(spy_driver: AsyncMock, tmp_path: Path) -> None:
    """Custom names key payloads and failed captures add no incomplete payload."""
    spy_driver.screenshot.side_effect = RuntimeError("capture failed")
    result = await execute_plan_steps(
        spy_driver,
        plan=_plan({"action": "screenshot", "name": "receipt", "output_path": str(tmp_path), "output_name": "receipt"}),
        config=DriverConfig(delay_between_actions=0),
    )

    assert "receipt" not in result.extracted_data
    assert result.metadata["step_errors"][0]["action"] == "screenshot"


async def test_screenshot_rejects_path_traversal_when_confined(spy_driver: AsyncMock, tmp_path: Path) -> None:
    """A confined screenshot cannot escape through its custom filename."""
    token = FILES_ROOT.set(tmp_path)
    try:
        with pytest.raises(PathConfinementError):
            await executor_module._action_screenshot(
                spy_driver,
                ACTION_MAP["screenshot"](output_name="../escape.png"),
                AsyncMock(),
                {},
            )
    finally:
        FILES_ROOT.reset(token)


async def test_every_action_map_entry_is_dispatched() -> None:
    """Every registered action opcode has an explicit dispatcher branch."""
    source = inspect.getsource(executor_module._dispatch_step)
    missing = [action_type for action_type in ACTION_MAP if f'action_type == "{action_type}"' not in source]
    assert missing == []
