"""Unit tests for the librarian answer-layer contracts (FEAT-449 TASK-2495)."""

from datetime import UTC, date, datetime

import pytest
from parrot_tools.legal.librarian.models import (
    DEFAULT_DISCLAIMER,
    ConflictNote,
    DraftAnswer,
    DraftConflictNote,
    DraftReadingNote,
    DraftSpan,
    LegalAnswer,
    PayloadEntry,
    ReadingNote,
    SpanRef,
    SuppressionRecord,
    span_key,
)


def _span_ref(**overrides) -> SpanRef:
    fields = {
        "kind": "articulo",
        "id": "BOE-A-2000-1:art1",
        "version_n": 0,
        "start": 0,
        "end": 5,
        "quote": "hello",
        "content_hash": "deadbeef",
        "hash_norm_version": 1,
        "title": "t",
        "url": "u",
        "as_of": date(2024, 1, 1),
        "basis": "retrieval",
    }
    fields.update(overrides)
    return SpanRef(**fields)


def test_span_key_format():
    ref = _span_ref()
    assert span_key(ref) == "BOE-A-2000-1:art1:0:0-5"


def test_legal_answer_defaults():
    answer = LegalAnswer(as_of=date(2024, 1, 1))
    assert answer.dossier == []
    assert answer.suppressed_count == 0
    assert answer.disclaimer == DEFAULT_DISCLAIMER


def test_reading_note_requires_at_least_one_span():
    with pytest.raises(ValueError):
        ReadingNote(text="x", spans=[], basis="llm")


def test_draft_reading_note_requires_at_least_one_span():
    with pytest.raises(ValueError):
        DraftReadingNote(text="x", spans=[], basis="llm")


def test_draft_span_is_key_and_quote_only():
    span = DraftSpan(payload_key="BOE-A-2000-1:art1:0", quote="hola")
    assert span.payload_key == "BOE-A-2000-1:art1:0"
    assert span.quote == "hola"
    assert not hasattr(span, "start")
    assert not hasattr(span, "end")


def test_payload_entry_shape():
    entry = PayloadEntry(
        payload_key="BOE-A-2000-1:art1:0",
        payload="texto",
        content_hash="deadbeef",
        title="t",
        url="u",
        as_of=date(2024, 1, 1),
        version_n=0,
        articulo_key="BOE-A-2000-1:art1",
        basis="retrieval",
    )
    assert entry.payload_key == "BOE-A-2000-1:art1:0"


def test_suppression_record_reason_is_closed_literal():
    with pytest.raises(ValueError):
        SuppressionRecord(
            execution_id="x",
            suppressed_text="y",
            claimed_anchors=[],
            reason="not_a_real_reason",
            user_id=None,
            created_at=datetime.now(UTC),
        )


def test_draft_answer_and_conflict_note_roundtrip():
    span_a = DraftSpan(payload_key="a:0", quote="foo")
    span_b = DraftSpan(payload_key="b:0", quote="bar")
    draft = DraftAnswer(
        reading_order=["a:0", "b:0"],
        conflicts=[DraftConflictNote(span_a=span_a, span_b=span_b, note="conflict")],
        reading_guide=[],
        not_found=[],
    )
    assert draft.conflicts[0].span_a.payload_key == "a:0"


def test_conflict_note_final_shape():
    note = ConflictNote(span_a="a:0:0-3", span_b="b:0:0-3", note="conflict")
    assert note.span_a == "a:0:0-3"
