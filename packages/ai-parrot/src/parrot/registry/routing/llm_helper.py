"""Shared LLM-route helper utilities (FEAT-111 Module 3).

Extracted from ``IntentRouterMixin._parse_invoke_response`` to be reused by
both the strategy-level router and the new store-level ``StoreRouter``.

Usage::

    from parrot.registry.routing import extract_json_from_response, run_llm_ranking

    raw_dict = extract_json_from_response(ai_message)
    result = await run_llm_ranking(bot.invoke, prompt, timeout_s=1.0)
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Any, Callable, Optional

_logger = logging.getLogger(__name__)


def extract_json_from_response(response: Any) -> Optional[dict]:
    """Extract the first JSON object from an LLM response.

    Supports:
    * Objects with a ``.output`` attribute (``AIMessage`` style).
    * Objects with a ``.content`` attribute.
    * Plain ``str`` — the first ``{...}`` block is extracted.
    * Plain ``dict`` — returned as-is.
    * Any other type / unparseable input → ``None``.

    Args:
        response: Raw response from ``invoke()`` or a test fixture.

    Returns:
        A parsed ``dict``, or ``None`` when parsing fails.
    """
    try:
        # Normalise to a raw value
        if isinstance(response, dict):
            return response

        raw: Any = None
        if hasattr(response, "output"):
            raw = response.output
        elif hasattr(response, "content"):
            raw = response.content
        else:
            raw = response

        if isinstance(raw, dict):
            return raw

        if not isinstance(raw, str):
            raw = str(raw) if raw is not None else None

        if raw is None:
            return None

        # Extract JSON block from string
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            return None

        return _json.loads(raw[start:end])

    except Exception:  # noqa: BLE001
        return None


async def run_llm_ranking(
    invoke_fn: Callable,
    prompt: str,
    timeout_s: float,
) -> Optional[dict]:
    """Call *invoke_fn* with *prompt*, apply a timeout, and parse JSON output.

    On timeout, exception, or un-parseable output the function logs a WARNING
    and returns ``None``.  It **never** raises.

    Args:
        invoke_fn: An async callable that accepts a ``str`` prompt and returns
            an ``AIMessage``-like object.
        prompt: The prompt to pass to the LLM.
        timeout_s: Maximum seconds to wait for the LLM response.

    Returns:
        Parsed ``dict`` from the LLM response, or ``None`` on failure.
    """
    try:
        raw = await asyncio.wait_for(invoke_fn(prompt), timeout=timeout_s)
        result = extract_json_from_response(raw)
        if result is None:
            _logger.warning("LLM ranking produced an unparseable response")
        return result
    except asyncio.TimeoutError:
        _logger.warning(
            "LLM ranking timed out after %.2f seconds — falling back", timeout_s
        )
        return None
    except Exception as exc:  # noqa: BLE001
        _logger.warning("LLM ranking failed: %s", exc)
        return None
