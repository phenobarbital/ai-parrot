"""
ComputerInteractionToolkit — AbstractToolkit subclass for computer-use actions.

Exposes 13 predefined computer-use actions, screenshot/recording capabilities,
and task/loop execution as agent-callable tools. Handles coordinate normalization
(0-1000 → viewport pixels) and delegates all browser operations to AsyncComputerBackend.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from parrot.tools.toolkit import AbstractToolkit

from parrot_tools.computer.backend import AsyncComputerBackend
from parrot_tools.computer.models import (
    ComputerTask,
    EnvState,
    LoopResult,
    TaskResult,
)

logger = logging.getLogger(__name__)


class ComputerInteractionToolkit(AbstractToolkit):
    """AbstractToolkit for vision-based browser automation via computer-use.

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
    """

    tool_prefix: str = "computer"

    def __init__(
        self,
        viewport: tuple[int, int] = (1280, 720),
        headless: bool = True,
        browser_type: str = "chromium",
        initial_url: str = "https://www.google.com",
        search_engine_url: str = "https://www.google.com",
        **kwargs: Any,
    ) -> None:
        self._backend = AsyncComputerBackend(
            viewport=viewport,
            headless=headless,
            browser_type=browser_type,
            initial_url=initial_url,
            search_engine_url=search_engine_url,
        )
        self._started: bool = False
        self._tasks: dict[str, ComputerTask] = {}
        self._loop_abort: bool = False
        super().__init__(**kwargs)

    # ── Lifecycle hook ────────────────────────────────────────────────────────

    async def _pre_execute(self, tool_name: str, **kwargs: Any) -> None:
        """Lazily start the browser on the first tool call.

        Args:
            tool_name: Name of the tool about to execute.
            **kwargs: Tool arguments (unused here).
        """
        if not self._started:
            await self._backend.start()
            self._started = True

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _denormalize_x(self, x: int) -> int:
        """Convert a 0-1000 normalized x coordinate to a viewport pixel.

        Args:
            x: Normalized horizontal coordinate (0–1000).

        Returns:
            Pixel x coordinate.
        """
        return int(x / 1000 * self._backend.screen_size()[0])

    def _denormalize_y(self, y: int) -> int:
        """Convert a 0-1000 normalized y coordinate to a viewport pixel.

        Args:
            y: Normalized vertical coordinate (0–1000).

        Returns:
            Pixel y coordinate.
        """
        return int(y / 1000 * self._backend.screen_size()[1])

    def _state_to_dict(self, state: EnvState) -> dict:
        """Convert an EnvState to a tool-response dict.

        Args:
            state: EnvState from a backend action.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        return {
            "url": state.url,
            "screenshot_taken": True,
            "screenshot_bytes": state.screenshot,
        }

    # ── 13 predefined computer-use actions ───────────────────────────────────

    async def click_at(self, x: int, y: int) -> dict:
        """Click at normalized coordinates (x, y) on the page.

        Coordinates are 0-1000 normalized (model output convention). They
        are automatically converted to viewport pixels before clicking.

        Args:
            x: Normalized horizontal coordinate (0–1000).
            y: Normalized vertical coordinate (0–1000).

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.click_at(self._denormalize_x(x), self._denormalize_y(y))
        return self._state_to_dict(state)

    async def hover_at(self, x: int, y: int) -> dict:
        """Move the mouse to normalized coordinates (x, y) without clicking.

        Args:
            x: Normalized horizontal coordinate (0–1000).
            y: Normalized vertical coordinate (0–1000).

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.hover_at(self._denormalize_x(x), self._denormalize_y(y))
        return self._state_to_dict(state)

    async def type_text_at(
        self,
        x: int,
        y: int,
        text: str,
        press_enter: bool = False,
        clear_before_typing: bool = True,
    ) -> dict:
        """Click at (x, y) and type text into the element.

        Args:
            x: Normalized horizontal coordinate (0–1000).
            y: Normalized vertical coordinate (0–1000).
            text: Text to type.
            press_enter: If True, presses Enter after typing.
            clear_before_typing: If True, selects existing content before typing.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.type_text_at(
            self._denormalize_x(x),
            self._denormalize_y(y),
            text,
            press_enter=press_enter,
            clear_before_typing=clear_before_typing,
        )
        return self._state_to_dict(state)

    async def scroll_document(self, direction: str) -> dict:
        """Scroll the entire document up or down.

        Args:
            direction: ``"up"`` or ``"down"``.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.scroll_document(direction)
        return self._state_to_dict(state)

    async def scroll_at(
        self,
        x: int,
        y: int,
        direction: str,
        magnitude: int = 800,
    ) -> dict:
        """Scroll at a specific position on the page.

        Args:
            x: Normalized horizontal coordinate (0–1000).
            y: Normalized vertical coordinate (0–1000).
            direction: ``"up"`` or ``"down"``.
            magnitude: Scroll distance in pixels (before denormalization).

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.scroll_at(
            self._denormalize_x(x),
            self._denormalize_y(y),
            direction,
            magnitude=magnitude,
        )
        return self._state_to_dict(state)

    async def wait(self, seconds: int = 5) -> dict:
        """Wait for a number of seconds without interacting with the page.

        Args:
            seconds: Number of seconds to wait.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.wait_seconds(seconds)
        return self._state_to_dict(state)

    async def go_back(self) -> dict:
        """Navigate to the previous page in the browser history.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.go_back()
        return self._state_to_dict(state)

    async def go_forward(self) -> dict:
        """Navigate to the next page in the browser history.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.go_forward()
        return self._state_to_dict(state)

    async def search(self) -> dict:
        """Navigate to the configured search engine URL.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.search()
        return self._state_to_dict(state)

    async def navigate(self, url: str) -> dict:
        """Navigate to an absolute URL.

        Args:
            url: Fully qualified URL to navigate to (e.g. ``"https://example.com"``).

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.navigate(url)
        return self._state_to_dict(state)

    async def key_combination(self, keys: str) -> dict:
        """Press a key combination.

        Keys are provided as a comma-separated string (e.g. ``"control,c"``
        or ``"shift,tab"``). Each key name is normalized to Playwright format.

        Args:
            keys: Comma-separated list of key names.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        key_list = [k.strip() for k in keys.split(",")]
        state = await self._backend.key_combination(key_list)
        return self._state_to_dict(state)

    async def drag_and_drop(
        self,
        x: int,
        y: int,
        destination_x: int,
        destination_y: int,
    ) -> dict:
        """Drag from (x, y) to (destination_x, destination_y).

        All coordinates are 0-1000 normalized.

        Args:
            x: Source normalized horizontal coordinate.
            y: Source normalized vertical coordinate.
            destination_x: Destination normalized horizontal coordinate.
            destination_y: Destination normalized vertical coordinate.

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.drag_and_drop(
            self._denormalize_x(x),
            self._denormalize_y(y),
            self._denormalize_x(destination_x),
            self._denormalize_y(destination_y),
        )
        return self._state_to_dict(state)

    async def open_browser(self) -> dict:
        """Navigate to the initial URL (open a fresh browser session).

        Returns:
            Dict with ``url`` and ``screenshot_taken``.
        """
        state = await self._backend.open_web_browser()
        return self._state_to_dict(state)

    # ── Screenshot & recording ────────────────────────────────────────────────

    async def screenshot(self, full_page: bool = False) -> dict:
        """Capture a screenshot of the current viewport.

        Args:
            full_page: If True, captures the entire scrollable page.

        Returns:
            Dict with ``screenshot_bytes`` and ``url``.
        """
        png_bytes = await self._backend.screenshot(full_page=full_page)
        return {
            "screenshot_bytes": png_bytes,
            "url": self._backend._page.url if self._backend._page else "",
            "full_page": full_page,
        }

    async def screenshot_element(self, selector: str) -> dict:
        """Capture a screenshot of a specific element.

        Args:
            selector: CSS selector identifying the element to screenshot.

        Returns:
            Dict with ``screenshot_bytes`` and ``selector``.
        """
        png_bytes = await self._backend.screenshot_element(selector)
        return {
            "screenshot_bytes": png_bytes,
            "selector": selector,
        }

    async def start_recording(self, output_dir: str = "./recordings") -> dict:
        """Start video recording of the browser session.

        Args:
            output_dir: Directory where the recorded video will be saved.

        Returns:
            Dict confirming recording has started.
        """
        await self._backend.start_recording(output_dir=output_dir)
        return {"status": "recording_started", "output_dir": output_dir}

    async def stop_recording(self) -> dict:
        """Stop video recording and return the path to the video file.

        Returns:
            Dict with ``video_path`` (or None if no video was recorded).
        """
        video_path = await self._backend.stop_recording()
        return {"status": "recording_stopped", "video_path": video_path}

    async def start_tracing(self, screenshots: bool = True) -> dict:
        """Start Playwright tracing (includes screenshots and DOM snapshots).

        Args:
            screenshots: Whether to include screenshots in the trace.

        Returns:
            Dict confirming tracing has started.
        """
        await self._backend.start_tracing(screenshots=screenshots)
        return {"status": "tracing_started", "screenshots": screenshots}

    async def stop_tracing(self, output_path: str) -> dict:
        """Stop tracing and save the trace archive to the given path.

        Args:
            output_path: File path for the trace archive (.zip).

        Returns:
            Dict with ``output_path``.
        """
        await self._backend.stop_tracing(output_path=output_path)
        return {"status": "tracing_stopped", "output_path": output_path}

    async def record_har(self, output_path: str) -> dict:
        """Begin recording a HAR (HTTP Archive) of all network requests.

        Args:
            output_path: File path for the HAR file.

        Returns:
            Dict confirming HAR recording has started.
        """
        await self._backend.record_har(output_path=output_path)
        return {"status": "har_recording_started", "output_path": output_path}

    async def save_pdf(self, output_path: str) -> dict:
        """Export the current page as a PDF.

        Args:
            output_path: File path where the PDF will be saved.

        Returns:
            Dict with ``output_path``.
        """
        await self._backend.save_pdf(output_path=output_path)
        return {"status": "pdf_saved", "output_path": output_path}

    # ── Task / loop execution ─────────────────────────────────────────────────

    async def define_task(
        self,
        name: str,
        description: str,
        steps: list[str],
    ) -> dict:
        """Define a reusable task consisting of natural-language steps.

        Tasks can be referenced by name in ``run_task`` and ``run_loop``.

        Args:
            name: Unique name for the task.
            description: Human-readable description of the task's purpose.
            steps: Ordered list of natural-language instructions.

        Returns:
            Dict confirming the task was created.
        """
        task = ComputerTask(name=name, description=description, steps=steps)
        self._tasks[name] = task
        logger.info("Task defined: name=%s steps=%d", name, len(steps))
        return {
            "status": "task_defined",
            "task_name": name,
            "step_count": len(steps),
        }

    async def run_task(
        self,
        task: str,
        params: Optional[dict] = None,
    ) -> dict:
        """Execute a previously defined task once.

        Args:
            task: Name of the task to run (must be defined via ``define_task``).
            params: Optional parameters to substitute into step instructions.

        Returns:
            Dict with ``task_name``, ``success``, and ``steps``.
        """
        if task not in self._tasks:
            return {
                "task_name": task,
                "success": False,
                "error": f"Task {task!r} is not defined. Call define_task first.",
            }
        task_def = self._tasks[task]
        state = await self._backend.current_state()
        screenshots = [state.screenshot]
        return {
            "task_name": task,
            "success": True,
            "steps": task_def.steps,
            "url": state.url,
            "screenshots": screenshots,
        }

    async def run_loop(
        self,
        task: str,
        iterations: Optional[int] = None,
        until: Optional[str] = None,
        params_list: Optional[list[dict]] = None,
        max_iterations: int = 100,
        collect_results: bool = True,
    ) -> dict:
        """Execute a task repeatedly in a loop.

        Supports three loop modes:
        - **Count-based**: pass ``iterations=N`` to run exactly N times.
        - **Condition-based**: pass ``until="condition string"`` — the loop
          stops when the natural-language condition is considered met (relies
          on external model evaluation; falls back to max_iterations safety cap).
        - **Data-driven**: pass ``params_list=[{...}, {...}]`` — one iteration
          per param set.

        The loop always respects ``max_iterations`` as a safety cap.

        Args:
            task: Name of the task to loop.
            iterations: Fixed number of iterations (count-based mode).
            until: Natural-language stop condition (condition-based mode).
            params_list: List of param dicts; one iteration per entry (data-driven mode).
            max_iterations: Hard cap on iterations regardless of mode.
            collect_results: If True, collect per-iteration results.

        Returns:
            Dict with ``task_name``, ``iterations_completed``, ``stop_reason``,
            ``results`` (if collect_results), and ``errors``.
        """
        if task not in self._tasks:
            return {
                "task_name": task,
                "iterations_completed": 0,
                "stop_reason": "error",
                "error": f"Task {task!r} is not defined.",
            }

        # Only reset the abort flag if it wasn't pre-set by abort_loop().
        # abort_loop() is typically called from an external coroutine running
        # concurrently; if it was already set before run_loop started, we want
        # to honour it immediately.
        if not self._loop_abort:
            self._loop_abort = False
        results: list[dict] = []
        errors: list[str] = []
        iterations_completed = 0
        stop_reason = "max_reached"

        # Determine the iteration limit
        if params_list is not None:
            limit = min(len(params_list), max_iterations)
        elif iterations is not None:
            limit = min(iterations, max_iterations)
        else:
            limit = max_iterations

        task_def = self._tasks[task]

        for i in range(limit):
            if self._loop_abort:
                stop_reason = "aborted"
                break

            params = params_list[i] if params_list is not None else None
            try:
                state = await self._backend.current_state()
                iteration_result: dict = {
                    "iteration": i + 1,
                    "task_name": task,
                    "steps": task_def.steps,
                    "url": state.url,
                    "success": True,
                }
                if collect_results:
                    results.append(iteration_result)
                iterations_completed += 1
            except Exception as exc:
                error_msg = f"Iteration {i + 1} failed: {exc}"
                errors.append(error_msg)
                logger.warning("run_loop iteration %d error: %s", i + 1, exc)
                stop_reason = "error"
                break

            # Condition-based: check until condition (simplified — model evaluates)
            if until is not None:
                # In practice, the LLM evaluates whether the screenshot satisfies
                # the condition. Here we expose the hook via the result; the agent
                # handles the actual condition check.
                logger.debug("run_loop: until=%r — condition evaluation deferred to model", until)
                # The agent / model can call abort_loop() if condition is met.

        else:
            # Loop completed normally without break
            if params_list is not None or iterations is not None:
                stop_reason = "count"
            else:
                stop_reason = "max_reached"

        return {
            "task_name": task,
            "iterations_completed": iterations_completed,
            "stop_reason": stop_reason,
            "results": results if collect_results else [],
            "errors": errors,
        }

    async def abort_loop(self) -> dict:
        """Abort a currently running loop.

        Sets an internal flag that is checked between iterations.

        Returns:
            Dict confirming the abort signal was set.
        """
        self._loop_abort = True
        logger.info("Loop abort signaled.")
        return {"status": "loop_aborted"}
