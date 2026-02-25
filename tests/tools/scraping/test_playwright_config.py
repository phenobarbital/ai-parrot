"""Unit tests for PlaywrightConfig dataclass (TASK-057)."""

import pytest

from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig


class TestPlaywrightConfigDefaults:
    def test_default_browser_type(self):
        config = PlaywrightConfig()
        assert config.browser_type == "chromium"

    def test_default_headless(self):
        config = PlaywrightConfig()
        assert config.headless is True

    def test_default_timeout(self):
        config = PlaywrightConfig()
        assert config.timeout == 30

    def test_default_slow_mo(self):
        config = PlaywrightConfig()
        assert config.slow_mo == 0

    def test_default_mobile(self):
        config = PlaywrightConfig()
        assert config.mobile is False

    def test_default_ignore_https_errors(self):
        config = PlaywrightConfig()
        assert config.ignore_https_errors is False

    def test_permissions_default_empty_list(self):
        config = PlaywrightConfig()
        assert config.permissions == []

    def test_optional_fields_are_none(self):
        config = PlaywrightConfig()
        assert config.viewport is None
        assert config.locale is None
        assert config.timezone is None
        assert config.geolocation is None
        assert config.device_name is None
        assert config.proxy is None
        assert config.extra_http_headers is None
        assert config.http_credentials is None
        assert config.record_video_dir is None
        assert config.record_har_path is None
        assert config.storage_state is None


class TestPlaywrightConfigCustomValues:
    def test_custom_browser_type(self):
        config = PlaywrightConfig(browser_type="firefox")
        assert config.browser_type == "firefox"

    def test_webkit_browser_type(self):
        config = PlaywrightConfig(browser_type="webkit")
        assert config.browser_type == "webkit"

    def test_custom_viewport(self):
        config = PlaywrightConfig(viewport={"width": 1920, "height": 1080})
        assert config.viewport == {"width": 1920, "height": 1080}

    def test_custom_proxy(self):
        config = PlaywrightConfig(proxy={"server": "http://localhost:8080"})
        assert config.proxy["server"] == "http://localhost:8080"

    def test_mobile_with_device(self):
        config = PlaywrightConfig(mobile=True, device_name="iPhone 13")
        assert config.mobile is True
        assert config.device_name == "iPhone 13"

    def test_custom_locale_and_timezone(self):
        config = PlaywrightConfig(locale="es-ES", timezone="Europe/Madrid")
        assert config.locale == "es-ES"
        assert config.timezone == "Europe/Madrid"

    def test_custom_geolocation(self):
        config = PlaywrightConfig(
            geolocation={"latitude": 40.7, "longitude": -74.0}
        )
        assert config.geolocation["latitude"] == 40.7

    def test_custom_http_credentials(self):
        config = PlaywrightConfig(
            http_credentials={"username": "user", "password": "pass"}
        )
        assert config.http_credentials["username"] == "user"

    def test_custom_extra_http_headers(self):
        config = PlaywrightConfig(
            extra_http_headers={"X-Custom": "value"}
        )
        assert config.extra_http_headers["X-Custom"] == "value"

    def test_recording_paths(self):
        config = PlaywrightConfig(
            record_video_dir="/tmp/videos",
            record_har_path="/tmp/trace.har",
        )
        assert config.record_video_dir == "/tmp/videos"
        assert config.record_har_path == "/tmp/trace.har"

    def test_storage_state(self):
        config = PlaywrightConfig(storage_state="/tmp/auth.json")
        assert config.storage_state == "/tmp/auth.json"

    def test_headless_false(self):
        config = PlaywrightConfig(headless=False)
        assert config.headless is False

    def test_custom_slow_mo(self):
        config = PlaywrightConfig(slow_mo=250)
        assert config.slow_mo == 250

    def test_custom_timeout(self):
        config = PlaywrightConfig(timeout=60)
        assert config.timeout == 60


class TestPlaywrightConfigMutableSafety:
    def test_permissions_not_shared(self):
        """Each instance gets its own permissions list."""
        c1 = PlaywrightConfig()
        c2 = PlaywrightConfig()
        c1.permissions.append("geolocation")
        assert c2.permissions == []


class TestPlaywrightConfigValidation:
    def test_invalid_browser_type_raises(self):
        with pytest.raises(ValueError, match="Invalid browser_type"):
            PlaywrightConfig(browser_type="opera")

    def test_invalid_browser_type_message(self):
        with pytest.raises(ValueError, match="chromium"):
            PlaywrightConfig(browser_type="netscape")

    def test_valid_browser_types(self):
        for bt in ("chromium", "firefox", "webkit"):
            config = PlaywrightConfig(browser_type=bt)
            assert config.browser_type == bt


class TestPlaywrightConfigImports:
    def test_import_from_module(self):
        from parrot.tools.scraping.drivers.playwright_config import (
            PlaywrightConfig as PC,
        )

        assert PC is not None
