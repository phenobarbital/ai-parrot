"""Structural plane services and tools (FEAT-498) — read-only symbol queries.

Re-exports :class:`StructuralService`, its Pydantic output models, the
three ``AbstractTool`` wrappers, and :class:`CodeStructuralToolkit` so
callers can ``from parrot.knowledge.wiki.structural import
StructuralService`` (etc.) without reaching into the submodules.
"""

from __future__ import annotations

from importlib import import_module

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - re-export surface, resolved lazily below
    from parrot.knowledge.wiki.structural.service import (
        BlastRadiusOutput,
        CodeOutlineOutput,
        ImpactedSymbol,
        StructuralService,
        SymbolHit,
        SymbolLookupOutput,
    )
    from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit
    from parrot.knowledge.wiki.structural.tools import (
        BlastRadiusInput,
        CodeOutlineInput,
        SymbolLookupInput,
        WikiBlastRadiusTool,
        WikiCodeOutlineTool,
        WikiSymbolLookupTool,
        create_structural_tools,
    )

#: Re-exported name -> submodule that defines it. Resolved on first access
#: (PEP 562) rather than at import: the tool wrappers pull in parrot.tools,
#: and importing ANY submodule of this package runs this file, so a CLI that
#: only wants StructuralService used to pay for the whole agent tool stack.
_EXPORTS: dict[str, str] = {
    "BlastRadiusOutput": "service",
    "CodeOutlineOutput": "service",
    "ImpactedSymbol": "service",
    "StructuralService": "service",
    "SymbolHit": "service",
    "SymbolLookupOutput": "service",
    "CodeStructuralToolkit": "toolkit",
    "BlastRadiusInput": "tools",
    "CodeOutlineInput": "tools",
    "SymbolLookupInput": "tools",
    "WikiBlastRadiusTool": "tools",
    "WikiCodeOutlineTool": "tools",
    "WikiSymbolLookupTool": "tools",
    "create_structural_tools": "tools",
}


def __getattr__(name: str) -> Any:
    """Import the defining submodule on first access to a re-exported name."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value  # cache: subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    """Keep tab-completion and `dir()` showing the full re-export surface."""
    return sorted(__all__)


__all__ = [
    "BlastRadiusInput",
    "BlastRadiusOutput",
    "CodeOutlineInput",
    "CodeOutlineOutput",
    "CodeStructuralToolkit",
    "ImpactedSymbol",
    "StructuralService",
    "SymbolHit",
    "SymbolLookupInput",
    "SymbolLookupOutput",
    "WikiBlastRadiusTool",
    "WikiCodeOutlineTool",
    "WikiSymbolLookupTool",
    "create_structural_tools",
]
