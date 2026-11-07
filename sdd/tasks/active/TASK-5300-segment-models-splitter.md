# TASK-5300: Segment models, block splitter and addresses

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1**. Every other piece of FEAT-840 is defined on segments: the
store (TASK-5302), the transaction (TASK-5303), injection scanning (TASK-5305), framing
(TASK-5306), ownership (TASK-5301) and the read tools (TASK-5309). This task fixes the data
models and the pure, deterministic functions that turn markdown into segments, so that
`revision` can be a content hash.

---

## Scope

- Create `knowledge/pageindex/segments.py` with the Pydantic models of spec §2 *Data Models*:
  `SegmentKind`, `InjectionMark`, `Segment`, `SourceInfo`, `DocumentRevision`,
  `SegmentAddress` (with `label` and `key`), `SegmentRead`, `ReadResult`,
  `RevisionMismatchError`, `RevisionUnavailableError`.
- Implement `split_blocks`, `segment_pages`, `segment_text`, `revision_id`, `derive_doc_id`,
  `parse_page_spec`, `parse_cursor`, `format_cursor`.
- Write `tests/knowledge/pageindex/test_segments.py`.

**NOT in scope**: spans/ownership/rendering (TASK-5301 adds them to this same module),
persistence (TASK-5302), injection scoring (TASK-5305), framing (TASK-5306).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` | CREATE | Models + splitter + address helpers |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segments.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import utils as _utils   # verified: knowledge/pageindex/utils.py:66 defines count_tokens
```

### Existing Signatures to Use
```python
# knowledge/pageindex/utils.py
def count_tokens(text: str, model: str = "gpt-4o") -> int          # line 66 (tiktoken-based)

# knowledge/pageindex/md_builder.py  (PATTERN ONLY — copy the regexes, do not import private helpers)
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")                         # line 21
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")                      # line 24
def _fence_marker(line: str) -> tuple[str, int] | None               # line 27 — (char, length) of an opening fence
# parse_markdown_structure closes a fence on the same char with length >= opener and a line made
# only of that char (lines 81-97). Reproduce the same rule.

# knowledge/pageindex/pdf_to_markdown.py
def extract_markdown_per_page(...) -> list[tuple[int, str]]          # line 39 — dense, 1-based, empty pages are (n, "")
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.segments`~~ — created by this task
- ~~a segment, page or paragraph model anywhere under `knowledge/pageindex/`~~
- ~~`count_tokens` in `segments`~~ — always call `_utils.count_tokens(...)` through the module, never
  `from .utils import count_tokens`: the test suites stub `parrot.knowledge.pageindex.utils.count_tokens`
  with `monkeypatch.setattr` (`tests/knowledge/pageindex/test_toolkit.py:53-63`) because tiktoken downloads
  its encodings on first use, and a name imported by value would bypass the stub.
- ~~`EbookSection.section_path`~~ — not relevant here; section paths are passed in by callers

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segments.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/utils.py#count_tokens",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py#parse_markdown_structure"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Pure and deterministic**: no I/O, no randomness, no time in anything except
  `DocumentRevision.created_at` (set by callers). The same markdown must always yield the same
  segments — *because* `revision_id` hashes them and a re-import of an unchanged file must give
  the same revision (spec AC-4).
- **Verbatim text**: never `strip()` inner lines; remove only leading and trailing blank lines of a
  block — *because* every character offset in FEAT-840 (`SegmentRead.start/end`, cursors, later
  citations) indexes `Segment.text`.
- `revision_id` hashes texts only (joined by U+001E), not pages or kinds.
- Splitter rules (spec §7, in this order per line): ATX heading → own `heading` segment with
  `level`; fence opener → `code` until the matching closer or end of input; consecutive lines
  starting with `|` → one `table`; consecutive list lines (`-`, `*`, `+`, `\d+.`) and their
  indented continuations → one `list`; a line that is only an image reference (`![`) → `caption`;
  everything else split on blank lines into `paragraph`. Whitespace-only blocks are dropped.
- Label format: paged → `p. {page} ¶{ordinal + 1}`; unpaged → `" > ".join(section) + f" ¶{ordinal + 1}"`
  (ordinals are 0-based internally, 1-based for humans).

---

