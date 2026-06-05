"""
ComputerAgent — Agent subclass for vision-based browser automation (FEAT-227).

Configured for Google Gemini computer-use models. Composes
ComputerInteractionToolkit + optional WebScrapingToolkit. Manages
screenshot memory pruning and safety decision handling.
"""
from __future__ import annotations

import logging
from typing import List, Literal, Optional

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
        **kwargs,
    ) -> None:
        self._computer_toolkit = ComputerInteractionToolkit(
            viewport=viewport,
            headless=headless,
            initial_url=initial_url,
        )
        self._include_scraping = include_scraping
        self._safety_mode = safety_mode
        self._max_screenshot_turns = max_screenshot_turns
        super().__init__(
            agent_id=self.agent_id,
            llm=model,
            **kwargs,
        )

    def agent_tools(self) -> List[AbstractTool]:
        """Return the tools available to the ComputerAgent.

        Always includes all tools from ComputerInteractionToolkit.
        When ``include_scraping=True``, also adds WebScrapingToolkit tools
        for hybrid selector-based extraction.

        Returns:
            List of AbstractTool instances.
        """
        tools: List[AbstractTool] = self._computer_toolkit.get_tools()
        if self._include_scraping:
            try:
                from parrot_tools.scraping.toolkit import WebScrapingToolkit
                scraping = WebScrapingToolkit(driver_type="playwright", headless=True)
                tools.extend(scraping.get_tools())
                logger.info("ComputerAgent: WebScrapingToolkit tools added (%d tools)", len(tools))
            except Exception as exc:
                logger.warning("ComputerAgent: could not load WebScrapingToolkit: %s", exc)
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
        In ``"interactive"`` mode, emits a ``"safety_decision"`` event so
        an external handler can decide whether to proceed.

        Args:
            decision: A dict describing the safety decision from the model.

        Returns:
            True to proceed, False to abort (only in interactive mode; auto
            always returns True).
        """
        if self._safety_mode == "auto":
            logger.warning(
                "ComputerAgent safety decision (auto-acknowledged): %s", decision
            )
            return True
        else:
            # Interactive mode: emit event and let external handler decide.
            try:
                self.emit("safety_decision", decision)
            except Exception as exc:
                logger.warning("ComputerAgent: could not emit safety_decision: %s", exc)
            logger.info("ComputerAgent safety decision emitted (interactive mode): %s", decision)
            return True  # Default to proceeding; external handler can override
