"""Terminal helpers for interactive CLI prompts."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def restore_stdin_blocking() -> Iterator[None]:
    """Put stdin back in blocking mode when the wrapped prompt finishes.

    parrot imports install uvloop's event-loop policy, so questionary/prompt_toolkit
    prompts run on libuv, which sets ``O_NONBLOCK`` on fd 0 and never clears it.
    The flag lives on the shared open file description: a later ``input()`` or
    ``click.confirm()`` reads EOF and aborts, and the parent shell inherits the
    non-blocking tty once the process exits. Wrap every questionary ``ask()`` /
    ``ask_async()`` with this context manager.

    Yields:
        None.
    """
    try:
        yield
    finally:
        try:
            os.set_blocking(sys.stdin.fileno(), True)
        except (AttributeError, OSError, ValueError):
            # stdin replaced by a non-file object (pytest capture) or closed.
            pass