## Implementation Blueprint

### Steps (in order)
1. Create `segments.py` from the block below — *why*: the names are fixed by spec §2 and imported by
   six later tasks.
2. Fill `split_blocks` — *why*: it is the only non-trivial logic and every revision depends on it.
3. Fill the remaining helpers and write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` (CREATE)
```python
"""Segments: the addressable substrate of imported PageIndex documents (FEAT-840)."""

from __future__ import annotations

import hashlib
import re
from typing import Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex import utils as _utils  # count_tokens via the module (test stub)

SegmentKind = Literal["heading", "paragraph", "list", "table", "code", "caption", "other"]

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CURSOR_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})@([0-9a-f]{16})#(\d+)\+(\d+)$")
_RS = "\x1e"


class InjectionMark(BaseModel):
    """Why a segment was flagged as a possible prompt injection."""

    engine: str
    score: Optional[float] = None
    threats: list[str] = Field(default_factory=list)


class Segment(BaseModel):
    """One block of an imported document; ``text`` is verbatim and every offset indexes it."""

    seq: int
    kind: SegmentKind
    page: Optional[int] = None
    ordinal: int
    section: Optional[list[str]] = None
    level: Optional[int] = None
    text: str
    tokens: int
    sha16: str
    flags: list[str] = Field(default_factory=list)
    injection: Optional[InjectionMark] = None


# FILL IN: SourceInfo, DocumentRevision, SegmentAddress (label/key properties), SegmentRead,
# ReadResult exactly as spec §2 Data Models — bounded by spec §2 (field names are not renegotiable)


class RevisionMismatchError(ValueError):
    """A cursor or address names a different revision than the document being read."""


class RevisionUnavailableError(ValueError):
    """The named revision file no longer exists (swept after the grace period)."""


def split_blocks(markdown: str) -> list[tuple[SegmentKind, str, Optional[int]]]:
    """Split markdown into ``(kind, text, heading_level)`` blocks following spec §7 v1 rules."""
    # FILL IN: line scanner implementing the rules in Key Constraints — bounded by AC-1/AC-2
    raise NotImplementedError


def _make(seq: int, kind: SegmentKind, text: str, level: Optional[int], *, page: Optional[int],
          ordinal: int, section: Optional[list[str]]) -> Segment:
    return Segment(seq=seq, kind=kind, page=page, ordinal=ordinal, section=section, level=level, text=text,
                   tokens=_utils.count_tokens(text), sha16=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])


def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]:
    """Segments of a paged source in page order; ``seq`` is global, ``ordinal`` restarts per page."""
    # FILL IN: loop pages, split_blocks each, _make(...) with page=n — bounded by AC-3
    raise NotImplementedError


def segment_text(text: str, section: list[str], *, seq_start: int = 0) -> list[Segment]:
    """Segments of one section of an unpaged source; ``ordinal`` restarts per section."""
    # FILL IN: split_blocks + _make(page=None, section=list(section)) — bounded by AC-3
    raise NotImplementedError


def revision_id(segments: Sequence[Segment]) -> str:
    """sha256 over the segment texts joined by U+001E, first 16 hex chars."""
    return hashlib.sha256(_RS.join(s.text for s in segments).encode("utf-8")).hexdigest()[:16]


def derive_doc_id(name: str, *, taken: Mapping[str, Optional[str]], source_sha256: Optional[str]) -> str:
    """Slug of ``name``; suffixed with 6 hex only when ``taken[slug]`` holds a different source hash."""
    # FILL IN: lowercase, non [a-z0-9] runs → "-", strip "-", cap 48, fallback "doc"; collision rule
    # from the docstring (suffix = sha256(source_sha256 or name)[:6]) — bounded by AC-5
    raise NotImplementedError


def parse_page_spec(spec: str, *, max_page: int) -> list[int]:
    """``"5-7,12"`` → ``[5, 6, 7, 12]`` (sorted, unique); ValueError on empty/malformed/out of range."""
    # FILL IN — bounded by AC-6
    raise NotImplementedError


def format_cursor(doc_id: str, revision: str, seq: int, offset: int) -> str:
    """Inverse of :func:`parse_cursor`."""
    return f"{doc_id}@{revision}#{seq}+{offset}"


