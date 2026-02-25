"""Playwright browser configuration dataclass."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

_VALID_BROWSER_TYPES = frozenset({"chromium", "firefox", "webkit"})


@dataclass
class PlaywrightConfig:
    """Configuration for PlaywrightDriver.

    Holds all browser, context, and page settings used to launch and
    configure Playwright browser instances.

    Args:
        browser_type: Browser engine — ``"chromium"``, ``"firefox"``,
            or ``"webkit"``.
        headless: Whether to run the browser in headless mode.
        slow_mo: Milliseconds to wait between each action (useful for
            debugging).
        timeout: Default timeout in seconds for navigation and waiting.
        viewport: Browser viewport dimensions, e.g.
            ``{"width": 1280, "height": 720}``.
        locale: Browser locale, e.g. ``"en-US"``.
        timezone: Timezone ID, e.g. ``"America/New_York"``.
        geolocation: Geolocation coordinates, e.g.
            ``{"latitude": 40.7, "longitude": -74.0}``.
        permissions: List of browser permissions to grant, e.g.
            ``["geolocation"]``.
        mobile: Whether to emulate a mobile device.
        device_name: Playwright device descriptor name, e.g.
            ``"iPhone 13"``.
        proxy: Proxy settings, e.g.
            ``{"server": "http://proxy:8080"}``.
        ignore_https_errors: Whether to ignore HTTPS certificate errors.
        extra_http_headers: Additional HTTP headers for every request.
        http_credentials: HTTP authentication credentials, e.g.
            ``{"username": "u", "password": "p"}``.
        record_video_dir: Directory path to save screen recordings.
        record_har_path: File path to record HAR network log.
        storage_state: Path to a JSON file with saved cookies and
            localStorage for session reuse.
    """

    browser_type: str = "chromium"
    headless: bool = True
    slow_mo: int = 0
    timeout: int = 30
    viewport: Optional[Dict[str, int]] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    geolocation: Optional[Dict[str, float]] = None
    permissions: List[str] = field(default_factory=list)
    mobile: bool = False
    device_name: Optional[str] = None
    proxy: Optional[Dict[str, str]] = None
    ignore_https_errors: bool = False
    extra_http_headers: Optional[Dict[str, str]] = None
    http_credentials: Optional[Dict[str, str]] = None
    record_video_dir: Optional[str] = None
    record_har_path: Optional[str] = None
    storage_state: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.browser_type not in _VALID_BROWSER_TYPES:
            raise ValueError(
                f"Invalid browser_type '{self.browser_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_BROWSER_TYPES))}"
            )
