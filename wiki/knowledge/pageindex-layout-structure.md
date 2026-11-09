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
2. **analyze_layout** — measure body text, rank heading sizes, find running headers/footers, read bookmarks (dropping a few out-of-order entries), collect standalone bold rows and enumerated title rows. Returns a `LayoutProfile`.
3. **extract_markdown_per_page** — use `LayoutHeaders(profile)` to decide which spans are headings, then segment pages (FEAT-840 splitter).
4. **build_structure** — score a **bookmarks** candidate and a **layout** candidate, return the chosen structure or nothing.
5. **LLM fallback** — if nothing was chosen, run the existing LLM structure pipeline (framed) when an adapter is configured and `structure_mode` allows it.
6. **page fallback** — if the LLM pipeline fails or no adapter is configured, build one node per page.

**Bookmarks candidate.** Each usable bookmark is anchored to a heading segment on its page (normalized equality first, then `_titles_match`). A bookmark is *found* when it is anchored or when its normalized title is contained in the text of any segment of its page. `confidence = found / usable`. Bookmarks are rejected when there are fewer than 2 usable entries, when their page order cannot be repaired (non-monotonic), or when they are a per-page enumeration (e.g., "Page 1", "Page 2", ...).

**Outline repair (FEAT-855).** Before those checks, `_read_bookmarks` keeps one longest non-decreasing page
subsequence of the valid entries. When the entries left out number at most
`floor(BOOKMARK_MAX_DROPPED_SHARE × valid entries)` (5 %, rounded down), they are dropped and the rest is used; the
count is stored as `LayoutProfile.bookmarks_dropped`, logged at INFO and reported as `dropped` on the bookmarks
`CandidateScore` in `structure_report.candidates`. Otherwise nothing is dropped and the outline is rejected with
`non-monotonic: page decreases at entry N`. An outline under 20 entries therefore tolerates no drop. NIST SP 800-53 r5
is the case that motivated this: one of its 358 bookmarks (`PS-1 POLICY AND PROCEDURES`, filed under §3.15) points
back to page 249, which used to discard the whole outline.

