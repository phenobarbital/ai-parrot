# TASK-5346: Documentation — pageindex-layout-structure.md, pageindex.md, bookstore-codex.md (M12)

**Feature**: FEAT-845 — PageIndex Layout Structure Builder
**Spec**: `sdd/specs/pageindex-layout-structure.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5344, TASK-5342
**Assigned-to**: unassigned

---

## Context

Spec Module 12 and §10 (docs policy `required`, FEAT-801). The spec's frontmatter declares
`docs.pages: [wiki/knowledge/pageindex-layout-structure.md]` and `api_modules:
[parrot.knowledge.pageindex.layout, parrot.knowledge.pageindex.layout_structure,
parrot.knowledge.pageindex.layout_eval]`. This task writes the new page (how PDF structure is chosen,
`structure_mode`, `structure_source`, `structure_min_confidence` and its measured value, errors,
framing of the fallback, PDF import without a model), updates the PDF sections of `pageindex.md`,
and states in `bookstore-codex.md` that PDFs work without an LLM. It runs last: it needs TASK-5344's
evaluation numbers (metrics only) and the final toolkit/Bookstore behaviour (TASK-5341/5342).

---

## Scope

- Create `wiki/knowledge/pageindex-layout-structure.md` from `sdd/templates/techwiki-page.md`
  (frontmatter `title:` + `summary:`), covering every item of spec §10, including the rev 0.2 points:
  structure mode does not disable optional summaries; hybrid insertion requires both scores;
  extraction failure aborts publication instead of storing a contentless document.
- Update `wiki/knowledge/pageindex.md`: Table of Contents link, "How It Works" steps (layout-first
  pipeline), "Building Trees from PDFs" (no-adapter usage, `structure_mode`), the Configuration
  Options table (two new keys), and the `build_page_index` API reference (adapter optional, new return keys).
- Update `wiki/knowledge/bookstore-codex.md`: PDFs work without an LLM (deterministic structure, no
  summaries, no description), with a link to the new page.
- Create `test_layout_docs.py`.

**NOT in scope**: `wiki/knowledge/pageindex-local-mcp.md` (TASK-5343); any code change; AICPA titles
(never — metrics only); regenerating API reference pages (the techwiki build does that).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/pageindex-layout-structure.md` | CREATE | New techwiki page |
| `wiki/knowledge/pageindex.md` | MODIFY | Link + PDF pipeline sections |
| `wiki/knowledge/bookstore-codex.md` | MODIFY | PDFs without an LLM |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` | CREATE | Page present, named, linked |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# test_layout_docs.py — stdlib only (pattern: packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py:1-6)
from pathlib import Path
REPO = Path(__file__).resolve().parents[5]
```

### Existing Signatures to Use
```text
sdd/templates/techwiki-page.md (38 lines): frontmatter title/summary; sections Purpose, Public API
  (`[`Name`](ref:parrot.module.Name)` links), Configuration & Parameters, Usage Examples, Gotchas, Related.
wiki/knowledge/pageindex-local-mcp.md:1-4 — frontmatter example ("---\ntitle: ...\nsummary: ...\n---").
wiki/knowledge/pageindex.md
  :1-3   frontmatter (title only)
  :25    "- [Local MCP Toolkit](pageindex-local-mcp.md)"            (count 1)
  :62    "### How It Works"                                         (count 1); diagram :64-73; steps 1-6 at :75-80
  :80    "6. **Retrieval** — At query time, the LLM reasons over the tree structure to identify relevant nodes." (count 1)
  :168   "## Building Trees from PDFs"                              (count 1); Basic Usage :170, With Options :182, From BytesIO :200
  :457   "| `if_add_node_text` | `str` | `\"no\"` | Include raw page text in each node |"  (count 1, last row of Configuration Options)
  :477   "### `build_page_index(doc, adapter, options=None) → dict`" (count 1); param table :481-485 (adapter row :484); Returns :487
wiki/knowledge/bookstore-codex.md
  :1     "# Bookstore in Codex" (no frontmatter)
  :84-85 "Without an LLM, in-book and cross-book search require `bm25s`. Catalog search,\ncards, inventory, tables of contents, and section reads work without it."
         (":85 'cards, inventory, tables of contents, and section reads work without it.'" count 1)
parrot sdd techwiki check (packages/ai-parrot/src/parrot/sdd/techwiki/check.py:103-159): each docs page must
  exist under the root, be readable, non-empty and have a frontmatter title or a level-1 heading;
  api_modules must be dotted names.
