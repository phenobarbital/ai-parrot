"""
ComputerAgent — Agent subclass for vision-based browser automation (FEAT-227).

Configured for Google Gemini computer-use models. Composes
ComputerInteractionToolkit + optional WebScrapingToolkit. Manages
screenshot memory pruning and safety decision handling.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Literal, Optional

from parrot.bots.agent import Agent
from parrot.registry import register_agent
from parrot.tools.abstract import AbstractTool

from parrot_tools.computer.toolkit import ComputerInteractionToolkit

logger = logging.getLogger(__name__)


@register_agent(name="computer_agent", at_startup=False)
class ComputerAgent(Agent):
    """Agent configured for vision-based browser automation via computer-use.

    Uses a Google Gemini computer-use model (default:
    ``gemini-2.5-computer-use-preview-10-2025``). Composes
    :class:`ComputerInteractionToolkit` for all 13 predefined browser
    actions plus screenshot, recording, and loop execution. Optionally
    composes :class:`~parrot_tools.scraping.toolkit.WebScrapingToolkit`
    for hybrid selector-based extraction workflows.

    Features:
    - Lazy browser start via ``_pre_execute`` in the toolkit.
    - Screenshot memory pruning: conversation history is pruned to keep
      only the last ``max_screenshot_turns`` turns that contain screenshots.
    - Safety mode:
      ``"auto"`` — log and auto-acknowledge safety decisions.
      ``"interactive"`` — emit an event for external handling.

    Args:
        model: Gemini computer-use model identifier.
        viewport: Browser viewport as ``(width, height)`` in pixels.
        headless: Whether to run the browser in headless mode.
        initial_url: URL to open when the browser first starts.
        safety_mode: ``"auto"`` or ``"interactive"``.
        max_screenshot_turns: Number of turns whose screenshots to retain in
            the conversation history.
        include_scraping: If True, include WebScrapingToolkit tools.
        **kwargs: Forwarded to Agent.
    """

    agent_id: str = "computer_agent"

    def __init__(
        self,
        *,
        model: str = "gemini-2.5-computer-use-preview-10-2025",
        viewport: tuple[int, int] = (1280, 720),
        headless: bool = True,
        initial_url: str = "https://www.google.com",
        safety_mode: Literal["auto", "interactive"] = "auto",
        max_screenshot_turns: int = 3,
        include_scraping: bool = False,
        safety_callback: Optional[Callable[..., Any]] = None,
        **kwargs: Any,
    ) -> None:
        self._computer_toolkit = ComputerInteractionToolkit(
            viewport=viewport,
            headless=headless,
            initial_url=initial_url,
        )
        self._include_scraping = include_scraping
        self._safety_mode = safety_mode
        self._max_screenshot_turns = max_screenshot_turns
        self._safety_callback = safety_callback
        # Cache WebScrapingToolkit at init time to avoid re-instantiation on
        # every agent_tools() call. Import failure is caught here.
        self._scraping_toolkit = None
        if include_scraping:
            try:
                from parrot_tools.scraping.toolkit import WebScrapingToolkit
                self._scraping_toolkit = WebScrapingToolkit(
                    driver_type="playwright", headless=True
                )
            except ImportError as exc:
                logger.warning(
                    "ComputerAgent: WebScrapingToolkit not available (ImportError): %s", exc
                )
            except Exception as exc:
                logger.warning(
                    "ComputerAgent: could not initialize WebScrapingToolkit: %s", exc
                )
        super().__init__(
            agent_id=self.agent_id,
            llm=model,
            **kwargs,
        )

    def agent_tools(self) -> List[AbstractTool]:
        """Return the tools available to the ComputerAgent.

        Always includes all tools from ComputerInteractionToolkit.
        When ``include_scraping=True``, also adds the cached
        :class:`~parrot_tools.scraping.toolkit.WebScrapingToolkit` tools for
        hybrid selector-based extraction.

        Returns:
            List of AbstractTool instances.
        """
        tools: List[AbstractTool] = self._computer_toolkit.get_tools()
        if self._include_scraping and self._scraping_toolkit is not None:
            scraping_tools = self._scraping_toolkit.get_tools()
            tools.extend(scraping_tools)
            logger.info(
                "ComputerAgent: WebScrapingToolkit tools added (%d scraping, %d total)",
                len(scraping_tools),
                len(tools),
            )
        return tools

    def prune_screenshots(self, history: list) -> list:
        """Remove old screenshots from conversation history.

        Walks history backwards, keeps screenshots in the last
        ``max_screenshot_turns`` turns, strips screenshot data from older
        turns to prevent context-window bloat (~100-500KB per PNG).

        Args:
            history: List of conversation turn dicts (arbitrary structure).

        Returns:
            Pruned history list.
        """
        if not history:
            return history

        screenshot_turn_count = 0
        result = []
        for turn in reversed(history):
            if self._has_screenshot(turn):
                screenshot_turn_count += 1
                if screenshot_turn_count > self._max_screenshot_turns:
                    # Strip screenshot data from this turn
                    turn = self._strip_screenshots(turn)
            result.insert(0, turn)
        return result

    def _has_screenshot(self, turn: dict) -> bool:
        """Check whether a conversation turn contains screenshot data.

        Args:
            turn: A conversation turn dict.

        Returns:
            True if the turn contains any screenshot bytes.
        """
        if not isinstance(turn, dict):
            return False
        images = turn.get("images") or turn.get("screenshot_bytes")
        return bool(images)

    def _strip_screenshots(self, turn: dict) -> dict:
        """Remove screenshot data from a conversation turn.

        Creates a shallow copy and removes image fields.

        Args:
            turn: A conversation turn dict.

        Returns:
            Copy of the turn without screenshot data.
        """
        stripped = dict(turn)
        stripped.pop("images", None)
        stripped.pop("screenshot_bytes", None)
        return stripped

    def handle_safety_decision(self, decision: dict) -> bool:
        """Process a safety decision from the model.

        In ``"auto"`` mode, logs the decision and returns True (proceed).

        In ``"interactive"`` mode, emits a ``"safety_decision"`` event and
        then invokes ``self._safety_callback(decision)`` if one was provided at
        construction time — returning its boolean result. When no callback is
        set, defaults to True and logs a warning. Pass ``safety_callback=`` to
        the constructor to get real abort behaviour in interactive mode.

        Args:
            decision: A dict describing the safety decision from the model.

        Returns:
            True to proceed, False to abort. ``"auto"`` mode always returns
            True. ``"interactive"`` mode returns the callback's result, or True
            when no callback is configured.
        """
        if self._safety_mode == "auto":
            logger.warning(
                "ComputerAgent safety decision (auto-acknowledged): %s", decision
            )
            return True
        else:
            # Interactive mode: emit event for any listeners.
            try:
                self.emit("safety_decision", decision)
            except Exception as exc:
                logger.warning("ComputerAgent: could not emit safety_decision: %s", exc)
            # Invoke the injected callback if available.
            if self._safety_callback is not None:
                try:
                    result = self._safety_callback(decision)
                    logger.info(
                        "ComputerAgent safety decision (interactive, callback=%s): %s",
                        result,
                        decision,
                    )
                    return bool(result)
                except Exception as exc:
                    logger.warning(
                        "ComputerAgent: safety_callback raised, defaulting to proceed: %s",
                        exc,
                    )
            # No callback configured — default to proceeding with a clear warning.
            logger.warning(
                "ComputerAgent safety decision (interactive mode, no callback set — "
                "defaulting to proceed): %s",
                decision,
            )
            return True
