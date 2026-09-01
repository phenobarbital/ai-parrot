"""Quiet the HTTP transport stacks the LLM SDKs log through.

``httpx`` and ``httpcore`` trace every phase of every request at DEBUG::

    [DEBUG] httpcore2.http11(_trace.py:85) :: send_request_headers.complete
    [DEBUG] httpcore2.http11(_trace.py:85) :: receive_response_body.started

For a caller of an AI-Parrot client this is pure noise — one LLM call
produces a dozen of these lines and none of them carries information the
client's own logging does not already report.

**Why the logger names are not just ``httpx``/``httpcore``**: the 2.x line of
that stack ships under *different top-level names* — ``httpx2`` and
``httpcore2`` — and can be installed side by side with 1.x. In this workspace
``openai`` requires ``httpx2<3,>=2.7.0`` while ``anthropic`` and ``groq``
still require ``httpx<1``, so BOTH stacks are live in one process. That is
why the long-standing ``logging.getLogger("httpcore").setLevel(WARNING)``
lines around the codebase never silenced the OpenAI-protocol clients — and
those include :class:`~parrot.clients.nova.mantle.BedrockMantleClient`, which
reaches AWS Bedrock over Bedrock Mantle's OpenAI-compatible endpoint via the
OpenAI SDK. Its transport logs as ``httpcore2``, so the ``httpcore`` rule
missed it entirely.

Override via ``PARROT_HTTP_LOG_LEVEL`` (e.g. ``DEBUG`` to restore the full
wire trace while debugging a connection problem, or a numeric level).
"""

from __future__ import annotations

import logging
import os

from .log_levels import resolve_log_level

__all__ = ("HTTP_LOGGER_NAMES", "quiet_http_loggers")

#: Every HTTP transport logger family an LLM SDK in this workspace logs
#: through. Both the 1.x names and the separately-published 2.x names are
#: listed because both lines can be installed at once (see module docstring).
HTTP_LOGGER_NAMES: tuple[str, ...] = ("httpx", "httpcore", "httpx2", "httpcore2")

_ENV_VAR = "PARROT_HTTP_LOG_LEVEL"


def quiet_http_loggers(level: int | str | None = None) -> None:
    """Raise the httpx/httpcore logger families to WARNING. Idempotent.

    Setting a level on a logger by name works whether or not that logger (or
    the library behind it) exists yet — loggers are singletons created on
    first ``getLogger`` — so this is safe to call at import time, before the
    SDK that will do the logging has been imported, and safe to call again
    later to re-assert the level after an application reconfigures logging.

    Args:
        level: Explicit level (int or name) to apply. When ``None``, the
            ``PARROT_HTTP_LOG_LEVEL`` environment variable is consulted and
            WARNING is used if it is unset.
    """
    if level is None:
        resolved = resolve_log_level(os.environ.get(_ENV_VAR), logging.WARNING)
    elif isinstance(level, str):
        resolved = resolve_log_level(level, logging.WARNING)
    else:
        resolved = level
    for name in HTTP_LOGGER_NAMES:
        logging.getLogger(name).setLevel(resolved)
