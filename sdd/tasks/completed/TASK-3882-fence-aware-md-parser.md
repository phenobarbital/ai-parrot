# TASK-3882: Fence-aware `parse_markdown_structure` + regression tests

**Feature**: FEAT-613 — PageIndex md_builder — fence-aware heading parser
**Spec**: `sdd/specs/pageindex-md-builder-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:8b6d7358c602

---

## Context

Implements spec §3 Module 1 (the only module). `parse_markdown_structure()`
in `md_builder.py` runs `_HEADER_RE` on every stripped line, so a `# comment`
inside a fenced code block becomes a heading and a bogus tree node. This was
observed while indexing the Odoo 19 Cookbook code companion via
`bookstore add-folder` (ledger `issue:8b6d7358c602`, minor bug). The fix adds
fence tracking to the line loop, with CommonMark open/close rules (spec §1
G1–G3), and a dedicated regression test file.

---

## Scope

- Add `_FENCE_RE` and the pure helper `_fence_marker(line) -> tuple[str, int] | None`
  to `md_builder.py`, directly below `_HEADER_RE`.
- Extend the loop in `parse_markdown_structure` with an `open_fence` state so
  lines inside a fence are appended to `current_text` verbatim and never go
  through `_parse_header_level`. Closing requires the same fence character,
  length ≥ opening length, and nothing but fence characters on the stripped
  line. An unterminated fence runs to end of document.
- Update the `parse_markdown_structure` docstring to document the fence
  behaviour (spec §3 skeleton text).
- Create `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py`
  with the spec §4 test matrix (10 unit tests + 1 offline `md_to_tree` test).

**NOT in scope**: indented (4-space) code blocks, setext headings, any
change to `sections_to_tree` / `thin_tree` / `md_to_tree` options, closing
the ledger issue (done by `/sdd-fix` after validation).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` | MODIFY | Add `_FENCE_RE`, `_fence_marker`, fence state in the parse loop, docstring |
| `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py` | CREATE | Regression tests for fence handling and unchanged heading numbering |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.md_builder import parse_markdown_structure  # verified: md_builder.py:34
from parrot.knowledge.pageindex.md_builder import md_to_tree                 # verified: md_builder.py:194
from parrot.knowledge.pageindex.md_builder import _parse_header_level        # verified: md_builder.py:24
import re  # already imported in md_builder.py:6 — do NOT add a second import
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py  (dev @ 52c8ba940)
_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")                                   # line 21
def _parse_header_level(line: str) -> tuple[int, str] | None:                  # line 24  (matches on line.strip())
def parse_markdown_structure(md_text: str) -> list[dict]:                      # line 34
    #   line 41:  for line_num, line in enumerate(lines, 1):
    #   line 42:      parsed = _parse_header_level(line)
    #   lines 61-68: section entry keys structure/title/level/line_num/text/token_count
def sections_to_tree(sections: list[dict]) -> list[dict]:                      # line 80
async def md_to_tree(md_text: str, adapter=None, options=None, doc_name="document.md") -> dict:  # line 194
    #   line 237: sections = parse_markdown_structure(md_text)
```

`count_tokens` is imported into `md_builder` from `.utils` (line 12) and is
what the tests monkeypatch as `"parrot.knowledge.pageindex.md_builder.count_tokens"`
(existing pattern: `packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py:54`).

### Does NOT Exist
- ~~`packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py`~~ — this task creates it.
- ~~`md_builder._FENCE_RE`~~, ~~`md_builder._fence_marker`~~ — this task adds them.
- ~~`parrot.knowledge.pageindex.utils.strip_code_fences`~~ — no such helper.
- ~~`markdown`, `markdown_it`, `mistune`~~ — not dependencies; regex + loop only.
- ~~`parse_markdown_structure(md_text, fence_aware=...)`~~ — no new parameters; signature is fixed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py#_parse_header_level",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py#parse_markdown_structure",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py#md_to_tree"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The existing loop body stays byte-identical after the two new guard clauses;
only the fence checks are inserted before `parsed = _parse_header_level(line)`.
Fence detection runs on the **raw** line (indentation matters for the 0–3
space rule); heading detection keeps running on `line.strip()` inside
`_parse_header_level`.

