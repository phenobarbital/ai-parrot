""""Thales" — research flow with structured citations, decks & final report.

Named after Thales of Miletus (the codename's English spelling; the
Spanish "Tales" survives only in the working slug
``agentcrew-tales-research``, kept for ledger/file continuity).

A domain flow package (``parrot.flows.thales``), following the
``parrot.flows.dev_loop`` application-flow pattern: a planner LLM splits a
user thesis into research angles, parallel research nodes (web search,
deep research, arxiv) gather sourced findings, and deterministic
downstream nodes render research decks into slides, an executive summary,
a final print-CSS document (+ optional PDF), and a summary infographic.

See ``sdd/specs/agentcrew-tales-research.spec.md`` for the full spec.

This ``__init__`` re-exports Module 1's Pydantic contracts (see
``parrot.flows.thales.models``) for convenient top-level import.
"""

from __future__ import annotations

from parrot.flows.thales.models import (
    ArtifactRef,
    Bibliography,
    Finding,
    ResearchAngle,
    ResearchDeck,
    SlideSpec,
    SourceClaim,
    ThalesConfig,
    ThalesResult,
)

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