def parse_cursor(cursor: str) -> tuple[str, str, int, int]:
    """``(doc_id, revision, seq, offset)``; ValueError on a malformed cursor."""
    match = _CURSOR_RE.fullmatch(cursor or "")
    if match is None:
        raise ValueError(f"malformed cursor {cursor!r}")
    return match.group(1), match.group(2), int(match.group(3)), int(match.group(4))
```
**Why this shape**: spec §2 fixes the models and §3 M1 fixes the helper names; `format_cursor` is added
so TASK-5309 never hand-builds the grammar. `_make` centralises token counting through the module so the
test stub applies.

### FILL IN checklist
- [ ] remaining models (SourceInfo, DocumentRevision, SegmentAddress, SegmentRead, ReadResult); bounded by spec §2
- [ ] `split_blocks`; bounded by AC-1, AC-2
- [ ] `segment_pages`, `segment_text`; bounded by AC-3
- [ ] `derive_doc_id`; bounded by AC-5
- [ ] `parse_page_spec`; bounded by AC-6

---

## Acceptance Criteria

- [ ] AC-1: a fenced block containing blank lines, and a pipe table, are each exactly one segment (`code`, `table`); a heading is its own `heading` segment with `level`.
- [ ] AC-2: `"".join` of nothing is lost: every non-blank line of the input appears verbatim in exactly one segment's `text`.
- [ ] AC-3: `segment_pages` gives a global `seq`, `ordinal` restarting per page, `page` set, no segment for an empty page; `segment_text` sets `section` and `page=None`.
- [ ] AC-4: `revision_id` is equal for equal texts and differs after a one-character change; it ignores `page`.
- [ ] AC-5: `derive_doc_id("Report 2026.pdf", taken={}, …)` is stable; a different `source_sha256` under a taken slug gets a 6-hex suffix; the same hash does not.
- [ ] AC-6: `parse_page_spec("5-7,12", max_page=20) == [5, 6, 7, 12]`; `"0"`, `"21"`, `""`, `"a-b"` raise `ValueError`; `parse_cursor` round-trips `format_cursor`.
- [ ] AC-7: labels render `p. 12 ¶3` and `Setup > Install ¶2`.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segments.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/pageindex/test_segments.py
import pytest

from parrot.knowledge.pageindex.segments import (
    SegmentAddress, derive_doc_id, format_cursor, parse_cursor, parse_page_spec,
    revision_id, segment_pages, segment_text, split_blocks,
)


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t)))


PAGE = "# Title\n\nIntro para.\n\n```py\nx = 1\n\ny = 2\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n"


def test_split_blocks_keeps_fences_and_tables_whole():
    kinds = [k for k, _, _ in split_blocks(PAGE)]
    assert kinds == ["heading", "paragraph", "code", "table", "list"]


def test_segment_pages_ordinals_restart_per_page():
    segs = segment_pages([(1, "A.\n\nB."), (2, ""), (3, "C.")])
    assert [(s.seq, s.page, s.ordinal) for s in segs] == [(0, 1, 0), (1, 1, 1), (2, 3, 0)]


def test_revision_id_is_content_hash():
    # FILL IN: equal texts → equal id; changed char → different id; page ignored
    ...


def test_derive_doc_id_stable_and_disambiguated():
    # FILL IN — AC-5
    ...


def test_parse_page_spec_and_cursor():
    assert parse_page_spec("5-7,12", max_page=20) == [5, 6, 7, 12]
    for bad in ("", "0", "21", "a-b"):
        with pytest.raises(ValueError):
            parse_page_spec(bad, max_page=20)
    assert parse_cursor(format_cursor("doc", "0" * 16, 3, 10)) == ("doc", "0" * 16, 3, 10)


def test_address_labels():
    # FILL IN — AC-7
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-segment-store --feature-id FEAT-840`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design,
   §7 holds the splitter rules and the known risks).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-segment-store.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   within the constraint it names; touch only the files in *Files to Create / Modify*.
7. **Validate** — `ruff check --fix` on your files, then every command under *Validation Commands*.
8. **Commit code** (`feat(pageindex-segment-store): TASK-5300 — Segment models, block splitter and addresses`), then close with
   `parrot sdd task close TASK-5300 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
