"""Matrix streaming handler — edit-based token streaming.

Uses Matrix's m.replace (message edit) relation to simulate
streaming output by progressively updating a single message
as the LLM generates tokens. The result is visible in any
Matrix client (Element, etc.) and persists in room history.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from navconfig.logging import logging

from .client import MatrixClientWrapper


class MatrixStreamHandler:
    """Handles streaming LLM output to a Matrix room via message edits.

    Usage::

        handler = MatrixStreamHandler(wrapper, room_id)
        event_id = await handler.begin_stream("Thinking...")

        async for token in llm_stream:
            await handler.send_token(event_id, token)

        await handler.end_stream(event_id, final_text)
    """

    def __init__(
        self,
        wrapper: MatrixClientWrapper,
        room_id: str,
        *,
        min_edit_interval_ms: int = 500,
        min_chars_delta: int = 50,
    ) -> None:
        """Initialize the stream handler.

        Args:
            wrapper: Connected MatrixClientWrapper.
            room_id: Target room for streaming.
            min_edit_interval_ms: Minimum milliseconds between edits.
            min_chars_delta: Minimum character change before sending edit.
        """
        self._wrapper = wrapper
        self._room_id = room_id
        self._min_interval = min_edit_interval_ms / 1000.0
        self._min_chars = min_chars_delta
        self._accumulated = ""
        self._last_edit_time: float = 0.0
        self._last_edit_len: int = 0
        self._pending_edit: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("parrot.matrix.streaming")

    async def begin_stream(self, initial_text: str = "▌") -> str:
        """Send the initial message and return its event_id.

        Args:
            initial_text: Initial placeholder text (e.g., cursor).

        Returns:
            The event_id to use for subsequent edits.
        """
        self._accumulated = initial_text
        self._last_edit_time = time.monotonic()
        self._last_edit_len = len(initial_text)
        event_id = await self._wrapper.send_text(
            self._room_id, initial_text
        )
        self.logger.debug(
            f"Stream started in {self._room_id}: {event_id}"
        )
        return event_id

    async def send_token(self, event_id: str, token: str) -> None:
        """Accumulate a token and edit the message if thresholds are met.

        Args:
            event_id: The original message event_id.
            token: New token to append.
        """
        self._accumulated += token

        now = time.monotonic()
        time_delta = now - self._last_edit_time
        chars_delta = len(self._accumulated) - self._last_edit_len

        if (
            time_delta >= self._min_interval
            and chars_delta >= self._min_chars
        ):
            await self._do_edit(event_id)

    async def end_stream(
        self,
        event_id: str,
        final_text: Optional[str] = None,
    ) -> None:
        """Finalize the stream with the complete response.

        Args:
            event_id: The original message event_id.
            final_text: Final complete text (uses accumulated if None).
        """
        # Cancel any pending edit
        if self._pending_edit and not self._pending_edit.done():
            self._pending_edit.cancel()
            try:
                await self._pending_edit
            except asyncio.CancelledError:
                pass

        text = final_text if final_text is not None else self._accumulated
        await self._wrapper.edit_message(
            self._room_id, event_id, text
        )
        self.logger.debug(
            f"Stream finished in {self._room_id}: "
            f"{len(text)} chars"
        )

        # Reset state
        self._accumulated = ""
        self._last_edit_time = 0.0
        self._last_edit_len = 0

    async def _do_edit(self, event_id: str) -> None:
        """Perform the actual message edit."""
        try:
            # Append cursor indicator while still streaming
            display = self._accumulated + " ▌"
            await self._wrapper.edit_message(
                self._room_id, event_id, display
            )
            self._last_edit_time = time.monotonic()
            self._last_edit_len = len(self._accumulated)
        except Exception as exc:
            self.logger.warning(
                f"Stream edit failed: {exc}"
            )
