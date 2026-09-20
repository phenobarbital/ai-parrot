# TASK-3486: ADR Markdown parser — sections, status, and identity aliases

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3479, TASK-3480
**Assigned-to**: unassigned

---

## Context

Module 3's pure half. Turns one ADR Markdown file into a documented
`DecisionRecord` with exact source spans, or into `None` when the file is an
ordinary document. The bounded metadata subset is deliberately narrow: spec §2
says *"nested YAML and arbitrary YAML execution are unsupported"* and §7 says
*"no new parser dependency"* — stdlib only.

Two traps this parser must not fall into, both named in the spec:

- A heading inside a fenced code block is not a section.
- A missing `Decision` section means "ordinary document plus diagnostic", never
  a fabricated ADR.

---

## Scope

- Implement `parse_adr(rel_path, text) -> DecisionRecord | None` plus the
  status/alias normalization helpers.
- Extract flat frontmatter fields `id`, `title`, `status`, `supersedes` only.
- Recognize case-insensitive ATX sections `Context`, `Decision`, `Consequences`,
  `Status`, ignoring fenced-code headings.
- Resolve status frontmatter-first, then the `Status` section; disagreement
  yields `ADR_STATUS_CONFLICT` and effective `unknown`; preserve the raw text.
- Normalize `ADR-42`, `ADR/042`, `ADR 42` and filenames like `0042-*.md` to the
  canonical `ADR-42` alias; conflicting ids produce a diagnostic.
- Emit `EvidenceRef`s with exact 1-based inclusive line spans.
- Unit-test the whole fixture matrix from spec §4.

**NOT in scope**: file discovery/globbing and store writes (TASK-3489), Python
code citations (TASK-3487), link resolution across the inventory (TASK-3489).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` | CREATE | Bounded ADR Markdown subset parser |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py` | CREATE | Section, status, alias and span matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.codec import documented_decision_id, normalize_rel_path  # TASK-3480
from parrot.knowledge.wiki.decisions.models import (  # TASK-3479
    ADR_PARSE_FAILED, ADR_STATUS_CONFLICT, DecisionDiagnostic, DecisionError,
    DecisionRecord, EvidenceRef,
)
```

Standard library only otherwise (`re`, `hashlib`). Spec §7: "no new parser
dependency" — do **not** import `yaml`, `frontmatter`, `markdown`, or
`mistune`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/codec.py  (TASK-3480)
def documented_decision_id(rel_path: str) -> str: ...
def normalize_rel_path(rel_path: str) -> str: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py:634 — behavioural reference ONLY
def build_file_slice(root, rel_path, body_max_chars=DEFAULT_BODY_MAX_CHARS,
                     max_file_bytes=DEFAULT_MAX_FILE_BYTES, symbol_depth=2) -> FileSlice | None: ...
#   truncates page bodies at line 709 — THIS PARSER MUST NOT SEE THAT TRUNCATION

# packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/code.py:35 — normalization source of truth
_CITATION_RE = re.compile(r"\b(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
```

### Does NOT Exist

- ~~a YAML parser in this dependency set for ADR frontmatter~~ — the flat-scalar
  subset is hand-parsed (spec §2). `pyyaml` is not a declared dependency of this
  feature (§7 External Dependencies lists only pydantic/aiosqlite/pathspec/
  tree-sitter/stdlib).
- ~~`repo_scan.build_file_slice` as the ADR text source~~ — it truncates at
  `repo_scan.py:709` (default `body_max_chars=16_000`). Spec §2: "Read complete
  eligible files up to the existing configured source-byte limit **before**
  generic wiki body truncation" and AC1 forbids silent truncation. This function
  receives the **full** text as its `text` argument.
- ~~a `Status` frontmatter field that wins silently over the section~~ —
  disagreement is `ADR_STATUS_CONFLICT` with effective `unknown`, not a
  precedence rule (spec §2).
- ~~an inferred `DecisionRecord` from this module~~ — `parse_adr` only ever
  produces `origin='documented'`. Candidates come from TASK-3491.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- Pure and synchronous: no file I/O, no store, no CLI imports (spec §7).
- Line spans are **1-based inclusive** and must survive CRLF input.
- Unknown status text is preserved in `source_status_raw` and never elevated:
  `source_status` stays `'unknown'` (spec §2, AC3).
- `black` line length 120.

### Fixture matrix (spec §4 "Test Data / Fixtures")

Accepted / superseded / proposed / unknown-status ADRs, a fenced-code heading, a
missing `Decision` section, malformed frontmatter, duplicate `ADR-42` aliases,
and a long ADR whose `Decision` sits past character 16000.

---

## Implementation Blueprint

### Steps (in order)

1. Write the line-indexed section splitter first, fence-aware — *why*: every
   other value (spans, status, body text) is derived from it, and a fence bug
   silently mis-attributes whole sections.
