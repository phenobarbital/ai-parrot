"""FEAT-843 M2 — citation validator and renderer."""

import pytest

from parrot.knowledge.pageindex.citations import (
    ProposedCitation,
    find_covered_match,
    parse_address_key,
    render_citation,
    render_citations,
    validate_citations,
)
from parrot.knowledge.pageindex.read_ledger import ReadLedger
from parrot.knowledge.pageindex.segments import DocumentRevision, ReadResult, Segment, SegmentAddress, SegmentRead, SourceInfo

REVISION = "a" * 16


def _revision(
    text: str, *, page: int | None = 2, section: list[str] | None = None, ordinal: int = 0
) -> DocumentRevision:
    """Build a one-segment revision used by validator tests."""
    return DocumentRevision(
        doc_id="doc",
        revision=REVISION,
        source=SourceInfo(name="doc.pdf" if page else "Notes.md", kind="pdf" if page else "markdown"),
        created_at="2026-01-01T00:00:00Z",
        segments=[
            Segment(
                seq=0,
                kind="paragraph",
                page=page,
                ordinal=ordinal,
                section=section,
                text=text,
                tokens=len(text.split()),
                sha16="b" * 16,
            )
        ],
    )


def _ledger(
    *ranges: tuple[int, int], revision: str = REVISION, ledger: ReadLedger | None = None
) -> ReadLedger:
    """Record ranges from the test revision's only segment."""
    ledger = ledger or ReadLedger(budget_chars=10_000, max_reads=20)
    address = SegmentAddress(doc_id="doc", revision=revision, seq=0, page=2, ordinal=0)
    for start, end in ranges:
        ledger.record(
            ReadResult(
                tree_name="tree",
                doc_id="doc",
                revision=revision,
                segments=[
                    SegmentRead(
                        address=address,
                        seq=0,
                        kind="paragraph",
                        text="x" * (end - start),
                        start=start,
                        end=end,
                    )
                ],
                framed="",
            )
        )
    return ledger


def _proposal(excerpt: str, address: str | None = None) -> ProposedCitation:
    """Build a proposal targeting the one-segment test revision."""
    return ProposedCitation(address=address or f"doc@{REVISION}#0", excerpt=excerpt)


def test_parse_address_key_accepts_only_document_revision_segment_shape():
    """Citation addresses accept the address-key grammar and reject all other shapes."""
    assert parse_address_key(f"doc_1@{REVISION}#12") == ("doc_1", REVISION, 12)
    for bad in ("", "doc@short#0", f"doc@{REVISION}#-1", f"doc@{REVISION}#0+1"):
        with pytest.raises(ValueError):
            parse_address_key(bad)


def test_validator_rejects_then_keeps_exact_covered_slice():
    """A matching excerpt is citable only after its entire stored slice is covered."""
    text = "x" * 700 + "y" * 60 + "z" * 440
    revision = _revision(text)
    proposal = _proposal("y" * 60)

    kept, rejected = validate_citations(_ledger((0, 500)), lambda *_: revision, [proposal])
    assert kept == []
    assert [item.reason for item in rejected] == ["outside_covered_ranges"]

    kept, rejected = validate_citations(_ledger((0, 500), (500, 1200)), lambda *_: revision, [proposal])
    assert rejected == []
    assert (kept[0].start, kept[0].end, kept[0].excerpt) == (700, 760, "y" * 60)


def test_validator_requires_one_range_and_uses_first_covered_repetition():
    """Matches spanning a gap fail, while the first covered repeated match wins."""
    spanning = _revision("x" * 480 + "match" * 28 + "x" * 280)
    kept, rejected = validate_citations(_ledger((0, 500), (600, 900)), lambda *_: spanning, [_proposal("match" * 28)])
    assert kept == []
    assert [item.reason for item in rejected] == ["outside_covered_ranges"]

    text = "x" * 100 + "repeat" + "x" * 444 + "repeat" + "x" * 450
    repeated = _revision(text)
    kept, rejected = validate_citations(_ledger((0, 700)), lambda *_: repeated, [_proposal("repeat")])
    assert rejected == []
    assert kept[0].start == 100


def test_validator_normalizes_whitespace_and_searches_interval_bounds():
    """Whitespace normalization preserves stored offsets and interval search avoids earlier overlap."""
    revision = _revision("two words here")
    kept, rejected = validate_citations(_ledger((0, 15)), lambda *_: revision, [_proposal("two  words\nhere")])
    assert rejected == []
    assert kept[0].excerpt == "two words here"
    assert find_covered_match("a a a", "a a", [(2, 5)]) == (2, 5)


def test_validator_rejection_ladder_and_duplicate_collapse():
    """Validator reports the specified rejection reasons and ignores duplicate proposals."""
    revision = _revision("visible text")
    loaded: list[tuple[str, str]] = []

    def load(doc_id: str, revision_id: str) -> DocumentRevision | None:
        loaded.append((doc_id, revision_id))
        return None if revision_id == "b" * 16 else revision

    unread = _proposal("text", f"other@{REVISION}#0")
    unavailable = _proposal("text", f"doc@{'b' * 16}#0")
    bad = _proposal("text", "not-an-address")
    empty = _proposal("   ")
    segment_unread = _proposal("text", f"doc@{REVISION}#1")
    missing = _proposal("missing")
    duplicate = _proposal(" visible   text ")
    ledger = _ledger((0, 12))
    _ledger((0, 1), revision="b" * 16, ledger=ledger)
    kept, rejected = validate_citations(
        ledger, load, [bad, empty, unread, unavailable, segment_unread, missing, _proposal("visible text"), duplicate]
    )

    assert [item.reason for item in rejected] == [
        "bad_address",
        "empty_excerpt",
        "revision_unread",
        "revision_unavailable",
        "segment_unread",
        "excerpt_not_found",
    ]
    assert len(kept) == 1
    assert loaded == [("doc", "b" * 16), ("doc", REVISION), ("doc", REVISION), ("doc", REVISION)]


def test_renderer_uses_paged_and_section_labels():
    """Rendered citations use document names and the SegmentAddress display labels."""
    paged = _revision("visible", page=2)
    notes = _revision("visible", page=None, section=["Setup", "Install"], ordinal=1)
    paged_citation = validate_citations(_ledger((0, 7)), lambda *_: paged, [_proposal("visible")])[0][0]
    notes_citation = validate_citations(_ledger((0, 7)), lambda *_: notes, [_proposal("visible")])[0][0]
    assert render_citation(paged_citation) == "[doc.pdf, p. 2 ¶1]"
    assert render_citation(notes_citation) == "[Notes.md, Setup > Install ¶2]"
    assert render_citations([paged_citation, notes_citation]) == "[doc.pdf, p. 2 ¶1]; [Notes.md, Setup > Install ¶2]"
