---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — carried from sdd/proposals/pageindex-tree-optimizer.brainstorm.md; only core files are touched (ai-parrot-tools is slice 4)
tags: [pageindex, pdf-structure, tree-optimizer, prompt-injection, mcp, bookstore]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-layout-structure.md]
  api_modules: [parrot.knowledge.pageindex.layout, parrot.knowledge.pageindex.layout_structure, parrot.knowledge.pageindex.layout_eval]
---

# Feature Specification: PageIndex Layout Structure Builder

**Feature ID**: FEAT-<NNN>
**Date**: 2026-11-08
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 2.2.0

> Third of the six slices of `sdd/proposals/pageindex-tree-optimizer.brainstorm.md`
> (revision 4). It builds on FEAT-831 (`pageindex-generation-publication`) and FEAT-840
> (`pageindex-segment-store`), both merged, and runs alongside FEAT-843
> (`pageindex-agentic-retrieval`). It carries two hand-offs: FEAT-840 left the framing of the
> builder's own prompts to this slice, and FEAT-842 (`pageindex-local-mcp-toolkit`) left the
> removal of `pageindex_import_pdf` from `llm_dependent_tools` to it. Source paths below are
> relative to `packages/ai-parrot/src/parrot/` unless stated; line numbers were verified at
> `dev` @ `634b507bb5`.

---

## 1. Motivation & Business Requirements

### Problem Statement

PDF structure in PageIndex is built entirely by the LLM. `build_page_index`
(`knowledge/pageindex/builder.py:1545`) hands the raw page text to `tree_parser`
(`builder.py:1436`), which asks the model to find a table of contents, transform it, assign
physical pages, verify every title (`check_title_appearance_in_start_concurrent`,
`builder.py:683`), repair the wrong ones and split large nodes recursively
(`process_large_node_recursively`, `builder.py:1366`). Concretely:

1. **It is the slowest and most expensive part of an import.** Thirteen prompt sites run in
   the structure pipeline alone, before any summary is written, and a TOC-less document goes
   through the no-TOC generator page group by page group.
2. **The PDF's own structure is ignored.** `Document.get_toc()` (embedded bookmarks) and the
   font data of every span are never read in `knowledge/pageindex/`. The repo's test fixture
   (`tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf`) carries ten correct two-level
   bookmarks that the LLM pipeline re-derives at a cost.
3. **The segments FEAT-840 introduced have almost no headings.** The per-page markdown comes
   from `pymupdf4llm.to_markdown(page_chunks=True)` (`pdf_to_markdown.py:94-103`) with its
   default `IdentifyHeaders`, whose `body_limit` defaults to 12 pt
   (`pymupdf4llm/helpers/pymupdf_rag.py:89`): any heading at 12 pt or less is treated as body
   text. On the fixture, 1 of its 189 segments is a heading; the ten bookmarked section titles
   are plain paragraphs (`**1** **Introduction**`). `attach_pdf_document`
   (`segments.py:358`) can therefore only start a node's span at the first segment of its
   page, and the optimizer slice has no heading candidates to expand at.
4. **The builder's prompts are unframed.** None of the thirteen structure prompts uses
   `framing.py` or passes a system prompt (`PageIndexLLMAdapter` accepts one at
   `llm_adapter.py:66`), so text hidden in a PDF reaches the model as instructions. FEAT-840
   left this to slices 3 and 5.
5. **PDF import is impossible without a model.** FEAT-842 lists `pageindex_import_pdf` among
   the tools hidden when no `llm` is configured, and Bookstore refuses PDFs outright when it
   has no LLM (`knowledge/bookstore/library.py:1130-1135`).

### Goals

- **Structure from the PDF itself.** Sources of structure are tried in order and scored for
  confidence: embedded **bookmarks** (rejected when non-monotonic or a per-page enumeration),
  **layout** headings from font statistics (size and weight relative to measured body text,
  running headers and footers excluded), a **hybrid** of the two when bookmarks are coarser
  than the printed headings, the existing **LLM** pipeline as fallback, and one node per
  **page** when nothing else works.
- **Headings become heading segments.** The per-page markdown is extracted with a
  layout-aware header detector, so every printed heading the builder uses is a `heading`
  segment and every structure node is anchored to the exact segment it starts at.
- **`structure_source`** (`bookmarks` | `layout` | `hybrid` | `llm` | `pages`) is recorded on
  every node of the imported subtree, returned by `import_pdf` with the confidence and a
  structure report, and listed by `list_documents`.
- **Deterministic PDF import.** `build_page_index` and `import_pdf` work with no adapter:
  structure from bookmarks or layout (or pages), no summaries, no description.
  `pageindex_import_pdf` leaves `llm_dependent_tools` (FEAT-842 hand-off) and Bookstore
  accepts PDFs without an LLM.
- **Framed fallback prompts.** Every prompt of the LLM structure pipeline wraps document text
  with `frame_text` and carries `DATA_FRAMING_INSTRUCTION` as its system prompt.
- **Explicit failures.** A PDF with no text layer is rejected with a clear error (OCR is out of
  scope); an unreadable PDF raises a clear error instead of a PyMuPDF `FileDataError`.
- **A measured threshold.** A deterministic evaluation script compares layout-built structure
  with LLM-built reference trees (the committed fixture and the local compliance corpus) and
  the default confidence threshold is set from its report.

### Non-Goals (explicitly out of scope)

- The optimizer (`pageindex-tree-optimizer`, slice 5): no normalize/merge/expand passes, no
  token cost model, no `key_items`, no bottom-up summaries. Layout-built leaves are as fine as
  the printed headings and are not split further by the LLM (`process_large_node_recursively`
  runs only on the LLM path, as today).
- Framing the **summary** and **doc-description** prompts (`generate_node_summary`,
  `builder.py:1496`; `generate_doc_description`, `builder.py:1527`): slice 5 rewrites both.
- Rewriting the LLM fallback's own logic (TOC detection, verification, fixing). It is reached
  less often and its prompts are framed; its decisions are unchanged.
- The brainstorm's optional spot-check of low-confidence headings with the light adapter.
  The existing check (`check_title_appearance`, `builder.py:604`) answers "does this title
  appear on this page", which this slice answers deterministically for bookmarks and which is
  true by construction for layout headings; asking "is this line a heading" would need a new
  prompt, and a low-confidence result already falls back to the LLM pipeline.
- OCR, `pymupdf_layout` (pymupdf4llm suggests it on stderr; it is not a dependency), and the
  layout path for `BytesIO` input (it keeps the LLM path, as today).
- Changing `structure_source` semantics for markdown, ebook or free-text imports: those nodes
  carry no `structure_source`.
- `multistoresearch` citations and the agentic loop (FEAT-843).
