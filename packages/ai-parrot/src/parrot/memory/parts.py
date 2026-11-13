"""Structured message parts and the one canonical text formatter (FEAT-886 M16).

Leaf module: stdlib only. ``compaction`` produces already-budgeted parts and the text derived from them with
:func:`render_parts_text`; ``render_history`` carries both. Phase 1 sends only the text to providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence

TOOL_ACTIVITY_OPEN = "\n\n<tool-activity>\n"
TOOL_ACTIVITY_CLOSE = "\n</tool-activity>"


@dataclass(frozen=True)
class MessagePart:
    """One structured piece of a rendered message.

    Attributes:
        kind: ``"text"``, ``"tool_use"`` (an invocation header line) or ``"tool_result"`` (its body).
        content: The rendered text of this part.
        tool_name: The tool a ``tool_use`` / ``tool_result`` part belongs to.
        tool_call_id: Always ``None`` in Phase 1 (``ToolInvocation`` has no call id).
    """

    kind: Literal["text", "tool_use", "tool_result"]
    content: str
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None


def render_parts_text(parts: Sequence[MessagePart]) -> str:
    """The ONE canonical text rendering of tool parts.

    For the same invocations it returns exactly the string ``assistant_suffix`` holds today.

    Args:
        parts: Ordered parts of one turn's tool activity (``tool_use`` / ``tool_result`` / ``text``).

    Returns:
        ``""`` for no parts; otherwise the ``<tool-activity>`` block followed by any trailer text parts.
    """
    if not parts:
        return ""
    lines: List[str] = []
    trailers: List[str] = []
    for part in parts:
        if part.kind == "tool_result" and lines:
            lines[-1] = f"{lines[-1]} {part.content}"
        elif part.kind == "text" and part.content.startswith("\n"):
            trailers.append(part.content)
        else:
            lines.append(part.content)
    return TOOL_ACTIVITY_OPEN + "\n".join(lines) + TOOL_ACTIVITY_CLOSE + "".join(trailers)
