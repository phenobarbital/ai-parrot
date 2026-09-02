"""Structural plane services (FEAT-498) — read-only symbol queries.

Re-exports :class:`StructuralService` and its Pydantic output models so
callers can ``from parrot.knowledge.wiki.structural import StructuralService``
without reaching into ``structural.service``.
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

__all__ = [
    "BlastRadiusOutput",
    "CodeOutlineOutput",
    "ImpactedSymbol",
    "StructuralService",
    "SymbolHit",
    "SymbolLookupOutput",
]
