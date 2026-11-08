"""Citations for PageIndex agentic retrieval (FEAT-843): models, exact-range validator, renderer."""

from __future__ import annotations

import re
from typing import Callable, Literal, Optional, Sequence

from pydantic import BaseModel

from parrot.knowledge.pageindex.read_ledger import Range, ReadLedger
from parrot.knowledge.pageindex.segments import DocumentRevision, SegmentAddress

__all__ = [
    "ProposedCitation",
    "Citation",
    "RejectedCitation",
    "RejectReason",
    "parse_address_key",
    "normalize_ws",
    "find_covered_match",
    "find_any_match",
    "validate_citations",
    "render_citation",
    "render_citations",
]

_ADDRESS_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})@([0-9a-f]{16})#(\d+)$")

RejectReason = Literal[
    "bad_address",
    "revision_unread",
    "revision_unavailable",
    "segment_unread",
    "empty_excerpt",
    "excerpt_not_found",
    "outside_covered_ranges",
]


class ProposedCitation(BaseModel):
    """What the model proposes: an address key and a verbatim excerpt."""

    address: str
    excerpt: str


class Citation(BaseModel):
    """A validated citation; ``start``/``end`` are computed by the validator (half-open, stored text)."""

    doc_id: str
    revision: str
    seq: int
    page: Optional[int] = None
    ordinal: int
    section: Optional[list[str]] = None
    start: int
    end: int
    excerpt: str
    label: str
    document: str


class RejectedCitation(BaseModel):
    """A proposed citation rejected by the validation ladder."""

    proposed: ProposedCitation
    reason: RejectReason


def parse_address_key(key: str) -> tuple[str, str, int]:
    """Parse ``doc@rev#seq`` into ``(doc_id, revision, seq)``.

    Raises:
        ValueError: If the key does not use the supported address shape.
    """
    match = _ADDRESS_RE.match((key or "").strip())
    if match is None:
        raise ValueError(f"bad citation address: {key!r}")
    return match.group(1), match.group(2), int(match.group(3))


def normalize_ws(text: str) -> str:
    """Normalize all runs of whitespace to one space."""
    return " ".join(text.split())


def _pattern(excerpt: str) -> re.Pattern[str]:
    """Build a pattern that permits arbitrary stored whitespace between excerpt tokens."""
    return re.compile(r"\s+".join(re.escape(token) for token in normalize_ws(excerpt).split(" ")))


def find_covered_match(segment_text: str, excerpt: str, covered: list[Range]) -> Optional[Range]:
    """Return the first excerpt match contained entirely in one covered range."""
    pattern = _pattern(excerpt)
    for start, end in covered:
        match = pattern.search(segment_text, start, end)
        if match is not None:
            return match.start(), match.end()
    return None


def find_any_match(segment_text: str, excerpt: str) -> bool:
    """Return whether the normalized excerpt occurs anywhere in stored text."""
    return _pattern(excerpt).search(segment_text) is not None


def validate_citations(
    ledger: ReadLedger,
    load_revision: Callable[[str, str], Optional[DocumentRevision]],
    proposed: Sequence[ProposedCitation],
) -> tuple[list[Citation], list[RejectedCitation]]:
    """Validate proposed citations against read coverage and loaded document revisions.

    Order is preserved and proposals with an already-seen normalized address and excerpt are ignored.
    """
    kept: list[Citation] = []
    rejected: list[RejectedCitation] = []
    seen: set[tuple[str, str]] = set()
    for proposal in proposed:
        duplicate_key = (proposal.address.strip(), normalize_ws(proposal.excerpt))
        if duplicate_key in seen:
            continue
        seen.add(duplicate_key)

        try:
            doc_id, revision_id, seq = parse_address_key(proposal.address)
        except ValueError:
            rejected.append(RejectedCitation(proposed=proposal, reason="bad_address"))
            continue
        if not normalize_ws(proposal.excerpt):
            rejected.append(RejectedCitation(proposed=proposal, reason="empty_excerpt"))
            continue
        if not ledger.has_revision(doc_id, revision_id):
            rejected.append(RejectedCitation(proposed=proposal, reason="revision_unread"))
            continue

        revision = load_revision(doc_id, revision_id)
        if revision is None:
            rejected.append(RejectedCitation(proposed=proposal, reason="revision_unavailable"))
            continue
        covered = ledger.covered(doc_id, revision_id, seq)
        if seq >= len(revision.segments) or not covered:
            rejected.append(RejectedCitation(proposed=proposal, reason="segment_unread"))
            continue

        segment = revision.segments[seq]
        match = find_covered_match(segment.text, proposal.excerpt, covered)
        if match is None:
            reason: RejectReason = "outside_covered_ranges" if find_any_match(segment.text, proposal.excerpt) else "excerpt_not_found"
            rejected.append(RejectedCitation(proposed=proposal, reason=reason))
            continue

        start, end = match
        address = SegmentAddress(
            doc_id=doc_id,
            revision=revision_id,
            seq=seq,
            page=segment.page,
            ordinal=segment.ordinal,
            section=segment.section,
        )
        kept.append(
            Citation(
                doc_id=doc_id,
                revision=revision_id,
                seq=seq,
                page=segment.page,
                ordinal=segment.ordinal,
                section=segment.section,
                start=start,
                end=end,
                excerpt=segment.text[start:end],
                label=address.label,
                document=revision.source.name,
            )
        )
    return kept, rejected


def render_citation(citation: Citation) -> str:
    """Render a citation as ``[<document>, <label>]``."""
    return f"[{citation.document}, {citation.label}]"


def render_citations(citations: Sequence[Citation]) -> str:
    """Render citations in input order, separated by semicolons."""
    return "; ".join(render_citation(citation) for citation in citations)
