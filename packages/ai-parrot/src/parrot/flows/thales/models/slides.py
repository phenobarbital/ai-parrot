"""Slide and bibliography contracts for the "Thales" research flow (FEAT-425).

``SlideSpec`` is filled by an LLM as structured output — it is a spec, never
raw HTML (deterministic rendering happens in
``parrot.flows.thales.rendering``, Module 4). ``Bibliography`` is the
container model for the deterministic APA-ish formatter (the formatter
itself lives in Module 3's ``nodes/bibliography.py``, not here).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from parrot.flows.thales.models.deck import SourceClaim


class SlideSpec(BaseModel):
    """Structured content for one research-deck slide.

    LLM-filled structured output — never HTML. Deterministic rendering
    (Jinja2 + ECharts/static-SVG) consumes this model in Module 4.

    Attributes:
        deck_ref: Identifier of the :class:`~parrot.flows.thales.models.deck.ResearchDeck`
            (its angle's ``angle_id``) this slide belongs to.
        layout: Template variant hint for the renderer.
        headline: Slide headline text.
        bullets: Bullet-point summary lines.
        charts: ECharts option-JSON payloads, only when chartable numeric
            data is present in the source findings.
        tables: Table payloads for the slide.
        quotes: Quote payloads; each entry pairs quote text with a
            :class:`~parrot.flows.thales.models.deck.SourceClaim` reference.
    """

    deck_ref: str
    layout: str
    headline: str
    bullets: list[str] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    quotes: list[dict[str, Any]] = Field(default_factory=list)


class Bibliography(BaseModel):
    """Deduplicated, APA-ish formatted bibliography for the final document.

    Attributes:
        entries: APA-ish formatted bibliography entry strings, deduped by
            source URL. Missing publication dates render as "n.d." — never
            invented.
        claims: The deduplicated :class:`SourceClaim` objects backing the
            formatted entries, in the same order.
    """

    entries: list[str] = Field(default_factory=list)
    claims: list[SourceClaim] = Field(default_factory=list)
