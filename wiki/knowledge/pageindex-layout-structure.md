---
title: PageIndex Layout Structure Builder
summary: How PageIndex builds a PDF's tree from its bookmarks and printed headings (no model needed), when it falls back to the LLM or one node per page, and how structure_source records the winner.
---

# PageIndex Layout Structure Builder

## Purpose

PageIndex can build a PDF's tree structure from the PDF itself, without calling an LLM. It first analyzes the PDF's bookmarks and font statistics to extract printed headings, then scores these candidates against the bookmarks. If both scores are high enough, it inserts the printed headings into the bookmark tree (hybrid mode). If neither is reliable, it falls back to the LLM pipeline or one node per page. This deterministic path is useful for Bookstore, MCP toolkits, and any environment without an LLM configured.

## Public API

- [`analyze_layout`](ref:parrot.knowledge.pageindex.layout.analyze_layout) — one pass over span data: body size, heading sizes, running lines, bold lines, bookmarks
- [`LayoutHeaders`](ref:parrot.knowledge.pageindex.layout.LayoutHeaders) — pymupdf4llm `hdr_info` header detector driven by the profile
- [`build_structure`](ref:parrot.knowledge.pageindex.layout_structure.build_structure) — scores the bookmarks and layout candidates and returns the chosen structure
- [`page_structure`](ref:parrot.knowledge.pageindex.layout_structure.page_structure) — one node per page fallback
- [`StructureReport`](ref:parrot.knowledge.pageindex.layout_structure.StructureReport) — what `import_pdf` returns as `structure_report`
- [`layout_eval`](ref:parrot.knowledge.pageindex.layout_eval.main) — the evaluation CLI

## How structure is chosen

For a PDF given by path, `build_page_index` runs the following pipeline:

1. **get_page_tokens** — open the PDF, raise `UnreadablePDFError` on failure, raise `NoTextLayerError` if no non-whitespace text exists on any page.
2. **analyze_layout** — measure body text, rank heading sizes, find running headers/footers, read bookmarks, collect standalone bold lines. Returns a `LayoutProfile`.
3. **extract_markdown_per_page** — use `LayoutHeaders(profile)` to decide which spans are headings, then segment pages (FEAT-840 splitter).
4. **build_structure** — score a **bookmarks** candidate and a **layout** candidate, return the chosen structure or nothing.
5. **LLM fallback** — if nothing was chosen, run the existing LLM structure pipeline (framed) when an adapter is configured and `structure_mode` allows it.
6. **page fallback** — if the LLM pipeline fails or no adapter is configured, build one node per page.

**Bookmarks candidate.** Each usable bookmark is anchored to a heading segment on its page (normalized equality first, then `_titles_match`). A bookmark is *found* when it is anchored or when its normalized title is contained in the text of any segment of its page. `confidence = found / usable`. Bookmarks are rejected when there are fewer than 2 usable entries, when page numbers ever decrease (non-monotonic), or when they are a per-page enumeration (e.g., "Page 1", "Page 2", ...).

**Layout candidate.** The heading segments whose text is not a running-line key and whose title is non-empty. Fewer than 2 → confidence 0. Otherwise `confidence = clean × density_factor × start_factor`, where:
- `clean` is the share of headings with at most 20 words not ending in `.`.
- `density_factor` is 1 when there are at most 8 headings per page on average, else `8 / density`.
- `start_factor` is 1 when the first heading is on a page `<= max(3, ceil(0.1 × page_count))`, else 0.5.

**Choice order.** With `structure_mode` in `auto` | `layout` and `structure_min_confidence` (default 0.6):
1. If bookmarks confidence `>= min_confidence` → the bookmark tree. Apply hybrid insertion only when the layout candidate also has confidence `>= min_confidence`; otherwise keep the bookmark tree unchanged. `structure_source` is `hybrid` when at least one heading was inserted, else `bookmarks`. Hybrid confidence is the minimum of the bookmark and layout confidence.
2. Else if layout confidence `>= min_confidence` → `layout`.
3. Else nothing (the builder then runs the LLM pipeline in `auto` mode with an adapter, or builds the page fallback).

**Hybrid rule.** Only run this rule after both candidate scores pass the threshold. With no anchored bookmarks there is no level mapping, so insert nothing. The anchored bookmarks map a heading *level* to a bookmark *depth* (for each level, the most common depth among the bookmarks anchored at that level). Every heading segment that anchors no bookmark is placed by its level `L`:
- `L` lower (shallower) than every mapped level → not structure; its text stays owned by the node it falls in.
- `L` mapped → that depth.
- `L` unmapped but deeper than some mapped level → `depth(M) + (L − M)`, where `M` is the deepest mapped level below `L`.

