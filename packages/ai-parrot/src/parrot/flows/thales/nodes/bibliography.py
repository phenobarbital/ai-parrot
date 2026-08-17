"""BibliographyNode + `format_apa` — deterministic APA-ish formatting (FEAT-425 Module 3).

``format_apa`` is a pure function (no LLM, no node machinery) so it is
exhaustively table-driven-testable in isolation. ``BibliographyNode`` wraps
it as a fan-in over all of a run's ``ResearchDeck``s.
"""

from __future__ import annotations

from typing import Any, Optional, Set

from pydantic import Field

from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.types import DependencyResults
from parrot.flows.thales.models import Bibliography, ResearchDeck, SourceClaim


def _normalize_url(url: str) -> str:
    """Normalize a URL for dedupe comparison (case/trailing-slash insensitive)."""
    return url.strip().rstrip("/").lower()


def _dedupe_claims(claims: list[SourceClaim]) -> list[SourceClaim]:
    """Drop later claims that share a normalized URL with an earlier one."""
    seen: set[str] = set()
    deduped: list[SourceClaim] = []
    for claim in claims:
        key = _normalize_url(claim.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def _year_from_date(published_date: Optional[str]) -> str:
    """Derive an APA-ish year token from an ISO date string.

    Renders ``"n.d."`` when the date is missing — NEVER invents a year.
    """
    if not published_date or len(published_date) < 4:
        return "n.d."
    return published_date[:4]


def _sort_key(claim: SourceClaim) -> str:
    """Deterministic ordering key: first author, else publisher, else title/url."""
    if claim.authors:
        return claim.authors[0].lower()
    if claim.publisher:
        return claim.publisher.lower()
    if claim.title:
        return claim.title.lower()
    return claim.url.lower()


def _format_entry(claim: SourceClaim) -> str:
    """Format one APA-ish bibliography entry.

    - With authors: ``"Author(s) (year). Title. Publisher. URL"``
    - Without authors (publisher-led): ``"Publisher. (year). Title. URL"``
    - Missing date renders ``"(n.d.)"`` in either form — never invented.
    """
    year = _year_from_date(claim.published_date)
    title = (claim.title or "Untitled").rstrip(".")

    if claim.authors:
        lead = ", ".join(claim.authors)
        parts = [f"{lead} ({year}).", f"{title}."]
        if claim.publisher:
            parts.append(f"{claim.publisher}.")
        parts.append(claim.url)
    else:
        publisher = claim.publisher or "Unknown"
        parts = [f"{publisher}. ({year}).", f"{title}.", claim.url]

    return " ".join(parts)


def format_apa(claims: list[SourceClaim]) -> Bibliography:
    """Deterministically format a claim list into an APA-ish ``Bibliography``.

    Args:
        claims: Source claims to format, in any order, possibly containing
            duplicate URLs.

    Returns:
        A ``Bibliography`` with deduplicated, deterministically-ordered
        ``entries`` (alphabetical by first author/publisher/title) and the
        corresponding deduplicated ``claims`` in the same order.
    """
    deduped = _dedupe_claims(claims)
    ordered = sorted(deduped, key=_sort_key)
    entries = [_format_entry(claim) for claim in ordered]
    return Bibliography(entries=entries, claims=ordered)


def _parse_deck(raw: str) -> Optional[ResearchDeck]:
    """Parse one upstream dependency's raw JSON into a ``ResearchDeck``.

    Returns ``None`` for anything that isn't a valid ``ResearchDeck`` (e.g.
    a dropped-deck sentinel from ``DeckBuilderNode`` — it carries no claims).
    """
    try:
        return ResearchDeck.model_validate_json(raw)
    except Exception:  # noqa: BLE001 - any malformed/sentinel payload is skipped
        return None


class BibliographyNode(Node):
    """Fan-in over all decks -> one deterministic ``Bibliography``.

    Args:
        node_id: Unique identifier within the graph.
        dependencies: Set of node_ids that must complete first — expected
            to be every angle's ``DeckBuilderNode``.
        successors: Set of node_ids that depend on this one.
        fsm: Auto-created if ``None``.
    """

    node_id: str
    dependencies: Set[str] = Field(default_factory=set)
    successors: Set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context: Any) -> None:
        """Auto-create FSM and call parent hook (initialises ``self.logger``)."""
        super().model_post_init(__context)
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        """Node identifier."""
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs: Any,
    ) -> str:
        """Collect every deck's claims and format them into one ``Bibliography``.

        Args:
            ctx: The current flow execution context (unused — pure aggregation).
            deps: Mapping of angle DeckBuilderNode node_id -> JSON-encoded
                ``ResearchDeck`` (or a dropped-deck sentinel, skipped).

        Returns:
            The ``Bibliography`` as JSON.
        """
        claims: list[SourceClaim] = []
        for raw in deps.values():
            deck = _parse_deck(raw)
            if deck is None:
                continue
            for finding in deck.findings:
                claims.extend(finding.claims)

        bibliography = format_apa(claims)
        return bibliography.model_dump_json()
