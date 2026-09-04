"""Per-turn conversation compaction (FEAT-525).

Deterministic Stages 0 (normalization), 0.5 (token counting) and 1
(pruning/retention). See ``sdd/specs/per-turn-conversation-compaction.spec.md``
for the full design.

Import-cycle note: ``parrot.memory.abstract`` imports this package's leaf
modules (``.models``, ``.omission``, ``.budget`` — none of which import
``abstract``) at module level. The other submodules (``.tokens``,
``.normalize``, ``.policies``, ``.compact``, ``.recover``) import
``ConversationTurn``/``ConversationMemory`` from ``abstract`` themselves,
so re-exporting their names *eagerly* here would deadlock the very first
``import parrot.memory`` (``abstract`` triggers this package's
``__init__``, which would try to re-import a still-initializing
``abstract``). Those names are therefore resolved lazily (PEP 562, same
pattern as the FEAT-390 dream-cycle block in ``parrot.memory``) — by the
time anything outside this bootstrap path touches them, ``abstract`` has
finished loading and the import is safe.
"""

from typing import TYPE_CHECKING

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
from .omission import FileOmissionStore, InMemoryOmissionStore, OmissionStore, RedisOmissionStore
from .budget import MODEL_WINDOWS, build_default_budget, resolve_window

if TYPE_CHECKING:
    from .compact import compact_history, render_tool_activity
    from .normalize import normalize_turn
    from .policies import PrunePolicy, get_policy, register_policy
    from .recover import READ_OMITTED_CONTENT_SCHEMA, bind_read_omitted_content
    from .tokens import HeuristicCounter, TiktokenCounter, TokenCounter, count_turn

#: Names resolved lazily via ``__getattr__`` — see the module docstring.
_LAZY_EXPORTS: dict[str, str] = {
    name: f"parrot.memory.compaction.{module}"
    for module, names in {
        "tokens": ("TokenCounter", "TiktokenCounter", "HeuristicCounter", "count_turn"),
        "normalize": ("normalize_turn",),
        "policies": ("PrunePolicy", "register_policy", "get_policy"),
        "compact": ("compact_history", "render_tool_activity"),
        "recover": ("READ_OMITTED_CONTENT_SCHEMA", "bind_read_omitted_content"),
    }.items()
    for name in names
}


def __getattr__(name: str):
    """Resolve the lazy (abstract-importing) compaction exports on first access."""
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    """Expose lazy compaction exports to :func:`dir`."""
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "CALIBRATION_MAX",
    "CALIBRATION_MIN",
    "EWMA_ALPHA",
    "FALLBACK_WINDOW",
    "MODEL_WINDOWS",
    "READ_OMITTED_CONTENT_SCHEMA",
    "CompactionCommit",
    "CompactionResult",
    "CompactionState",
    "ContextBudget",
    "FileOmissionStore",
    "HeuristicCounter",
    "InMemoryOmissionStore",
    "Limit",
    "Omission",
    "OmissionStore",
    "PrunePolicy",
    "RedisOmissionStore",
    "TiktokenCounter",
    "TokenCount",
    "TokenCounter",
    "ToolInvocation",
    "ToolStatus",
    "TurnState",
    "TurnView",
    "bind_read_omitted_content",
    "build_default_budget",
    "compact_history",
    "count_turn",
    "get_policy",
    "normalize_turn",
    "register_policy",
    "render_tool_activity",
    "resolve_window",
]