**Heading detection (`LayoutHeaders`).** pymupdf4llm asks `LayoutHeaders.get_header_id` for each span; a line takes
the highest level found on any of its spans. In order:
1. Running headers and footers are never headings.
2. A span at a size-ranked heading size (above body, at most 10 % of the characters, up to 4 sizes) gets `#` to `####`.
3. **Bold rows.** A bold span inside a recorded bold row of its page gets that row size's level. `analyze_layout`
   records bold rows at the sizes in `LayoutProfile.bold_sizes`: the body size plus at most one larger *body-text*
   size (above body but holding more than 10 % of the characters, so not a heading size), largest first, one level
   each below every size-ranked heading. Lines of one block whose vertical extents overlap by at least half are one
   visual row, so a code cell and a title cell printed on one baseline (`AC-2` + `ACCOUNT MANAGEMENT`) are one row
   and one heading `AC-2 ACCOUNT MANAGEMENT`. A row counts when every span is bold at one eligible size, it is
   standalone (its block's only row, or the first row with no other all-bold row), it has at most 12 words, and it
   does not end with `.` or `,`. It does not count when it is a list item (starts with `(a)`, `(1)`, `(iv)`…, or ends
   with `;`, `:`, `; and`, `; or`), starts with a lowercase letter (glossary terms), or its text recurs on
   `BOLD_REPEAT_MIN_PAGES` (3) or more pages (table headers, labels).
4. **Bookmark rule.** With a usable outline, a span that is bold, or larger than body and not a body-text size, is
   tagged when its normalized text equals a bookmark title of its page, is a word-boundary prefix of it, or begins
   with the whole title. Mid-title words (`attempts.` in `AC-7 UNSUCCESSFUL LOGON ATTEMPTS`) and prose that merely
   contains a title do not match; the title's first span does, and that tags the whole line.
5. **Enumerated rows (FEAT-856).** A block's first visual row is an *enumerated title* when its first span is bold and
   is a parenthesized enumerator (`(1)`, `(a)`, `(iv)`), and the rest of the row has no lowercase letter and contains
   `ENUMERATED_SEPARATOR` (`|`). NIST SP 800-53 prints every control enhancement this way: a bold 10 pt `(1)`, then
   `ACCOUNT MANAGEMENT | AUTOMATED SYSTEM ACCOUNT MANAGEMENT` in 9 pt small caps that are not bold, which no size,
   bold-row or bookmark rule matches. A wrapped title keeps up to `MAX_CONTINUATION_ROWS` (2) more rows: later rows
   of the same block, or the first row of the next block, that are caps-only, do not start with an enumerator and
   start within half a row height of the row above. Titles are stored in `LayoutProfile.enumerated_lines` (rows
   containing a running line are skipped, and a title recurring on `BOLD_REPEAT_MIN_PAGES` pages is dropped). Every
   span inside one gets the level one below the lowest bold row (at most `######`); pymupdf4llm joins consecutive
   heading lines of one level, so a wrapped title becomes one heading. Mixed-case rows (`(a) Have expired;`) stay
   list items, and a caps row without `|` is not a heading.

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

**The level map only grows deeper (FEAT-856).** `_level_to_depth` visits the levels in ascending order and keeps a
level only when its majority depth is greater than the depth kept for the nearest shallower level; a dropped level is
placed by the third rule above. Without this, one bookmarked heading at a deep level could pull every unanchored
heading of that level up to its depth. In NIST SP 800-53 the control `PL-10 BASELINE SELECTION` is set in 10 pt bold
(level 6, depth 3) while the other controls are 11 pt (level 5, depth 3), and level 6 is also where the enumerated
enhancement titles sit: the raw map `{1: 1, 2: 1, 3: 2, 5: 3, 6: 3}` placed all of them beside their control. The
kept map `{1: 1, 3: 2, 5: 3}` nests them at depth 4. Bookmark items keep their own depth.

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
- `candidates` — list of `CandidateScore` (source, confidence, entries, anchored, rejected, dropped — JSON report only)
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
from bad pairs. The misses were systematic, not a confidence problem: in 800-53 the unmatched titles are the
per-control headings (`ACCOUNT MANAGEMENT`, `SC-22 …`, `POLICY AND PROCEDURES`). Ledger `issue:a3d282c67ed0`
tracked that gap; FEAT-855 fixed it (next run).

**Four-pair run after FEAT-855 (2026-11-09, host, `feat-FEAT-855-pageindex-layout-structure-fixes @ 72267fd08b`,
`--min-confidence 0.6`).** Report `artifacts/logs/layout_eval/20261109T135450Z.json` (git-ignored), sha256
`76fbc0356b4614eda6bc4fe1e3bf282b274d9d3ca299e84b763bf8b80e80fca0`:

| Pair | Pages | Source | Chosen confidence | Candidates (bookmarks / layout) | Reference nodes | Layout nodes | Recall top | Recall all | Page agreement | Seconds |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| arxiv | 9 | hybrid | 1.000 | 1.000 / 1.000 | 10 | 17 | 1.000 | 1.000 | 1.000 | 9.0 |
| nist_800_53 | 492 | hybrid | 0.997 | 0.997 / 1.000 | 164 | 391 | 1.000 | 1.000 | 0.805 | 133.2 |
| nist_csf_2_0 | 32 | hybrid | 1.000 | 1.000 / 1.000 | 14 | 22 | 0.643 | 0.643 | 1.000 | 3.6 |
| aicpa_tsc | 75 | layout | 1.000 | 0.000 / 1.000 | 18 | 16 | 1.000 | 0.611 | 1.000 | 15.4 |

800-53's bookmarks candidate reports 357 entries with `dropped = 1`. Its outline (every family and control) is now
used, and the 11 pt bold control rows anchor it. Two causes lifted the numbers: the outline repair, and bold rows at
a body-text size. 800-53 sets its control headings in 11 pt bold, and AICPA its section sub-headings in 12 pt bold,
both on 10 pt body text. Those sizes carry so much prose (11.3 % and 34.7 % of the characters) that they are not
heading sizes. Either fix alone lifts 800-53 to `recall_all` 1.0; only the bold-row rule helps AICPA. The remaining
misses are not structure bugs:
- **CSF 2.0** — the five unmatched titles are figure captions (`Fig. 1. CSF Core structure`, `Fig. 2. CSF Functions`,
  …) that the LLM reference tree listed as sections; the layout tree is right not to.
- **AICPA** — seven unmatched titles sit inside the criteria tables, which pymupdf4llm renders as markdown tables,
  where no header rule applies.

Deterministic optimizer on the new 800-53 tree (`python -m parrot.knowledge.pageindex.optimizer_eval`, report
`artifacts/logs/optimizer_eval/feat_855_deterministic/optimizer_eval-20261109T135423866777Z.json`, sha256
`25d4a7c30c990fddbfac320465df8f996966639f7af7dd6407612a63c7ba83b1`): 392 → 326 nodes, 290 leaves, leaf tokens
p50 / p90 / max 611 / 1694 / 28862, 35 leaves over target (the 2026-11-09 baseline: 106 nodes, 69 leaves,
1214 / 8271 / 28862, 28 over target — more, smaller leaves now). The widest leaves left are the 38-page
`CONTROL SUMMARIES` table section and long controls (SA-8 spans 15 pages) whose enhancements (`(1) ACCOUNT MANAGEMENT |
AUTOMATED SYSTEM ACCOUNT MANAGEMENT`, a bold marker plus 9 pt small caps) were not headings yet — FEAT-856's
enumerated rows split them (see "Runs after FEAT-856" below).

**Threshold:** `structure_min_confidence` is **fixed at `0.6`** (decision 2026-11-09, from the run above; closes
ledger `issue:ca2daac2be1d`).

**Body-size bold lines (FEAT-845 open question 2, settled by FEAT-855).** Standalone bold rows at the body size *are*
headings, with or without bookmarks (an earlier version of this page said otherwise; the code never matched that).
FEAT-855 added the list-item, lowercase-start and repeat guards because, in 800-53, 78 of the 82 body-size bold
candidates were enumerated list items and list lead-ins (`(a) Have expired;`, `Release information outside of the
system only if:`). With the guards, 4 remain, and the arxiv and CSF 2.0 trees are unchanged.

**Runs after FEAT-856 (2026-11-09, host, `feat-FEAT-856-pageindex-layout-fixes`, `--min-confidence 0.6`).** Four-pair
report `artifacts/logs/layout_eval/20261109T161154Z.json` (git-ignored), sha256
`c626d2fb194b1fe826882049c87b7aee064930696e3415cadce624554dcd91c5`:

| Pair | Pages | Source | Chosen confidence | Candidates (bookmarks / layout) | Reference nodes | Layout nodes | Recall top | Recall all | Page agreement | Seconds |
|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| arxiv | 9 | hybrid | 1.000 | 1.000 / 1.000 | 10 | 17 | 1.000 | 1.000 | 1.000 | 8.7 |
| nist_800_53 | 492 | hybrid | 0.997 | 0.997 / 1.000 | 164 | 1258 | 1.000 | 1.000 | 0.799 | 131.5 |
| nist_csf_2_0 | 32 | hybrid | 1.000 | 1.000 / 1.000 | 14 | 22 | 0.643 | 0.643 | 1.000 | 3.4 |
| aicpa_tsc | 75 | layout | 1.000 | 0.000 / 1.000 | 18 | 16 | 1.000 | 0.611 | 1.000 | 15.3 |

Only 800-53 changed: 391 → 1258 layout nodes, the 867 enhancement titles (the bookmarks candidate still reports 357
entries, `dropped = 1`). `page_agreement` moved from 0.805 to 0.799 because `layout_eval` matches a reference title to
the first node whose title contains it: the reference `SECURITY AND PRIVACY ATTRIBUTES` (AC-16, page 71) now first
meets the enhancement `(1) INFORMATION FLOW ENFORCEMENT | OBJECT SECURITY AND PRIVACY ATTRIBUTES` on page 56. The
AC-16 node itself did not change. In the built 800-53 tree (layout mode, no LLM, 1,258 nodes) every enhancement sits at
depth 4 directly under its control, no enhancement title is cut mid-phrase, and SA-8 (pages 284–298, one leaf before)
has 33 enhancement children.

Deterministic optimizer (`python -m parrot.knowledge.pageindex.optimizer_eval`, target 1500, min 200, no LLM). Reports
(git-ignored) under `artifacts/logs/optimizer_eval/`:

| Run | Report | sha256 |
|---|---|---|
| `dev` before FEAT-856 (after FEAT-853's optimizer fixes) | `dev_4ace6b6d11_deterministic/optimizer_eval-20261109T151738665862Z.json` | `d4e9734e31446f38fff9cfa8afb163ebfcab57f9217d38ac3a0abf0f488c9b0a` |
| FEAT-856 branch | `feat_856_deterministic/optimizer_eval-20261109T161416884344Z.json` | `1d5ecd8ad374e4b942e550ce190d243b53849c01ba2309ff9a21f5fe050558bb` |
| `dev` after FEAT-856 + FEAT-857 (`d643c0c0d4`) | `dev_d643c0c0d4_deterministic/optimizer_eval-20261109T163506928918Z.json` | `550ff81dc66dc73684b04e4f4a1c53af123f20014497059e125df4cb6fae2c04` |
| FEAT-859 branch (`60237d38c6`) | `feat859_60237d38c6_deterministic/optimizer_eval-20261109T172759957700Z.json` | `38036a234c771620c8861f816edece75cd1d2b0cec83a02477c956785e54a8ed` |
| FEAT-861 branch (`90442976dc`) | `feat861_90442976dc_deterministic/optimizer_eval-20261109T183947944098Z.json` | `018fb80a935c7943cad38158ddb25bfab0c11b38fef4c4badf5c1599e9e09229` |

| Document | Run | Nodes before → after | Leaf tokens p50 / p90 / max | Leaves over target before / after |
|---|---|---|---|---|
| nist_800_53_r5 | `dev` before FEAT-856 | 392 → 494 | 596 / 1051 / 3987 | 34 / 5 |
| nist_800_53_r5 | FEAT-856 | 1259 → 735 | 351 / 779 / 1704 | 1 / 1 |
| nist_800_53_r5 | FEAT-856 + FEAT-857 | 1259 → 722 | 341 / 735 / 3864 | 1 / 5 |
| nist_800_53_r5 | FEAT-859 | 1259 → 719 | 341 / 755 / 3864 | 1 / 8 |
| nist_800_53_r5 | FEAT-861 | 1259 → 740 | 350 / 780 / 1704 | 1 / 1 |
| aicpa_tsc_2017 | before FEAT-861 (all four runs above) | 17 → 16 | 1273 / 11239 / 27651 | 4 / 4 |
| aicpa_tsc_2017 | FEAT-861 | 17 → 39 | 1208 / 1474 / 4206 | 4 / 3 |

Before FEAT-856 the optimizer reached its numbers by splitting long controls at pseudo-headings, and the pieces took
the running footer or a statement fragment as their title (`CHAPTER THREE PAGE 19`). Now the controls arrive already
split into titled enhancements; the optimizer merges the short ones (withdrawn enhancements are one line) into a
sibling enhancement.

**After FEAT-857.** The 38-page `CONTROL SUMMARIES` table section used to be cut at every page footer (`APPENDIX C PAGE
428`, …), which kept its pieces small but meaningless. FEAT-857's `running_key` repeat rule drops those footers, so the
section now splits at its real table titles (`TABLE C-1: ACCESS CONTROL FAMILY` … `TABLE C-20: SUPPLY CHAIN RISK
MANAGEMENT FAMILY`). Four of those tables span four to five pages and are single leaves over the target —
`TABLE C-17` (3,864 tokens, pages 481–485), `TABLE C-18` (3,789), `TABLE C-1` (3,213), `TABLE C-19` (2,828) — together
with one enhancement, `(17) INFORMATION FLOW ENFORCEMENT | DOMAIN
AUTHENTICATION` (1,704); that is why the leaf maximum and the over-target count rose while every title became
meaningful. Table rows have no headings, so no heading rule splits them further. Leaf titles and sizes come from a
per-leaf dump of the same deterministic run (same settings, identical node counts).

**After FEAT-859.** Three shorter tables (`TABLE C-3`, `C-5`, `C-7`) were still cut once more at a footer
(`APPENDIX C PAGE 434`, `437`, `441`): FEAT-857's repeat rule counts footers inside one leaf, and a two- or three-page
leaf holds its footer only once or twice (`issue:5a605ae51f61`). FEAT-859's document running lines
(`document_running_keys`, see [pageindex-tree-optimizer.md](pageindex-tree-optimizer.md)) drop a footer in any leaf,
so no node is titled after a footer any more. The three tables become single leaves just over the target —
`TABLE C-7` 1,801 tokens (pages 468–470), `TABLE C-3` 1,654 (461–463), `TABLE C-5` 1,545 (464–466) — which is why the
over-target count rose from 5 to 8 while the leaf maximum stayed at 3,864. The per-leaf dump of the FEAT-859 run
lists 718 nodes below the tree root (the report's 719 counts the root) and no title ending in `PAGE <n>`. Run over the
arxiv fixture, CSF 2.0, HIPAA, AICPA and three book PDFs, the same code leaves every split unchanged.

**After FEAT-861.** The table leaves had no split point left: their rows are `table` segments and the only repeated
line inside is the footer FEAT-859 ignores (`issue:f31b01d845b0`). FEAT-861's page splits (`table_page_splits`, see
[pageindex-tree-optimizer.md](pageindex-tree-optimizer.md)) cut all seven `TABLE C-*` leaves at page boundaries into
21 pieces of 557–1,277 tokens, titled after the table plus their page range — `TABLE C-17: SYSTEM AND SERVICES
ACQUISITION FAMILY (page 481)` … `(pages 484-485)`. The 43-token stub that ends each table (the next page's running
header) joins the last piece. The one leaf still over the target is the enhancement
`(17) INFORMATION FLOW ENFORCEMENT | DOMAIN AUTHENTICATION` (1,704 tokens), which is not a table, so the leaf maximum
fell from 3,864 to 1,704 and the over-target count from 8 to 1. The per-leaf dump lists 739 nodes below the root (the report's 740 counts it), no title
ending in `PAGE <n>`, and 8 layout expansions (the section split plus the seven tables). On AICPA the 27,651-token table
leaf (pages 14–67, 54 table segments) becomes 23 pieces of 667–1,470 tokens; its leaf maximum is now a 4,206-token prose
leaf, and 3 prose leaves stay over the target. Run over the arxiv fixture (whose two tables share one page), CSF 2.0,
HIPAA and three book PDFs, the same code leaves every split unchanged.

## Gotchas

- **Re-imports of FEAT-840 PDFs.** Re-importing a PDF that was indexed with the old per-page markdown (no headings) creates a new revision. The new headings carry `#` markers, so the old revision remains as a historical snapshot.
- **Re-imports after FEAT-855.** A PDF with a body-text-size bold row, a heading split across a baseline, a repaired outline or a formerly over-tagged span renders different markdown, so re-importing it creates a new revision.
- **Re-imports after FEAT-856.** A PDF with enumerated title rows (NIST 800-53 and its relatives) renders new
  headings, and a PDF whose hybrid level map was not increasing places its inserted headings deeper, so re-importing
  either creates a new revision.
- **Enumerated rows need the `|` separator.** A document that titles its enumerated items in caps with `—` or `:`
  between the parts gets no enumerated headings; no corpus PDF has that shape yet.
- **Bold-row guards cut real headings too.** A bold heading that ends with `:`, starts with a lowercase letter, or is printed identically on 3 or more pages (a `Summary` per chapter at body size) is not a heading. Size-ranked headings are unaffected.
- **Bold-line label noise.** Standalone bold rows are a heuristic; in hybrid mode both bookmark and layout scores must pass `structure_min_confidence` before any unbookmarked row is inserted.
- **Same-level heading lines merge.** pymupdf4llm joins consecutive heading lines of one level, so a bold link line directly above a control heading can come out as one title (`Quick link … PT-1 POLICY AND PROCEDURES` in 800-53).
- **BytesIO keeps the LLM path.** When you pass a `BytesIO` stream to `build_page_index`, it skips layout analysis and extraction, keeping the existing LLM pipeline (no structure from bookmarks or layout).
- **pymupdf4llm hint.** pymupdf4llm prints a `pymupdf_layout` hint on import (e.g., "Suggest installing pymupdf_layout for better results"). This is harmless and can be ignored.
- **Headings at <= 12 pt.** Before this feature, headings at 12 pt or less were treated as body text by pymupdf4llm's default `IdentifyHeaders`. Now they are detected by the layout profile, so they become heading segments.

## Related

- [PageIndex](pageindex.md) — trees, adapters, retrieval
- [PageIndex Segment Store](pageindex-segment-store.md) — segments, revisions, `read_pages`
- [PageIndex Local MCP Toolkit](pageindex-local-mcp.md) — `pageindex_import_pdf` without a model