2. Write the flat frontmatter reader — *why*: it bounds what the parser will
   ever accept, which is the security property in spec §2.
3. Write status resolution and alias normalization — *why*: both produce
   diagnostics the caller must see, so their contract is "value + diagnostics".
4. Assemble `parse_adr`, returning `None` (plus a diagnostic) when `Decision` is
   absent — *why*: AC1 and spec §2 forbid fabricating an ADR.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py` (CREATE)

```python
"""Bounded ADR Markdown subset parser (FEAT-578 Module 3).

Accepts UTF-8 Markdown with ATX headings and an optional flat frontmatter
block carrying only ``id``, ``title``, ``status`` and ``supersedes``. Nested
YAML is unsupported by design — the parser reads scalars with a regex and
never evaluates the document (spec §2).

Every returned record is ``origin='documented'``. Inferred candidates are
produced elsewhere (``decisions/generation.py``).
"""

from __future__ import annotations

import hashlib
import re

from parrot.knowledge.wiki.decisions.codec import documented_decision_id, normalize_rel_path
from parrot.knowledge.wiki.decisions.models import (
    ADR_PARSE_FAILED,
    ADR_STATUS_CONFLICT,
    DecisionDiagnostic,
    DecisionRecord,
    EvidenceRef,
)

#: The only frontmatter keys read. Anything else is ignored, not an error.
FRONTMATTER_KEYS = ("id", "title", "status", "supersedes")

#: Section names recognised, matched case-insensitively.
SECTION_NAMES = ("context", "decision", "consequences", "status")

#: Lifecycle values recognised; anything else stays ``unknown`` with the raw
#: text preserved in ``source_status_raw``.
KNOWN_STATUSES = ("accepted", "proposed", "rejected", "deprecated", "superseded")

