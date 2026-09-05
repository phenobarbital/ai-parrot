"""Tests for `DriverRegistry`'s Obscura entry (FEAT-530 review fix).

Covers the CRITICAL gap found by code review: `WebScrapingToolkit`/
`WebScrapingTool`'s session-based dispatch (`DriverRegistry.get(driver_type)`)
had no `"obscura"` entry at all, and `DriverConfig.driver_type` was a
pydantic `Literal["selenium", "playwright"]` that rejected `"obscura"`
outright — meaning the acceptance criterion "AbstractDriver callers and
existing scraping plans require no Obscura-specific branching" did not
actually hold for this dispatch path. All Playwright API calls are
mocked — no real Obscura process is spawned.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.scraping.driver_context import DriverRegistry, _ObscuraSetup
from parrot.tools.scraping.toolkit_models import DriverConfig


def test_obscura_registered_in_driver_registry():
    assert "obscura" in DriverRegistry.list_registered()
    factory = DriverRegistry.get("obscura")
    assert callable(factory)


def test_create_obscura_setup_returns_obscura_setup():
    setup = DriverRegistry.get("obscura")(DriverConfig(driver_type="obscura"))
    assert isinstance(setup, _ObscuraSetup)


class TestObscuraSetupGetDriver:
    async def test_builds_correct_playwright_config(self):
        config = DriverConfig(
            driver_type="obscura",
            headless=False,
            default_timeout=15,
            cdp_endpoint_url="http://127.0.0.1:9333",
            obscura_binary="/usr/local/bin/obscura",
            obscura_port=9333,
            obscura_stealth=True,
            obscura_allow_private_network=True,
        )
        setup = _ObscuraSetup(config)

        mock_driver = AsyncMock()
        with patch(
            "parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver",
            return_value=mock_driver,
        ) as mock_cls:
            driver = await setup.get_driver()

        assert driver is mock_driver
        mock_driver.start.assert_awaited_once()
        pw_config = mock_cls.call_args.args[0]
        assert pw_config.engine == "obscura"
        assert pw_config.browser_type == "chromium"
        assert pw_config.headless is False
        assert pw_config.timeout == 15
        assert pw_config.cdp_endpoint_url == "http://127.0.0.1:9333"
        assert pw_config.obscura_binary == "/usr/local/bin/obscura"
        assert pw_config.obscura_port == 9333
        assert pw_config.obscura_stealth is True
        assert pw_config.obscura_allow_private_network is True

    async def test_ignores_browser_field_always_chromium(self):
        """Obscura never selects browser type via DriverConfig.browser —
        it always connects over Chromium CDP."""
        config = DriverConfig(driver_type="obscura", browser="firefox")
        setup = _ObscuraSetup(config)

        mock_driver = AsyncMock()
        with patch(
            "parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver",
            return_value=mock_driver,
        ) as mock_cls:
            await setup.get_driver()

        pw_config = mock_cls.call_args.args[0]
        assert pw_config.browser_type == "chromium"


def test_driver_config_accepts_obscura_driver_type():
    config = DriverConfig(driver_type="obscura")
    assert config.driver_type == "obscura"


def test_driver_config_obscura_field_defaults():
    config = DriverConfig()
    assert config.cdp_endpoint_url is None
    assert config.obscura_binary is None
    assert config.obscura_port == 9222
    assert config.obscura_stealth is False
    assert config.obscura_allow_private_network is False