### Key Constraints
- Pure, synchronous, no logging, no new imports, no signature change.
- Fenced lines are appended raw so the section `text` round-trips the code.
- Closing fence: same char, `len >= opening len`, stripped line is only fence
  chars (an info string such as ```` ```python ```` never closes).
- `black` (120 cols), Google-style docstrings, type hints.

### References in Codebase
- `packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py:48-54` — `count_tokens` stub pattern
- `packages/ai-parrot/tests/knowledge/pageindex/test_tree_ops.py` — sibling test style

---

## Implementation Blueprint

### Steps (in order)
1. Insert `_FENCE_RE` + `_fence_marker` below `_HEADER_RE` — *why*: the helper must be defined before `parse_markdown_structure` uses it, and it stays private (underscore) because the spec adds no public API.
2. Replace the `parse_markdown_structure` docstring with the spec §3 text — *why*: the unterminated-fence behaviour (G3) must be documented on the function, not only in tests.
3. Add `open_fence` state before the loop and the two guard clauses at the top of the loop body — *why*: fenced lines must bypass `_parse_header_level` entirely while still landing in `current_text`, so `line_num` of later real headings is unchanged.
4. Create the test file from the block below and complete every `FILL IN` test body against the spec §4 matrix — *why*: AC1/AC2 are the regression guard for the ledger issue.
5. Run `ruff check --fix` on both files, then the Validation Commands — *why*: AC3/AC4.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` (MODIFY — block 1)
```python
# occurrences: 1 (verified: grep -c '^_HEADER_RE = re.compile' packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py)
# AFTER — insert below `_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)")` (verified: md_builder.py:21)
# --- Fenced code block delimiter (CommonMark: 0-3 spaces indent, >=3 backticks or tildes) ---
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _fence_marker(line: str) -> tuple[str, int] | None:
    """Classify ``line`` as a fenced-code-block delimiter.

    Args:
        line: One raw (unstripped) line of Markdown.

    Returns:
        ``(fence_char, run_length)`` — ``fence_char`` is ``"`"`` or ``"~"`` and
        ``run_length`` the number of consecutive fence characters — when the
        line, after at most three leading spaces, starts with three or more
        identical backticks or tildes. Info strings after an opening fence
        (```` ```python ````) are allowed. ``None`` otherwise.
    """
    m = _FENCE_RE.match(line)
    if not m:
        return None
    run = m.group(1)
    return run[0], len(run)
```
**Why this shape**: the spec §3 skeleton fixes the regex and the `(char, length)` return
so the loop can apply the CommonMark close rule (same char, length ≥ opening). It runs on
the raw line because `_parse_header_level` strips, and stripping would erase the 0–3 space
indentation rule.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` (MODIFY — block 2)
```python
# occurrences: 1 (verified: grep -c '^def parse_markdown_structure(md_text: str) -> list\[dict\]:' packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py)
# REPLACE — the docstring directly under `def parse_markdown_structure(md_text: str) -> list[dict]:` (verified: md_builder.py:34-35)
    """Parse markdown text into a flat list of section entries.

    Fenced code blocks (``` or ~~~, CommonMark rules) are opaque: lines inside
    them are appended to the current section's text and are never interpreted
    as headings. A block closes on a fence of the same character whose length
    is at least the opening length; an unterminated fence extends to the end
    of the document.

    Args:
        md_text: Full markdown document text.

    Returns:
        Section entries with ``structure``, ``title``, ``level``, ``line_num``,
        ``text`` and ``token_count`` keys, in document order.
    """
```
**Why**: documents G1–G3 on the function itself; the return-shape sentence pins AC5.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py` (MODIFY — block 3)
```python
# occurrences: 1 (verified: grep -c '^    for line_num, line in enumerate(lines, 1):' packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py)
# BEFORE — insert above `    for line_num, line in enumerate(lines, 1):` (verified: md_builder.py:41)
    open_fence: tuple[str, int] | None = None

# occurrences: 1 (verified: grep -c '        parsed = _parse_header_level(line)' packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py)
# BEFORE — insert above `        parsed = _parse_header_level(line)` (verified: md_builder.py:42), same indentation
        marker = _fence_marker(line)
        if open_fence is not None:
            current_text.append(line)
            stripped = line.strip()
            if (
                marker is not None
                and marker[0] == open_fence[0]
                and marker[1] >= open_fence[1]
                and stripped == marker[0] * len(stripped)
            ):
                open_fence = None
            continue
        if marker is not None:
            open_fence = marker
            current_text.append(line)
            continue
```
**Why**: the spec's decided state machine. Inside a fence the line is content
regardless of what it looks like; it only closes when it is a bare fence of
the same character with at least the opening length (so ```` ```python ````
and a shorter ```` ``` ```` inside a ```` ```` ```` block stay content). The
`continue` statements are what keep `_parse_header_level` from ever seeing a
fenced line. Nothing after `parsed = _parse_header_level(line)` changes.

### `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py` (CREATE)
```python
"""Regression tests for the fence-aware PageIndex Markdown parser (FEAT-613)."""
from __future__ import annotations

import pytest

from parrot.knowledge.pageindex.md_builder import (  # verified: md_builder.py:24/34/194
    _fence_marker,
    md_to_tree,
    parse_markdown_structure,
)


@pytest.fixture(autouse=True)
def _stub_count_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Char-count tokenizer so no tiktoken model download is needed offline."""
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.md_builder.count_tokens",
        lambda text, model="gpt-4o": max(1, len(text or "")),
    )


