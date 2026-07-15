---
type: Wiki Entity
title: PlaywrightDriver
id: class:parrot_tools.scraping.drivers.playwright_driver.PlaywrightDriver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Playwright-based browser automation driver.
relates_to:
- concept: class:parrot_tools.scraping.drivers.abstract.AbstractDriver
  rel: extends
---

# PlaywrightDriver

Defined in [`parrot_tools.scraping.drivers.playwright_driver`](../summaries/mod:parrot_tools.scraping.drivers.playwright_driver.md).

```python
class PlaywrightDriver(AbstractDriver)
```

Playwright-based browser automation driver.

Implements the full ``AbstractDriver`` interface using Playwright's async
API, plus Playwright-exclusive capabilities (HAR, tracing, PDF,
interception, session persistence).

The ``playwright`` package is imported lazily inside :meth:`start` so the
module can be loaded even when Playwright is not installed.

Args:
    config: Browser and context configuration.  Defaults to
        ``PlaywrightConfig()`` (headless Chromium).

## Methods

- `async def start(self) -> None` — Launch browser and create a default context + page.
- `async def quit(self) -> None` — Close browser and release resources.
- `async def navigate(self, url: str, timeout: int=30) -> None` — Navigate to *url*.
- `async def go_back(self) -> None` — Navigate back.
- `async def go_forward(self) -> None` — Navigate forward.
- `async def reload(self) -> None` — Reload the current page.
- `async def click(self, selector: str, timeout: int=10) -> None` — Click element matching *selector*.
- `async def fill(self, selector: str, value: str, timeout: int=10) -> None` — Fill input matching *selector* with *value*.
- `async def select_option(self, selector: str, value: str, *, by: str='value', timeout: int=10) -> None` — Select an option in a ``<select>`` element.
- `async def hover(self, selector: str, timeout: int=10) -> None` — Hover over element matching *selector*.
- `async def press_key(self, key: str) -> None` — Press a keyboard key.
- `async def get_page_source(self) -> str` — Return the full HTML of the current page.
- `async def get_text(self, selector: str, timeout: int=10) -> str` — Return the inner text of the first matching element.
- `async def get_attribute(self, selector: str, attribute: str, timeout: int=10) -> Optional[str]` — Return the value of *attribute* on the matching element.
- `async def get_all_texts(self, selector: str, timeout: int=10) -> List[str]` — Return inner text of every matching element.
- `async def screenshot(self, path: str, full_page: bool=False) -> bytes` — Take a screenshot and save to *path*.
- `async def wait_for_selector(self, selector: str, timeout: int=10, state: str='visible') -> None` — Wait for *selector* to reach *state*.
- `async def wait_for_navigation(self, timeout: int=30) -> None` — Wait for a navigation event to complete.
- `async def wait_for_load_state(self, state: str='load', timeout: int=30) -> None` — Wait until the page reaches the given load *state*.
- `async def execute_script(self, script: str, *args: Any) -> Any` — Execute JavaScript with arguments in the page context.
- `async def evaluate(self, expression: str) -> Any` — Evaluate a JavaScript expression and return the result.
- `def current_url(self) -> str` — The URL of the current page.
- `async def intercept_requests(self, handler: Callable) -> None` — Register a request interception handler on all routes.
- `async def intercept_by_resource_type(self, resource_types: List[str], action: str='abort') -> None` — Block or modify requests by resource type.
- `async def mock_route(self, url_pattern: str, handler: Callable) -> None` — Mock network requests matching *url_pattern*.
- `async def record_har(self, path: str) -> None` — Log a note about HAR recording.
- `async def save_pdf(self, path: str) -> bytes` — Export the current page as a PDF (Chromium only).
- `async def start_tracing(self, name: str='trace', screenshots: bool=True, snapshots: bool=True) -> None` — Start Playwright tracing.
- `async def stop_tracing(self, path: str) -> None` — Stop tracing and save the trace archive to *path*.
- `async def save_storage_state(self, path: str) -> None` — Persist cookies and localStorage to a JSON file.
- `async def new_page(self) -> Any` — Open a new tab within the same browser context.
- `async def get_network_responses(self) -> List[Dict[str, Any]]` — Return captured network responses.
