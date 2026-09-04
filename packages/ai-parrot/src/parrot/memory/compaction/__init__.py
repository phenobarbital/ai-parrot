"""Per-turn conversation compaction (FEAT-525).

Deterministic Stages 0 (normalization), 0.5 (token counting) and 1
(pruning/retention). See ``sdd/specs/per-turn-conversation-compaction.spec.md``
for the full design.
"""

from .models import (
    CALIBRATION_MAX,
    CALIBRATION_MIN,
    EWMA_ALPHA,
    FALLBACK_WINDOW,
    CompactionCommit,
    CompactionResult,
    CompactionState,
    ContextBudget,
    Limit,
    Omission,
    TokenCount,
    ToolInvocation,
    ToolStatus,
    TurnState,
    TurnView,
)

__all__ = [
    "CALIBRATION_MAX",
    "CALIBRATION_MIN",
    "EWMA_ALPHA",
    "FALLBACK_WINDOW",
    "CompactionCommit",
    "CompactionResult",
    "CompactionState",
    "ContextBudget",
    "Limit",
    "Omission",
    "TokenCount",
    "ToolInvocation",
    "ToolStatus",
    "TurnState",
    "TurnView",
]
