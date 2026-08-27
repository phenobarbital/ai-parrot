"""Unit tests for the deterministic span existence gate (FEAT-449 TASK-2495)."""

from datetime import date

from parrot_tools.legal.boe.hashing import seal_hash
from parrot_tools.legal.librarian.models import (
    DraftAnswer,
    DraftConflictNote,
    DraftReadingNote,
    DraftSpan,
    PayloadEntry,
)
from parrot_tools.legal.librarian.verifier import SpanVerifier

TEXT = "El plazo será de tres meses. El plazo se cuenta desde la notificación."


def entry(text=TEXT, h=None, payload_key="BOE-A-2000-1:art1:0"):
    return PayloadEntry(
        payload_key=payload_key,
        payload=text,
        content_hash=h or seal_hash(text),
        title="t",
        url="u",
        as_of=date(2024, 1, 1),
        version_n=0,
        articulo_key="BOE-A-2000-1:art1",
        basis="retrieval",
    )


def draft(key="BOE-A-2000-1:art1:0", quote="tres meses"):
    return DraftAnswer(
        reading_order=[key],
        conflicts=[],
        not_found=[],
        reading_guide=[
            DraftReadingNote(
                text="Plazo de tres meses.",
                basis="llm",
                spans=[DraftSpan(payload_key=key, quote=quote)],
            )
        ],
    )


def run(d, rs):
    return SpanVerifier().verify(d, rs, as_of=date(2024, 1, 1), materias=["civil"], execution_id="x")


def test_span_verifier_hash_mismatch_prunes():
    ans, recs = run(draft(), {"BOE-A-2000-1:art1:0": entry(h="deadbeef")})
    assert ans.dossier == []
    assert recs[0].reason == "hash_mismatch"
    assert ans.suppressed_count == 1


def test_span_verifier_quote_mismatch_prunes():
    _ans, recs = run(draft(quote="cuatro meses"), {"BOE-A-2000-1:art1:0": entry()})
    assert recs[0].reason == "quote_mismatch"


def test_span_verifier_unknown_key_prunes():
    ans, recs = run(draft(key="unknown:0"), {})
    assert recs[0].reason == "span_not_found"
    assert ans.dossier == []


def test_offsets_are_first_occurrence_and_slice_equals_quote():
    ans, recs = run(draft(quote="El plazo"), {"BOE-A-2000-1:art1:0": entry()})
    ref = ans.dossier[0]
    assert (ref.start, ref.end) == (0, 8)
    assert TEXT[ref.start : ref.end] == ref.quote
    assert recs == []


def test_reading_note_loses_all_anchors_is_suppressed():
    ans, recs = run(draft(quote="not present anywhere"), {"BOE-A-2000-1:art1:0": entry()})
    assert ans.reading_guide == []
    assert ans.suppressed_count == 1
    assert recs[0].claimed_anchors == ["BOE-A-2000-1:art1:0"]
    assert recs[0].suppressed_text == "Plazo de tres meses."


def test_conflict_with_pruned_side_dropped():
    good = DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="tres meses")
    bad = DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="not present anywhere")
    d = DraftAnswer(
        reading_order=[],
        conflicts=[DraftConflictNote(span_a=good, span_b=bad, note="conflict")],
        reading_guide=[],
        not_found=[],
    )
    ans, recs = run(d, {"BOE-A-2000-1:art1:0": entry()})
    assert ans.conflicts == []
    assert recs[0].reason == "anchor_lost"
    assert ans.suppressed_count == 1


def test_conflict_with_both_sides_surviving_kept():
    span_a = DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="tres meses")
    span_b = DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="notificación")
    d = DraftAnswer(
        reading_order=[],
        conflicts=[DraftConflictNote(span_a=span_a, span_b=span_b, note="conflict")],
        reading_guide=[],
        not_found=[],
    )
    ans, recs = run(d, {"BOE-A-2000-1:art1:0": entry()})
    assert recs == []
    assert len(ans.conflicts) == 1
    assert len(ans.dossier) == 2


def test_empty_dossier_is_no_encontre():
    ans, _ = run(draft(key="nope:0"), {})
    assert ans.dossier == []
    assert ans.reading_guide == []
    assert ans.not_found


def test_reading_order_filtered_silently():
    d = DraftAnswer(
        reading_order=["BOE-A-2000-1:art1:0", "ghost:0"],
        conflicts=[],
        not_found=[],
        reading_guide=[
            DraftReadingNote(
                text="Plazo de tres meses.",
                basis="llm",
                spans=[DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="tres meses")],
            )
        ],
    )
    ans, _ = run(d, {"BOE-A-2000-1:art1:0": entry()})
    assert ans.reading_order == ["BOE-A-2000-1:art1:0"]


def test_dossier_deduped_by_span_key():
    d = DraftAnswer(
        reading_order=[],
        conflicts=[],
        not_found=[],
        reading_guide=[
            DraftReadingNote(
                text="Sentence one.",
                basis="llm",
                spans=[DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="tres meses")],
            ),
            DraftReadingNote(
                text="Sentence two.",
                basis="llm",
                spans=[DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="tres meses")],
            ),
        ],
    )
    ans, recs = run(d, {"BOE-A-2000-1:art1:0": entry()})
    assert len(ans.dossier) == 1
    assert len(ans.reading_guide) == 2
    assert recs == []
