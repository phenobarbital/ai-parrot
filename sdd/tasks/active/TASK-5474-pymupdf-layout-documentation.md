# TASK-5474: Documentation — bookstore-pymupdf-layout.md, pageindex-layout-structure.md

**Feature**: FEAT-875 — Optional PyMuPDF Layout for Bookstore PDF Ingestion
**Spec**: `sdd/specs/bookstore-pymupdf-layout.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5469, TASK-5470, TASK-5471, TASK-5472
**Assigned-to**: unassigned

---

## Context

Spec §10 (`docs.policy: required`). This documents the new optional extractor for users and maintainers,
using the verified facts from TASK-5469's compatibility report. Do not use the spec's unverified candidates.

## Scope

- **Create** `wiki/knowledge/bookstore-pymupdf-layout.md` from `sdd/templates/techwiki-page.md`. It covers
  the supported dependency tuple and platforms, `uv pip install 'ai-parrot[bookstore-layout]'`, CLI and Python
  examples, no-LLM behavior, mixed folders, dry-run, re-indexing with `--force`, missing-package and timeout errors,
  rollback guarantees, comparison results (once TASK-5473's log exists, otherwise a pointer), and
  `parrot.knowledge.pageindex.pdf_layout_backend` (transport, errors, lifecycle).
- **Update** `wiki/knowledge/pageindex-layout-structure.md` (anchor `## How structure is chosen`). Distinguish
  `structure_mode` from `pdf_backend`, explain native versus custom (`LayoutHeaders`) headings, and replace the
  implication that the PyMuPDF Layout suggestion can only be ignored.
- State the limits plainly: native inference can change headings, quality depends on the corpus, and the legacy backend is kept intentionally.

**NOT in scope**: code docstrings (each code task owns its own), and README or other wiki pages.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/bookstore-pymupdf-layout.md` | CREATE | New techwiki page |
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | Backend vs structure mode section |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

None (documentation task). Documented symbols:

- `parrot.knowledge.pageindex.pdf_layout_backend.extract_layout_pages`, `LayoutExtractionRequest`, `LayoutExtractionResult` (TASK-5470)
- `build_page_index(options={"pdf_backend": ...})`, `PageIndexToolkit.import_pdf(..., *, pdf_backend=...)` (TASK-5471)
- `Bookstore.add_book` / `add_folder(..., *, pdf_backend=...)`, `bookstore add|add-folder --pdf-backend` (TASK-5472)

### Existing Signatures to Use

- `wiki/knowledge/pageindex-layout-structure.md:21`: `## How structure is chosen` (occurrences: 1)
- Template: `sdd/templates/techwiki-page.md`

### Does NOT Exist

- `wiki/knowledge/bookstore-pymupdf-layout.md` does not exist yet.
- Do not document an `ocr` flag, a `pymupdf_layout` import, or version pins unless the TASK-5469 report verified them.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/bookstore-pymupdf-layout.md", "action": "CREATE"},
    {"path": "wiki/knowledge/pageindex-layout-structure.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

## Implementation Notes

### Key Constraints

- Follow the techwiki page template's frontmatter exactly. `parrot sdd techwiki check` validates it.
- Every command shown must be one that actually works on the merged feature.

## Implementation Blueprint

### Steps (in order)

1. Read the TASK-5469 report and the final signatures from TASK-5470, TASK-5471, and TASK-5472 on the feature branch.
2. Create the new page from the template.
3. Add the backend section to the existing page.
4. Run the techwiki check and its test.

### `wiki/knowledge/bookstore-pymupdf-layout.md` (CREATE)

```markdown
<!-- FILL IN: frontmatter exactly per sdd/templates/techwiki-page.md (api_modules: parrot.knowledge.pageindex.pdf_layout_backend) -->

# Optional PyMuPDF Layout backend for Bookstore

## When to use it
## Install
<!-- FILL IN: verified tuple + platforms from the report -->
## Usage
    bookstore add manual.pdf --pdf-backend pymupdf-layout --no-llm
    bookstore add manual.pdf --pdf-backend pymupdf-layout --force --no-llm
    bookstore add-folder ./books --pdf-backend pymupdf-layout --no-llm
## Native vs custom headings
## Re-indexing an existing book (--force)
## Failure modes and troubleshooting
## How it works (isolated worker)
## Comparison results
```

**Why:** the section list mirrors spec §10's required topics one-for-one, so a reviewer can check coverage.

### `wiki/knowledge/pageindex-layout-structure.md` (MODIFY)

```markdown
<!-- occurrences: 1 (verified: grep -c '## How structure is chosen' wiki/knowledge/pageindex-layout-structure.md) -->
<!-- BEFORE — insert above `## How structure is chosen` (verified: pageindex-layout-structure.md:21) -->
## Extraction backend vs structure mode

<!-- FILL IN: pdf_backend picks the text extractor; structure_mode picks how the tree is built; independent -->
<!-- FILL IN: replace any text implying the PyMuPDF Layout suggestion can only be ignored; link bookstore-pymupdf-layout.md -->
```

### FILL IN checklist

- [ ] Frontmatter per template
- [ ] Every section of the new page
- [ ] Backend section in the existing page and the stale wording replaced

## Acceptance Criteria

- [ ] Both pages cover every spec §10 topic.
- [ ] `parrot sdd techwiki check --spec sdd/specs/bookstore-pymupdf-layout.spec.md --root .` passes.
- [ ] No unverified API names or versions are documented.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_techwiki_check.py -q`

## Test Specification

There are no new tests. Besides the pytest command above, run
`parrot sdd techwiki check --spec sdd/specs/bookstore-pymupdf-layout.spec.md --root .` and paste its result into the Completion Note.

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**: `parrot sdd worktree ensure --slug bookstore-pymupdf-layout --feature-id FEAT-875`
2. **Read the spec** and `sdd/state/FEAT-875/layout-compatibility.md`.
3. **Check dependencies**: TASK-5469, TASK-5470, TASK-5471, and TASK-5472 must be `"done"`.
4. **Verify** the documented symbols exist on the feature branch.
5. **Update status** to `"in-progress"` and commit only the index file.
6. **Implement** from the blueprint, completing every `FILL IN`.
7. **Verify**: run the Validation Commands and the techwiki check.
8. **Commit** only the files this task lists.
9. **Close** with `parrot sdd task close TASK-5474 bookstore-pymupdf-layout verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
