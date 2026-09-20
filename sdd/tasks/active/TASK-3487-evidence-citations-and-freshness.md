# TASK-3487: Python citations, evidence packing, and freshness verification

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3479, TASK-3486
**Assigned-to**: unassigned

---

## Context

Module 3's evidence half, and the module every retrieval label depends on.
Three separable jobs:

1. **Citation extraction** — find `ADR-<n>` references in Python source, from
   `tokenize` comment tokens and `ast` docstrings **only**. Spec §2 is explicit
   that an executable string literal is not rationale: a bare `"see ADR-42"`
   expression in the middle of a function must not become a citation.
2. **Evidence construction** — build `EvidenceRef`s with exact spans and the
   SHA-1 of the bytes actually read.
3. **Freshness verification** — compare a stored evidence hash against the
   current file. `current` / `stale` / `missing` / `unverified`, where
   `unverified` (no local root) is never silently upgraded to `current`.

---

## Scope

- Implement `extract_python_citations(rel_path, source)` returning per-citation
  alias + owning symbol span + 1-based line, attaching each to the nearest
  enclosing symbol and falling back to **file scope** for module-level comments.
- Implement `build_evidence(...)` and the span-hashing helper.
- Implement `async verify_freshness(root, evidence)` with confined paths and
  `asyncio.to_thread` offloading.
- Unit-test the whole citation/ambiguity/freshness matrix.

**NOT in scope**: ADR Markdown parsing (TASK-3486), resolving an alias to a
stored record (TASK-3489), ranking or dossier assembly (TASK-3490), generation
packets (TASK-3491).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py` | CREATE | Python citations, evidence refs, freshness |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py` | CREATE | Citation, exclusion, scope and freshness matrix |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.wiki.decisions.models import (  # TASK-3479
    ADR_PATH_OUTSIDE_ROOT, ADR_SOURCE_UNAVAILABLE, DecisionDiagnostic,
    DecisionError, EvidenceRef,
)
from parrot.knowledge.wiki.decisions.parser import ADR_REFERENCE_RE, normalize_adr_alias  # TASK-3486
from parrot.knowledge.wiki.symbols import SymbolRecord, sym_concept_id  # symbols.py:56, :141
```

Standard library: `ast`, `asyncio`, `hashlib`, `io`, `tokenize`, `pathlib`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py:56
class SymbolRecord(BaseModel):
    rel_path: str; language: str; kind: SymbolKind; name: str; qualname: str
    parent: str | None = None; signature: str = ""; doc: str = ""
    exported: bool = False; is_async: bool = False
    start_line: int; end_line: int      # 1-based inclusive (lines 86-87 docstring)
    start_byte: int; end_byte: int
    node_kind: str = ""; decorators: list[str]; content_hash: str; depth: int = 1

# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py:141
def sym_concept_id(rel_path: str, qualname: str, ordinal: int = 1) -> str: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py:327
def sha1_of_text(text: str) -> str: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/parser.py  (TASK-3486)
ADR_REFERENCE_RE: re.Pattern      # copied from graphindex/extractors/code.py:35
def normalize_adr_alias(text: str) -> str | None: ...
```

### Does NOT Exist

- ~~a GraphIndex API that resolves a citation to a wiki id~~ — spec §6:
  GraphIndex citation nodes "do not resolve ADR text or accepted status", and
  its ids are **not** wiki ids. Use `sym_concept_id` to mint the wiki symbol id
  yourself; never pass a GraphIndex `node_id` through.
- ~~tree-sitter for Python citation extraction~~ — spec §2 says "tokenizer
  comment tokens and AST docstrings". Use stdlib `tokenize` + `ast`.
- ~~automatic citation extraction for non-Python languages~~ — spec §2 defers
  it. Other languages get explicit document→symbol links only. Do not add a
  JavaScript/PHP/Rust path here.