def _outline(md: str) -> list[tuple[int, str]]:
    return [(s["level"], s["title"]) for s in parse_markdown_structure(md)]


REPRO = "# Top\n\nintro\n\n```python\n# comment line\nx = 1\n```\n\n## Real\n\nbody\n"


def test_hash_comment_inside_backtick_fence_is_not_heading() -> None:
    sections = parse_markdown_structure(REPRO)
    assert [(s["level"], s["title"]) for s in sections] == [(1, "Top"), (2, "Real")]
    assert "# comment line" in sections[0]["text"]
    assert "```python" in sections[0]["text"]


def test_hash_comment_inside_tilde_fence_is_not_heading() -> None:
    # FILL IN: same as the backtick case with ~~~ fences — bounded by spec G2
    raise NotImplementedError


def test_backtick_fence_does_not_close_tilde_fence() -> None:
    # FILL IN: open ~~~, put a ``` line and then "# x" inside, close with ~~~; "# x" must be text — spec G2
    raise NotImplementedError


def test_longer_closing_fence_closes_shorter_opening() -> None:
    # FILL IN: open ```, close ````, a "## After" heading afterwards IS a section — spec G2
    raise NotImplementedError


def test_shorter_closing_fence_does_not_close_longer_opening() -> None:
    # FILL IN: open ````, a ``` line does not close; "## After" before the real close is NOT a section — spec G2
    raise NotImplementedError


def test_closing_fence_with_info_string_does_not_close() -> None:
    # FILL IN: inside an open ``` block a "```python" line is content; heading after it is NOT a section — spec §3
    raise NotImplementedError


def test_fence_indented_up_to_three_spaces_is_recognised() -> None:
    # FILL IN: "   ```" opens a fence (heading inside ignored); "    ```" does not (heading inside IS a section) — spec G2
    raise NotImplementedError


def test_unterminated_fence_swallows_rest_of_document() -> None:
    # FILL IN: "# Top", open ``` never closed, "## Later" → only Top; Top text contains "## Later" — spec G3
    raise NotImplementedError


def test_headings_outside_fences_unchanged() -> None:
    md = "# A\n\ntext\n\n## A.1\n\n### A.1.1\n\n## A.2\n\n# B\n"
    sections = parse_markdown_structure(md)
    assert [(s["structure"], s["title"], s["line_num"]) for s in sections] == [
        ("1", "A", 1),
        ("1.1", "A.1", 5),
        ("1.1.1", "A.1.1", 7),
        ("1.2", "A.2", 9),
        ("2", "B", 11),
    ]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("```", ("`", 3)),
        ("```python", ("`", 3)),
        ("~~~~", ("~", 4)),
        ("   ```", ("`", 3)),
        ("    ```", None),
        ("``", None),
        ("text with ``` inline", None),
        ("# heading", None),
    ],
)
def test_fence_marker_classification(line: str, expected: tuple[str, int] | None) -> None:
    assert _fence_marker(line) == expected


