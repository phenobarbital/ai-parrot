"""Tests for Chrome user-profile plumbing (user_data_dir et al.)."""
import pytest

from parrot_tools.scraping.driver_factory import DriverFactory
from parrot_tools.scraping.toolkit_models import DriverConfig


class TestDriverConfigProfileFields:
    def test_defaults_are_none(self):
        cfg = DriverConfig()
        assert cfg.user_data_dir is None
        assert cfg.profile_directory is None
        assert cfg.browser_channel is None

    def test_merge_applies_profile_fields(self):
        cfg = DriverConfig().merge(
            {
                "user_data_dir": "/tmp/profile",
                "profile_directory": "Profile 1",
                "browser_channel": "chrome",
            }
        )
        assert cfg.user_data_dir == "/tmp/profile"
        assert cfg.profile_directory == "Profile 1"
        assert cfg.browser_channel == "chrome"


class TestDriverFactoryProfileForwarding:
    def test_playwright_receives_profile(self):
        pytest.importorskip("playwright")
        driver = DriverFactory.create(
            {
                "driver_type": "playwright",
                "browser": "chrome",
                "user_data_dir": "/tmp/profile",
                "browser_channel": "chrome",
            }
        )
        assert driver.config.user_data_dir == "/tmp/profile"
        assert driver.config.channel == "chrome"

    def test_selenium_receives_profile(self):
        driver = DriverFactory.create(
            {
                "driver_type": "selenium",
                "browser": "chrome",
                "user_data_dir": "/tmp/profile",
                "profile_directory": "Profile 1",
            }
        )
        assert driver._options["user_data_dir"] == "/tmp/profile"
        assert driver._options["profile_directory"] == "Profile 1"


class TestSeleniumSetupProfileDirectory:
    def test_chrome_options_include_profile_arguments(self):
        pytest.importorskip("selenium")
        from parrot_tools.scraping.driver import SeleniumSetup

        setup = SeleniumSetup(
            browser="chrome",
            user_data_dir="/tmp/profile",
            profile_directory="Profile 1",
        )
        options = setup._setup_chrome_options()
        args = options.arguments
        assert "--user-data-dir=/tmp/profile" in args
        assert "--profile-directory=Profile 1" in args
