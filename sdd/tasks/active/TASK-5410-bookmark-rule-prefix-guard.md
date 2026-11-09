# TASK-5410: Bookmark-rule guard — prefix-only matching, no body-text prose

**Feature**: FEAT-855 — PageIndex Layout Structure Fixes
**Spec**: `sdd/specs/pageindex-layout-structure-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5409
**Assigned-to**: unassigned

**Discovered-from**: `issue:a3d282c67ed0`

---

## Context

Spec §1 cause 4 (bookmark half) and §3 Module 3. Once TASK-5408 makes NIST 800-53's outline usable, the bookmark
rule (`LayoutHeaders.get_header_id` rule 5) tags any span that is bold **or larger than body** and shares text with a
bookmark title of its page **in either direction** (`_titles_match` containment). The prototype measured the result:
11 pt prose lines containing `requirements and controls`, a lone `requirement`, and bold mid-title words `attempts.`
and `information` became headings. This task restricts the rule to spans that are bold or larger than every
body-text size, and matches only equal, word-boundary-prefix or whole-title-prefix spans. The title's first span still
matches, and pymupdf4llm then tags the whole line.

---

## Scope

- Add `_bookmark_prefix_match(text, title)` to `layout.py`.
- Change rule 5's condition to `bold or (body is not None and size > body and size not in self._bold_prefixes)`.
- `_matches_bookmark` uses `_bookmark_prefix_match`; drop the now-unused `_titles_match` import.
- Tests for the matcher and the rule.

**NOT in scope**: bold rows and `_bold_prefixes` (TASK-5409, done first); `score_bookmarks` anchoring in
`layout_structure.py` (unchanged — it keeps `_titles_match`); the wiki (TASK-5411).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `_bookmark_prefix_match`, rule 5 condition, `_matches_bookmark`, import |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import _titles_match, normalize_title  # verified: layout.py:14
# after this task: `from parrot.knowledge.pageindex.segments import normalize_title` (the only _titles_match use
# in layout.py is _matches_bookmark, verified: grep -n _titles_match layout.py → lines 14 and 319)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
def normalize_title(title: str) -> str      # line 305 — casefold, collapse spaces, strip leading "1.2." numbering
                                            #   and trailing " \t.:;,-–—)"; "2.1" → ""
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
class LayoutHeaders:                        # line 260
    self._bookmark_titles: dict[int, list[str]]   # lines 272-275 — usable bookmark titles per page (empty when rejected)
    self._body_bold_prefix                  # line 268 — the prefix rule 5 returns (unchanged)
    self._bold_prefixes: dict[int, str]     # added by TASK-5409 after line 268
    def get_header_id(self, span: dict, page: Any = None) -> str:   # line 277
        # rule 5 today (line 294):
        # if page_no is not None and (bold or (body is not None and size > body)):
        #     if self._matches_bookmark(page_no, text): return self._body_bold_prefix
    def _matches_bookmark(self, page_no: int, text: str) -> bool:   # line 317
        # today: return any(_titles_match(text, title) for title in self._bookmark_titles.get(page_no, []))  # line 319
```

### Does NOT Exist
- ~~`_bookmark_prefix_match`~~ — created by this task.
- ~~a `_titles_match` use elsewhere in layout.py~~ — only line 319; removing the import is required (ruff F401).
- ~~a change to `segments._titles_match`~~ — it stays as is; `score_bookmarks` and `layout_eval` use it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#normalize_title"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `test_header_detector_rules` must pass unchanged: bold `Getting Started` vs bookmark `2 Getting Started` is a
  normalized equality; non-bold body-size `Getting Started is easy` is excluded by the condition, not the matcher.
- Word boundary means a following space after normalization: `requirement` is not a prefix of `requirements and
  controls`, `requirements` is.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_bookmark_prefix_match` as a module-level function above `class LayoutHeaders` — *why*: pure, unit-testable.
2. Replace rule 5's condition — *why*: a body-text size carries prose (spec §2 M3).
3. Replace `_matches_bookmark`'s body and drop `_titles_match` from the import — *why*: mid-title fragments must not match.
4. Write the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — matcher, above `class LayoutHeaders:`)
```python
def _bookmark_prefix_match(text: str, title: str) -> bool:
    """Whether a span's text is a bookmark title, a word-boundary prefix of it, or begins with all of it."""
    span, wanted = normalize_title(text), normalize_title(title)
    if not span or not wanted:
        return False
    return span == wanted or wanted.startswith(span + " ") or span.startswith(wanted + " ")
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` (MODIFY — rule 5 and matcher)
```python
# occurrences: 1 (verified: grep -c '        if page_no is not None and (bold or (body is not None and size > body)):' layout.py)
# REPLACE that line (verified: layout.py:294) with:
        if page_no is not None and (bold or (body is not None and size > body and size not in self._bold_prefixes)):
