---
type: Wiki Entity
title: PageDriver
id: class:parrot_tools.scraping.drivers.page_driver.PageDriver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Adapt a live Playwright ``Page`` to the :class:`AbstractDriver` interface.
relates_to:
- concept: class:parrot_tools.scraping.drivers.abstract.AbstractDriver
  rel: extends
---

# PageDriver

Defined in [`parrot_tools.scraping.drivers.page_driver`](../summaries/mod:parrot_tools.scraping.drivers.page_driver.md).

```python
class PageDriver(AbstractDriver)
```

Adapt a live Playwright ``Page`` to the :class:`AbstractDriver` interface.

Args:
    page: A live Playwright ``Page`` (already created within a
        ``BrowserContext``).

## Methods

- `async def start(self) -> None` — No-op: the page is already alive when handed to this adapter.
- `async def quit(self) -> None` — Close the wrapped page (not the context or browser).
- `async def navigate(self, url: str, timeout: int=30) -> None` — Navigate to *url*.
- `async def go_back(self) -> None` — Navigate back in history.
- `async def go_forward(self) -> None` — Navigate forward in history.
- `async def reload(self) -> None` — Reload the current page.
- `async def click(self, selector: str, timeout: int=10) -> None` — Click the element matching *selector*.
- `async def fill(self, selector: str, value: str, timeout: int=10) -> None` — Fill the input matching *selector* with *value*.
- `async def select_option(self, selector: str, value: str, *, by: str='value', timeout: int=10) -> None` — Select an option in a ``<select>`` element.
- `async def hover(self, selector: str, timeout: int=10) -> None` — Hover over the element matching *selector*.
- `async def press_key(self, key: str) -> None` — Press a keyboard key.
- `async def get_page_source(self) -> str` — Return the full HTML of the current page.
- `async def get_text(self, selector: str, timeout: int=10) -> str` — Return the inner text of the first matching element.
- `async def get_attribute(self, selector: str, attribute: str, timeout: int=10) -> Optional[str]` — Return the value of *attribute* on the matching element.
- `async def get_all_texts(self, selector: str, timeout: int=10) -> List[str]` — Return the inner text of every matching element.
- `async def screenshot(self, path: str, full_page: bool=False) -> bytes` — Take a screenshot and save it to *path*.
- `async def wait_for_selector(self, selector: str, timeout: int=10, state: str='visible') -> None` — Wait until *selector* reaches *state*.
- `async def wait_for_navigation(self, timeout: int=30) -> None` — Wait for navigation/network to settle.
- `async def wait_for_load_state(self, state: str='load', timeout: int=30) -> None` — Wait until the page reaches the given load *state*.
- `async def execute_script(self, script: str, *args: Any) -> Any` — Execute JavaScript with arguments in the page context.
- `async def evaluate(self, expression: str) -> Any` — Evaluate a JavaScript expression and return the result.
- `def current_url(self) -> str` — The URL of the wrapped page.