- ~~`SymbolRecord.stale`~~ — not a field of `SymbolRecord`. `SymbolHit` (the
  structural service's output model) carries `stale`, not the record.
- ~~call-graph propagation of applicability~~ — spec §2: "do not propagate
  applicability through the call graph". This module produces direct citations
  only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#SymbolRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#sym_concept_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py#sha1_of_text"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- `tokenize.generate_tokens` yields `COMMENT` tokens with 1-based `start[0]`
  line numbers — use them directly, do not recompute.
- Docstrings come from `ast.get_docstring(node)` for `Module`, `FunctionDef`,
  `AsyncFunctionDef` and `ClassDef` nodes **only**. Any other `ast.Constant`
  string is executable data, not rationale (spec §2).
- A file that fails to tokenize or parse yields a diagnostic, not an exception —
  a syntax error in one file must not abort a sync.
- Path confinement: resolve against the root and reject anything escaping it
  with `ADR_PATH_OUTSIDE_ROOT`. Use `Path.resolve()` and `is_relative_to`.
- All file I/O through `asyncio.to_thread` (spec §2).

---

## Implementation Blueprint

### Steps (in order)

1. Write the symbol-range index and `_owner_for_line` — *why*: "nearest
   enclosing symbol" is a containment query, and getting it wrong silently
   attributes a decision to the wrong function.
2. Write comment extraction, then docstring extraction — *why*: the two use
   different stdlib passes over the same text and must agree on line numbers.
3. Write `verify_freshness` last — *why*: it depends on the `EvidenceRef` shape
   the first two produce.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py` (CREATE)

```python
"""ADR citations, evidence refs and freshness checks (FEAT-578 Module 3).

Citation extraction is Python-only and deliberately narrow: comment tokens
from :mod:`tokenize` and docstrings from :mod:`ast`. An executable string
literal is data, not rationale, so ``x = "see ADR-42"`` is never a citation
(spec §2).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
import logging
import tokenize
from dataclasses import dataclass
from pathlib import Path

from parrot.knowledge.wiki.decisions.models import (
    ADR_PATH_OUTSIDE_ROOT,
    ADR_SOURCE_UNAVAILABLE,
    DecisionDiagnostic,
    DecisionError,
    EvidenceRef,
)
from parrot.knowledge.wiki.decisions.parser import normalize_adr_alias
from parrot.knowledge.wiki.symbols import sym_concept_id

logger = logging.getLogger(__name__)

#: Freshness of one stored evidence span against the current source.
#: ``unverified`` means "no local root to check against" and is NEVER
#: upgraded to ``current`` (spec §2).
FRESHNESS_CURRENT = "current"
FRESHNESS_STALE = "stale"
FRESHNESS_MISSING = "missing"
FRESHNESS_UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Citation:
    """One resolved ``ADR-<n>`` reference in a Python source file."""

    alias: str          # canonical "ADR-42"
    rel_path: str
    line: int           # 1-based line the reference text sits on
    page_id: str        # sym:<rel>#<qualname>, or file:<rel> for module scope
    qualname: str | None  # None == file scope
    start_line: int     # owning span, 1-based inclusive
    end_line: int
    kind: str           # "comment" | "document" (docstring)


def sha1_of_span(text: str) -> str:
    """SHA-1 of the exact bytes an evidence span was read from."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()  # noqa: S324


def _symbol_ranges(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Every def/class as ``(qualname, start_line, end_line)``, 1-based inclusive."""
    # FILL IN: walk the tree building dotted qualnames (Class.method, nested
    # funcs included) from FunctionDef/AsyncFunctionDef/ClassDef, using
    # node.lineno and node.end_lineno. Bounded by "nearest enclosing symbol"
    # and SymbolRecord's 1-based inclusive convention (symbols.py:86-87).
    raise NotImplementedError


def _owner_for_line(ranges: list[tuple[str, int, int]], line: int) -> tuple[str, int, int] | None:
    """Innermost symbol span containing ``line``, or ``None`` for file scope."""
    # FILL IN: among ranges whose start <= line <= end, return the one with the
    # SMALLEST span (the innermost). Bounded by spec §2 "Attach to the nearest
    # enclosing symbol range".
    raise NotImplementedError


def extract_python_citations(rel_path: str, source: str) -> tuple[list[Citation], list[DecisionDiagnostic]]:
    """Find ADR references in comments and docstrings of one Python file.

    Module-level comments attach to the file and are reported as file scope
    (``page_id='file:<rel>'``, ``qualname=None``) — spec §2.

    Returns:
        ``(citations, diagnostics)``. A file that cannot be tokenized or
        parsed yields an ``ADR_PARSE_FAILED`` diagnostic and no citations,
        never an exception: one bad file must not abort a whole sync.
    """
    # FILL IN:
    #   1. ast.parse(source) inside try/except SyntaxError -> diagnostic, return
    #   2. ranges = _symbol_ranges(tree)
    #   3. tokenize.generate_tokens(io.StringIO(source).readline); for each
    #      tokenize.COMMENT token, normalize_adr_alias(token.string); on a hit
    #      build a Citation with line=token.start[0], kind="comment", owner via
    #      _owner_for_line
    #   4. for Module/FunctionDef/AsyncFunctionDef/ClassDef nodes ONLY, run
    #      ast.get_docstring(node) through normalize_alias; kind="document",
    #      owner = that node
    #   5. page_id = sym_concept_id(rel_path, qualname) when owned, else
    #      f"file:{rel_path}"
    # Bounded by spec §2 "come only from tokenizer comment tokens and AST
    # docstrings" and "Do not treat executable string literals as rationale".
    raise NotImplementedError


def build_evidence(rel_path: str, source: str, page_id: str, start_line: int, end_line: int, kind: str) -> EvidenceRef:
    """Construct one ``EvidenceRef`` over a 1-based inclusive line span."""
    lines = source.splitlines()
    excerpt = "\n".join(lines[start_line - 1 : end_line])
    return EvidenceRef(
        page_id=page_id,
        rel_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        source_sha1=sha1_of_span(excerpt),
        excerpt=excerpt,
        kind=kind,
    )


def _resolve_confined(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` under ``root``, refusing anything that escapes it.

    Raises:
        DecisionError: ``ADR_PATH_OUTSIDE_ROOT``.
    """
    # FILL IN: resolve root and (root / rel_path); use Path.is_relative_to to
    # confirm containment AFTER resolution so symlinks and ".." are both caught.
    # Bounded by spec §2 "using confined paths" and ADR_PATH_OUTSIDE_ROOT.
    raise NotImplementedError


def _read_span_sync(path: Path, start_line: int, end_line: int) -> str | None:
    """Read one 1-based inclusive span, or ``None`` when the file is gone."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[start_line - 1 : end_line])


async def verify_freshness(root: Path | None, evidence: EvidenceRef) -> tuple[str, DecisionDiagnostic | None]:
    """Check one evidence span against the current bytes on disk.

    Args:
        root: Local project root, or ``None`` for a store-only/remote
            namespace. ``None`` yields ``unverified`` — spec §2: "If no
            project root is available, report unverified, never current."

    Returns:
        ``(freshness, diagnostic_or_None)``. A changed hash is ``stale``, an
        absent file is ``missing``; neither rewrites the stored record —
        reads never mutate review status (spec §2).
    """
    if root is None:
        return FRESHNESS_UNVERIFIED, None
    # FILL IN: resolve confined (letting DecisionError propagate as an
    # ADR_PATH_OUTSIDE_ROOT), read the span via asyncio.to_thread(_read_span_sync,
    # ...), return MISSING when None, then compare sha1_of_span(text) against
    # evidence.source_sha1 -> CURRENT or STALE, attaching an
    # ADR_SOURCE_UNAVAILABLE / mismatch diagnostic where the spec asks for one.
    # Bounded by spec §2 "Failed hash verification returns a diagnostic" and
    # "Do not rewrite review status during reads".
    raise NotImplementedError
```

**Why this shape**: `Citation` is a frozen dataclass rather than a Pydantic
model because it never crosses a serialization boundary — it is consumed by
TASK-3489 within the same process, and keeping it out of `models.py` keeps that
module the stable wire contract. Returning `(value, diagnostics)` everywhere
matches the parser's convention so `refresh_decisions` can merge both streams
into one `SyncResult`. `verify_freshness` returning `unverified` for a `None`
root is load-bearing: spec §2 forbids ever reporting `current` without a check,
and a remote namespace legitimately has no local root.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py` (CREATE)

```python
"""Python citations, scope attribution and freshness (FEAT-578 Module 3)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.evidence import (
    build_evidence,
    extract_python_citations,
    verify_freshness,
)
from parrot.knowledge.wiki.decisions.models import DecisionError

SOURCE = '''\
# Module-level note: see ADR-42 for the storage choice.
import os


def alpha():
    """Docstring rationale, see ADR/007."""
    # inline comment, ADR 99
    label = "this string mentions ADR-13 but is executable data"
    return label


class Beta:
    def alpha(self):
        """Same method name as the module function — ADR-42 again."""
        return 1
'''


class TestPythonCitations:
    def test_comments_and_docstrings_are_found(self):
        cites, diags = extract_python_citations("pkg/mod.py", SOURCE)
        assert diags == []
        assert {c.alias for c in cites} == {"ADR-42", "ADR-7", "ADR-99"}

    def test_executable_string_is_not_rationale(self):
        """spec §2: a string literal in code is data, never a citation."""
        cites, _ = extract_python_citations("pkg/mod.py", SOURCE)
        assert "ADR-13" not in {c.alias for c in cites}

    def test_module_comment_is_file_scope(self):
        """A module-level comment attaches to the file, not to a symbol."""
        cites, _ = extract_python_citations("pkg/mod.py", SOURCE)
        module_note = next(c for c in cites if c.line == 1)
        assert module_note.qualname is None
        assert module_note.page_id == "file:pkg/mod.py"

    def test_nearest_enclosing_symbol_wins(self):
        """ADR-42 in Beta.alpha's docstring must not attach to module scope."""
        # FILL IN: assert the citation on the Beta.alpha docstring line has
        # qualname == "Beta.alpha" and a page_id built by sym_concept_id
        raise NotImplementedError

    def test_duplicate_symbol_names_stay_distinct(self):
        """Two `alpha`s in one file resolve to two different page_ids (AC2)."""
        # FILL IN: assert the module-level `alpha` and `Beta.alpha` produce
        # different page_ids
        raise NotImplementedError

    def test_syntax_error_is_a_diagnostic_not_an_exception(self):
        cites, diags = extract_python_citations("pkg/bad.py", "def (:\n")
        assert cites == []
        assert diags and diags[0].code == "ADR_PARSE_FAILED"

    def test_no_reference_yields_nothing(self):
        assert extract_python_citations("pkg/x.py", "# plain comment\n") == ([], [])


class TestEvidence:
    def test_span_excerpt_and_hash_are_exact(self):
        ref = build_evidence("pkg/mod.py", SOURCE, "file:pkg/mod.py", 1, 1, "comment")
        assert ref.start_line == 1 and ref.end_line == 1
        assert ref.excerpt.startswith("# Module-level note")
        # FILL IN: assert source_sha1 equals sha1_of_span of that same excerpt
        raise NotImplementedError


class TestFreshness:
    async def test_no_root_is_unverified_never_current(self, tmp_path):
        """spec §2: absent a local root, freshness is unverified."""
        ref = build_evidence("m.py", "a\nb\n", "file:m.py", 1, 1, "code")
        assert (await verify_freshness(None, ref))[0] == "unverified"

    async def test_unchanged_source_is_current(self, tmp_path):
        # FILL IN: write m.py with known content, build evidence from it,
        # assert verify_freshness(tmp_path, ref)[0] == "current"
        raise NotImplementedError

    async def test_changed_source_is_stale(self, tmp_path):
        # FILL IN: mutate the file after building the evidence; assert "stale"
        # and that a diagnostic is returned (spec §2)
        raise NotImplementedError

    async def test_deleted_source_is_missing(self, tmp_path):
        # FILL IN: delete the file; assert "missing"
        raise NotImplementedError

    @pytest.mark.parametrize("bad", ["../escape.py", "/etc/passwd"])
    async def test_path_escape_is_refused(self, tmp_path, bad):
        """Confined paths only (spec §2)."""
        # FILL IN: build an EvidenceRef whose rel_path is `bad` (bypassing the
        # model validator with model_construct if needed) and assert
        # DecisionError.code == "ADR_PATH_OUTSIDE_ROOT"
        raise NotImplementedError

    async def test_verification_does_not_mutate(self, tmp_path):
        """Reads never rewrite review status or the record (spec §2)."""
        # FILL IN: assert the EvidenceRef object is unchanged after a stale
        # verification
        raise NotImplementedError
```

### FILL IN checklist

- [ ] `evidence.py::_symbol_ranges` — dotted qualnames + 1-based spans; bounded by `symbols.py:86-87`
- [ ] `evidence.py::_owner_for_line` — innermost containing span; bounded by spec §2
- [ ] `evidence.py::extract_python_citations` — the five numbered steps; bounded by spec §2 comment/docstring-only rule
- [ ] `evidence.py::_resolve_confined` — post-resolution containment; bounded by `ADR_PATH_OUTSIDE_ROOT`
- [ ] `evidence.py::verify_freshness` — the four outcomes + diagnostics; bounded by spec §2
- [ ] `test_evidence.py` — nine test bodies; bounded by the assertions named in each docstring

---

## Acceptance Criteria

- [ ] Citations come only from `tokenize` COMMENT tokens and `ast.get_docstring` (spec §2)
- [ ] An executable string literal containing `ADR-13` is **not** a citation
- [ ] A module-level comment yields file scope (`file:<rel>`, `qualname is None`)
- [ ] Two same-named symbols in one file yield distinct `page_id`s (AC2)
- [ ] Applicability is never propagated through the call graph (spec §2)
- [ ] `ADR_REFERENCE_RE` from TASK-3486 is reused — no second, divergent regex
- [ ] `verify_freshness(None, ...)` returns `unverified`, never `current`
- [ ] Changed → `stale` + diagnostic; deleted → `missing`; escaping path → `ADR_PATH_OUTSIDE_ROOT`
- [ ] Verification mutates nothing (spec §2)
- [ ] All file I/O is offloaded with `asyncio.to_thread`
- [ ] No non-Python citation extractor is added (spec §2 defers it)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_evidence.py -q`

---

## Agent Instructions

1. **Read the spec** §2 "ADR parsing and references" and "Retrieval and freshness".
2. **Verify the Codebase Contract** — confirm `symbols.py:56`, `:141`, `:327` and `graphindex/extractors/code.py:35`.
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
