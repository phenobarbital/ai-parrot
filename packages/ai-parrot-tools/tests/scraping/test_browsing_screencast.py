"""Session recording exposure and a real local browser recording smoke test."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.browsing.toolkit import WebBrowsingToolkit


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded", [True, False])
async def test_close_browser_reports_finalized_recording(tmp_path: Path, recorded: bool) -> None:
    """Read the path after quit finishes, including drivers without recording support."""
    toolkit = WebBrowsingToolkit(catalog_dir=tmp_path / "catalog")
    driver = MagicMock(spec=["quit", "recording_path"] if recorded else ["quit"])
    if recorded:
        driver.recording_path = None

    async def quit_driver() -> None:
        if recorded:
            driver.recording_path = str(tmp_path / "session.webm")

    driver.quit = AsyncMock(side_effect=quit_driver)
    toolkit._session_driver = driver
    result = await toolkit.close_browser()
    assert result == {"closed": True, "recording_path": str(tmp_path / "session.webm") if recorded else None}
    driver.quit.assert_awaited_once()
    assert toolkit._session_driver is None
    assert await toolkit.close_browser() == {"closed": False, "recording_path": None}


@pytest.mark.asyncio
async def test_close_browser_no_session(tmp_path: Path) -> None:
    """Closing an unopened session is safe."""
    toolkit = WebBrowsingToolkit(catalog_dir=tmp_path / "catalog")
    assert toolkit._config.driver_type == "playwright"
    assert await toolkit.close_browser() == {"closed": False, "recording_path": None}


@pytest.mark.asyncio
async def test_real_playwright_session_produces_webm_recording(tmp_path: Path) -> None:
    """A catalogued navigation produces a finalized, nonempty WebM file."""
    pytest.importorskip("playwright")
    fixture = Path(__file__).parent / "fixtures" / "action_gaps.html"
    toolkit = WebBrowsingToolkit(
        catalog_dir=tmp_path / "catalog",
        plans_dir=tmp_path / "plans",
        headless=True,
        record_video=True,
        delay_between_actions=0,
    )
    try:
        try:
            await toolkit.start()
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip(f"Playwright browser/recorder tooling unavailable: {exc}")
            raise
        await toolkit.register_site(base_url="https://fixture.example", name="fixture")
        await toolkit.save_site_action(
            site="fixture",
            name="visit",
            description="Visit the local fixture",
            steps=[{"action": "navigate", "url": fixture.as_uri()}],
        )
        await toolkit.run_site_action("fixture", "visit")
        assert toolkit._session_driver.current_url == fixture.as_uri()
        result = await toolkit.close_browser()
        assert result["closed"] is True
        assert result["recording_path"] is not None
        path = Path(result["recording_path"])
        assert path.suffix == ".webm"
        assert path.is_relative_to(tmp_path / "plans" / "files" / "recordings")
        assert path.stat().st_size > 0
    finally:
        await toolkit.stop()
