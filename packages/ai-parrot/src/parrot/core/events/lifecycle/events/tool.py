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
        result_size_bytes: UTF-8 encoded byte length of the serialized
            result. FEAT-380: this is now documented as the
            **post-compression** size — the tool-result compression
            pipeline (``parrot.tools.compression``) may shrink the payload
            between this event's original emission point and the value a
            consumer ultimately reads via ``ToolResult.metadata``. See the
            new ``compression_*`` fields below for the pre-compression size
            and the codec/level/duration/tee outcome. Renamed semantics
            documented in the FEAT-380 changelog entry.
        compression_codec: Name of the codec that ran (empty string if
            compression did not run/was skipped).
        compression_level: Effective :class:`FilterLevel` value applied
            (empty string if compression did not run/was skipped).
        result_size_bytes_original: UTF-8 byte length of the result BEFORE
            compression. Equal to ``result_size_bytes`` when compression did
            not run.
        compression_duration_ms: Wall-clock time spent in the compression
            codec, in milliseconds. ``0.0`` when compression did not run.
        compression_teed: Whether the original (pre-compression) payload was
            persisted to working memory for recovery (``True`` for lossy
            compressions and teed errors).
    """

    tool_name: str = ""
    duration_ms: float = 0.0
    result_status: str = ""           # "success" | "partial"
    result_size_bytes: int = 0
    compression_codec: str = ""
    compression_level: str = ""
    result_size_bytes_original: int = 0
    compression_duration_ms: float = 0.0
    compression_teed: bool = False


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
