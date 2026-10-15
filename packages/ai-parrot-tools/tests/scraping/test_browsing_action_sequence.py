"""Local-browser integration for hover, typing, submit, and screenshots."""

import struct
from pathlib import Path

import pytest

from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.plan import ScrapingPlan
from parrot_tools.scraping.toolkit_models import DriverConfig


def _png_dimensions(path: Path) -> tuple[int, int]:
    """Read width and height from a PNG IHDR without an image dependency."""
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


async def test_browsing_sequence_hover_type_submit_screenshot(tmp_path: Path) -> None:
    """Run the local fixture through the real executor and browser driver."""
    pytest.importorskip("playwright")
    driver = PlaywrightDriver()
    try:
        try:
            await driver.start()
        except Exception as exc:
            if exc.__class__.__module__.startswith("playwright") or "Connection closed while reading from the driver" in str(
                exc
            ):
                pytest.skip(f"Playwright browser tooling unavailable: {exc}")
            raise

        fixture = Path(__file__).parent / "fixtures" / "action_gaps.html"
        await driver.navigate(fixture.as_uri())
        result = await execute_plan_steps(
            driver,
            plan=ScrapingPlan(
                url=fixture.as_uri(),
                objective="exercise browser action gaps",
                steps=[
                    {"action": "hover", "selector": "#hover-target"},
                    {"action": "type", "selector": "#query", "text": "browser proof", "clear_first": True},
                    {"action": "submit", "selector": "#search-form", "wait_after_submit": "#submit-result"},
                    {
                        "action": "screenshot",
                        "name": "element",
                        "selector": "#submit-result",
                        "output_path": str(tmp_path),
                        "output_name": "element",
                    },
                    {
                        "action": "screenshot",
                        "name": "full_page",
                        "output_path": str(tmp_path),
                        "output_name": "full-page",
                        "full_page": True,
                    },
                ],
            ),
            config=DriverConfig(delay_between_actions=0),
        )

        assert await driver.evaluate("document.querySelector('#hover-menu').hidden") is False
        assert await driver.evaluate("document.querySelector('#query').value") == "browser proof"
        assert await driver.evaluate("document.querySelector('#submit-result').textContent") == "Submitted: browser proof"
        element_path = Path(result.extracted_data["element"]["path"])
        page_path = Path(result.extracted_data["full_page"]["path"])
        assert element_path.exists() and element_path.read_bytes().startswith(b"\x89PNG")
        assert page_path.exists() and page_path.read_bytes().startswith(b"\x89PNG")
        assert _png_dimensions(page_path)[1] > _png_dimensions(element_path)[1]
    finally:
        await driver.quit()
