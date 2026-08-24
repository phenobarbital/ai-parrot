"""``real_playwright_driver`` — a real, started :class:`PlaywrightDriver`
fixture for FEAT-455's real-browser integration tests.

Skips (never fails) the requesting test when Chromium is not installed —
these are opt-in real-browser tests, not a hard CI requirement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver


@pytest.fixture
async def real_playwright_driver() -> AsyncIterator[PlaywrightDriver]:
    """Yield a started, headless :class:`PlaywrightDriver`.

    Guarantees ``.quit()`` even when the test body raises. Skips the test
    (via ``pytest.skip``) when Chromium cannot be launched — e.g. Chromium
    was never installed via ``playwright install chromium`` — rather than
    failing the suite.
    """
    driver = PlaywrightDriver(PlaywrightConfig(headless=True))
    try:
        await driver.start()
    except Exception as exc:  # noqa: BLE001 — any launch failure means "skip", not "fail"
        pytest.skip(f"Real Chromium is not available in this environment: {exc}")

    try:
        yield driver
    finally:
        await driver.quit()
