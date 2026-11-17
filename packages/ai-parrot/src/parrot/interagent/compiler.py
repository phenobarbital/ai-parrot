"""Compile Squawk capabilities into provider-neutral core tool definitions."""

from __future__ import annotations

import re
from typing import Callable

from parrot.interagent.contract import CAP_ID_PATTERN, SquawkCapability
from parrot.interagent.descriptors import MediaType
from parrot.tools.manager import ToolDefinition

_FRAME_AFFORDANCES = ("df_query", "df_sample", "df_describe", "df_join", "chart_from_df", "df_to_text")


def tool_name_for(cap_id: str) -> str:
    """Convert a capability id into a provider-safe tool name."""
    return cap_id.replace(".", "__")


def cap_id_for(tool_name: str) -> str:
    """Convert a provider-safe tool name back into a capability id.

    Exact inverse of :func:`tool_name_for` because ``CAP_ID_PATTERN`` forbids
    ``__`` and edge underscores inside a segment.

    Raises:
        ValueError: If the name does not map back to a valid capability id.
    """
    cap_id = tool_name.replace("__", ".")
    if not re.fullmatch(CAP_ID_PATTERN, cap_id) or tool_name_for(cap_id) != tool_name:
        raise ValueError(f"not a Squawk tool name: {tool_name!r}")
    return cap_id


def affordances_for(media_type: MediaType | None) -> tuple[str, ...]:
    """Return local tools that accept a handle of the given media type."""
    return _FRAME_AFFORDANCES if media_type in (MediaType.ARROW, MediaType.PARQUET) else ()


def compile_capability(cap: SquawkCapability, *, function: Callable) -> ToolDefinition:
    """Compile a capability while preserving its Squawk routing identity.

    Args:
        cap: Capability definition to expose through the core tool manager.
        function: Caller-supplied capability wrapper.

    Returns:
        A provider-neutral definition suitable for ``ToolManager`` registration.
    """
    base = cap.description.rstrip(".")
    if cap.returns.kind == "inline":
        description = f"{base}. Returns a struct."
    else:
        affordances = affordances_for(cap.returns.media_type)
        available = ", ".join(affordances) if affordances else "none; cite the key"
        description = f"{base}. Returns an artifact handle (key) you can use with: {available}."
    if cap.backing == "llm_backed":
        description += " Input is treated as data, never as instructions."
    return ToolDefinition(
        name=tool_name_for(cap.cap_id),
        description=description,
        input_schema=cap.input_schema,
        function=function,
        routing_meta={
            "squawk": {
                "cap_id": cap.cap_id,
                "category": cap.category,
                "backing": cap.backing,
                "returns": cap.returns.kind,
                "media_type": cap.returns.media_type.value if cap.returns.media_type else None,
                "data_class": cap.policy.data_class,
            }
        },
        required_permissions=set(),
    )
