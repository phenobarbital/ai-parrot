---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [pageindex, markdown, bookstore, ledger-fix]
---

# Feature Specification: PageIndex md_builder — fence-aware heading parser

**Feature ID**: FEAT-613
**Date**: 2026-09-30
**Author**: Jesus Lara (via /sdd-fix, agent:sdd-fix)
**Status**: approved
**Target version**: next minor

**Ledger origin**: `issue:8b6d7358c602` — *parse_markdown_structure is not
fence-aware: '# comment' lines inside code blocks become headings* (kind
`bug`, severity `minor`, discovered from `agent:odoo_hd`). Plan group
`fixgroup:d93a96d44a6a`, lane `sdd`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`parse_markdown_structure()` in
`packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` applies
`_HEADER_RE` (`^(#{1,6})\s+(.*)`) to every stripped line of a Markdown
document with no notion of fenced code blocks. Any line inside a
```` ``` ```` / `~~~` fence that starts with one to six `#` followed by
whitespace — a Python, shell, YAML or TOML comment — is promoted to a
heading and becomes a tree node.

Reproduced on `dev` (`f062ab4e6`):

```python
from parrot.knowledge.pageindex.md_builder import parse_markdown_structure
md = "# Top\n\nintro\n\n```python\n# comment line\nx = 1\n```\n\n## Real\n\nbody\n"
[(s["level"], s["title"]) for s in parse_markdown_structure(md)]
# -> [(1, 'Top'), (1, 'comment line'), (2, 'Real')]   ← 'comment line' is bogus
```

Observed in production while indexing the *Odoo 19 Cookbook* code companion
with `bookstore add-folder`: chapter trees contained bogus sections such as
`],`. The workaround in use (rewriting `# x` as `#: x` inside code blocks
before indexing) mutates the source content and must be retired.

Downstream impact: every consumer of `md_to_tree()` — `PageIndexToolkit`
folder import, the bookstore indexer and the GraphIndex loader/extractor —
inherits the corrupted section tree, wrong `structure` numbering and split
section `text` bodies.

### Goals

- G1: Lines inside a fenced code block are never treated as headings; they
  stay in the enclosing section's `text` verbatim.
- G2: Both backtick and tilde fences are recognised, following the
  CommonMark rules that matter here: an opening fence is ≥3 identical fence
  characters (after up to three spaces of indentation) and the block closes
  only on a fence of the **same character** with **at least the opening
  length**. A backtick fence inside a tilde block does not close it, and
  vice versa.
- G3: An unterminated fence swallows the rest of the document (CommonMark
  behaviour) — no heading after it is recognised. This is deterministic and
  matches how the file renders.
- G4: Pure regression tests with no LLM or tiktoken dependency; the
  existing `count_tokens` monkeypatch pattern is reused.

### Non-Goals (explicitly out of scope)

- Indented (4-space) code blocks. `_HEADER_RE` runs on `line.strip()`, so
  an indented `    # comment` is still a heading; that is a separate,
  lower-impact defect and is not touched here.
- Setext headings (`Title\n=====`) — not supported today; unchanged.
- Any change to `sections_to_tree`, `thin_tree`, node ids, summaries, or
  the `md_to_tree` option surface.
- Retro-reindexing existing bookstore/pageindex stores.

---

## 2. Architectural Design

### Overview

Add fence tracking to the single line loop in `parse_markdown_structure`.
A small pure helper `_fence_marker(line)` classifies a raw line as a fence
line (returning its fence character and run length) or not. The loop keeps
one piece of state, the currently open fence (`None` or `(char, length)`):

- Not in a fence and the line is a fence marker → open it, append the line
  to `current_text`, continue.
- In a fence → append the line to `current_text`; if the line is a closing
  marker (same char, length ≥ opening length, nothing else on the line)
  close it. Never consult `_HEADER_RE`.
- Otherwise → existing heading/body logic, unchanged.

No signature, return shape, or numbering semantics changes. `_HEADER_RE`
and `_parse_header_level` are untouched.

### Component Diagram