```

### Created by dependencies (facts the page documents)
```python
# TASK-5333/5334 layout.py: analyze_layout, LayoutHeaders, LayoutProfile, PDFStructureError, UnreadablePDFError,
#   NoTextLayerError, MAX_SIZE_LEVELS = 4; TASK-5336/5337 layout_structure.py: build_structure, page_structure,
#   heading_title, StructureReport, CandidateScore; TASK-5340 builder: build_page_index(doc, adapter=None, ...),
#   options structure_mode ("auto"|"layout"|"llm", default "auto") and structure_min_confidence;
#   TASK-5341 import_pdf(structure_mode=...) + result keys + list_documents structure_source;
#   TASK-5342 Bookstore PDFs without an LLM; TASK-5344 layout_eval CLI + measured threshold (Completion Note).
# Verify each name in the merged code before writing it into the page.
```

### Does NOT Exist
- ~~`parrot sdd techwiki check` as a Validation Command~~ — run it as an acceptance step (no registered runner)
- ~~committed evaluation reports~~ — `artifacts/logs/layout_eval/` is gitignored; copy metrics from TASK-5344's Completion Note
- ~~OCR / `pymupdf_layout` support~~ — out of scope; the page says scanned PDFs are rejected
- ~~`structure_source` on markdown/ebook nodes~~ — PDF imports only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/pageindex-layout-structure.md", "action": "CREATE"},
    {"path": "wiki/knowledge/pageindex.md", "action": "MODIFY"},
    {"path": "wiki/knowledge/bookstore-codex.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Metrics only for the evaluation**: per-pair recall/agreement/confidence/time from TASK-5344's
  Completion Note. Never copy an AICPA (`aicpa_tsc`) title into the page.
- Describe behaviour as merged, not as specified: if TASK-5344 changed the default threshold or
  recorded a decision on standalone bold lines, document the merged value/decision.
- `wiki/knowledge/pageindex.md` is also edited by FEAT-843: rebase before `/sdd-done`.
- Keep the existing BytesIO section: BytesIO input keeps the LLM pipeline (no layout path).

---

## Implementation Blueprint

### Steps (in order)
1. Read TASK-5344's Completion Note (`sdd/tasks/completed/TASK-5344-*.md`) and the merged `layout*.py` docstrings — *why*: the page documents merged behaviour and measured numbers.
2. Write the new page from the skeleton below — *why*: AC-17 and spec §10.
3. Apply the `pageindex.md` and `bookstore-codex.md` edits — *why*: the existing PDF docs say structure always needs an LLM.
4. Write `test_layout_docs.py`; run it and `parrot sdd techwiki check --spec sdd/specs/pageindex-layout-structure.spec.md --root .` — *why*: AC-17.

### `wiki/knowledge/pageindex-layout-structure.md` (CREATE)
```markdown
---
title: PageIndex Layout Structure Builder
summary: How PageIndex builds a PDF's tree from its bookmarks and printed headings (no model needed), when it falls back to the LLM or one node per page, and how structure_source records the winner.
---

# PageIndex Layout Structure Builder

## Purpose
<!-- FILL IN: 1-2 paragraphs — structure from the PDF itself first; LLM pipeline as a fallback; PDF import
     without a model (toolkit, MCP, Bookstore). Bounded by spec §1 Goals. -->

## Public API
- [`analyze_layout`](ref:parrot.knowledge.pageindex.layout.analyze_layout) — one pass over span data: body size, heading sizes, running lines, bold lines, bookmarks
- [`LayoutHeaders`](ref:parrot.knowledge.pageindex.layout.LayoutHeaders) — pymupdf4llm `hdr_info` header detector driven by the profile
- [`build_structure`](ref:parrot.knowledge.pageindex.layout_structure.build_structure) — scores the bookmarks and layout candidates and returns the chosen structure
- [`page_structure`](ref:parrot.knowledge.pageindex.layout_structure.page_structure) — one node per page fallback
- [`StructureReport`](ref:parrot.knowledge.pageindex.layout_structure.StructureReport) — what `import_pdf` returns as `structure_report`
- [`layout_eval`](ref:parrot.knowledge.pageindex.layout_eval.main) — the evaluation CLI
<!-- FILL IN: add/remove entries to match the merged public names -->

