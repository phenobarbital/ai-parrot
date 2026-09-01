"""Contradiction protocol (FEAT-481, spec Module 11, contract §22 —
mandatory).

Detects materially incompatible claims BEFORE the project page update
runs (§27 step 9 — this node runs ahead of ``project_reconcile.py`` in
the orchestrator's pipeline order). Contradictions are first-class
objects: never silently overwritten, never resolved by recency (§22
rule 9) — only explicit evidence or user instruction resolves one (rule
10), which this node structurally cannot do on its own (it never sets a
non-empty ``resolution``).
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient

from ..models import ContradictionFrontmatter
from ..naming import now_iso, title_case_name
from ..render.contradiction import (
    ContradictionClaim,
    ContradictionState,
    render_contradiction_page,
)
from .classify import ReviewItemDraft

logger = logging.getLogger(__name__)

#: §22 — severities that always add a Review Queue item (rule #8).
_HIGH_IMPACT_SEVERITIES = frozenset({"high", "critical"})

_SYSTEM_PROMPT = (
    "You are detecting contradictions for a governed knowledge base (contract "
    "§22). A contradiction exists when two credible sources make MATERIALLY "
    "incompatible claims about requirements, decisions, ownership, scope, "
    "dates, technical capabilities, status, costs, policies, or risks. Do NOT "
    "flag claims that are merely additive, refined, or a legitimate update — "
    "only genuine incompatibilities. Never resolve a conflict by preferring "
    "the newer claim; describe the conflict, its impact, and what evidence "
    "would be needed to resolve it."
)


class ExistingClaimRef(BaseModel):
    """One existing claim available for contradiction detection.

    Attributes:
        text: The claim text.
        source: Wikilink target of its supporting source page.
        date: ``YYYY-MM-DD`` the claim was made.
    """

    text: str
    source: str
    date: str


class ConflictCandidate(BaseModel):
    """One detected contradiction between an existing and a new claim."""

    title: str
    existing_claim_text: str
    new_claim_text: str
    why_conflict: str
    impact: str
    severity: Literal["low", "medium", "high", "critical"]
    resolution_needed: str


class ContradictionDetectionResult(BaseModel):
    """The strong-tier client's full detection result for one meeting."""

    conflicts: list[ConflictCandidate] = Field(default_factory=list)


class ContradictionPage(BaseModel):
    """One rendered/updated contradiction page.

    Attributes:
        frontmatter: The validated §10.5 frontmatter.
        content: The rendered page.
        vault_path: ``Wiki/Contradictions/<Title>.md``.
        affected_pages: Every project/entity/concept/source page this
            contradiction must be linked from (§22 rule 6).
        review_item: A high-impact ``contradiction`` review item (§22
            rule 8), when ``severity`` is ``"high"``/``"critical"``.
    """

    frontmatter: ContradictionFrontmatter
    content: str
    vault_path: str
    affected_pages: list[str] = Field(default_factory=list)
    review_item: ReviewItemDraft | None = None


async def detect_contradictions(
    strong_client: AbstractClient,
    existing_claims: list[ExistingClaimRef],
    new_claims: list[str],
) -> ContradictionDetectionResult:
    """§22 — detect materially incompatible claims (strong-tier client).

    Args:
        strong_client: The strong-tier :class:`AbstractClient`.
        existing_claims: The project/Wiki's current claims (decisions,
            requirements, risks, ...), each with its source/date.
        new_claims: The new meeting's claims (same categories).

    Returns:
        The :class:`ContradictionDetectionResult` — empty ``conflicts``
        when nothing materially conflicts.
    """
    if not existing_claims or not new_claims:
        return ContradictionDetectionResult()

    prompt = "\n".join(
        [
            "Existing claims:",
            *[f"- {c.text} (source: {c.source}, date: {c.date})" for c in existing_claims],
            "",
            "New meeting claims:",
            *[f"- {c}" for c in new_claims],
        ]
    )
    result = await strong_client.invoke(
        prompt, output_type=ContradictionDetectionResult, system_prompt=_SYSTEM_PROMPT, temperature=0.0
    )
    return result.output


