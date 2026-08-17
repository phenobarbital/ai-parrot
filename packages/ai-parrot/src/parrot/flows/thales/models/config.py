"""Run configuration contract for the "Thales" research flow (FEAT-425)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ThalesConfig(BaseModel):
    """Configuration for one Thales run.

    Attributes:
        thesis: The user-supplied thesis statement to research.
        num_decks: Number of research angles/decks to generate. Minimum 10
            (resolved in brainstorm) — deliberately has **no upper cap**.
        sources: Research sources to enable per angle.
        output_dir: Optional filesystem directory to mirror artifacts into.
        per_node_timeout: Optional per-research-node timeout, in seconds.
        max_paragraphs_per_finding: Cap on extracted paragraphs per finding.
    """

    thesis: str
    num_decks: int = Field(default=10, ge=10)
    sources: list[str] = Field(default_factory=lambda: ["web", "deep_research", "arxiv"])
    output_dir: Optional[Path] = None
    per_node_timeout: Optional[float] = None
    max_paragraphs_per_finding: int = 6