#: ``ADR-42`` / ``ADR/042`` / ``ADR 42`` -> canonical ``ADR-42``.
#: The separator class and digit bound are copied VERBATIM from GraphIndex's
#: citation regex (verified: graphindex/extractors/code.py:35,
#: ``\b(ADR|RFC)[\s\-/]?(\d{1,5})\b``) so the two planes agree on what is a
#: reference; only the RFC alternative is dropped, and leading zeros are
#: stripped here to form the canonical alias. Do NOT widen the separator
#: class (no ``_``) — that would make the wiki see references GraphIndex does
#: not, which spec §2 forbids ("consistently with GraphIndex").
ADR_REFERENCE_RE = re.compile(r"\bADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)

#: A leading ``0042-`` style filename prefix.
FILENAME_ID_RE = re.compile(r"^0*(\d+)[-_]")

_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_FRONTMATTER_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


def normalize_adr_alias(text: str) -> str | None:
    """Return the canonical ``ADR-<n>`` alias in ``text``, or ``None``."""
    match = ADR_REFERENCE_RE.search(text)
    return f"ADR-{int(match.group(1))}" if match else None


def split_sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Map lowercase section name -> ``(start_line, end_line)``, 1-based inclusive.

    Headings inside fenced code blocks are ignored (spec §2), so a fenced
    example ADR cannot fabricate sections in the document that quotes it.
    """
    # FILL IN: walk `lines` tracking fence open/close via _FENCE_RE (a fence
    # closes only on the same marker), match _ATX_RE outside fences, and record
    # a span for each name in SECTION_NAMES running from the line AFTER the
    # heading to the line BEFORE the next heading of the same or higher level
    # (or EOF). Bounded by spec §2 "Ignore fenced-code headings" and AC1
    # "exact source spans".
    raise NotImplementedError


def parse_frontmatter(lines: list[str]) -> tuple[dict[str, str], int, list[DecisionDiagnostic]]:
    """Read the flat ``---`` block at the top of the file.

    Returns:
        ``(fields, body_start_index, diagnostics)``. Only
        :data:`FRONTMATTER_KEYS` are kept. A block that never closes, or a
        line that is not a flat ``key: value`` scalar, yields an
        ``ADR_PARSE_FAILED`` diagnostic and is skipped — it is never fatal,
        because an ADR with a bad header is still an ADR.
    """
    # FILL IN: require lines[0].strip() == "---", scan to the closing "---",
    # apply _FRONTMATTER_SCALAR_RE, strip matching surrounding quotes, and
    # ignore nested structures (a value that is empty followed by an indented
    # line) with a diagnostic. Bounded by spec §2 "Extract only these known
    # scalar fields using a bounded parser".
    raise NotImplementedError


def resolve_status(frontmatter_status: str, section_status: str) -> tuple[str, str, list[DecisionDiagnostic]]:
    """Resolve the declared lifecycle status.

    Returns:
        ``(status, status_raw, diagnostics)``. Frontmatter is consulted
        first, then the ``Status`` section. When both are present and
        disagree, the result is ``('unknown', <raw>, [ADR_STATUS_CONFLICT])``
        — a conflict is never silently resolved by precedence (spec §2).
        Unrecognised text yields ``'unknown'`` with the original preserved.
    """
    # FILL IN: normalize both inputs (strip, lowercase, take the first word so
    # "Accepted — 2024-01-01" reads as accepted), compare against
    # KNOWN_STATUSES, and apply the conflict rule above. Bounded by spec §2
    # "disagreeing values yield ADR_STATUS_CONFLICT and effective unknown".
    raise NotImplementedError


def parse_adr(rel_path: str, text: str) -> tuple[DecisionRecord | None, list[DecisionDiagnostic]]:
    """Parse one ADR document.

    Args:
        rel_path: Repository-relative POSIX path, used for identity.
        text: The COMPLETE file text. Callers must not pass a truncated
            page body — AC1 requires a ``Decision`` past the ordinary
            16000-character body head to be extracted with correct spans.

    Returns:
        ``(record, diagnostics)``. ``record`` is ``None`` when the document
        has no ``Decision`` section: that is an ordinary document plus a
        diagnostic, never a fabricated ADR (spec §2).
    """
    # FILL IN: normalize newlines, split into lines, read frontmatter, split
    # sections, resolve status, derive the external_id from
    # frontmatter["id"] -> the H1 heading -> FILENAME_ID_RE (in that order,
    # emitting a diagnostic when two of them disagree), build one EvidenceRef
    # of kind='adr' per populated section with its 1-based inclusive span and
    # a sha1 of that span's text, derive `supersedes` links, and assemble the
    # DecisionRecord with origin='documented' and
    # decision_id=documented_decision_id(rel_path).
    # Bounded by: AC1 (exact spans, no truncation), spec §2 identity rules,
    # and the requirement that the record's content_fingerprint is filled by
    # the caller, not here.
    raise NotImplementedError
```

**Why this shape**: each helper returns `(value, diagnostics)` rather than
raising, because spec §2 requires these to reach the caller as typed
diagnostics inside a `SyncResult`, not as exceptions that abort a whole sync.
`parse_adr` taking `text` rather than a path is what keeps the module pure and
keeps `repo_scan`'s 16000-character truncation (`repo_scan.py:709`) out of the
ADR path — AC1's long-ADR requirement depends on that separation.
`ADR_REFERENCE_RE` must stay consistent with GraphIndex's normalization
(`graphindex/extractors/code.py:564`); TASK-3487 reuses it.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py` (CREATE)

```python
"""ADR parser fixture matrix (FEAT-578 Module 3, AC1)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.parser import normalize_adr_alias, parse_adr, resolve_status, split_sections

ACCEPTED = """\
---
id: ADR-42
title: Use pgvector
status: Accepted
---

# ADR-42: Use pgvector

## Context
Postgres is already deployed.

## Decision
Use pgvector as the primary vector store.

## Consequences
One less service to run.
"""


class TestSections:
    def test_adr_sections_and_status(self):
        """A well-formed ADR yields every section with a 1-based span."""
        record, diags = parse_adr("docs/adr/0042-pgvector.md", ACCEPTED)
        assert record is not None and diags == []
        assert record.origin == "documented"
        assert record.source_status == "accepted"
        assert record.external_id == "ADR-42"
        assert "pgvector as the primary" in record.decision
        # FILL IN: assert the Decision EvidenceRef's start_line/end_line point
        # at the real 1-based lines of that section in ACCEPTED
        raise NotImplementedError

    def test_fenced_headings_are_not_sections(self):
        """A fenced example must not fabricate a Decision (spec §2)."""
        text = ACCEPTED.replace("## Decision\n", "```md\n## Decision\nfake\n```\n\n## Decision\n")
        # FILL IN: assert the real Decision body is captured and the fenced
        # "fake" text is not
        raise NotImplementedError

    def test_missing_decision_is_an_ordinary_document(self):
        """No Decision section -> (None, diagnostic), never a fabricated ADR."""
        record, diags = parse_adr("docs/adr/notes.md", "# Notes\n\n## Context\nhi\n")
        assert record is None
        assert diags and diags[0].code == "ADR_PARSE_FAILED"

    def test_crlf_input_keeps_correct_spans(self):
        """Windows line endings must not shift the reported lines."""
        # FILL IN: parse ACCEPTED.replace("\n", "\r\n") and assert the Decision
        # span matches the LF parse exactly
        raise NotImplementedError


class TestStatus:
    @pytest.mark.parametrize(
        "fm,section,expected",
        [
            ("Accepted", "", "accepted"),
            ("", "Superseded by ADR-50", "superseded"),
            ("Proposed", "", "proposed"),
            ("", "Draft-ish", "unknown"),
        ],
    )
    def test_recognised_and_unknown_statuses(self, fm, section, expected):
        status, raw, diags = resolve_status(fm, section)
        assert status == expected
        assert not diags

    def test_conflicting_status_is_unknown_with_a_diagnostic(self):
        """Disagreement is reported, never resolved by precedence (spec §2)."""
        status, raw, diags = resolve_status("Accepted", "Rejected")
        assert status == "unknown"
        assert [d.code for d in diags] == ["ADR_STATUS_CONFLICT"]

    def test_unknown_status_preserves_raw_text(self):
        """AC3: unknown is displayed, not elevated."""
        # FILL IN: parse an ADR whose status is "Needs review"; assert
        # source_status == "unknown" and source_status_raw == "Needs review"
        raise NotImplementedError


class TestIdentity:
    @pytest.mark.parametrize("text", ["ADR-42", "ADR/042", "ADR 42", "adr42"])
    def test_alias_normalization(self, text):
        """Consistent with GraphIndex's normalization (spec §2)."""
        assert normalize_adr_alias(text) == "ADR-42"

    @pytest.mark.parametrize("text", ["ADR_42", "ADR--42", "ADR - 42"])
    def test_separators_graphindex_rejects_are_not_references(self, text):
        """The two planes must agree on what counts as a citation (spec §2).

        GraphIndex allows exactly one optional separator from ``[\s\-/]``
        (graphindex/extractors/code.py:35); widening it here would make the
        wiki resolve references GraphIndex never saw.
        """
        assert normalize_adr_alias(text) is None

    def test_filename_supplies_the_alias_when_absent(self):
        """`0042-*.md` normalizes to ADR-42."""
        # FILL IN: parse an ADR with no id/heading alias from path
        # "docs/adr/0042-thing.md"; assert external_id == "ADR-42"
        raise NotImplementedError

    def test_conflicting_ids_produce_a_diagnostic(self):
        """frontmatter id vs filename disagreement is reported (spec §2)."""
        # FILL IN: id: ADR-7 in frontmatter, path docs/adr/0042-x.md; assert a
        # diagnostic is emitted and the record still parses
        raise NotImplementedError


class TestBoundedParsing:
    def test_long_adr_not_body_truncated(self):
        """AC1: a Decision past 16000 chars is still extracted with real spans."""
        filler = "\n".join(f"padding line {i}" for i in range(3000))
        text = f"# ADR-9\n\n## Context\n{filler}\n\n## Decision\nUse the bounded parser.\n"
        record, _ = parse_adr("docs/adr/0009-long.md", text)
        assert record is not None
        assert record.decision.strip() == "Use the bounded parser."
        # FILL IN: assert the Decision EvidenceRef start_line is greater than
        # 3000, proving no 16000-character head truncation happened
        raise NotImplementedError

    def test_malformed_frontmatter_is_survivable(self):
        """A bad header yields a diagnostic, not a dropped ADR."""
        # FILL IN: nested/unclosed frontmatter; assert the record still parses
        # from its sections and a diagnostic is present
        raise NotImplementedError

    def test_nested_yaml_is_not_evaluated(self):
        """Only flat scalars are read (spec §2)."""
        # FILL IN: frontmatter containing a nested mapping and a YAML tag;
        # assert neither appears in any record field and no exception escapes
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `parser.py::split_sections` — fence tracking + 1-based span computation; bounded by spec §2 / AC1
- [ ] `parser.py::parse_frontmatter` — flat-scalar subset + diagnostics; bounded by spec §2
- [ ] `parser.py::resolve_status` — recognition, conflict rule, raw preservation; bounded by spec §2 / AC3
- [ ] `parser.py::parse_adr` — assembly, id precedence, evidence refs, `None` path; bounded by AC1
- [ ] `test_parser.py` — eleven test bodies; bounded by the assertions named in each docstring

---

## Acceptance Criteria

- [ ] Every fixture ADR in spec §4 parses with exact 1-based source spans and the right status (AC1)
- [ ] A `Decision` past character 16000 is extracted with correct spans — no truncation (AC1)
- [ ] Headings inside fenced code blocks are ignored
- [ ] A missing `Decision` returns `(None, [diagnostic])`
- [ ] Conflicting statuses give `unknown` + `ADR_STATUS_CONFLICT`; unknown text is preserved in `source_status_raw` (AC3)
- [ ] `ADR-42`, `ADR/042`, `ADR 42`, `0042-*.md` all normalize to `ADR-42`; conflicts emit a diagnostic
- [ ] Every returned record has `origin='documented'`
- [ ] The module imports no YAML/Markdown library and no CLI module (spec §7)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_parser.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "ADR parsing and references", §4 fixtures, and AC1/AC3.
2. **Verify the Codebase Contract** — confirm `repo_scan.py:709` still truncates, which is why this parser takes text.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** the Validation Command passes.
5. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
6. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
