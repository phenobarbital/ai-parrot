"""Structural plane services and tools (FEAT-498) — read-only symbol queries.

Re-exports :class:`StructuralService`, its Pydantic output models, the
three ``AbstractTool`` wrappers, and :class:`CodeStructuralToolkit` so
callers can ``from parrot.knowledge.wiki.structural import
StructuralService`` (etc.) without reaching into the submodules.
"""

from __future__ import annotations

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
