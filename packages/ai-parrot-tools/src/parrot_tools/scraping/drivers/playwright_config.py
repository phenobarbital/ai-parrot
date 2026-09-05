"""Playwright browser configuration dataclass."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

_VALID_BROWSER_TYPES = frozenset({"chromium", "firefox", "webkit"})
_VALID_ENGINES = frozenset({"playwright", "obscura"})


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
        user_data_dir: Path to a persistent browser profile directory
            (e.g. a Google Chrome user-data dir). When set, the driver
            launches a *persistent context* over that profile, exposing
            its cookies, saved sessions and credential store.
        channel: Browser distribution channel (e.g. ``"chrome"``,
            ``"msedge"``). Required to open a real Google Chrome profile
            with its keyring-encrypted data; only meaningful for
            ``browser_type="chromium"``.
        engine: Connection engine — ``"playwright"`` (default) launches a
            local browser as before; ``"obscura"`` connects to a
            supervised Obscura CDP endpoint via
            ``chromium.connect_over_cdp()`` instead of launching a
            browser, preserving all other driver methods unchanged.
        cdp_endpoint_url: Explicit CDP endpoint to connect to when
            ``engine="obscura"``, e.g. ``"http://127.0.0.1:9222"``. When
            unset, the endpoint is derived from ``obscura_port`` on
            ``127.0.0.1``.
        obscura_binary: Path to (or ``PATH``-resolvable name of) the
            Obscura binary. Not used by ``PlaywrightDriver`` itself —
            carried through for callers (e.g. the driver factory or CLI)
            that supervise the Obscura process via
            ``parrot.mcp.obscura.ObscuraProcessManager``.
        obscura_port: CDP port of the supervised Obscura process, used to
            derive ``cdp_endpoint_url`` when it is not set explicitly.
        obscura_stealth: Obscura stealth-mode flag, carried through for
            process supervision callers; unused by this driver directly.
        obscura_allow_private_network: Obscura
            ``--allow-private-network`` flag, carried through for process
            supervision callers; unused by this driver directly.
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
    user_data_dir: Optional[str] = None
    channel: Optional[str] = None
    engine: str = "playwright"
    cdp_endpoint_url: Optional[str] = None
    obscura_binary: Optional[str] = None
    obscura_port: int = 9222
    obscura_stealth: bool = False
    obscura_allow_private_network: bool = False

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.browser_type not in _VALID_BROWSER_TYPES:
            raise ValueError(
                f"Invalid browser_type '{self.browser_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_BROWSER_TYPES))}"
            )
        if self.engine not in _VALID_ENGINES:
            raise ValueError(
                f"Invalid engine '{self.engine}'. "
                f"Must be one of: {', '.join(sorted(_VALID_ENGINES))}"
            )
        if not (0 < self.obscura_port < 65536):
            raise ValueError(
                f"obscura_port out of range: {self.obscura_port}"
            )
        if self.engine == "obscura" and self.browser_type != "chromium":
            # Obscura only speaks CDP as a Chromium-compatible engine.
            # DriverFactory/DriverRegistry already force this — this is
            # a defense-in-depth check for direct PlaywrightConfig
            # construction that bypasses both.
            raise ValueError(
                "engine='obscura' requires browser_type='chromium' "
                f"(got {self.browser_type!r})"
            )
