# TASK-5322: Citation models, exact-range validator and renderer

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5320
**Assigned-to**: unassigned

---

## Context

Spec §2 "Validation (M2)", "Rendering (M2)", §3 Module 2, AC-3..AC-7, AC-20. A citation is
kept only when its revision + segment are in the read ledger and its excerpt (after whitespace
normalisation) equals a stored slice lying entirely inside ONE merged covered range.
`start`/`end` are computed here, never taken from the model.

---

## Scope

- Create `knowledge/pageindex/citations.py`: `ProposedCitation`, `Citation`, `RejectedCitation`,
  `parse_address_key`, `normalize_ws`, `find_covered_match`, `find_any_match`,
  `validate_citations`, `render_citation`, `render_citations`.
- Search each covered interval with `pattern.search(text, lo, hi)` — never filter a whole-segment
  `finditer` (AC-20: `"a a a"`, excerpt `"a a"`, covered `[2,5)` → `[2,5)`).
- Rejection reasons, in check order: `bad_address` → `empty_excerpt` → `revision_unread`
  (ledger has no entry for that doc+revision) → `revision_unavailable` (`load_revision` → `None`)
  → `segment_unread` (revision read, this seq not; or seq out of range) → `outside_covered_ranges` / `excerpt_not_found`.
- Duplicates (same address + normalised excerpt) collapse to the first; order preserved.
- Write `test_citations.py`.

**NOT in scope**: async preloading of revisions (TASK-5324 passes an in-memory callback);
`AgenticAnswer` (lives in `agentic.py`, TASK-5323).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py` | CREATE | Models, validator, renderer |
| `packages/ai-parrot/tests/knowledge/pageindex/test_citations.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import DocumentRevision, SegmentAddress   # segments.py:59, :71
from parrot.knowledge.pageindex.read_ledger import ReadLedger, Range               # created by TASK-5320
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
_CURSOR_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})@([0-9a-f]{16})#(\d+)\+(\d+)$")   # :19 (same alphabet; no +offset here)
class Segment(BaseModel): seq, kind, page=None, ordinal, section=None, level=None, text, tokens, sha16, flags, injection  # :33
class SourceInfo(BaseModel): name, kind, path=None, pages=None                                   # :49
class DocumentRevision(BaseModel): doc_id, revision, source: SourceInfo, segmenter, scored_by, created_at, segments: list[Segment]  # :59
class SegmentAddress(BaseModel): doc_id, revision, seq, page=None, ordinal, section=None        # :71
    @property label -> str   # "p. 12 ¶3" | "Setup > Install ¶2"                                # :82
    @property key -> str     # "<doc_id>@<revision>#<seq>"                                       # :92

# read_ledger.py (TASK-5320)
ReadLedger.covered(doc_id, revision, seq) -> list[Range]   # sorted, disjoint, merged
ReadLedger.has_revision(doc_id, revision) -> bool
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.citations`~~ — you create it.
- ~~`knowledge/contracts/carding.py: validate_obligation_clauses` reuse~~ — different normalisation, no ranges; do not import it.
- ~~`SegmentAddress.from_key` / `parse_address`~~ in `segments.py` — write `parse_address_key` here.
- ~~`OKFToolkit.cite` changes~~ — untouched.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_citations.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#DocumentRevision",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#SegmentAddress"
  ]
}
```

---

## Implementation Notes

- Pattern: tokens of `normalize_ws(excerpt).split(" ")`, each `re.escape`d, joined by `r"\s+"`.
  Offsets index the STORED text; normalise only for comparison.
