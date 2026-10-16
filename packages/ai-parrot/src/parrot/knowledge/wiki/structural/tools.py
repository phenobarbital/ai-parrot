"""Lazy compatibility exports for the moved structural plane tools (FEAT-540 M3)."""

from typing import Any

_TARGET = "parrot_tools.wiki.structural"
_NAMES: frozenset[str] = frozenset(
    {
        "AbstractTool",
        "BaseWikiStore",
        "BlastRadiusInput",
        "Callable",
        "CodeOutlineInput",
        "FederatedWikiStore",
        "Path",
        "ServiceFactory",
        "StructuralService",
        "SymbolKind",
        "SymbolLookupInput",
        "ToolResult",
        "WikiBlastRadiusTool",
        "WikiCodeOutlineTool",
        "WikiProjectConfig",
        "WikiSymbolLookupTool",
        "_NAMESPACE_DESC",
        "_scoped_store",
        "_unknown_namespace_error",
        "create_structural_tools",
        "op_blast_radius",
        "op_code_outline",
        "op_symbol_lookup",
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
