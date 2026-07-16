---
type: Wiki Entity
title: AbstractDriver
id: class:parrot_tools.scraping.drivers.abstract.AbstractDriver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified interface for browser automation drivers.
---

# AbstractDriver

Defined in [`parrot_tools.scraping.drivers.abstract`](../summaries/mod:parrot_tools.scraping.drivers.abstract.md).

```python
class AbstractDriver(ABC)
```

Unified interface for browser automation drivers.

All driver-specific capabilities are exposed through this interface.
Concrete drivers implement the abstract methods for their backend.
Methods not supported by a driver raise ``NotImplementedError`` with
a clear message indicating which driver does support the feature.

Method groups:
    - **Lifecycle**: start / quit
    - **Navigation**: navigate, go_back, go_forward, reload
    - **DOM interaction**: click, fill, select_option, hover, press_key
    - **Content extraction**: get_page_source, get_text, get_attribute,
      get_all_texts, screenshot
    - **Waiting**: wait_for_selector, wait_for_navigation,
      wait_for_load_state
    - **Media / Scripts**: execute_script, evaluate
    - **Property**: current_url
    - **Extended** (non-abstract, Playwright-only by default):
      intercept_requests, record_har, save_pdf, start_tracing,
      stop_tracing, mock_route

## Methods

- `async def start(self) -> None` — Initialize the browser and create a default page/tab.
- `async def quit(self) -> None` — Close the browser and release all resources.
- `async def navigate(self, url: str, timeout: int=30) -> None` — Navigate to *url*.
- `async def go_back(self) -> None` — Navigate back in history.
- `async def go_forward(self) -> None` — Navigate forward in history.
- `async def reload(self) -> None` — Reload the current page.
- `async def click(self, selector: str, timeout: int=10) -> None` — Click the element matching *selector*.
- `async def fill(self, selector: str, value: str, timeout: int=10) -> None` — Clear and fill the input matching *selector* with *value*.
- `async def select_option(self, selector: str, value: str, *, by: Literal['value', 'text', 'index']='value', timeout: int=10) -> None` — Select an option in a ``<select>`` element.
- `async def hover(self, selector: str, timeout: int=10) -> None` — Hover over the element matching *selector*.
- `async def press_key(self, key: str) -> None` — Press a keyboard key.
- `async def get_page_source(self) -> str` — Return the full HTML source of the current page.
- `async def get_text(self, selector: str, timeout: int=10) -> str` — Return the inner text of the element matching *selector*.
- `async def get_attribute(self, selector: str, attribute: str, timeout: int=10) -> Optional[str]` — Return the value of *attribute* on the element matching *selector*.
- `async def get_all_texts(self, selector: str, timeout: int=10) -> List[str]` — Return the inner text of every element matching *selector*.
- `async def screenshot(self, path: str, full_page: bool=False) -> bytes` — Take a screenshot of the current page.
- `async def wait_for_selector(self, selector: str, timeout: int=10, state: str='visible') -> None` — Wait until an element matching *selector* reaches *state*.
- `async def wait_for_navigation(self, timeout: int=30) -> None` — Wait for a navigation event to complete.
- `async def wait_for_load_state(self, state: str='load', timeout: int=30) -> None` — Wait until the page reaches the given load *state*.
- `async def execute_script(self, script: str, *args: Any) -> Any` — Execute JavaScript in the page context.
- `async def evaluate(self, expression: str) -> Any` — Evaluate a JavaScript expression and return the result.
- `def current_url(self) -> str` — The URL of the current page.
- `async def intercept_requests(self, handler: Callable) -> None` — Set up a request interception handler.
- `async def record_har(self, path: str) -> None` — Start recording a HAR file.
- `async def save_pdf(self, path: str) -> bytes` — Save the current page as a PDF.
- `async def start_tracing(self, name: str='trace', screenshots: bool=True, snapshots: bool=True) -> None` — Start tracing browser activity.
- `async def stop_tracing(self, path: str) -> None` — Stop tracing and save to *path*.
- `async def mock_route(self, url_pattern: str, handler: Callable) -> None` — Mock network requests matching *url_pattern*.