# occurrences: 1 (verified: grep -c '    def _matches_bookmark(self, page_no: int, text: str) -> bool:' layout.py)
# REPLACE the body of `_matches_bookmark` (verified: layout.py:317-319) with:
    def _matches_bookmark(self, page_no: int, text: str) -> bool:
        """Return whether ``text`` is a usable bookmark title of ``page_no`` or a word-boundary prefix of one."""
        return any(_bookmark_prefix_match(text, title) for title in self._bookmark_titles.get(page_no, []))
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.pageindex.segments import _titles_match, normalize_title' layout.py)
# REPLACE (verified: layout.py:14) with:
from parrot.knowledge.pageindex.segments import normalize_title
```
**Why**: `_bold_prefixes` holds the body size and any body-text size, so `size not in self._bold_prefixes` excludes
exactly the prose sizes while sizes above body that are neither (e.g. a size cut by `MAX_SIZE_LEVELS`) still qualify.

### FILL IN checklist
- [ ] tests below — bodies

---

## Acceptance Criteria

- [ ] `_bookmark_prefix_match`: `("AC-7", "AC-7 UNSUCCESSFUL LOGON ATTEMPTS")` → True; `("attempts.", …)` → False;
      `("information", "SI-7 SOFTWARE, FIRMWARE, AND INFORMATION INTEGRITY")` → False; `("requirement",
      "2.1 REQUIREMENTS AND CONTROLS")` → False; `("REQUIREMENTS", …)` → True; `("2.1", …)` → False.
- [ ] With bold_sizes `[11, 10]` and a bookmark on the page, a non-bold 11 pt span starting with the title → `""`;
      a bold `AC-7` span → `_body_bold_prefix`; bold `attempts.` → `""`.
- [ ] `test_header_detector_rules` passes unchanged; `ruff check` clean (no unused import).

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py -q`

---

## Test Specification

```python
# test_layout.py — add `_bookmark_prefix_match` to the import list
@pytest.mark.parametrize(
    ("text", "title", "expected"),
    [
        ("AC-7", "AC-7 UNSUCCESSFUL LOGON ATTEMPTS", True),
        ("attempts.", "AC-7 UNSUCCESSFUL LOGON ATTEMPTS", False),
        ("information", "SI-7 SOFTWARE, FIRMWARE, AND INFORMATION INTEGRITY", False),
        ("requirement", "2.1   REQUIREMENTS AND CONTROLS", False),
        ("REQUIREMENTS", "2.1   REQUIREMENTS AND CONTROLS", True),
        ("2.1", "2.1   REQUIREMENTS AND CONTROLS", False),
        ("AC-2 ACCOUNT MANAGEMENT Control", "AC-2 ACCOUNT MANAGEMENT", True),
    ],
)
def test_bookmark_prefix_match(text: str, title: str, expected: bool) -> None:
    assert _bookmark_prefix_match(text, title) is expected


def test_bookmark_match_prefix_only() -> None:
    # FILL IN: LayoutProfile(page_count=1, body_size=10, heading_sizes=[16, 14], bold_sizes=[11, 10],
    #   bookmarks=[Bookmark(level=1, title="AC-7 UNSUCCESSFUL LOGON ATTEMPTS", page=1)]); headers = LayoutHeaders(...)
    #   assert headers.get_header_id(_span("AC-7", 10, (72, 300, 100, 312), bold=True), page=_page(0)) == "### "
    #   assert headers.get_header_id(_span("attempts.", 10, (72, 320, 120, 332), bold=True), page=_page(0)) == ""
    #   assert headers.get_header_id(_span("AC-7 UNSUCCESSFUL LOGON ATTEMPTS are counted", 11, (72, 340, 300, 352)), page=_page(0)) == ""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure-fixes --feature-id FEAT-855`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5409 must be `"done"` in `sdd/tasks/index/pageindex-layout-structure-fixes.json`
4. **Verify the Codebase Contract** before writing any code (earlier tasks shifted line numbers in `layout.py`)
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5410 pageindex-layout-structure-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
