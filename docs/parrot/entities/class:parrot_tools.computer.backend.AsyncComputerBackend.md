---
type: Wiki Entity
title: AsyncComputerBackend
id: class:parrot_tools.computer.backend.AsyncComputerBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async Playwright wrapper implementing the computer-use action interface.
---

# AsyncComputerBackend

Defined in [`parrot_tools.computer.backend`](../summaries/mod:parrot_tools.computer.backend.md).

```python
class AsyncComputerBackend
```

Async Playwright wrapper implementing the computer-use action interface.

Manages browser lifecycle (start/stop), translates pixel-coordinate
actions into Playwright mouse/keyboard calls, and returns EnvState
(screenshot + URL) after each action.

Coordinate parameters accepted by action methods are ALREADY in pixel
units — the toolkit layer is responsible for denormalization.

Args:
    viewport: Browser viewport as ``(width, height)`` in pixels.
    headless: Whether to run the browser in headless mode.
    browser_type: Playwright browser engine — ``"chromium"``, ``"firefox"``
        or ``"webkit"``.
    initial_url: URL to navigate to when the browser first opens.
    search_engine_url: URL used by the ``search()`` action.

## Methods

- `async def start(self) -> None` — Launch the browser and navigate to the initial URL.
- `async def stop(self) -> None` — Close the browser and release all Playwright resources.
- `def current_url(self) -> str` — Return the current page URL, or empty string if browser not started.
- `def screen_size(self) -> tuple[int, int]` — Return the current viewport dimensions.
- `async def current_state(self) -> EnvState` — Capture the current page state (screenshot + URL).
- `async def screenshot(self, full_page: bool=False) -> bytes` — Capture a standalone screenshot without triggering state updates.
- `async def click_at(self, x: int, y: int) -> EnvState` — Click at pixel coordinates (x, y).
- `async def hover_at(self, x: int, y: int) -> EnvState` — Hover the mouse at pixel coordinates (x, y).
- `async def type_text_at(self, x: int, y: int, text: str, press_enter: bool=False, clear_before_typing: bool=True) -> EnvState` — Click at (x, y) and type text into the element.
- `async def scroll_document(self, direction: str) -> EnvState` — Scroll the entire document up or down.
- `async def scroll_at(self, x: int, y: int, direction: str, magnitude: int=800) -> EnvState` — Scroll at a specific pixel position.
- `async def wait_seconds(self, seconds: int=5) -> EnvState` — Wait for the specified number of seconds (capped at 60).
- `async def go_back(self) -> EnvState` — Navigate to the previous page in history.
- `async def go_forward(self) -> EnvState` — Navigate to the next page in history.
- `async def search(self) -> EnvState` — Navigate to the configured search engine URL.
- `async def navigate(self, url: str) -> EnvState` — Navigate to an absolute URL.
- `async def key_combination(self, keys: list[str]) -> EnvState` — Press a key combination (e.g. Ctrl+C).
- `async def drag_and_drop(self, x: int, y: int, dest_x: int, dest_y: int) -> EnvState` — Drag from (x, y) to (dest_x, dest_y).
- `async def open_web_browser(self) -> EnvState` — Open (or navigate to) the initial URL.
- `async def screenshot_element(self, selector: str) -> bytes` — Capture a screenshot of a specific element.
- `async def start_recording(self, output_dir: str='./recordings') -> None` — Start video recording.
- `async def stop_recording(self) -> Optional[str]` — Stop video recording and return the video file path.
- `async def start_tracing(self, screenshots: bool=True, snapshots: bool=True) -> None` — Start Playwright tracing.
- `async def stop_tracing(self, output_path: str) -> None` — Stop tracing and save the trace to the given path.
- `async def record_har(self, output_path: str) -> None` — Start recording network traffic to a HAR file.
- `async def save_pdf(self, output_path: str) -> bytes` — Export the current page as a PDF.