**Page conventions.** Page fields follow the convention of the LLM path: `start_index` is the item's page; `end_index` is the next item's page, minus 1 when the next item *appears at the start* of its page, or `page_count` for the last item. An item appears at the start when its anchor segment is the first segment of its page once running-line segments are skipped. When the first item starts after page 1, a `Preface` node covers the pages before it.

**Anchors.** Bookmark, layout and hybrid nodes carry a transient `anchor: {"page": int, "ordinal": int}` naming their heading segment. `attach_pdf_document` resolves it to that segment's `seq` before trying its title match, which removes the containment ambiguity of two similar titles on one page, and removes the `anchor` key from every node it visits. Anchors never reach a stored tree.

## Configuration & Parameters

| Name | Where | Default | Meaning |
|---|---|---|---|
| `structure_mode` | `build_page_index` option, `import_pdf(structure_mode=)` | `"auto"` | `auto` (bookmarks/layout, LLM fallback), `layout` (no LLM structure call), `llm` (LLM only) |
| `structure_min_confidence` | `build_page_index` option | `0.6` | Threshold a candidate must reach before the fallback |
| `structure_source` | every node of a PDF import; `import_pdf` result; `list_documents` row | — | `bookmarks` / `layout` / `hybrid` / `llm` / `pages` |

**Mode scope.** `structure_mode` controls structure generation only. With an adapter, `layout` skips all LLM structure calls but still generates summaries and descriptions when their existing options enable them. To guarantee no model calls with a configured adapter, select `structure_mode="layout"` and `if_add_node_summary="no"` and `if_add_doc_description="no"`. Without a model: `auto` behaves as `layout`, `llm` raises `ValueError("structure_mode='llm' needs an LLM adapter")`.

## Usage Examples

```python
from parrot.knowledge.pageindex import build_page_index

# No adapter: structure from bookmarks or layout (no LLM call)
tree = await build_page_index("manual.pdf")
print(tree["structure_source"], tree["structure_report"]["confidence"])

# With structure_mode: force layout-only structure
tree = await build_page_index(
    "document.pdf",
    options={"structure_mode": "layout", "structure_min_confidence": 0.7}
)
print(tree["structure_source"])  # "layout"
```

**Bookstore.** Bookstore adds PDFs without an LLM:

```python
from parrot.knowledge.pageindex import import_pdf

# Bookstore calls this without an adapter
result = await import_pdf("book.pdf", structure_mode="auto")
# result["structure_source"] is "bookmarks", "layout", or "hybrid"
# result["structure_report"]["confidence"] is the chosen candidate's score
```

## Errors

- **`UnreadablePDFError`** — the PDF file cannot be opened (e.g., permission denied, corrupted file). Raised before any write transaction, so any existing document stays unchanged.
- **`NoTextLayerError`** — the PDF has no non-whitespace text on any page. OCR is out of scope; scanned PDFs are rejected.
- **`PDFStructureError`** — a general structure failure (layout analysis, extraction, or segmentation failed, or extraction yielded no non-whitespace segments). Raised before `import_pdf` opens its write transaction, so nothing is published and an existing document stays unchanged. Bookstore reports it as "Cannot index <name>: <reason>".

The page fallback (low confidence or LLM failure) still publishes a readable revision with the successfully extracted pages and segments.

## Framed fallback prompts

The 13 structure-pipeline functions (`toc_detector_single_page`, `detect_page_index`, `check_if_toc_extraction_is_complete`, `check_if_toc_transformation_is_complete`, `extract_toc_content`, `toc_transformer`, `toc_index_extractor`, `add_page_number_to_toc`, `check_title_appearance`, `check_title_appearance_in_start`, `single_toc_item_index_fixer`, `generate_toc_init`, `generate_toc_continue`) wrap every document-derived value they interpolate with `frame_text(value, source="document")` and pass `system_prompt=DATA_FRAMING_INSTRUCTION` on every adapter call. The `<physical_index_N>` tags stay inside the frame. Summaries and description are not framed yet (slice 5).

## Evaluation

Run the evaluation CLI to measure layout vs LLM structure:

```bash
# Fixture pair (committed)
python -m parrot.knowledge.pageindex.layout_eval \
  --pair arxiv=packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf::packages/ai-parrot/tests/knowledge/pageindex/fixtures/docling_structure.json \
  --min-confidence 0.6 --out artifacts/logs/layout_eval

# Four-pair run (local corpus)
python -m parrot.knowledge.pageindex.layout_eval \
  --pair arxiv=packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf::packages/ai-parrot/tests/knowledge/pageindex/fixtures/docling_structure.json \
  --pair nist_800_53=/path/to/corpus/raw/nist_800_53_r5.pdf::/path/to/corpus/trees/nist_800_53.json \
  --pair nist_csf_2_0=/path/to/corpus/raw/nist_csf_2_0.pdf::/path/to/corpus/trees/nist_csf_2_0.json \
  --pair aicpa_tsc=/path/to/corpus/raw/aicpa_tsc_2017.pdf::/path/to/corpus/trees/aicpa_tsc.json \
  --internal aicpa_tsc --min-confidence 0.6 --out artifacts/logs/layout_eval
```

