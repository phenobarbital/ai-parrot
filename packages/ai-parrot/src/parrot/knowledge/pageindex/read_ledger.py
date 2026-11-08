"""Request-local read ledger for PageIndex agentic retrieval (FEAT-843).

Records the half-open character ranges of stored segment text that read tools actually
returned. Cursors are not a ledger; only ranges recorded here are citable.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex.segments import ReadResult, SegmentRead

Range = tuple[int, int]
_Key = tuple[str, str, int]

__all__ = ["Range", "BudgetExhausted", "LedgerEntry", "ReadLedger"]


class BudgetExhausted(RuntimeError):
    """Internal read-budget signal, caught by the wrapper; never a provider-loop stop mechanism."""


class LedgerEntry(BaseModel):
    """Merged coverage of one segment of one document revision."""

    doc_id: str
    revision: str
    seq: int
    ranges: list[Range]
    chars: int


def _merge(ranges: list[Range], new: Range) -> list[Range]:
    """Insert ``new`` into sorted disjoint ``ranges``; touching or overlapping ranges merge."""
    merged: list[Range] = []
    for start, end in sorted([*ranges, new]):
        if merged and merged[-1][1] >= start:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


class ReadLedger:
    """Ranges delivered to the model in one request, plus its read budget."""

    def __init__(self, *, budget_chars: int, max_reads: int) -> None:
        self._budget_chars = int(budget_chars)
        self._max_reads = int(max_reads)
        self._ranges: dict[_Key, list[Range]] = {}
        self._chars_read = 0
        self._reads = 0
        self._generation: Optional[int] = None

    def charge(self, requested_chars: int) -> int:
        """Grant at most the remaining characters, including allowances below 500.

        Raise ``BudgetExhausted`` when ``reads >= max_reads`` or nothing is left.
        Caller holds the read lock through charge, read, clipping and record.
        """
        remaining = self._budget_chars - self._chars_read
        if self._reads >= self._max_reads or remaining <= 0:
            raise BudgetExhausted
        return min(requested_chars, remaining)

    def record(self, result: ReadResult) -> None:
        """Merge every read range in ``result`` into its document-revision-segment entry.

        Touching or overlapping ranges merge; a read from another revision is a separate entry.
        Records ``result.generation`` on first use and counts delivered ``chars`` and ``reads``.
        Counts repeated characters again for budget accounting, independently of merged coverage.
        """
        if self._generation is None and result.generation is not None:
            self._generation = result.generation
        self._reads += 1
        for read in result.segments:
            self._add(read)

    def _add(self, read: SegmentRead) -> None:
        """Record one non-empty segment range and its delivered character count."""
        if read.end <= read.start:
            return
        key = (read.address.doc_id, read.address.revision, read.seq)
        self._ranges[key] = _merge(self._ranges.get(key, []), (read.start, read.end))
        self._chars_read += read.end - read.start

    def covered(self, doc_id: str, revision: str, seq: int) -> list[Range]:
        """Return sorted, disjoint ranges covered for one segment."""
        return list(self._ranges.get((doc_id, revision, seq), []))

    def has_revision(self, doc_id: str, revision: str) -> bool:
        """Return whether any segment of the document revision was recorded."""
        return any(key[0] == doc_id and key[1] == revision for key in self._ranges)

    def entries(self) -> list[LedgerEntry]:
        """Return coverage entries sorted by document, revision, and segment sequence."""
        return [
            LedgerEntry(
                doc_id=key[0],
                revision=key[1],
                seq=key[2],
                ranges=list(ranges),
                chars=sum(end - start for start, end in ranges),
            )
            for key, ranges in sorted(self._ranges.items())
        ]

    @property
    def chars_read(self) -> int:
        """Return delivered characters, including repeated reads."""
        return self._chars_read

    @property
    def reads(self) -> int:
        """Return recorded read results."""
        return self._reads

    @property
    def generation(self) -> Optional[int]:
        """Return the first non-null generation recorded by this ledger."""
        return self._generation