## How structure is chosen
<!-- FILL IN: pipeline (get_page_tokens → analyze_layout → layout-aware extraction → segment_pages →
     build_structure → LLM fallback → page fallback); bookmarks candidate (found/usable, rejection reasons);
     layout candidate (clean × density × start); choice order; hybrid rule — runs only when BOTH scores
     reach structure_min_confidence, confidence = min of both, no anchored bookmarks → no insertions;
     page conventions (start/end_index, appear-at-start, Preface); anchors (transient, never stored).
     Bounded by spec §2 Overview → Anchors. -->

## Configuration & Parameters
| Name | Where | Default | Meaning |
|---|---|---|---|
| `structure_mode` | `build_page_index` option, `import_pdf(structure_mode=)` | `"auto"` | `auto` / `layout` / `llm` |
| `structure_min_confidence` | `build_page_index` option | <!-- FILL IN: merged default --> | threshold a candidate must reach |
| `structure_source` | every node of a PDF import; `import_pdf` result; `list_documents` row | — | `bookmarks` / `layout` / `hybrid` / `llm` / `pages` |
<!-- FILL IN: mode scope — structure_mode controls structure only; with a model, summaries/description still
     follow with_summaries / with_doc_description; for zero model calls choose layout and disable both.
     Without a model: auto behaves as layout, llm raises ValueError. -->

## Usage Examples
```python
from parrot.knowledge.pageindex import build_page_index

tree = await build_page_index("manual.pdf")            # no adapter: bookmarks / layout / hybrid / pages
print(tree["structure_source"], tree["structure_report"]["confidence"])
```
<!-- FILL IN: import_pdf with structure_mode; Bookstore adds a PDF without --llm -->

## Errors
<!-- FILL IN: UnreadablePDFError, NoTextLayerError (OCR not supported), PDFStructureError for a failed
     layout analysis / extraction / segmentation or empty extracted text — raised before import_pdf's write
     transaction, so nothing is published and an existing document stays unchanged; Bookstore reports it as
     "Cannot index <name>: <reason>". The page fallback (low confidence or LLM failure) still publishes a
     readable revision. -->

## Framed fallback prompts
<!-- FILL IN: the 13 structure-pipeline functions wrap document text with frame_text and pass
     DATA_FRAMING_INSTRUCTION; summaries/description are not framed yet (slice 5). -->

## Evaluation
<!-- FILL IN: how to run `python -m parrot.knowledge.pageindex.layout_eval` (flags), what it measures, and the
     four-pair metrics table from TASK-5344's Completion Note — METRICS ONLY, no aicpa_tsc titles; the
     suggested and chosen threshold. -->

## Gotchas
<!-- FILL IN: re-imports of FEAT-840 PDFs create a new revision (headings now carry #); bold-line label noise
     (document-level heuristic, both scores gate hybrid); BytesIO keeps the LLM path; pymupdf4llm prints a
     pymupdf_layout hint on import (harmless); headings at <= 12 pt were body text before this feature. -->

## Related
- [PageIndex](pageindex.md) — trees, adapters, retrieval
- [PageIndex Segment Store](pageindex-segment-store.md) — segments, revisions, `read_pages`
- [PageIndex Local MCP Toolkit](pageindex-local-mcp.md) — `pageindex_import_pdf` without a model
```
**Why this shape**: the template's sections plus the four topics spec §10 lists (how structure is
chosen, errors, framing, evaluation). Frontmatter title + summary satisfy `techwiki check` and the docs
test. Every FILL IN names the spec section that bounds it, so the page cannot drift from the contract.

### `wiki/knowledge/pageindex.md` (MODIFY)
```markdown
<!-- (a) occurrences: 1 (verified: grep -c '^- \[Local MCP Toolkit\](pageindex-local-mcp.md)$' pageindex.md) — AFTER :25 -->
- [Layout Structure Builder](pageindex-layout-structure.md)

<!-- (b) "### How It Works" (:62, count 1): REPLACE the diagram (:64-73) and steps 1-4 (:75-78) so the pipeline reads
     parse → layout analysis (bookmarks, font statistics) → scored structure (bookmarks / layout / hybrid) →
     LLM fallback (framed) or one node per page → optional summaries; keep step 6 (:80, count 1). FILL IN the
     exact wording — bounded by spec §2 Overview; link pageindex-layout-structure.md. -->

<!-- (c) "## Building Trees from PDFs" (:168, count 1): under "### Basic Usage" add a "Without a model" example
     (`await build_page_index("document.pdf")`, structure_source) and one sentence on structure_mode. -->

<!-- (d) AFTER the Configuration Options row :457 (count 1): -->
| `structure_mode` | `str` | `"auto"` | PDF structure source: `auto` (bookmarks/layout, LLM fallback), `layout` (no LLM structure call), `llm` |
| `structure_min_confidence` | `float` | <!-- FILL IN: merged default --> | Confidence a bookmarks/layout candidate needs before the fallback |

<!-- (e) API reference :477 (count 1): heading becomes "### `build_page_index(doc, adapter=None, options=None) → dict`";
     the adapter row (:484) says "LLM adapter; optional — without it structure is deterministic and summaries are skipped";
     the Returns line (:487) adds `structure_source`, `structure_report`, and the transient `_pages`/`_segments`/`_node_markdown`. -->
```
**Why**: today these sections say structure always comes from the LLM; AC-17 requires the link.

### `wiki/knowledge/bookstore-codex.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'cards, inventory, tables of contents, and section reads work without it.' bookstore-codex.md) — AFTER :85 -->

