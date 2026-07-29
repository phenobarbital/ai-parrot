"""Tool lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: before/after/failed AbstractTool.execute() calls.
"""
from dataclasses import dataclass, field
from navigator_eventbus.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class BeforeToolCallEvent(LifecycleEvent):
    """Emitted just before AbstractTool._execute() is called.

    Attributes:
        tool_name: Name of the tool being called.
        tool_class: Fully-qualified class name of the concrete tool.
        args_summary: Truncated, JSON-safe dict of call arguments.
            Strings are truncated at 200 chars; binary/non-primitive values
            are replaced with type descriptors. Hashing happens at the
            emission site (AbstractTool.execute), not here.
    """

    tool_name: str = ""
    tool_class: str = ""
    args_summary: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AfterToolCallEvent(LifecycleEvent):
    """Emitted after AbstractTool._execute() completes successfully.

    NOT emitted when _execute() raises (ToolCallFailedEvent is used instead).

    Attributes:
        tool_name: Name of the tool that was called.
        duration_ms: Wall-clock time in milliseconds.
        result_status: ``"success"`` or ``"partial"`` based on the ToolResult.
        result_size_bytes: UTF-8 encoded byte length of the serialized result.
    """

    tool_name: str = ""
    duration_ms: float = 0.0
    result_status: str = ""           # "success" | "partial"
    result_size_bytes: int = 0


@dataclass(frozen=True)
class ToolCallFailedEvent(LifecycleEvent):
    """Emitted when AbstractTool._execute() raises an exception.

    AfterToolCallEvent is NOT emitted when this fires.

    Attributes:
        tool_name: Name of the tool that was called.
        duration_ms: Wall-clock time in milliseconds until failure.
        error_type: ``type(exc).__name__`` of the exception.
        error_message: String representation of the exception.
    """

    tool_name: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