@pytest.mark.asyncio
async def test_md_to_tree_offline_ignores_fenced_comments() -> None:
    tree = await md_to_tree(REPRO, adapter=None, options={"if_add_node_summary": "no"})
    titles = [node["title"] for node in tree["structure"]]
    assert "comment line" not in titles
    # FILL IN: assert the top node is "Top" and its single child is "Real" — bounded by spec §4 integration row
    raise NotImplementedError
```
**Why this shape**: mirrors the spec §4 test table one-to-one; the concrete
tests (repro, numbering guard, marker classification) pin the exact
behaviour, and the `FILL IN` bodies are the edge cases whose fixtures the
executor writes from the table description. The `count_tokens` stub is the
established offline pattern in this test directory.

### FILL IN checklist
- [ ] `test_md_builder.py::test_hash_comment_inside_tilde_fence_is_not_heading` — tilde variant of the repro; bounded by G2
- [ ] `test_md_builder.py::test_backtick_fence_does_not_close_tilde_fence` — mixed-char nesting; bounded by G2
- [ ] `test_md_builder.py::test_longer_closing_fence_closes_shorter_opening` — length rule; bounded by G2
- [ ] `test_md_builder.py::test_shorter_closing_fence_does_not_close_longer_opening` — length rule; bounded by G2
- [ ] `test_md_builder.py::test_closing_fence_with_info_string_does_not_close` — info-string rule; bounded by §3 closing rule
- [ ] `test_md_builder.py::test_fence_indented_up_to_three_spaces_is_recognised` — indentation rule; bounded by G2
- [ ] `test_md_builder.py::test_unterminated_fence_swallows_rest_of_document` — EOF rule; bounded by G3
- [ ] `test_md_builder.py::test_md_to_tree_offline_ignores_fenced_comments` — tree-shape assertion; bounded by §4 integration row

---

## Acceptance Criteria

- [ ] AC1: `parse_markdown_structure(REPRO)` yields `[(1, 'Top'), (2, 'Real')]` and `Top`'s text contains `# comment line`.
- [ ] AC2: every test in `packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py` passes (no `NotImplementedError` left).
- [ ] AC3: the pre-existing pageindex / graphindex suites listed in Validation Commands still pass.
- [ ] AC4: `ruff check` clean on both files.
- [ ] AC5: no signature or return-shape change in `md_builder.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_md_builder.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_folder_import.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_tree_ops.py -q`
- `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -q`

---

## Test Specification

See the CREATE block above — it is the scaffold. Key fixtures:

```python
REPRO = "# Top\n\nintro\n\n```python\n# comment line\nx = 1\n```\n\n## Real\n\nbody\n"
TILDE = "# Top\n\n~~~\n# not a heading\n~~~\n\n## Real\n"
NESTED = "# Top\n\n~~~\n```\n# x\n~~~\n\n## Real\n"
UNTERMINATED = "# Top\n\n```\n## Later\n"
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug pageindex-md-builder-fixes --feature-id FEAT-613`)
2. **Read the spec** `sdd/specs/pageindex-md-builder-fixes.spec.md`
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep -n '_HEADER_RE\|def parse_markdown_structure\|parsed = _parse_header_level' packages/ai-parrot/src/parrot/knowledge/pageindex/md_builder.py`
5. **Update status** in `sdd/tasks/index/pageindex-md-builder-fixes.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `FILL IN`; never change a fixed signature or path
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the two listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-3882 pageindex-md-builder-fixes verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: agent:sdd-fix (Claude Fable 5.1, interactive session)
**Date**: 2026-09-30
**Notes**: Added `_FENCE_RE` / `_fence_marker` and an `open_fence` state to the
`parse_markdown_structure` loop (code commit bf4e4356c). Fenced lines are appended
raw and never reach `_parse_header_level`; close requires same char, length >= opening,
bare fence line. New `test_md_builder.py` carries 20 tests (spec matrix + a line_num
guard + empty-line marker case). Validation: 105 passed across the five listed suites
with `PYTHONPATH=packages/ai-parrot/src` (Cython `.so` copied from the main checkout).
The `md_to_tree` integration test pads section bodies past `thin_tree`'s 50-token
threshold, which the spec's fixture note did not anticipate.

**Deviations from spec**: none (test fixture padded for `thin_tree`; behaviour unchanged)
