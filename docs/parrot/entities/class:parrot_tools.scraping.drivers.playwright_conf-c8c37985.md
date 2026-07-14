---
type: Wiki Entity
title: PlaywrightConfig
id: class:parrot_tools.scraping.drivers.playwright_config.PlaywrightConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for PlaywrightDriver.
---

# PlaywrightConfig

Defined in [`parrot_tools.scraping.drivers.playwright_config`](../summaries/mod:parrot_tools.scraping.drivers.playwright_config.md).

```python
class PlaywrightConfig
```

Configuration for PlaywrightDriver.

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
