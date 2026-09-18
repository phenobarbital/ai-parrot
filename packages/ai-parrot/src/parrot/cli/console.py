"""Shared Rich console and the modal ``LiveRegion`` discipline for the Parrot CLI (FEAT-573 M1).

Extracts the pause/resume pattern proven in ``parrot.cli.devloop.renderer.RunView``
(devloop/renderer.py:82-107): exactly one writer owns the terminal at a time.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any, Iterator, Optional

from rich.console import Console  # verified: parrot/cli/renderer.py:13
from rich.live import Live  # verified: parrot/cli/devloop/renderer.py:15

_console: Optional[Console] = None
_console_lock = threading.Lock()


def get_console() -> Console:
    """Return the process-wide shared Rich Console (created on first call)."""
    global _console
    with _console_lock:
        if _console is None:
            _console = Console()
        return _console


def set_console(console: Optional[Console]) -> None:
    """Override (or clear, with ``None``) the shared console. Test seam."""
    global _console
    with _console_lock:
        _console = console


def reset_console() -> None:
    """Restore lazy creation on the next ``get_console()`` call."""
    set_console(None)


class LiveRegion:
    """Managed ``rich.live.Live`` area with 'one writer at a time' discipline.

    When ``console.is_terminal`` is False every ``update()`` prints the renderable once,
    sequentially, and ``modal()`` is a no-op — piping stays clean.
    """

    def __init__(
        self, console: Optional[Console] = None, *, refresh_per_second: int = 8, transient: bool = False
    ) -> None:
        self.console = console or get_console()
        self._refresh_per_second = refresh_per_second
        self._transient = transient
        self._live: Optional[Live] = None
        self._paused = False
        self._renderable: Any = ""
        self.logger = logging.getLogger(__name__)

    @property
    def is_terminal(self) -> bool:
        """``console.is_terminal`` of the bound console."""
        return bool(self.console.is_terminal)

    def start(self) -> None:
        """Start the Live display (idempotent; no-op on non-terminals)."""
        if not self.is_terminal:
            return
        if self._live is None:
            self._live = Live(
                self._renderable,
                console=self.console,
                refresh_per_second=self._refresh_per_second,
                transient=self._transient,
            )
            self._live.start()
            self._paused = False

    def stop(self) -> None:
        """Stop the Live display, leaving the last frame on screen (idempotent)."""
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._paused = False

    def pause(self) -> None:
        """``Live.stop()`` so another writer may own the terminal."""
        self._paused = True
        if self._live:
            self._live.stop()

    def resume(self) -> None:
        """``Live.start()`` after a pause; no-op if never started."""
        self._paused = False
        if self._live is not None:
            self._live.start()

    def update(self, renderable: Any) -> None:
        """Replace the region content (repainted on the next refresh tick)."""
        self._renderable = renderable
        if not self.is_terminal:
            self.console.print(renderable)
            return
        if self._live is not None and not self._paused:
            self._live.update(renderable)

    @contextlib.contextmanager
    def modal(self) -> Iterator[None]:
        """Pause for the duration of a prompt/modal interaction, then resume."""
        self.pause()
        try:
            yield
        finally:
            self.resume()
