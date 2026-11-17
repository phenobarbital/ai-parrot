# TASK-5313: Documentation — wiki/knowledge/pageindex-segment-store.md

**Feature**: FEAT-840 — PageIndex Segment Store
**Spec**: `sdd/specs/pageindex-segment-store.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5301, TASK-5302, TASK-5304, TASK-5305, TASK-5306, TASK-5310, TASK-5311
**Assigned-to**: unassigned

---

## Context

Spec §10 (`docs.policy: required`). One new wiki page documents the segment store; the PageIndex
page links it and the generation-publication page notes that the sweep covers revision files.

---

## Scope

- Create `wiki/knowledge/pageindex-segment-store.md` from `sdd/templates/techwiki-page.md`.
- Update `wiki/knowledge/pageindex.md` (storage layout gains `segments/`; link the new page).
- Update `wiki/knowledge/pageindex-generation-publication.md` (steps 3/4 and the sweep mention revisions).
- Create `tests/knowledge/pageindex/test_segment_docs.py` (pattern: `test_generation_docs.py`).

**NOT in scope**: source changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-segment-store.md` | CREATE | New page |
| `wiki/knowledge/pageindex.md` | MODIFY | Link + storage layout |
| `wiki/knowledge/pageindex-generation-publication.md` | MODIFY | Revisions in publication and sweep |
| `packages/ai-parrot/tests/knowledge/pageindex/test_segment_docs.py` | CREATE | Doc presence test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# none — documentation task
```

### Existing Signatures to Use
```text
sdd/templates/techwiki-page.md                         — page template (frontmatter starts with "---\ntitle: ")
wiki/knowledge/pageindex-generation-publication.md     — sibling page written by FEAT-831 (style reference)
packages/ai-parrot/tests/knowledge/pageindex/test_generation_docs.py:1-27 — test pattern (REPO = parents[5])
Documented names (verify each exists in the merged code before writing it): Segment, DocumentRevision,
  SegmentAddress, ReadResult, SegmentStore, render_body, validate_ownership, scan_segments,
  get_injection_scoring_engine, InjectionScoringEngine, frame_segments, DATA_FRAMING_INSTRUCTION,
  pageindex_list_documents, pageindex_outline, pageindex_read_pages, pageindex_read_segments,
  pageindex_index_segments, bookstore_read_pages, bookstore_read_segments, bookstore_outline,
  scan_injection, injection_probability_threshold, read_max_chars
```

### Does NOT Exist
- ~~`wiki/knowledge/pageindex-segment-store.md`~~ — created here
- ~~a separate API reference generator step~~ — `parrot sdd techwiki check` only checks the pages listed in the spec

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "wiki/knowledge/pageindex-segment-store.md",
      "action": "CREATE"
    },
    {
      "path": "wiki/knowledge/pageindex.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/knowledge/pageindex-generation-publication.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_segment_docs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Content (spec §10): segments and kinds; addresses and labels; revisions vs generations; revision files and
  their sweep; spans/owned ranges and view bodies (gap markers); the four read tools with budgets and cursors;
  injection flags and `scored_by`; framing helpers; the public engine accessor; `index_segments` and its
  legacy-PDF limitation; Bookstore read tools; the three toolkit kwargs; known risks (parent bodies shrink,
  shared page without a heading match).
- Grep each documented name in the merged code first; document only what exists.

---

## Implementation Blueprint

### Steps (in order)
1. Copy the template, fill the page.
2. Update the two existing pages.
3. Write the doc test; run `parrot sdd techwiki check`.

### `packages/ai-parrot/tests/knowledge/pageindex/test_segment_docs.py` (CREATE)
```python
"""The PageIndex segment-store documentation is present and linked."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-segment-store.md"


def test_page_has_frontmatter_and_api() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "DocumentRevision", "SegmentStore", "pageindex_read_pages", "pageindex_read_segments",
        "pageindex_outline", "pageindex_index_segments", "get_injection_scoring_engine",
        "frame_segments", "bookstore_read_pages", "read_max_chars",
    ):
        assert name in text


def test_pageindex_page_links_new_page() -> None:
    text = (REPO / "wiki" / "knowledge" / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-segment-store.md" in text


def test_generation_page_mentions_revisions() -> None:
    # FILL IN: "segments/" or "revision" appears in pageindex-generation-publication.md
    ...
```

### `wiki/knowledge/pageindex-segment-store.md` (CREATE)
```markdown
<!-- FILL IN: from sdd/templates/techwiki-page.md, covering every item in Key Constraints -->
```

### FILL IN checklist
- [ ] new page; bounded by Key Constraints
- [ ] two page updates
- [ ] doc test

---

## Acceptance Criteria

- [ ] AC-1: `parrot sdd techwiki check --spec sdd/specs/pageindex-segment-store.spec.md --root .` passes.
- [ ] AC-2: the doc test passes.
- [ ] AC-3: every name listed in the test exists in the merged code.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_docs.py -q`

---

## Test Specification

See the blueprint block for `test_segment_docs.py`.

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
8. **Commit code** (`feat(pageindex-segment-store): TASK-5313 — Documentation — wiki/knowledge/pageindex-segment-store.md`), then close with
   `parrot sdd task close TASK-5313 pageindex-segment-store verified` and fill the Completion Note.

---

## Completion Note

New wiki page plus updates to pageindex.md and pageindex-generation-publication.md; doc test passes; 'parrot sdd techwiki check' reports 'Docs: required — ok'. Documented names verified against merged code.

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP unavailable)
**Date**: 2026-11-07
**Notes**: tests run with a scratchpad-only shim for navconfig's read-only log dir (environment, not committed)
**Deviations from spec**: none
