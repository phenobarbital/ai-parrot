"""Research deck contracts for the "Thales" research flow (FEAT-425).

Every research node (web, deep-research, arxiv, and any future source added
by the separate ``research-tools-for-agents`` spec) normalizes its output
into a :class:`Finding` list, each carrying one or more :class:`SourceClaim`
citations. Per-angle findings are aggregated into a :class:`ResearchDeck`.

This module is intentionally dependency-light (pydantic + stdlib only) so
satellite specs can build research nodes against :class:`SourceClaim` /
:class:`Finding` without pulling in any flow machinery.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ResearchAngle(BaseModel):
    """One research sub-thesis derived from the user's overall thesis.

    Attributes:
        angle_id: Stable identifier for this angle (used to key flow nodes).
        title: Short human-readable title for the angle.
        question: The specific sub-thesis/question to investigate.
        rationale: Why this angle matters to the overall thesis.
    """

    angle_id: str
    title: str
    question: str
    rationale: str


class SourceClaim(BaseModel):
    """One cited source backing a finding.

    ``published_date`` is intentionally ``Optional`` and must never be
    invented when unknown — downstream bibliography formatting renders
    missing dates as "n.d." (APA-ish convention) rather than guessing.

    Attributes:
        url: The source URL.
        title: Title of the source document/page, when available.
        authors: List of author names, when available.
        publisher: Publisher/site name, when available.
        published_date: ISO date string when discoverable; never invented.
        accessed_date: ISO date string of when this source was retrieved.
        source_tool: Name of the tool/node that produced this claim, e.g.
            ``"web_search"``, ``"deep_research"``, ``"arxiv_search"``.
        verification: The anti-hallucination verification channel for this
            claim — ``"groundedness"`` (scored via GroundednessGuardrail),
            ``"provider_grounding"`` (accepted for provider-native grounding
            paths such as Gemini built-in search / Deep Research that yield
            no ``ToolCall.result`` evidence), or ``"unverified"``.
    """

    url: str
    title: Optional[str] = None
    authors: list[str] = Field(default_factory=list)
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    accessed_date: str
    source_tool: str
    verification: Literal["groundedness", "provider_grounding", "unverified"]


class Finding(BaseModel):
    """One extracted finding backed by one or more source claims.

    Attributes:
        text: Extracted paragraph(s) of finding text, capped in length by
            the caller (see ``ThalesConfig.max_paragraphs_per_finding``).
        claims: The source claims backing this finding. Every finding must
            carry at least one claim (enforced by callers, not here).
        numeric_series: Optional chartable numeric data extracted alongside
            the finding text, when present.
    """

    text: str
    claims: list[SourceClaim] = Field(default_factory=list)
    numeric_series: Optional[dict[str, Any]] = None


class ResearchDeck(BaseModel):
    """All findings gathered for one research angle.

    Attributes:
        angle: The research angle this deck answers.
        findings: All findings gathered across enabled research sources.
        tools_used: Names of the tools/sources that contributed findings.
        groundedness: Per-source ``GroundednessReport`` dumps, keyed by
            source tool name, recorded for deck provenance.
        failed_sources: Names of sources that failed/timed out for this
            angle (OR-join degrade — the deck is still built from the
            surviving sources).
    """

    angle: ResearchAngle
    findings: list[Finding] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    groundedness: dict[str, Any] = Field(default_factory=dict)
    failed_sources: list[str] = Field(default_factory=list)
