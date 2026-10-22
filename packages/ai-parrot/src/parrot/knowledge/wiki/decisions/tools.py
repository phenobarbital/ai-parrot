"""Lazy compatibility exports for the moved decisions plane tools (FEAT-540 M3)."""

from typing import Any

_TARGET = "parrot_tools.wiki.decisions"
_NAMES: frozenset[str] = frozenset(
    {
        "ADR_INVALID_ARGUMENT",
        "AbstractTool",
        "BaseWikiStore",
        "Callable",
        "DEFAULT_BUDGET_TOKENS",
        "DecisionError",
        "DecisionGenerateInput",
        "DecisionService",
        "DecisionWhyInput",
        "DecisionsForSymbolInput",
        "Path",
        "ServiceFactory",
        "StructuralService",
        "ToolResult",
        "WikiDecisionGenerateTool",
        "WikiDecisionWhyTool",
        "WikiDecisionsForSymbolTool",
        "WikiProjectConfig",
        "_NAMESPACE_DESC",
        "_scoped_store",
        "_unknown_namespace_error",
        "create_decision_tools",
        "op_decision_generate",
        "op_decision_why",
        "op_decisions_for_symbol",
    }
)

__all__ = sorted(n for n in _NAMES if not n.startswith("_"))


def __getattr__(name: str) -> Any:
    """Resolve a moved name from ``parrot_tools.wiki`` only when requested."""
    if name not in _NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(_TARGET), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the moved names."""
    return sorted(_NAMES)
