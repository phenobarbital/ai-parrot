"""Pydantic v2 contracts for the "Thales" research flow (FEAT-425).

This package is the foundation for ``parrot.flows.thales`` and the
interface the separate ``research-tools-for-agents`` spec implements
against (``SourceClaim`` / ``Finding``). Dependency-light: pydantic +
stdlib only (plus internal cross-imports between the modules of this
package) — no other ``parrot.*`` imports.

See ``sdd/specs/agentcrew-tales-research.spec.md`` §2 "Data Models" for
the authoritative contracts.
"""

from __future__ import annotations

from parrot.flows.thales.models.config import ThalesConfig
from parrot.flows.thales.models.deck import (
    Finding,
    ResearchAngle,
    ResearchDeck,
    SourceClaim,
)
from parrot.flows.thales.models.result import ArtifactRef, ThalesResult
from parrot.flows.thales.models.slides import Bibliography, SlideSpec

__all__ = [
    "ArtifactRef",
    "Bibliography",
    "Finding",
    "ResearchAngle",
    "ResearchDeck",
    "SlideSpec",
    "SourceClaim",
    "ThalesConfig",
    "ThalesResult",
]
