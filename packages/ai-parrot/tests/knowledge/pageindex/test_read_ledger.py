"""FEAT-843 M1 — ReadLedger."""

import pytest

from parrot.knowledge.pageindex.read_ledger import BudgetExhausted, ReadLedger
from parrot.knowledge.pageindex.segments import ReadResult, SegmentAddress, SegmentRead

REV_A = "a" * 16
REV_B = "b" * 16


def _result(doc: str, rev: str, seq: int, start: int, end: int, generation: int | None = 1) -> ReadResult:
    addr = SegmentAddress(doc_id=doc, revision=rev, seq=seq, page=1, ordinal=1)
    read = SegmentRead(address=addr, seq=seq, kind="paragraph", text="x" * (end - start), start=start, end=end)
    return ReadResult(
        tree_name="t",
        doc_id=doc,
        revision=rev,
        generation=generation,
        segments=[read],
        truncated=False,
        next_cursor=None,
        framed="",
    )


def test_touching_ranges_merge():
    """Adjacent half-open ranges cover one continuous interval."""
    ledger = ReadLedger(budget_chars=2_000, max_reads=3)
    ledger.record(_result("doc", REV_A, 1, 0, 500))
    ledger.record(_result("doc", REV_A, 1, 500, 900))
    assert ledger.covered("doc", REV_A, 1) == [(0, 900)]


def test_gap_kept_separate():
    """Non-touching ranges remain separate coverage intervals."""
    ledger = ReadLedger(budget_chars=2_000, max_reads=3)
    ledger.record(_result("doc", REV_A, 1, 0, 500))
    ledger.record(_result("doc", REV_A, 1, 600, 900))
    assert ledger.covered("doc", REV_A, 1) == [(0, 500), (600, 900)]


def test_other_revision_separate_key():
    """Coverage from separate revisions cannot merge."""
    ledger = ReadLedger(budget_chars=2_000, max_reads=3)
    ledger.record(_result("doc", REV_A, 1, 0, 500))
    ledger.record(_result("doc", REV_B, 1, 0, 500))
    assert ledger.covered("doc", REV_A, 1) == [(0, 500)]
    assert ledger.covered("doc", REV_B, 1) == [(0, 500)]
    assert ledger.has_revision("doc", REV_A)
    assert ledger.has_revision("doc", REV_B)


def test_charge_grants_below_500():
    """The final allowance is not rounded up to a minimum chunk size."""
    ledger = ReadLedger(budget_chars=100, max_reads=1)
    assert ledger.charge(12_000) == 100


def test_charge_raises_on_max_reads_and_chars_exhausted():
    """Read count and delivered-character budget independently prevent charges."""
    maxed = ReadLedger(budget_chars=100, max_reads=1)
    maxed.record(_result("doc", REV_A, 1, 0, 1))
    with pytest.raises(BudgetExhausted):
        maxed.charge(1)

    spent = ReadLedger(budget_chars=100, max_reads=2)
    spent.record(_result("doc", REV_A, 1, 0, 100))
    with pytest.raises(BudgetExhausted):
        spent.charge(1)


def test_repeated_reads_count_chars_again_but_coverage_unique():
    """Budget consumption tracks delivery, while citations use merged coverage."""
    ledger = ReadLedger(budget_chars=1_000, max_reads=3)
    result = _result("doc", REV_A, 1, 10, 30)
    ledger.record(result)
    ledger.record(result)
    assert ledger.chars_read == 40
    assert ledger.covered("doc", REV_A, 1) == [(10, 30)]
    assert ledger.entries()[0].chars == 20


def test_generation_pinned_on_first_record():
    """The first non-null result generation is retained for the request."""
    ledger = ReadLedger(budget_chars=1_000, max_reads=3)
    ledger.record(_result("doc", REV_A, 1, 0, 1, generation=4))
    ledger.record(_result("doc", REV_A, 2, 0, 1, generation=9))
    assert ledger.generation == 4


def test_entries_sorted():
    """Ledger entries have deterministic document-revision-segment ordering."""
    ledger = ReadLedger(budget_chars=1_000, max_reads=3)
    ledger.record(_result("b", REV_B, 2, 0, 1))
    ledger.record(_result("a", REV_B, 3, 0, 1))
    ledger.record(_result("a", REV_A, 4, 0, 1))
    assert [(entry.doc_id, entry.revision, entry.seq) for entry in ledger.entries()] == [
        ("a", REV_A, 4),
        ("a", REV_B, 3),
        ("b", REV_B, 2),
    ]