The CLI writes JSON and markdown reports to `artifacts/logs/layout_eval/<UTC>.json` and `<UTC>.md`. It measures for each pair:
- `structure_source` — the chosen candidate
- `chosen_confidence` — the confidence of the chosen candidate
- `candidates` — list of `CandidateScore` (source, confidence, entries, anchored, rejected)
- `reference_nodes` / `layout_nodes` — node counts
- `recall_top` — top-level title recall (depth-1 references matched by any built node title)
- `recall_all` — all reference title recall (excluding "Preface")
- `page_agreement` — start-page agreement (|start_index delta| <= 1)
- `seconds` — time taken

**Metrics (TASK-5344).** The committed fixture pair (`docling_structure.json`) was measured with
`python -m parrot.knowledge.pageindex.layout_eval`: `recall_top = 1.0`, `recall_all = 1.0`,
`page_agreement = 1.0`, `structure_source = hybrid` (9 pages, confidence 1.0).

**Four-pair run (2026-11-09, host, `dev @ 09c95b1646`, `--min-confidence 0.6`).** Report
`artifacts/logs/layout_eval/20261109T122050Z.json` (git-ignored), sha256 `c203ca912ba536a8677aae6ab0b54c3e7d1ebc1b1b3806adf5fec450aa4c2130`:

| Pair | Pages | Source | Chosen confidence | Candidates (bookmarks / layout) | Reference nodes | Layout nodes | Recall top | Recall all | Page agreement | Seconds |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| arxiv | 9 | hybrid | 1.000 | 1.000 / 1.000 | 10 | 17 | 1.000 | 1.000 | 1.000 | 9.3 |
| nist_800_53 | 492 | layout | 0.940 | 0.000 / 0.940 | 164 | 117 | 1.000 | 0.409 | 0.627 | 137.3 |
| nist_csf_2_0 | 32 | hybrid | 1.000 | 1.000 / 1.000 | 14 | 22 | 0.643 | 0.643 | 1.000 | 3.7 |
| aicpa_tsc | 75 | layout | 1.000 | 0.000 / 1.000 | 18 | 11 | 0.778 | 0.389 | 1.000 | 16.4 |

`suggest_threshold` returned `None`: every chosen candidate scores at least 0.94, so no threshold separates good
from bad pairs. The misses are systematic, not a confidence problem: in 800-53 the unmatched titles are the
per-control headings (`ACCOUNT MANAGEMENT`, `SC-22 …`, `POLICY AND PROCEDURES`), in CSF 2.0 the mid-level sections
(`CSF Core structure`, `CSF Functions`, …). That gap is tracked as ledger `issue:a3d282c67ed0`.

**Threshold:** `structure_min_confidence` is **fixed at `0.6`** (decision 2026-11-09, from the run above; closes
ledger `issue:ca2daac2be1d`).

**Open question 2 (spec §8):** Body-size standalone bold lines do **not** count as headings when the document has no bookmarks. The layout candidate's `clean` factor already filters out noisy bold lines, and the hybrid rule requires both scores to pass, so the risk of false positives is low. The decision is to keep the current heuristic (only size-rank and bookmark-matching rules).

## Gotchas

- **Re-imports of FEAT-840 PDFs.** Re-importing a PDF that was indexed with the old per-page markdown (no headings) creates a new revision. The new headings carry `#` markers, so the old revision remains as a historical snapshot.
- **Bold-line label noise.** Document-level standalone bold lines are a heuristic; both bookmark and layout scores must pass `structure_min_confidence` for hybrid insertion. This prevents noisy bold lines from creating spurious structure.
- **BytesIO keeps the LLM path.** When you pass a `BytesIO` stream to `build_page_index`, it skips layout analysis and extraction, keeping the existing LLM pipeline (no structure from bookmarks or layout).
- **pymupdf4llm hint.** pymupdf4llm prints a `pymupdf_layout` hint on import (e.g., "Suggest installing pymupdf_layout for better results"). This is harmless and can be ignored.
- **Headings at <= 12 pt.** Before this feature, headings at 12 pt or less were treated as body text by pymupdf4llm's default `IdentifyHeaders`. Now they are detected by the layout profile, so they become heading segments.

## Related

- [PageIndex](pageindex.md) — trees, adapters, retrieval
- [PageIndex Segment Store](pageindex-segment-store.md) — segments, revisions, `read_pages`
- [PageIndex Local MCP Toolkit](pageindex-local-mcp.md) — `pageindex_import_pdf` without a model