- `Citation.excerpt` = `segment.text[start:end]` (the stored slice, verbatim).
- `load_revision` signature is `Callable[[str, str], Optional[DocumentRevision]]` = `(doc_id, revision)`
  — the caller binds `tree_name` (the store's real method is `load_revision(tree_name, doc_id, revision)`).

---

## Implementation Blueprint

### Steps (in order)
1. Create `citations.py` from the block.
2. Fill matching and the validation loop.
3. Tests; run.

### `citations.py` (CREATE)
```python
"""Citations for PageIndex agentic retrieval (FEAT-843): models, exact-range validator, renderer."""
from __future__ import annotations

import re
from typing import Callable, Literal, Optional, Sequence

from pydantic import BaseModel

from parrot.knowledge.pageindex.read_ledger import Range, ReadLedger
from parrot.knowledge.pageindex.segments import DocumentRevision, SegmentAddress

__all__ = [
    "ProposedCitation", "Citation", "RejectedCitation", "RejectReason", "parse_address_key", "normalize_ws",
    "find_covered_match", "find_any_match", "validate_citations", "render_citation", "render_citations",
]

_ADDRESS_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})@([0-9a-f]{16})#(\d+)$")

RejectReason = Literal["bad_address", "revision_unread", "revision_unavailable", "segment_unread",
                       "empty_excerpt", "excerpt_not_found", "outside_covered_ranges"]


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
    proposed: ProposedCitation
    reason: RejectReason


def parse_address_key(key: str) -> tuple[str, str, int]:
    """``doc@rev#seq`` → ``(doc_id, revision, seq)``; ``ValueError`` on any other shape."""
    m = _ADDRESS_RE.match((key or "").strip())
    if m is None:
        raise ValueError(f"bad citation address: {key!r}")
    return m.group(1), m.group(2), int(m.group(3))


def normalize_ws(text: str) -> str:
    """``" ".join(text.split())`` — the only normalisation the validator applies."""
    return " ".join(text.split())


def _pattern(excerpt: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(tok) for tok in normalize_ws(excerpt).split(" ")))


def find_covered_match(segment_text: str, excerpt: str, covered: list[Range]) -> Optional[Range]:
    """First match lying inside ONE covered range; each range searched with explicit pos/endpos."""
    # FILL IN: for lo, hi in covered (ascending): m = pat.search(segment_text, lo, hi); return (m.start(), m.end()) — AC-4, AC-20
    raise NotImplementedError


def find_any_match(segment_text: str, excerpt: str) -> bool:
    return _pattern(excerpt).search(segment_text) is not None


def validate_citations(
    ledger: ReadLedger,
    load_revision: Callable[[str, str], Optional[DocumentRevision]],
    proposed: Sequence[ProposedCitation],
) -> tuple[list[Citation], list[RejectedCitation]]:
    """Keep a citation only if its revision+segment were read and its excerpt is a covered slice.

    Order preserved; duplicates (same address+excerpt) collapse to the first. ``start``/``end`` are
    computed here, never taken from the model."""
    kept: list[Citation] = []
    rejected: list[RejectedCitation] = []
    seen: set[tuple[str, str]] = set()
    for p in proposed:
        # FILL IN: dedupe on (address.strip(), normalize_ws(excerpt)); then the reason ladder in Scope order;
        #          on success build Citation from SegmentAddress(...).label and revision.source.name — AC-3..AC-6
        raise NotImplementedError
    return kept, rejected


def render_citation(c: Citation) -> str:
    """``[<document>, <label>]`` e.g. ``[Report.pdf, p. 12 ¶3]``."""
    return f"[{c.document}, {c.label}]"


def render_citations(cs: Sequence[Citation]) -> str:
    return "; ".join(render_citation(c) for c in cs)
```
**Why**: `RejectReason` is a named alias so `EvidenceBundle` / tests reuse it. `revision_unread` is
checked BEFORE loading — because a revision never shown to the model must fail without I/O.

### `test_citations.py` (CREATE)
```python
"""FEAT-843 M2 — citation validator and renderer."""
from parrot.knowledge.pageindex.citations import (
    ProposedCitation, find_covered_match, parse_address_key, render_citation, validate_citations,
)
from parrot.knowledge.pageindex.read_ledger import ReadLedger
# FILL IN: helper building a DocumentRevision with one 1,200-char segment (see segments.py:33-68 for required fields)
#          and a ledger helper recording ranges via ReadResult/SegmentRead
# FILL IN: parse_address_key good/bad shapes
# FILL IN: AC-3 prefix [0,500) rejects [700,760) outside_covered_ranges; after [500,1200) kept start=700,end=760
# FILL IN: AC-4 reads [0,500)+[600,900): span [480,620) rejected; repeated excerpt at 100 and 550 -> start=100
# FILL IN: AC-5 "two  words\nhere" vs stored "two words here"
# FILL IN: AC-6 revision_unread / revision_unavailable (callback returns None) / bad_address; empty_excerpt; segment_unread
# FILL IN: AC-20 find_covered_match("a a a", "a a", [(2,5)]) == (2,5)
# FILL IN: duplicates collapse; AC-7 render "[doc.pdf, p. 2 ¶1]" and "[Notes.md, Setup > Install ¶2]"
```

### FILL IN checklist
- [ ] `find_covered_match`
- [ ] validation loop
- [ ] all tests

---

## Acceptance Criteria

- [ ] AC-3, AC-4, AC-5, AC-6, AC-7, AC-20.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_citations.py -q`

---

## Test Specification

Spec §4 row `test_citations.py`; fixture "a a a" from §4 Test Data.

---

## Agent Instructions

1. Confirm TASK-5320's `read_ledger.py` exports `Range`, `ReadLedger.has_revision`.
2. `ruff check --fix`; run validation with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit: `feat(pageindex-agentic-retrieval): TASK-5322 — citations validator`.

---

## Completion Note

*(Agent fills this in when done)*
