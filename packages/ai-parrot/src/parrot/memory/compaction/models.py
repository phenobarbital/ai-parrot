"""Data models for per-turn conversation compaction (FEAT-525).

This module is a **leaf module**: it imports stdlib and ``orjson`` only. It
must NEVER import :mod:`parrot.memory.abstract` — the dependency runs the
other way (``abstract.py`` imports these models). All models except
:class:`ToolInvocation` are frozen dataclasses; ``ToolInvocation`` is mutated
in place by the write-time offload performed by
``ConversationMemory.add_turn`` (see spec Sec 2).

Pydantic is deliberately not used here: :class:`~parrot.memory.abstract.
ConversationTurn` and :class:`~parrot.memory.abstract.ConversationHistory`
are stdlib dataclasses with hand-written ``to_dict``/``from_dict``, and these
compaction models round-trip through the same ``orjson`` path without
introducing a second serializer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class ToolStatus(str, Enum):
    """Outcome of a single tool invocation."""

    COMPLETED = "completed"
    ERROR = "error"


class TurnState(str, Enum):
    """Lifecycle state of a conversation turn.

    Storage always writes ``RAW`` in v1. ``PRUNED`` is a view-only state
    produced by :func:`parrot.memory.compaction.compact.compact_history`.
    ``SUMMARIZED`` is reserved for Stage 2 (LLM summary turns) and is never
    produced by this feature.
    """

    RAW = "raw"
    PRUNED = "pruned"
    SUMMARIZED = "summarized"


@dataclass
class ToolInvocation:
    """One tool call captured from ``AIMessage.tool_calls``.

    See ``parrot/models/basic.py:23-30`` for the source ``ToolCall`` shape.

    Attributes:
        tool_name: Name of the invoked tool.
        input: Canonical (``orjson`` ``OPT_SORT_KEYS``) arguments after
            Stage 0 normalization.
        output: Full text, or the short preview left behind once the
            original output has been offloaded to the omission store.
        status: Whether the invocation completed or errored.
        error: Condensed error/traceback text. Never omitted (spec G7/C7).
        elapsed_ms: Wall-clock duration of the invocation, in milliseconds.
        output_chars: Length of the ORIGINAL output, captured before any
            offload so the preview notice can report the true size.
        omitted: Maps a field name (``"output"`` is the only one used in
            v1) to the ``content_id`` ("om_...") it was offloaded to.
        wm_key: The FEAT-380 working-memory tee key copied from
            ``result["_tee"]["key"]`` when the tool result carries one.
    """

    tool_name: str
    input: Dict[str, Any]
    output: Optional[str] = None
    status: ToolStatus = ToolStatus.COMPLETED
    error: Optional[str] = None
    elapsed_ms: Optional[int] = None
    output_chars: Optional[int] = None
    omitted: Dict[str, str] = field(default_factory=dict)
    wm_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this invocation to a plain dict."""
        return {
            "tool_name": self.tool_name,
            "input": self.input,
            "output": self.output,
            "status": self.status.value,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "output_chars": self.output_chars,
            "omitted": dict(self.omitted),
            "wm_key": self.wm_key,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolInvocation":
        """Deserialize an invocation from a dict, tolerant of missing keys."""
        status_raw = data.get("status", ToolStatus.COMPLETED.value)
        return cls(
            tool_name=data.get("tool_name", ""),
            input=data.get("input", {}) or {},
            output=data.get("output"),
            status=ToolStatus(status_raw) if status_raw else ToolStatus.COMPLETED,
            error=data.get("error"),
            elapsed_ms=data.get("elapsed_ms"),
            output_chars=data.get("output_chars"),
            omitted=dict(data.get("omitted") or {}),
            wm_key=data.get("wm_key"),
        )


@dataclass(frozen=True)
class TokenCount:
    """Per-turn token accounting.

    ``context_used`` is deliberately NOT counted here (spec decision).
    """

    user: int
    assistant: int
    tools: int
    total: int
    tokenizer: str

    def to_dict(self) -> Dict[str, int | str]:
        """Serialize this token count to a plain dict."""
        return {
            "user": self.user,
            "assistant": self.assistant,
            "tools": self.tools,
            "total": self.total,
            "tokenizer": self.tokenizer,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TokenCount":
        """Deserialize a token count from a dict."""
        return cls(
            user=int(data.get("user", 0)),
            assistant=int(data.get("assistant", 0)),
            tools=int(data.get("tools", 0)),
            total=int(data.get("total", 0)),
            tokenizer=data.get("tokenizer", "heuristic"),
        )


@dataclass(frozen=True)
class Limit:
    """Bound on the RAW ``<tool-activity>`` block.

    Keeps a chatty recent turn from blowing the whole budget by itself.
    """

    max_invocations: int = 12
    max_input_chars: int = 200
    max_output_chars: int = 400
    max_block_tokens: int = 1_500


FALLBACK_WINDOW: int = 32_000


@dataclass(frozen=True)
class ContextBudget:
    """Token budget and retention configuration for one bot/agent.

    Attributes:
        window: The provider's context window, from ``MODEL_WINDOWS`` when
            the model is known, else :data:`FALLBACK_WINDOW`.
        reserve_output: Tokens reserved for the model's own output.
        reserve_fixed: Tokens reserved for the system prompt, tool schemas
            and provider framing allowance.
        high_watermark: Fraction of ``available`` the pruned tier may fill.
        low_watermark: Reserved for Stage 2 (target after summarization);
            unused by the deterministic three-tier walk.
        max_turns: Unified safety ceiling on the number of turns considered
            (was ``AbstractBot`` 50 / ``Chatbot`` 5 before this feature).
        verbatim_tokens: Cumulative token budget for the verbatim (RAW)
            tier.
        min_verbatim_turns: Minimum number of turns kept verbatim,
            regardless of size.
        oversize_tool_tokens: Any tool output above this size is pruned
            from every turn but the newest, even inside the verbatim tier.
        tool_activity_limit: Bound applied when rendering the RAW
            ``<tool-activity>`` block.
    """

    window: int
    reserve_output: int = 8_192
    reserve_fixed: int = 4_096
    high_watermark: float = 0.80
    low_watermark: float = 0.60
    max_turns: int = 30
    verbatim_tokens: int = 15_000
    min_verbatim_turns: int = 2
    oversize_tool_tokens: int = 2_000
    tool_activity_limit: Limit = field(default_factory=Limit)

    def __post_init__(self) -> None:
        """Validate the budget invariants (spec Sec 2)."""
        if self.window <= self.reserve_output + self.reserve_fixed:
            raise ValueError(
                "window must be greater than reserve_output + reserve_fixed: "
                f"window={self.window}, reserve_output={self.reserve_output}, "
                f"reserve_fixed={self.reserve_fixed}"
            )
        if not (0 < self.low_watermark <= self.high_watermark <= 1):
            raise ValueError(
                "watermarks must satisfy 0 < low_watermark <= high_watermark <= 1: "
                f"low_watermark={self.low_watermark}, high_watermark={self.high_watermark}"
            )
        if self.max_turns < self.min_verbatim_turns:
            raise ValueError(
                "max_turns must be >= min_verbatim_turns: "
                f"max_turns={self.max_turns}, min_verbatim_turns={self.min_verbatim_turns}"
            )
        if self.min_verbatim_turns < 1:
            raise ValueError(f"min_verbatim_turns must be >= 1: got {self.min_verbatim_turns}")
        if self.verbatim_tokens < 0:
            raise ValueError(f"verbatim_tokens must be >= 0: got {self.verbatim_tokens}")
        if self.oversize_tool_tokens <= 0:
            raise ValueError(f"oversize_tool_tokens must be > 0: got {self.oversize_tool_tokens}")

    @property
    def available(self) -> int:
        """Tokens available for history after reserves (never negative)."""
        return max(0, self.window - self.reserve_output - self.reserve_fixed)


@dataclass(frozen=True)
class CompactionState:
    """Persisted as ``history.metadata["compaction"]``.

    This is the ONLY compaction state ever persisted; pruned forms are
    never stored (spec G2/C2).
    """

    tokenizer: str
    calibration: float = 1.0
    samples: int = 0
    boundary_turn_id: Optional[str] = None
    stage2_needed: bool = False
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this state to a plain dict."""
        return {
            "tokenizer": self.tokenizer,
            "calibration": self.calibration,
            "samples": self.samples,
            "boundary_turn_id": self.boundary_turn_id,
            "stage2_needed": self.stage2_needed,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompactionState":
        """Deserialize a state from a dict, tolerant of missing keys."""
        return cls(
            tokenizer=data.get("tokenizer", "heuristic"),
            calibration=float(data.get("calibration", 1.0)),
            samples=int(data.get("samples", 0)),
            boundary_turn_id=data.get("boundary_turn_id"),
            stage2_needed=bool(data.get("stage2_needed", False)),
            updated_at=data.get("updated_at"),
        )


EWMA_ALPHA: float = 0.2
CALIBRATION_MIN: float = 0.5
CALIBRATION_MAX: float = 2.0


@dataclass(frozen=True)
class Omission:
    """A piece of content offloaded from a turn to the omission store."""

    content_id: str
    content: str
    turn_id: str
    tool_name: str
    field: str


@dataclass(frozen=True)
class TurnView:
    """Materialized text for one turn.

    ``render_history`` only concatenates ``user_text`` and
    ``assistant_text + assistant_suffix`` — it never re-derives them.
    """

    turn_id: str
    chatbot_id: Optional[str]
    user_text: str
    assistant_text: str
    assistant_suffix: str
    state: TurnState
    estimated_tokens: int


@dataclass(frozen=True)
class CompactionResult:
    """Output of :func:`parrot.memory.compaction.compact.compact_history`."""

    views: Tuple[TurnView, ...]
    omissions: Tuple[Omission, ...]
    history_estimate: int
    boundary_turn_id: Optional[str]
    stage2_needed: bool
    dropped_turn_ids: Tuple[str, ...]


@dataclass(frozen=True)
class CompactionCommit:
    """What the bot hands to ``save_conversation_turn`` after the round.

    Attributes:
        prompt_estimate: ``tokens(rendered history) + tokens(system_prompt)
            + tokens(prompt)``.
        boundary_turn_id: The new monotonic boundary.
        stage2_needed: Whether Stage 2 is needed for this session.
        history_estimate: Telemetry only — the compacted history's total
            estimated size. Ignored by :func:`apply_commit`; populated by
            ``AbstractBot.save_conversation_turn`` to feed
            ``Stage2CompactionNeededEvent`` without a second channel.
        dropped_turns: Telemetry only — count of turns dropped by the last
            compaction pass. Ignored by :func:`apply_commit`.
    """

    prompt_estimate: int
    boundary_turn_id: Optional[str]
    stage2_needed: bool
    history_estimate: int = 0
    dropped_turns: int = 0
