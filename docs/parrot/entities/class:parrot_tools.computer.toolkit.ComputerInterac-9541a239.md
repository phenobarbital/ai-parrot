---
type: Wiki Entity
title: ComputerInteractionToolkit
id: class:parrot_tools.computer.toolkit.ComputerInteractionToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: AbstractToolkit for vision-based browser automation via computer-use.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ComputerInteractionToolkit

Defined in [`parrot_tools.computer.toolkit`](../summaries/mod:parrot_tools.computer.toolkit.md).

```python
class ComputerInteractionToolkit(AbstractToolkit)
```

AbstractToolkit for vision-based browser automation via computer-use.

Exposes all 13 Gemini computer-use predefined actions plus screenshot,
recording, tracing, HAR, PDF, and task/loop execution as LLM-callable
tools. Actions accept 0-1000 normalized coordinates and denormalize them
to viewport pixels internally.

The browser is lazily started on the first tool call via ``_pre_execute``.

Args:
    viewport: Browser viewport as ``(width, height)`` in pixels.
    headless: Whether to run the browser in headless mode.
    browser_type: Playwright browser engine.
    initial_url: URL to open when the browser first starts.
    search_engine_url: URL navigated to by the ``computer_search`` action.
    **kwargs: Forwarded to AbstractToolkit.

## Methods

- `async def click_at(self, x: int, y: int) -> dict` — Click at normalized coordinates (x, y) on the page.
- `async def hover_at(self, x: int, y: int) -> dict` — Move the mouse to normalized coordinates (x, y) without clicking.
- `async def type_text_at(self, x: int, y: int, text: str, press_enter: bool=False, clear_before_typing: bool=True) -> dict` — Click at (x, y) and type text into the element.
- `async def scroll_document(self, direction: str) -> dict` — Scroll the entire document up or down.
- `async def scroll_at(self, x: int, y: int, direction: str, magnitude: int=800) -> dict` — Scroll at a specific position on the page.
- `async def wait(self, seconds: int=5) -> dict` — Wait for a number of seconds without interacting with the page.
- `async def go_back(self) -> dict` — Navigate to the previous page in the browser history.
- `async def go_forward(self) -> dict` — Navigate to the next page in the browser history.
- `async def search(self) -> dict` — Navigate to the configured search engine URL.
- `async def navigate(self, url: str) -> dict` — Navigate to an absolute URL.
- `async def key_combination(self, keys: str) -> dict` — Press a key combination.
- `async def drag_and_drop(self, x: int, y: int, destination_x: int, destination_y: int) -> dict` — Drag from (x, y) to (destination_x, destination_y).
- `async def open_browser(self) -> dict` — Navigate to the initial URL (open a fresh browser session).
- `async def screenshot(self, full_page: bool=False) -> dict` — Capture a screenshot of the current viewport.
- `async def screenshot_element(self, selector: str) -> dict` — Capture a screenshot of a specific element.
- `async def start_recording(self, output_dir: str='./recordings') -> dict` — Start video recording of the browser session.
- `async def stop_recording(self) -> dict` — Stop video recording and return the path to the video file.
- `async def start_tracing(self, screenshots: bool=True) -> dict` — Start Playwright tracing (includes screenshots and DOM snapshots).
- `async def stop_tracing(self, output_path: str) -> dict` — Stop tracing and save the trace archive to the given path.
- `async def record_har(self, output_path: str) -> dict` — Begin recording a HAR (HTTP Archive) of all network requests.
- `async def save_pdf(self, output_path: str) -> dict` — Export the current page as a PDF.
- `async def define_task(self, name: str, description: str, steps: list[str]) -> dict` — Define a reusable task consisting of natural-language steps.
- `async def run_task(self, task: str, params: Optional[dict]=None) -> dict` — Return a structured plan of steps for the agent to execute.
- `async def run_loop(self, task: str, iterations: Optional[int]=None, until: Optional[str]=None, params_list: Optional[list[dict]]=None, max_iterations: int=100, collect_results: bool=True) -> dict` — Execute a task repeatedly in a loop.
- `async def abort_loop(self) -> dict` — Abort a currently running loop.