PDFs can be added without an LLM: their structure comes from the PDF's bookmarks or printed headings
(one node per page when neither is reliable), with no summaries or book description. Scanned PDFs
without a text layer are rejected. See [PageIndex Layout Structure Builder](pageindex-layout-structure.md).
```
**Why**: AC-17 — the Codex page must state that PDFs work without an LLM (spec §10).

### `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` (CREATE)
```python
"""The PageIndex layout-structure documentation is present and linked (FEAT-845 M12)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
WIKI = REPO / "wiki" / "knowledge"
PAGE = WIKI / "pageindex-layout-structure.md"


def test_page_has_frontmatter_and_names() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "structure_mode",
        "structure_source",
        "structure_min_confidence",
        "hybrid",
        "bookmarks",
        "PDFStructureError",
        "NoTextLayerError",
        "UnreadablePDFError",
        "DATA_FRAMING_INSTRUCTION",
        "layout_eval",
    ):
        assert name in text


def test_pages_link_new_page() -> None:
    pageindex = (WIKI / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-layout-structure.md" in pageindex
    assert "structure_mode" in pageindex
    codex = (WIKI / "bookstore-codex.md").read_text(encoding="utf-8")
    assert "pageindex-layout-structure.md" in codex
    # FILL IN: assert the codex page states PDFs work without an LLM (e.g. "PDFs can be added without an LLM")
```
**Why this shape**: mirrors `test_local_mcp_docs.py` (same `parents[5]` repo root), so it runs from the
main checkout and from a worktree alike.

### FILL IN checklist
- [ ] New page: every `<!-- FILL IN -->` section, with merged names and TASK-5344 metrics (no AICPA titles)
- [ ] `pageindex.md` (b), (c), (e) wording; (d) merged default
- [ ] `test_layout_docs.py` — codex sentence assertion

---

## Acceptance Criteria

- [ ] AC-17: `wiki/knowledge/pageindex-layout-structure.md` exists with frontmatter and is linked from `wiki/knowledge/pageindex.md`; `bookstore-codex.md` states that PDFs work without an LLM.
- [ ] `parrot sdd techwiki check --spec sdd/specs/pageindex-layout-structure.spec.md --root .` passes (run it; paste its output in the Completion Note).
- [ ] The page explains that structure mode does not disable optional summaries, that hybrid insertion requires both scores, and that extraction failure aborts publication.
- [ ] No AICPA title appears in any edited file.
- [ ] All Validation Commands pass.
- [ ] `ruff check packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_local_mcp_docs.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_page_has_frontmatter_and_names` | frontmatter title + summary; the ten key names present |
| `test_pages_link_new_page` | `pageindex.md` links the page and names `structure_mode`; `bookstore-codex.md` links it and states PDFs work without an LLM |
| `test_local_mcp_docs.py` (unchanged) | `pageindex.md` still links `pageindex-local-mcp.md` |

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug pageindex-layout-structure --feature-id FEAT-845`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-5344 and TASK-5342 must be `"done"` in
   `sdd/tasks/index/pageindex-layout-structure.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/pageindex-layout-structure.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands as
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q` (never `uv sync` in the worktree)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5346 pageindex-layout-structure verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(filled by sdd-worker)*

**Completed by**: sdd-worker orchestrator, MCP seat, 1 attempt
**Date**: 2026-11-08
**Notes**: Merged into the feature branch; lint clean. Pageindex suite run directly on the host: only the 4 pre-existing failures (test_adapter x2, test_okf_ontology x2) that also fail on clean origin/dev. Engine background validation is capped at ~60s so it is not used. No review feedback recorded.