```
md_to_tree ──→ parse_markdown_structure ──→ sections_to_tree ──→ thin_tree
                       │
                       ├─→ _fence_marker (new, pure)
                       └─→ _parse_header_level (existing, unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `md_to_tree()` (`md_builder.py:237`) | unchanged caller | Benefits transparently |
| `PageIndexToolkit` folder import / bookstore `add-folder` | unchanged caller | Bogus code-comment nodes disappear |
| `parrot.knowledge.graphindex` loader/extractor | unchanged caller | Uses `md_to_tree`; no API change |

### Data Models

None. Section entries keep their exact keys:
`structure`, `title`, `level`, `line_num`, `text`, `token_count`.

### New Public Interfaces

None public. One private module-level helper:

```python
def _fence_marker(line: str) -> tuple[str, int] | None:
    """Return (fence_char, run_length) when ``line`` is a code-fence line, else None."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: fence-aware parser + tests | yes | Helper signature, loop state machine, fence rules and test matrix fixed below | — |

### Module 1: Fence-aware `parse_markdown_structure`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py`
  (MODIFY) and `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py`
  (CREATE)
- **Responsibility**: Skip heading detection inside fenced code blocks while
  preserving fenced lines in the enclosing section's text.
- **Depends on**: nothing new (stdlib `re` already imported).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py
  # (modifies md_builder.py:21 — add after _HEADER_RE)
  _FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

  def _fence_marker(line: str) -> tuple[str, int] | None:
      """Classify ``line`` as a fenced-code-block delimiter.

      Returns ``(fence_char, run_length)`` — ``fence_char`` is "`" or "~" and
      ``run_length`` the number of consecutive fence characters — when the
      line, after at most three leading spaces, starts with three or more
      identical backticks or tildes. Returns ``None`` otherwise. Info strings
      after an opening fence (```` ```python ````) are allowed.
      """

  # (modifies md_builder.py:34 — parse_markdown_structure body)
  def parse_markdown_structure(md_text: str) -> list[dict]:
      """Parse markdown text into a flat list of section entries.

      Fenced code blocks (``` or ~~~, CommonMark rules) are opaque: lines
      inside them are appended to the current section's text and are never
      interpreted as headings. A block closes on a fence of the same
      character whose length is at least the opening length; an unterminated
      fence extends to the end of the document.
      """
  ```

  Decided loop state machine (pseudocode — the task blueprint spells it out):

  ```
  open_fence: tuple[str, int] | None = None
  for line_num, line in enumerate(lines, 1):
      marker = _fence_marker(line)
      if open_fence is not None:
          current_text.append(line)
          if marker and marker[0] == open_fence[0] and marker[1] >= open_fence[1] \
             and line.strip() == marker[0] * len(line.strip()):
              open_fence = None
          continue
      if marker is not None:
          open_fence = marker
          current_text.append(line)
          continue
      # ... existing heading / body logic verbatim ...
  ```

  Closing-fence rule: the stripped line must consist **only** of fence
  characters (no info string) — CommonMark forbids info strings on closing
  fences, which is what keeps ```` ```python ```` from closing a block.

---

## 4. Test Specification

### Unit Tests

New file `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py`.
All tests monkeypatch `parrot.knowledge.pageindex.md_builder.count_tokens`
with a char-count stub (same pattern as `test_folder_import.py:54`) so no
tiktoken download is needed.

| Test | Module | Description |
|---|---|---|
| `test_hash_comment_inside_backtick_fence_is_not_heading` | M1 | The ledger repro: `# comment line` inside ```` ```python ```` yields only `Top` and `Real`; the fenced lines are in `Top`'s `text` |
| `test_hash_comment_inside_tilde_fence_is_not_heading` | M1 | Same with `~~~` |
| `test_backtick_fence_does_not_close_tilde_fence` | M1 | A ```` ``` ```` line inside a `~~~` block does not close it; a `# x` after it is still body text |
| `test_longer_closing_fence_closes_shorter_opening` | M1 | Opened with ```` ``` ````, closed with ```` ```` ````; heading after it is recognised |
| `test_shorter_closing_fence_does_not_close_longer_opening` | M1 | Opened with ```` ```` ````, a ```` ``` ```` line does not close; heading after it is NOT recognised until the real close |
| `test_closing_fence_with_info_string_does_not_close` | M1 | ```` ```python ```` inside an open block is content, not a close |
| `test_fence_indented_up_to_three_spaces_is_recognised` | M1 | `   ```` opens a fence; `    ```` (four spaces) does not |
| `test_unterminated_fence_swallows_rest_of_document` | M1 | Headings after an unclosed fence are not sections; text is kept |
| `test_headings_outside_fences_unchanged` | M1 | Existing behaviour: nested `#`/`##`/`###` produce the same `structure` numbering and `line_num` as before (regression guard) |
| `test_fence_marker_classification` | M1 | Parametrised direct test of `_fence_marker` on marker / non-marker lines (`` `` `` two backticks, inline code, prose) |

### Integration Tests

| Test | Description |
|---|---|
| `test_md_to_tree_offline_ignores_fenced_comments` | `await md_to_tree(md, adapter=None, options={"if_add_node_summary": "no"})` on the repro document produces a two-node tree with no `comment line` node |

### Test Data / Fixtures

```python
@pytest.fixture(autouse=True)
def _stub_count_tokens(monkeypatch):
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.md_builder.count_tokens",
        lambda text, model="gpt-4o": max(1, len(text or "")),
    )
```

---

## 5. Acceptance Criteria

- [ ] AC1: The §1 repro returns `[(1, 'Top'), (2, 'Real')]` and `Top`'s
      `text` contains the literal `# comment line`.
- [ ] AC2: All tests in `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py` pass.
- [ ] AC3: Existing suites still pass:
      `packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py`,
      `test_toolkit.py`, `test_tree_ops.py`, and
      `packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py`.
- [ ] AC4: `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py` is clean.
- [ ] AC5: No public signature or return-shape change in `md_builder.py`.
- [ ] AC6: Ledger `issue:8b6d7358c602` closed with `--resolved-by task:TASK-<NNN>`.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.pageindex.md_builder import parse_markdown_structure, md_to_tree  # verified: md_builder.py:34, :194
from parrot.knowledge.pageindex.md_builder import _parse_header_level  # verified: md_builder.py:24
import re  # already imported: md_builder.py:6
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py  (dev @ f062ab4e6)
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")                          # line 21
def _parse_header_level(line: str) -> tuple[int, str] | None: ...     # line 24
def parse_markdown_structure(md_text: str) -> list[dict]: ...         # line 34
def sections_to_tree(sections: list[dict]) -> list[dict]: ...         # line 80
async def md_to_tree(md_text, adapter=None, options=None, doc_name="document.md") -> dict: ...  # line 194
```

Section entry keys produced at `md_builder.py:61-68`:
`structure`, `title`, `level`, `line_num`, `text`, `token_count`.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_fence_marker` | `parse_markdown_structure` loop | direct call per line | `md_builder.py:41-42` |
| (unchanged) `parse_markdown_structure` | `md_to_tree` | `sections = parse_markdown_structure(md_text)` | `md_builder.py:237` |

### Does NOT Exist (Anti-Hallucination)
- ~~`packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py`~~ — does not exist yet; M1 creates it.
- ~~`parrot.knowledge.pageindex.md_builder._FENCE_RE`~~ / ~~`_fence_marker`~~ — do not exist yet; M1 adds them.
- ~~`parrot.knowledge.pageindex.utils.strip_code_fences`~~ — no such helper; do not invent one.
- ~~a `markdown`/`markdown-it`/`mistune` dependency~~ — not installed; the parser is regex + loop only.

### Edit Sites (Blueprint Anchors)

Verified against: `f062ab4e6`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` | MODIFY | `_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")` | `md_builder.py:21` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` | MODIFY | `def parse_markdown_structure(md_text: str) -> list[dict]:` | `md_builder.py:34` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` | MODIFY | `        parsed = _parse_header_level(line)` | `md_builder.py:42` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep the function pure and synchronous; no logging, no new imports.
- Fenced lines are appended **raw** (not stripped) so the section `text`
  round-trips the code block; `.strip()` on the joined text at flush time
  already exists and stays.
- Google-style docstrings, strict type hints, 120-column lines, `black`
  formatting.

### Known Risks / Gotchas
- **Unterminated fence** (G3): a document whose last fence is never closed
  loses every subsequent heading. This matches CommonMark rendering and is
  the deterministic choice; it is covered by an explicit test so the
  behaviour is documented, not accidental.
- **Regex on `line.strip()`**: `_parse_header_level` strips the line before
  matching, so a fence check must run on the **raw** line (indentation
  matters for the 0–3 space rule). Do not reorder these.
- `line_num` values of real headings are unchanged because the loop still
  enumerates every raw line.

### External Dependencies
None.

---

## 8. Open Questions

None. Indented code blocks are deliberately deferred (see Non-Goals); if
they surface in practice, open a new ledger issue against
`sym:…md_builder.py#_parse_header_level`.

---

## 9. Design Research Cross-Check

Skipped (ledger-fix lane: single-file `minor` bug with a fully decided
fix; no exploration document exists to review).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-09-30 | agent:sdd-fix | Initial spec from ledger issue 8b6d7358c602 |