def build_contradiction_page(
    conflict: ConflictCandidate,
    *,
    existing_claim: ExistingClaimRef,
    new_claim_source: str,
    new_claim_date: str,
    affected_pages: list[str],
) -> ContradictionPage:
    """Render one detected conflict into a §22 contradiction page.

    Never sets ``status`` to anything but ``"open"`` and never populates
    ``## Resolution`` (§22 rules 5/9/10) — this function has no pathway
    to "resolve by recency".

    Args:
        conflict: The detected :class:`ConflictCandidate`.
        existing_claim: The existing side's :class:`ExistingClaimRef`
            (source/date for ``## Claim A``).
        new_claim_source: Wikilink target of the new meeting's source page.
        new_claim_date: The new meeting's date (``## Claim B``).
        affected_pages: Every page this contradiction must be linked
            from (§22 rule 6) — the caller (orchestrator) supplies this
            from the project/entity/concept/source pages touched this
            operation.

    Returns:
        The :class:`ContradictionPage`.
    """
    title = title_case_name(conflict.title)
    now = now_iso()

    state = ContradictionState(
        claim_a=ContradictionClaim(text=existing_claim.text, source=existing_claim.source, date=existing_claim.date),
        claim_b=ContradictionClaim(text=conflict.new_claim_text, source=new_claim_source, date=new_claim_date),
        why_conflict=conflict.why_conflict,
        impact=conflict.impact,
        resolution_needed=conflict.resolution_needed,
    )
    frontmatter = ContradictionFrontmatter(
        id=f"contradiction:{title.lower().replace(' ', '-')}",
        title=title,
        status="open",
        severity=conflict.severity,
        affected_pages=affected_pages,
        source_pages=[existing_claim.source, new_claim_source],
        created=now,
        updated=now,
    )
    content = render_contradiction_page(frontmatter, state)

    review_item = None
    if conflict.severity in _HIGH_IMPACT_SEVERITIES:
        review_item = ReviewItemDraft(
            review_type="contradiction",
            source_id=new_claim_source,
            issue=f"High-impact contradiction: {title}",
            evidence=conflict.why_conflict,
        )

    return ContradictionPage(
        frontmatter=frontmatter,
        content=content,
        vault_path=f"Wiki/Contradictions/{title}.md",
        affected_pages=affected_pages,
        review_item=review_item,
    )


async def run_contradiction_detection(
    strong_client: AbstractClient,
    existing_claims: list[ExistingClaimRef],
    new_claims: list[str],
    *,
    new_claim_source: str,
    new_claim_date: str,
    affected_pages: list[str],
) -> list[ContradictionPage]:
    """Detect + render every contradiction between existing and new claims.

    Args:
        strong_client: The strong-tier :class:`AbstractClient`.
        existing_claims: The project/Wiki's current claims.
        new_claims: The new meeting's claims.
        new_claim_source: Wikilink target of the new meeting's source page.
        new_claim_date: The new meeting's date.
        affected_pages: Pages to link every detected contradiction from
            (§22 rule 6).

    Returns:
        One :class:`ContradictionPage` per detected conflict (empty when
        nothing conflicts).
    """
    detection = await detect_contradictions(strong_client, existing_claims, new_claims)
    if not detection.conflicts:
        return []

    by_text = {c.text: c for c in existing_claims}
    pages = []
    for conflict in detection.conflicts:
        existing_claim = by_text.get(conflict.existing_claim_text)
        if existing_claim is None:
            # The LLM must cite an existing claim verbatim — if it does
            # not match anything we actually supplied, skip rather than
            # fabricate a source/date for Claim A (rule #12).
            logger.warning(
                "Contradiction detection cited an unknown existing claim: %r", conflict.existing_claim_text
            )
            continue
        pages.append(
            build_contradiction_page(
                conflict,
                existing_claim=existing_claim,
                new_claim_source=new_claim_source,
                new_claim_date=new_claim_date,
                affected_pages=affected_pages,
            )
        )
    return pages
