"""Result / manifest contracts for the "Thales" research flow (FEAT-425)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.flows.thales.models.deck import ResearchDeck
from parrot.flows.thales.models.slides import Bibliography


class ArtifactRef(BaseModel):
    """Reference to one persisted Thales artifact.

    Attributes:
        kind: Artifact kind, e.g. ``"deck_json"``, ``"slide_html"``,
            ``"final_html"``, ``"final_pdf"``, ``"infographic"``,
            ``"raw_research"``.
        artifact_id: Identifier assigned by the :class:`ArtifactStore`,
            when persisted there.
        url: Public URL for the artifact, when available.
        path: Local filesystem path, when mirrored to ``output_dir``.
    """

    kind: str
    artifact_id: Optional[str] = None
    url: Optional[str] = None
    path: Optional[Path] = None


class ThalesResult(BaseModel):
    """The full manifest produced by one Thales run.

    Attributes:
        thesis: The thesis statement that was researched.
        decks: All generated :class:`ResearchDeck` objects, one per angle.
        slides: References to the per-deck slide HTML artifacts.
        bibliography: The deduplicated, APA-ish formatted bibliography.
        executive_summary: Synthesis text over all decks.
        final_document: Reference to the print-CSS final HTML document.
        final_pdf: Reference to the final `.pdf` artifact, present only
            when weasyprint was importable at render time.
        infographic: The ``InfographicRenderResult`` for the run's summary
            infographic. Kept as ``Optional[Any]`` to avoid importing
            toolkit machinery into this dependency-light models package.
        manifest_path: Local path to the written ``manifest.json``, when
            ``output_dir`` mirroring is enabled.
        warnings: Non-fatal warnings accumulated during the run (e.g. a
            missing weasyprint extra, or degraded/failed sources).
    """

    thesis: str
    decks: list[ResearchDeck] = Field(default_factory=list)
    slides: list[ArtifactRef] = Field(default_factory=list)
    bibliography: Bibliography
    executive_summary: str
    final_document: ArtifactRef
    final_pdf: Optional[ArtifactRef] = None
    infographic: Optional[Any] = None
    manifest_path: Optional[Path] = None
    warnings: list[str] = Field(default_factory=list)
