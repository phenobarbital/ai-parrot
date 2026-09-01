"""Result size policy + per-call deadline (FEAT-477, Module 3, G7/G8).

Tool responses must stay under the ~30,000-token custom-connector ceiling,
**enforced by the adapter layer, not left to method authors** (spec §1
Goal G8). This module provides the two pieces of response shaping that
enforcement needs:

- :func:`resolve_cap` / :func:`apply_size_policy` — a per-tool result cap
  (``MCPToolDeclaration.max_result_tokens`` when set, else
  ``AgentMCPMountConfig.max_result_tokens``), truncating/paginating
  **deterministically** and stating so explicitly in the response (spec §2
  Edge Cases) so the model never silently reasons over a clipped list.
  ``exclude_none`` is applied throughout.
- :func:`run_with_deadline` — enforces ``call_deadline_seconds`` (the
  deadline part of goal G7): a blocking method yields a clean timeout
  error **naming the method**, never a bare ``TimeoutError`` traceback.

No token counter exists anywhere in ``parrot.mcp`` — :func:`_approx_tokens`
uses a documented character-count heuristic (``_CHARS_PER_TOKEN``), not a
real tokenizer.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger("Parrot.MCP.ResultPolicy")

T = TypeVar("T")

#: Documented approximation: no tokenizer exists in `parrot.mcp` today, so
#: the cap is enforced against a serialized-character-count heuristic
#: (~4 chars/token, a common rough English/JSON estimate). Deliberately
#: conservative-agnostic — the point is a deterministic, cheap bound, not
#: token-exact accounting.
_CHARS_PER_TOKEN: int = 4

#: Fallback cap when neither a per-tool nor a mount default is available.
DEFAULT_MAX_RESULT_TOKENS: int = 25_000


class MCPToolError(Exception):
    """Clean, message-only error surfaced to MCP clients.

    Raised instead of letting a lower-level exception (e.g.
    `asyncio.TimeoutError`) propagate as a raw traceback — the message
    alone is safe to surface in an MCP tool-result error.
    """


def _approx_tokens(serialized: str) -> int:
    """Approximate a token count from a serialized string.

    Args:
        serialized: The JSON-serialized (or plain) string to measure.

    Returns:
        `len(serialized) // _CHARS_PER_TOKEN`, floored at 1 for non-empty
        input — a documented heuristic, not a real tokenizer.
    """
    if not serialized:
        return 0
    return max(1, len(serialized) // _CHARS_PER_TOKEN)


def resolve_cap(declaration: Any, mount_config: Any) -> int:
    """Resolve the effective result cap: per-tool, else mount default.

    Args:
        declaration: The tool's `MCPToolDeclaration` (or any object/`None`
            exposing `max_result_tokens`). `None` or a `None`
            `max_result_tokens` falls through to `mount_config`.
        mount_config: The `AgentMCPMountConfig` (or any object/`None`
            exposing `max_result_tokens`).

    Returns:
        The per-tool cap when set, else the mount's cap, else
        `DEFAULT_MAX_RESULT_TOKENS`.
    """
    per_tool = getattr(declaration, "max_result_tokens", None)
    if per_tool is not None:
        return per_tool
    mount_cap = getattr(mount_config, "max_result_tokens", None)
    if mount_cap is not None:
        return mount_cap
    return DEFAULT_MAX_RESULT_TOKENS


def _exclude_none(value: Any) -> Any:
    """Recursively drop `None`-valued dict entries (mirrors Pydantic's `exclude_none`).

    Args:
        value: Any JSON-serializable value.

    Returns:
        `value` with every `None`-valued dict key removed, recursively.
        Lists are processed element-wise; other types are returned as-is.
    """
    if isinstance(value, dict):
        return {k: _exclude_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_exclude_none(item) for item in value]
    return value


def _truncate_list(items: list[Any], cap: int) -> tuple[list[Any], int]:
    """Deterministically truncate `items` to fit within `cap` tokens.

    Args:
        items: The (already `exclude_none`d) list to truncate.
        cap: Approximate token budget.

    Returns:
        `(truncated_items, kept_count)`. Truncation always keeps a
        **prefix** of `items` in their original order — no set/dict
        iteration-order dependence — so the same input truncates
        identically every time.
    """
    kept: list[Any] = []
    for item in items:
        candidate = [*kept, item]
        if _approx_tokens(json.dumps(candidate, sort_keys=True, default=str)) > cap:
            break
        kept = candidate
    # Guarantee visible progress even when a single item exceeds the cap —
    # an empty result would hide the truncation rather than state it.
    if not kept and items:
        kept = [items[0]]
    return kept, len(kept)


def apply_size_policy(result: Any, cap: int) -> dict[str, Any]:
    """Apply the deterministic size/pagination policy to a raw tool result.

    Args:
        result: The raw, JSON-serializable tool result (e.g.
            `ToolResult.result`) — a `dict`, `list`, `str`, or primitive.
        cap: Approximate token budget (see `resolve_cap`).

    Returns:
        `{"result": ..., "truncated": bool, "note": str | None}`, plus
        `"total_count"`/`"returned_count"` when the truncated value is a
        list. `exclude_none` is always applied first. Truncation is
        deterministic — the same oversized input truncates identically on
        every call.
    """
    cleaned = _exclude_none(result)
    serialized = json.dumps(cleaned, sort_keys=True, default=str)
    if _approx_tokens(serialized) <= cap:
        return {"result": cleaned, "truncated": False, "note": None}

    if isinstance(cleaned, list):
        truncated_items, kept = _truncate_list(cleaned, cap)
        note = (
            f"Result truncated to {kept} of {len(cleaned)} item(s) "
            f"(~{cap}-token cap). Re-query with narrower filters/pagination "
            "for the remainder."
        )
        return {
            "result": truncated_items,
            "truncated": True,
            "note": note,
            "total_count": len(cleaned),
            "returned_count": kept,
        }

    # Non-list oversized result: deterministically truncate its serialized
    # string form (a prefix — order-independent, always identical).
    max_chars = max(1, cap * _CHARS_PER_TOKEN)
    truncated_str = serialized[:max_chars]
    note = f"Result truncated to ~{cap} tokens " f"(serialized length {len(serialized)} chars)."
    return {"result": truncated_str, "truncated": True, "note": note}


async def run_with_deadline(fn: Callable[[], Awaitable[T]], deadline: float, name: str) -> T:
    """Run `fn()` under `call_deadline_seconds`, naming `name` on timeout.

    Args:
        fn: A zero-argument async callable (e.g. `lambda:
            adapter.execute(arguments)`).
        deadline: Seconds before the call is aborted. Must stay strictly
            below the 300s client ceiling (`AgentMCPMountConfig` enforces
            this at construction time).
        name: The tool/method name, surfaced in the timeout error so the
            caller knows exactly what timed out.

    Returns:
        `fn()`'s result, if it completes within `deadline`.

    Raises:
        MCPToolError: If `fn()` does not complete within `deadline` — a
            clean, message-only error naming `name`, never a bare
            `asyncio.TimeoutError` traceback.
    """
    try:
        return await asyncio.wait_for(fn(), timeout=deadline)
    except TimeoutError as exc:
        raise MCPToolError(f"Tool {name!r} exceeded its {deadline}s call deadline") from exc


__all__ = [
    "DEFAULT_MAX_RESULT_TOKENS",
    "MCPToolError",
    "apply_size_policy",
    "resolve_cap",
    "run_with_deadline",
]
