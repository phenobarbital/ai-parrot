---
type: Wiki Entity
title: SeleniumDriver
id: class:parrot_tools.scraping.drivers.selenium_driver.SeleniumDriver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Selenium-based browser automation driver.
relates_to:
- concept: class:parrot_tools.scraping.drivers.abstract.AbstractDriver
  rel: extends
---

# SeleniumDriver

Defined in [`parrot_tools.scraping.drivers.selenium_driver`](../summaries/mod:parrot_tools.scraping.drivers.selenium_driver.md).

```python
class SeleniumDriver(AbstractDriver)
```

Selenium-based browser automation driver.

Wraps the existing ``SeleniumSetup`` class to implement the full
``AbstractDriver`` interface.  All blocking Selenium calls are run
via ``run_in_executor`` to avoid blocking the async event loop.

Extended capability methods (HAR, tracing, PDF, interception) are
**not** overridden — the base-class defaults raise
``NotImplementedError``.

Args:
    browser: Browser name (``"chrome"``, ``"firefox"``, ``"edge"``,
        ``"safari"``, ``"undetected"``).
    headless: Whether to run in headless mode.
    auto_install: Whether to auto-install the browser driver.
    mobile: Whether to emulate a mobile viewport.
    options: Additional keyword arguments forwarded to
        ``SeleniumSetup``.

## Methods

- `async def start(self) -> None` — Launch browser via ``SeleniumSetup`` and store the WebDriver.
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
