---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — core only: parrot.knowledge.pageindex (layout, layout_structure)
tags: [pageindex, layout-structure, pdf, ledger-fix]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-layout-structure.md]
  api_modules: [parrot.knowledge.pageindex.layout, parrot.knowledge.pageindex.layout_structure]
---

# Feature Specification: PageIndex Layout Fixes — Enumerated Enhancement Headings

**Feature ID**: FEAT-856
**Date**: 2026-11-09
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Ledger-driven follow-up to FEAT-855 (`pageindex-layout-structure-fixes`, merged as PR #2055). Drains the
> `/sdd-fix` group `fixgroup:303847bb291a` — one issue, `issue:92245af971f3`, filed by FEAT-855's host evaluation.
> No brainstorm or proposal: the issue body is the requirement. Every claim below was reproduced on the host
> against the corpus PDFs, and every change was prototyped (monkeypatched over a baseline tree of `origin/dev`,
> nothing committed) and measured with the real `layout_eval` / `optimizer_eval` before this spec was written.
> Code anchors are verified against `dev` at `3565f535df` (code identical to `4ace6b6d11`).

---

## 1. Motivation & Business Requirements

### Problem Statement

NIST SP 800-53 r5 prints each control **enhancement** as one line: a bold 10 pt enumerator `(1)` followed by the
control name and the enhancement name in 9 pt faux small caps (Calibri, not bold) separated by an 11 pt `|`:
`(1) ACCOUNT MANAGEMENT | AUTOMATED SYSTEM ACCOUNT MANAGEMENT`. No FEAT-845/855 heading rule matches that line —
the size rule needs a size above body (9 pt is below), the bold-row rule needs every span bold, and enhancements have
no bookmark — so a control and all its enhancements form one node (SA-8 spans pages 284–298).

The issue's numbers (35 leaves over `target_leaf_tokens` after the deterministic optimizer, max 28,862 tokens) were
measured on the FEAT-855 branch **before** FEAT-853's optimizer fixes reached `dev`. Re-measured on `dev`
(`4ace6b6d11`, host, `target_leaf_tokens` 1500, `min_leaf_tokens` 200): 34 leaves over target before optimizing,
5 after, max 3,987 tokens (`IA-5 AUTHENTICATOR MANAGEMENT`). The optimizer reaches those numbers by **expanding** 30
long controls at pseudo-headings, and the pieces get meaningless titles — the running footer (`AC-2 ACCOUNT
MANAGEMENT` → `CHAPTER THREE PAGE 19`, `CHAPTER THREE PAGE 21`, …) or a bold statement fragment (`Automatically
[ _Selection: remove; disable_ ] temporary and emergency accounts after`). The document's own structure — one titled
enhancement per section — is lost.

Facts measured for the design (host, 2026-11-09):

1. **The line shape is distinctive.** A block's first visual row whose first span is a bold parenthesized enumerator
   and whose remaining text has no lowercase letter and contains `|`: 868 rows in 800-53, **0** in NIST CSF 2.0,
   AICPA TSC, HIPAA 45 CFR 164, the arxiv fixture and the three Bookstore books (Analectas, Crítica de la razón pura,
   Meditaciones). Rows with a bold enumerator but mixed-case text (287 in 800-53: `(a) Have expired;`, all-bold list
   items) are list items and stay body text. No PDF in the set has a caps-only enumerated row **without** `|`.
2. **59 of the 868 titles wrap.** 17 continue on a second row of the same block, 42 in the next block (a one-row
   block whose top sits 1.7 pt above the previous row's bottom): `(3) ACCESS CONTROL FOR MOBILE DEVICES | USE OF
   PORTABLE STORAGE DEVICES WITH NO` + `IDENTIFIABLE OWNER`.
3. **pymupdf4llm joins consecutive heading lines of one level** (`pymupdf_rag.py`, "header text has been broken in
   multiple lines"), so tagging a continuation row with the title's prefix yields one full-title heading.
4. **800-53 uses all six markdown levels**: four size-ranked heading sizes `[26, 16, 14, 13]` (levels 1–4) and bold
   sizes `[11, 10]` (levels 5–6). An enhancement level below the bold rows is capped at 6 and shares it with the
   10 pt bold rows — one of which, `PL-10 BASELINE SELECTION`, is a bookmarked control at depth 3. The hybrid rule
   maps each heading level to the most common depth of the bookmarks anchored at it (`_level_to_depth`), so that one
   anchor maps level 6 to depth 3 and all 867 inserted enhancements land **beside** their control instead of under it.
5. `layout_eval`'s reference tree for 800-53 (165 nodes) has no enhancement nodes, so recall cannot show the gain; the
   optimizer evaluation and the tree shape can.

### Goals

- G1 — A block's first visual row that starts with a bold parenthesized enumerator span and continues in text with no
  lowercase letter containing `|` is a heading (an *enumerated row*), one level below the lowest bold-row level
  (capped at 6). Rows containing a running line, and rows whose text recurs on `BOLD_REPEAT_MIN_PAGES` pages, are not.
- G2 — A wrapped enumerated title keeps its whole text: up to `MAX_CONTINUATION_ROWS` (2) following caps-only rows —
  later rows of the same block, or the first row of the next block — that do not start with an enumerator and start
  within half a row height of the previous row's bottom join the heading.
- G3 — The hybrid level map is strictly increasing in depth: a heading level whose majority anchored depth is not
  deeper than the depth of the nearest shallower mapped level is dropped from the map, so its unanchored headings
  nest one level below that shallower level. Bookmark items keep their own depth.
- G4 — Measured on the host: 800-53 enhancements become titled children of their controls; after the deterministic
  optimizer, leaves over target ≤ 2 (5 today) and the largest leaf ≤ 2,000 tokens (3,987 today); the other three
  `layout_eval` pairs and the arxiv / CSF 2.0 trees are unchanged (§5 has the exact thresholds).

### Non-Goals (explicitly out of scope)

- Caps-only enumerated rows **without** `|` (generic `(a) DEFINITIONS` small-caps headings) — no PDF in the corpus or
  the Bookstore books has one; the separator keeps the rule from firing on unseen documents. Revisit with evidence.
- The optimizer's pseudo-heading fallback taking running footers as titles (`CHAPTER THREE PAGE 19`, `APPENDIX C PAGE
  428` in the `CONTROL SUMMARIES` tables) — `optimizer.py`, filed as `issue:38e4627b2284`.
- The 38-page `CONTROL SUMMARIES` table section — table-only content, still split by the optimizer's fallback.
- `layout_eval`'s first-containment title matching (one 800-53 reference title, `SECURITY AND PRIVACY ATTRIBUTES`,
  now matches the earlier enhancement `(1) INFORMATION FLOW ENFORCEMENT | OBJECT SECURITY AND PRIVACY ATTRIBUTES`;
  `page_agreement` 0.805 → 0.799) — a measurement artifact; the AC-16 node is unchanged.
- The optimizer's merges of short enhancements (withdrawn ones are one line) into neighbours — `min_leaf_tokens`
  behaviour, unchanged.
- Raising the 6-level markdown cap, `heading_sizes` ranking, the bold-row rule, the bookmark rule, `score_layout`,
  `items_to_tree`, `structure_min_confidence` (stays 0.6) — unchanged.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:4620d037145e1740990ac837715a3d364a17c54690710feb301130b9f2042c54 evaluation_digest=sha256:1bfe9f83a54e2dacbf78daf49818b60eb875ba56ccf4183d9416c65fdbbfa9a3 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two small changes, one per module, plus an evaluation. FEAT-845's decision `structure-nodes-anchor-heading-segments`
keeps `LayoutHeaders` the only producer of structure headings; FEAT-855's `bold-rows-at-body-text-sizes` and
`bookmark-rule-prefix-match` are untouched (enumerated rows are a separate rule, checked after the bold-row rule and
before the bookmark rule). FEAT-853's `pseudo-headings-in-optimizer` is untouched: this spec changes which PDF spans
get a `#` prefix and where inserted headings are placed, not how the optimizer segments text.

**Enumerated rows (M1).** `analyze_layout` collects them after the bold rows, from the same line dicts. Per page, the
text blocks are taken in order and split into visual rows (`_visual_rows`). A block's first row is an enumerated row
when `_is_enumerated_row` accepts it: at least two spans; the first span bold and its stripped text a full match of
`_LIST_MARKER_RE` (`(1)`, `(a)`, `(iv)`); the remaining spans' text has a letter, no lowercase letter
(`_is_caps`) and contains `ENUMERATED_SEPARATOR` (`|`). Rows containing a running line are skipped. The title then
takes up to `MAX_CONTINUATION_ROWS` continuation rows — the block's later rows, or, when the block has one row, the
next block's first row — while `_continues_title` accepts them: no running line, caps-only text, first span not an
enumerator, top at most half the previous row's height below its bottom. Candidates whose `running_key` text recurs
on `BOLD_REPEAT_MIN_PAGES` pages are dropped (same filter as bold rows). Each kept title becomes an `EnumeratedLine`
(normalized joined text, union bbox of its rows) in `LayoutProfile.enumerated_lines[page]`.

`LayoutHeaders` gives every span inside a recorded enumerated line of its page one prefix,
`"#" * min(6, len(heading_sizes) + 1 + len(bold_sizes))` (bold sizes as for the bold prefixes: `profile.bold_sizes`,
else `[body_size]`, else none). The check runs after the size rule and the bold-row rule and before the bookmark
rule, for bold and non-bold spans alike (the small caps are not bold). pymupdf4llm gives the line the highest prefix
among its spans and joins the continuation rows' lines into the same heading.

**Strictly increasing level map (M2).** `_level_to_depth` keeps today's majority vote, then walks the levels in
ascending order and keeps a level only when its depth is greater than the depth kept for the nearest shallower
level. `_placed_depth` is unchanged: a dropped level falls back to `depth(M) + (L − M)` from the nearest shallower
mapped level `M`. Anchored bookmark items are not re-placed (they carry their bookmark depth). For 800-53 the raw map
`{1: 1, 2: 1, 3: 2, 5: 3, 6: 3}` becomes `{1: 1, 3: 2, 5: 3}`: level-6 headings nest at depth 4, and level 2 is
dropped too (no unanchored level-2 heading exists — the prototype tree differs from the flat one in exactly the 867
enhancement nodes, every one moved from depth 3 to 4). arxiv (`{3: 1}`) and CSF 2.0 (`{3: 1, 4: 2}`) are already
increasing — their trees were measured identical.

**Measured effect (prototype, host, 2026-11-09 — M3 re-measures with the real code).**

`layout_eval`, four pairs, `--min-confidence 0.6` (baseline = `dev` @ `4ace6b6d11`):

| Pair | Baseline source / recall_all / page agreement / layout nodes | Prototype source / recall_all / page agreement / layout nodes |
|---|---|---|
| arxiv | hybrid / 1.000 / 1.000 / 17 | hybrid / 1.000 / 1.000 / 17 |
| nist_800_53 | hybrid / 1.000 / 0.805 / 391 | hybrid / 1.000 / 0.799 / 1258 (867 enhancements inserted; recall_top 1.000) |
| nist_csf_2_0 | hybrid / 0.643 / 1.000 / 22 | hybrid / 0.643 / 1.000 / 22 |
| aicpa_tsc | layout / 0.611 / 1.000 / 16 | layout / 0.611 / 1.000 / 16 |

`optimizer_eval`, NIST 800-53 r5 (deterministic, target 1500, min 200; AICPA identical in every variant: 17 → 16
nodes, max 27,651, 4 over target):

| Variant | Nodes before → after | Leaves before → after | Leaf tokens p50 / p90 / max | Over target before / after | Expansions | Enhancement nodes kept |
|---|---|---|---|---|---|---|
| `dev` baseline | 392 → 494 | 356 → 428 | 596 / 1051 / 3987 | 34 / 5 | 30 (footer / fragment titles) | — |
| marker row only, flat (M1 without continuations or M2) | 1259 → 555 | 1223 → 518 | 476 / 962 / 1704 | 1 / 4 | 1 | 222 (10 titles cut mid-phrase) |
| **M1 + M2** | 1259 → 735 | 1040 → 515 | 351 / 779 / 1704 | 1 / 1 | 1 (`CONTROL SUMMARIES`) | 337, all at depth 4 |

With M2 all 867 enhancements sit under their control node, and every optimizer merge of an enhancement lands in a
sibling enhancement (530 merges, reason `under_minimum`). The one leaf left over target is
`(17) INFORMATION FLOW ENFORCEMENT | DOMAIN AUTHENTICATION` (1,704 tokens, pp. 59–60). SA-8 (pp. 284–298, one leaf
today) becomes its control node plus enhancements `(1)`–`(33)`.

### Component Diagram

```
analyze_layout(pdf)                                         (layout.py)
 ├─ … bold rows (FEAT-855, unchanged)
 └─ per page, blocks in order: _visual_rows ─→ _is_enumerated_row ─→ _continues_title (≤ 2 rows)
       ─→ repeat filter ─→ LayoutProfile.enumerated_lines[page] = [EnumeratedLine(text, bbox)]   M1
LayoutHeaders(profile).get_header_id(span, page)            (pymupdf4llm hdr_info)
 ├─ size in heading_sizes                       → "#"…            unchanged
 ├─ bold, size in bold_sizes, inside a bold row → bold-size prefix  unchanged
 ├─ inside an enumerated line                   → enumerated prefix M1
 └─ bookmark rule                               → top bold prefix   unchanged
insert_layout_headings(bookmark_items, profile, segments)   (layout_structure.py)
 └─ _level_to_depth(anchored) ─→ strictly increasing map ─→ _placed_depth   M2
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `analyze_layout` (`layout.py:360`) | modifies | collects `enumerated_lines` after the bold rows |
| `LayoutProfile` (`layout.py:83`) | extends | `enumerated_lines` with a default (old profiles still validate) |
| `LayoutHeaders` (`layout.py:477`) | modifies | `_enumerated_prefix`, `_inside_enumerated_line`, one rule in `get_header_id` |
| `_level_to_depth` (`layout_structure.py:212`) | modifies | strictly increasing map |
| `insert_layout_headings` / `_placed_depth` (`layout_structure.py:220`, `:239`) | uses (unchanged) | |
| `build_page_index` → `_layout_pages` (`builder.py:1686`) | uses (unchanged) | calls `analyze_layout` and `LayoutHeaders(profile)` by name |
| pymupdf4llm 0.0.27 `max_header_id` + same-prefix line join | relies on | `pymupdf_rag.py:425`, `:632-638` |

### Data Models

```python
class EnumeratedLine(BaseModel):      # NEW — layout.py, before LayoutProfile
    """A standalone enumerated caps title row (with its continuation rows) and its page geometry."""
    text: str                                       # normalize_title of the joined row texts
    bbox: tuple[float, float, float, float]         # union of the title rows' line boxes

class LayoutProfile(BaseModel):       # layout.py:83
    ...                               # existing fields unchanged
    enumerated_lines: dict[int, list[EnumeratedLine]] = Field(default_factory=dict)   # NEW — by 1-based page
```

### New Public Interfaces

None. `EnumeratedLine` is a model like `BoldLine` (not exported from `parrot.knowledge.pageindex`); the rest are
module constants and private helpers.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Enumerated-row headings | yes | constants, model, helper signatures and the rule position below are fixed | — |
| M2: Strictly increasing level map | yes | the walk below is fixed; `_placed_depth` unchanged | — |
| M3: Evaluation & documentation | no | — | host-only run over the git-ignored corpus; numbers must be copied from the reports, never written by a seat |

### Module 1: Enumerated-row headings
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py`
- **Responsibility**: Detect enumerated caps title rows (with wrapped continuations) and tag them one level below the
  bold rows.
- **Depends on**: existing `_visual_rows`, `_row_text`, `_is_bold`, `_LIST_MARKER_RE`, `BOLD_REPEAT_MIN_PAGES`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py  (after BOLD_REPEAT_MIN_PAGES, layout.py:39-40)
  ENUMERATED_SEPARATOR: str = "|"
  """An enumerated title row names its control and enhancement around this separator."""
  MAX_CONTINUATION_ROWS: int = 2
  """Caps-only rows that may continue a wrapped enumerated title."""

  class EnumeratedLine(BaseModel):  # before LayoutProfile (layout.py:83)
      """A standalone enumerated caps title row (with its continuation rows) and its page geometry."""
      text: str
      bbox: tuple[float, float, float, float]

  class LayoutProfile(BaseModel):  # verified: layout.py:83
      enumerated_lines: dict[int, list[EnumeratedLine]] = Field(default_factory=dict)  # after bold_sizes (layout.py:94)

  def _is_caps(text: str) -> bool:
      """Return whether ``text`` has at least one letter and no lowercase letter."""

  def _is_enumerated_row(row: Sequence[dict]) -> bool:
      """Return whether a visual row opens an enumerated caps title.

      At least two spans; the first span is bold (``_is_bold``) and its stripped text fully matches
      ``_LIST_MARKER_RE``; the other spans' space-joined text passes ``_is_caps`` and contains
      ``ENUMERATED_SEPARATOR``.
      """

  def _continues_title(row: Sequence[dict], previous: Sequence[dict], running_keys: set[tuple[str, str]]) -> bool:
      """Return whether ``row`` continues the wrapped title whose last row is ``previous``.

      No line of the row is a running line; the row has spans; its first span's stripped text does not fully match
      ``_LIST_MARKER_RE``; ``_row_text(row)`` passes ``_is_caps``; and the row's top (min line y0) is at most
      ``previous``'s bottom (max line y1) plus half of ``previous``'s height.
      """

  def _collect_enumerated_lines(
      lines: Sequence[dict], running_keys: set[tuple[str, str]]
  ) -> dict[int, list[EnumeratedLine]]:
      """Return enumerated title rows per page, without titles repeated on ``BOLD_REPEAT_MIN_PAGES`` pages.

      Lines are grouped into blocks by ``(page, block)`` in document order and each block into visual rows. A block
      whose first row contains no running line and passes ``_is_enumerated_row`` opens a title. Continuation
      candidates are the block's later rows, or — when the block has one row — the first row of the next block on
      the same page; they are taken in order while ``_continues_title`` accepts them, at most
      ``MAX_CONTINUATION_ROWS``. Text is ``normalize_title`` of the rows' ``_row_text`` joined by spaces; bbox is the
      union of every line box of the title rows. A title whose ``running_key`` occurs on ``BOLD_REPEAT_MIN_PAGES`` or
      more distinct pages is dropped.
      """

  def analyze_layout(pdf_path: str) -> LayoutProfile:  # verified: layout.py:360
      """As today, plus ``enumerated_lines=_collect_enumerated_lines(lines, running_keys)``."""

  class LayoutHeaders:  # verified: layout.py:477
      def __init__(self, profile: LayoutProfile) -> None:
          """Adds ``self._enumerated_prefix = "#" * min(6, len(heading_sizes) + 1 + len(bold_sizes)) + " "``
          with ``bold_sizes`` resolved exactly as for ``_bold_prefixes``."""
      def get_header_id(self, span: dict, page: Any = None) -> str:  # verified: layout.py:499
          """New rule after the bold-row rule, before the bookmark rule: a span (bold or not) inside an enumerated
          line of its page → ``_enumerated_prefix``."""
      def _inside_enumerated_line(self, page_no: int, bbox: tuple[float, ...]) -> bool:
          """Return whether ``bbox`` is inside a recorded enumerated line on ``page_no`` (``TOLERANCE`` as for bold
          lines)."""
  ```

### Module 2: Strictly increasing level map
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py`
- **Responsibility**: Keep a stray anchor at a deep heading level from flattening every unanchored heading of that
  level to a shallow depth.
- **Depends on**: none (independent of M1; M3 measures both).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py  (modifies layout_structure.py:212)
  def _level_to_depth(anchored: Sequence[dict]) -> dict[int, int]:
      """Map heading levels to their most common anchored bookmark depths, strictly increasing with the level.

      The majority vote is today's (ties to the shallower depth). Levels are then visited in ascending order and a
      level is kept only when its depth is greater than the depth kept for the nearest shallower level; dropped
      levels are placed by ``_placed_depth`` from the nearest shallower mapped level.
      """
  ```

### Module 3: Evaluation & documentation
- **Path**: `wiki/knowledge/pageindex-layout-structure.md`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py`
- **Responsibility**: Re-run the four-pair `layout_eval` and the 800-53 + AICPA `optimizer_eval` on the host with
  the real code, record the numbers, and document the enumerated-row rule and the increasing level map.
- **Depends on**: Modules 1–2.
- **Interface Skeleton**: none (documentation and a content test). The runs read the corpus from the main checkout
  (`corpus/compliance_soc2_hipaa/`, git-ignored) on the host — never from a coder seat. Every number in the page is
  copied from the reports, with each report's path and sha256; if the corpus is unavailable the page says "not run"
  and §5's evaluation criteria are reported unmet, never estimated. AICPA stays metrics-only.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_enumerated_row_detection` | M1 | `_is_enumerated_row` on span dicts: bold `(1)` + `ACCOUNT MANAGEMENT \| DISABLE ACCOUNTS` → True; no `\|` → False; mixed case → False; non-bold `(1)` → False; one span → False |
| `test_enumerated_lines_in_profile` | M1 | synthetic PDF (body 10 pt `helv`, `(1)` 10 pt `hebo` + 9 pt `helv` caps with `\|`) → one `EnumeratedLine` on its page, text normalized; a `(a) Have expired;` bold row and a caps row without `\|` → none |
| `test_enumerated_title_continuations` | M1 | a title wrapped onto the next line (same block) and one whose continuation sits in the next block → one `EnumeratedLine` each whose text ends with the continuation; a mixed-case line below is not joined |
| `test_enumerated_repeat_filter` | M1 | the same enumerated title on 3 pages → no `EnumeratedLine` |
| `test_enumerated_prefix_level` | M1 | heading_sizes `[16, 14]`, bold_sizes `[12, 10]` → spans inside an enumerated line get `"##### "`; with four heading sizes and two bold sizes the prefix is capped at `"###### "`; a span outside gets `""` |
| `test_enumerated_heading_markdown` | M1 | synthetic PDF through `pymupdf4llm.to_markdown(hdr_info=LayoutHeaders(profile))` → exactly one heading line containing `(1)`, the control name and the enhancement name (and the continuation for a wrapped title) |
| `test_header_detector_rules` (unchanged) | M1 | profiles without `enumerated_lines` keep today's prefixes |
| `test_level_to_depth_strictly_increasing` | M2 | `{5: 3 (×3), 6: 3}` → `{5: 3}`; `{3: 1, 4: 2}` unchanged; `{2: 2, 3: 1}` → `{2: 2}`; empty → `{}` |
| `test_hybrid_nests_headings_below_stray_anchor` | M2 | two `##` bookmarked controls plus one `###` bookmarked outlier; unanchored `###` headings land at depth 2 (children), the anchored `###` item keeps depth 1 |
| `test_hybrid_insertion` (unchanged) | M2 | today's placement holds for an increasing map |
| `test_page_has_frontmatter_and_names` (extended) | M3 | page names `enumerated_lines`, `ENUMERATED_SEPARATOR`, `MAX_CONTINUATION_ROWS`, `_level_to_depth` |

### Integration Tests
| Test | Description |
|---|---|
| `test_builder_layout.py` / `test_layout_integration.py` (existing) | arxiv fixture through `build_page_index` keeps its structure source and recall |
| `test_layout_import.py` / `test_layout_eval.py` (existing) | toolkit import and eval report models accept the new profile field |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_layout.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py
- packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_import.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_eval.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py
markers: none

### Test Data / Fixtures

Synthetic PDFs written with `pymupdf` (`_write_pdf` / `insert_text`, fonts `helv` and `hebo`) as `test_layout.py`
does; the committed arxiv fixture for integration. Assertions check outcomes (recorded text, heading lines), never
how PyMuPDF split the lines into blocks: a test that needs a next-block continuation asserts the joined text, not
the block layout. The corpus PDFs are host-only and are used by M3's evaluation runs, never by a test.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] The Validation Contract tests pass with `PYTHONPATH=packages/ai-parrot/src`; `ruff check` is clean on every
      changed file.
- [ ] Enumerated rows (bold enumerator + caps text with `|`) are headings one level below the bold rows (capped at 6);
      wrapped titles keep up to two continuation rows; list items, caps rows without `|`, running lines and titles
      repeated on ≥ 3 pages are not.
- [ ] `_level_to_depth` returns a strictly increasing map; unanchored headings of a dropped level nest below the
      nearest shallower mapped level; anchored bookmark items keep their depth.
- [ ] Profiles built without the new field still validate (`enumerated_lines={}`) and `LayoutHeaders` gives today's
      prefixes for them.
- [ ] Host four-pair `layout_eval` (the wiki page's command, `--min-confidence 0.6`): nist_800_53 `recall_all` = 1.0,
      `recall_top` = 1.0, `page_agreement` ≥ 0.79, source `hybrid`; arxiv (17 layout nodes), nist_csf_2_0 (22) and
      aicpa_tsc (16) keep their FEAT-855 rows (recall, page agreement, layout nodes). Numbers are copied from the report.
- [ ] Host `optimizer_eval` on 800-53 + AICPA (defaults: target 1500, min 200, no LLM): 800-53
      `leaves_over_target_after` ≤ 2 and `leaf_tokens_max` ≤ 2,000; AICPA unchanged (16 nodes after, max 27,651).
- [ ] In the host-built 800-53 tree, enhancement nodes sit one depth below their control (no `(n) … | …` node at a
      control's depth) and no enhancement title ends with `|`, `AND`, `OF`, `WITH` or `—` (wrapped titles complete).
- [ ] `wiki/knowledge/pageindex-layout-structure.md` documents the enumerated-row rule, the continuation rows, the
      increasing level map, both runs (report paths + sha256) and the out-of-scope `CONTROL SUMMARIES` /
      `issue:38e4627b2284` note; AICPA appears as metrics only.
- [ ] No breaking change to public API: `build_page_index`, `import_pdf`, `StructureReport`, `LayoutProfile` keep their
      shapes (one defaulted field added).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# layout.py today (layout.py:3-20)
from __future__ import annotations
import bisect, logging, math, re                                   # verified: layout.py:5-8
from collections import Counter                                    # verified: layout.py:9
from pathlib import Path                                           # verified: layout.py:10
from typing import Any, Literal, Mapping, Optional, Sequence       # verified: layout.py:11
from pydantic import BaseModel, Field                              # verified: layout.py:13
from parrot.knowledge.pageindex.segments import normalize_title    # verified: layout.py:15
# layout_structure.py today
from collections import Counter                                    # verified: layout_structure.py (used by _level_to_depth)
from parrot.knowledge.pageindex.layout import LayoutProfile, StructureMode, StructureSource, running_key  # verified: layout_structure.py:17
# tests
from parrot.knowledge.pageindex.layout import (Bookmark, BoldLine, LayoutHeaders, LayoutProfile, RunningLine,
    UnreadablePDFError, _bookmark_prefix_match, _keep_page_order, _read_bookmarks, _visual_rows,
    analyze_layout)                                                # verified: test_layout.py:13-25
from parrot.knowledge.pageindex.layout_structure import (build_structure, insert_layout_headings,
    items_to_tree)                                                 # verified: test_layout_structure.py:147-151
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
BOLD_REPEAT_MIN_PAGES: int = 3                                     # line 39
_LIST_MARKER_RE = re.compile(r"^\(\s*[A-Za-z0-9]{1,4}\s*\)")       # line 41 — .fullmatch(text) accepts "(1)", "(a)", "(iv)"
class BoldLine(BaseModel): text: str; bbox: tuple[float, float, float, float]; size: Optional[int] = None   # 75-80
class LayoutProfile(BaseModel):                                    # line 83; last field bold_sizes at line 94
def running_key(text: str) -> str                                  # line 97 — casefold, collapse spaces, digits → '#'
def _is_bold(span: dict) -> bool                                   # line 102
def _visual_rows(block_lines: Sequence[dict]) -> list[list[dict]]  # line 146
def _row_all_bold(row: Sequence[dict]) -> bool                     # line 171
def _row_text(row: Sequence[dict]) -> str                          # line 177
def _collect_bold_lines(lines, running_keys, bold_sizes) -> dict[int, list[BoldLine]]  # line 215 — the pattern M1 mirrors
def analyze_layout(pdf_path: str) -> LayoutProfile                 # line 360; line dicts carry page, block, index,
    # block_lines, spans, text, bbox, band, key (382-394); running_keys 411; bold_lines 435; LayoutProfile(...) 445-455
class LayoutHeaders:                                               # line 477
    TOLERANCE: float = 0.5                                         # line 480
    def __init__(self, profile: LayoutProfile) -> None             # line 482; _bold_prefixes 488-490, _running 491
    def get_header_id(self, span: dict, page: Any = None) -> str   # line 499; bold-row rule 513-515, bookmark rule 516-518
    def _inside_bold_line(self, page_no: int, bbox) -> bool        # line 527
    def _matches_bookmark(self, page_no: int, text: str) -> bool   # line 539

# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py
def _level_to_depth(anchored: Sequence[dict]) -> dict[int, int]   # line 212 — majority depth per level
def _placed_depth(level: Optional[int], mapping: dict[int, int]) -> Optional[int]   # line 220
def insert_layout_headings(bookmark_items, profile, segments) -> tuple[list[dict], int]   # line 239
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `enumerated_lines` | `analyze_layout` | `_collect_enumerated_lines(lines, running_keys)` | `layout.py:435` |
| `_enumerated_prefix` | `get_header_id` | new rule before the bookmark rule | `layout.py:516` |
| increasing map | `insert_layout_headings` | `mapping = _level_to_depth(anchored)` | `layout_structure.py:246` |
| heading join | pymupdf4llm | same-prefix consecutive header lines merged | `.venv/.../pymupdf4llm/helpers/pymupdf_rag.py:632` |

### Does NOT Exist (Anti-Hallucination)
- ~~`EnumeratedLine`~~, ~~`LayoutProfile.enumerated_lines`~~, ~~`ENUMERATED_SEPARATOR`~~, ~~`MAX_CONTINUATION_ROWS`~~,
  ~~`_is_caps`~~, ~~`_is_enumerated_row`~~, ~~`_continues_title`~~, ~~`_collect_enumerated_lines`~~,
  ~~`LayoutHeaders._enumerated_prefix`~~, ~~`LayoutHeaders._inside_enumerated_line`~~ — added by this spec.
- ~~a small-caps / font-variant flag~~ — PyMuPDF reports the faux small caps as plain 9 pt text; none is added.
- ~~a `level` or `depth` on `EnumeratedLine`~~ — the level comes from `LayoutHeaders`, the depth from the hybrid map.
- ~~`StructureReport` level-map output~~ — the map is logged at DEBUG only (`hybrid: mapping=…`), as today.

### Edit Sites (Blueprint Anchors)

Verified against: `3565f535df`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `"""A bold row whose running_key text occurs on this many distinct pages is a label or table header."""` | `layout.py:40` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `class LayoutProfile(BaseModel):` | `layout.py:83` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    bold_sizes: list[int] = Field(default_factory=list)  # largest first, body last; [] means [body_size]` | `layout.py:94` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `def _keep_page_order(pages: Sequence[int]) -> list[int]:` | `layout.py:264` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    bold_lines = _collect_bold_lines(lines, running_keys, bold_sizes)` | `layout.py:435` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `        bookmarks_dropped=dropped,` | `layout.py:454` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `        self._running: dict[str, list[str]] = {}` | `layout.py:491` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `        if page_no is not None and (bold or (body is not None and size > body and size not in self._bold_prefixes)):` | `layout.py:516` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    def _matches_bookmark(self, page_no: int, text: str) -> bool:` | `layout.py:539` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | MODIFY | `def _level_to_depth(anchored: Sequence[dict]) -> dict[int, int]:` | `layout_structure.py:212` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | `    _visual_rows,` | `test_layout.py:23` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | `def test_bookmark_match_prefix_only() -> None:` | `test_layout.py:418` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | MODIFY | `    insert_layout_headings,` | `test_layout_structure.py:149` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | MODIFY | `def test_hybrid_confidence_and_empty_mapping():` | `test_layout_structure.py:195` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` | MODIFY | `        "BOLD_REPEAT_MIN_PAGES",` | `test_layout_docs.py:27` | 1 |
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | `## Gotchas` | `pageindex-layout-structure.md:219` | 1 |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- Mirror `_collect_bold_lines`: pure helpers over line dicts, no I/O; `analyze_layout` stays the only function that
  opens a document. Group blocks with an insertion-ordered dict keyed by `(page, block)`, as it does.
- Reuse `_LIST_MARKER_RE` (with `.fullmatch`), `_row_text`, `running_key`, `BOLD_REPEAT_MIN_PAGES` — no new regex.
- Pydantic v2 models with defaulted new fields; Google-style docstrings, strict type hints, 120 columns, `ruff` clean.

### Known Risks / Gotchas
- **Re-imports create new revisions.** Every 800-53-style PDF renders different markdown (new headings), so its
  revision id changes on re-import; any PDF whose hybrid map was non-increasing re-places its inserted headings.
- **Level cap.** With four heading sizes and two bold sizes the enumerated prefix shares level 6 with body-size bold
  rows; M2 is what nests enhancements in hybrid trees. In a layout-only tree they nest under the previous level-5
  heading by markdown level.
- **Separator dependence.** Only `|`-separated caps titles qualify (Non-Goals); a document using `—` or `:` gets no
  enumerated headings.
- **Optimizer merges.** The deterministic optimizer merges enhancements under `min_leaf_tokens` (withdrawn ones are a
  line) into neighbours, so the optimized tree keeps a subset of the enhancement nodes; their text is kept.
- **Corpus.** `corpus/compliance_soc2_hipaa/` is git-ignored and present only in the main checkout on the host; M3
  reads it from there (memory precedent: a seat once invented a metrics table).

### Ledger Linkage
Every task carries `**Discovered-from**: issue:92245af971f3`; `/sdd-fix` step 6 (or `/sdd-done`) closes the issue
with `--resolved-by task:<M3 task>` once the evaluation criteria are met. The optimizer footer bug found while
prototyping is `issue:38e4627b2284` (discovered-from `spec:FEAT-856`), not resolved here.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pymupdf` | 1.27.1 (installed) | span geometry, block order |
| `pymupdf4llm` | 0.0.27 (installed) | `hdr_info`, `max_header_id`, same-prefix heading-line join |

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-856-pageindex-layout-fixes`).
- **Module dependency graph**: M1 and M2 have no edge (different files); M3 → M1, M2 (it measures both).
- **Shared files**: none between M1 (`layout.py`, `test_layout.py`) and M2 (`layout_structure.py`,
  `test_layout_structure.py`); tasks still run in order in the one worktree.
- **Exclusive resources**: M3's runs read the git-ignored corpus in the main checkout on the host and write
  `artifacts/logs/layout_eval/` and `artifacts/logs/optimizer_eval/` — `parallel: false`, host only, never a coder seat.
- **Cross-feature dependencies**: none open. `issue:38e4627b2284` (optimizer footer titles) touches `optimizer.py` only.

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-layout-fixes
entries:
  - id: enumerated-caps-rows-are-headings
    statement: The layout header detector treats a block's first visual row that starts with a bold parenthesized enumerator span and continues in caps-only text containing ENUMERATED_SEPARATOR as a heading one level below the lowest bold-row level (capped at 6), joined with up to MAX_CONTINUATION_ROWS caps-only continuation rows, unless it contains a running line or its text recurs on BOLD_REPEAT_MIN_PAGES or more pages.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders]
    contradicts: []
    supersedes: []
    rationale: NIST 800-53 prints 868 control enhancements as a bold (n) plus 9 pt non-bold small caps with a | separator, which no size, bold-row or bookmark rule matched, so long controls were split only by the optimizer at running-footer pseudo-headings; the shape occurs in no other corpus or Bookstore PDF.
    rejected_alternatives: ["caps-only enumerated rows without the separator (no corpus evidence; higher false-positive risk on unseen documents)", "tag only the marker row (59 of 868 wrapped titles would be cut off)", "a font-variant small-caps detector (PyMuPDF reports the faux small caps as plain 9 pt text)"]
  - id: hybrid-level-map-strictly-increasing
    statement: The hybrid rule's heading-level-to-depth map keeps a level only when its majority anchored depth is deeper than the depth kept for the nearest shallower level, so unanchored headings of a dropped level nest below that level; anchored bookmark items keep their own depth.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#_level_to_depth]
    contradicts: []
    supersedes: []
    rationale: In NIST 800-53 one bookmarked control typeset at 10 pt (PL-10) mapped heading level 6 to control depth, which placed all 867 inserted enhancements beside their controls instead of under them; arxiv and CSF 2.0 maps are already increasing and their trees are unchanged.
    rejected_alternatives: ["place each inserted heading relative to the nearest preceding anchored item (changes placement for every hybrid document, not only inconsistent maps)", "raise the markdown level cap above 6 (non-standard markdown; the segment splitter reads at most six #)", "require a minimum anchor count per mapped level (a threshold with no principled value)"]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:4620d037145e1740990ac837715a3d364a17c54690710feb301130b9f2042c54 evaluation_digest=sha256:1bfe9f83a54e2dacbf78daf49818b60eb875ba56ccf4183d9416c65fdbbfa9a3 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-layout-fixes#enumerated-caps-rows-are-headings@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders; message: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders impacts 2 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_layout_pages, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#build_page_index; inferred: sym:packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py#test_extraction_failure_is_explicit, sym:packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py#test_layout_pages_propagates_errors
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-layout-fixes#hybrid-level-map-strictly-increasing@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#_level_to_depth; message: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#_level_to_depth impacts 2 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#build_structure, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#insert_layout_headings

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: layout-structure, ledger-fix, pdf
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "layout-structure",
      "ledger-fix",
      "pdf"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:1bfe9f83a54e2dacbf78daf49818b60eb875ba56ccf4183d9416c65fdbbfa9a3",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:30be48b9c4b3963f86467d19d5a68cc00473bf33cc32306e7d948fd6ef408ef3",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders impacts 2 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_layout_pages, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#build_page_index; inferred: sym:packages/ai-parrot/tests/knowledge/pageindex/test_builder_layout.py#test_extraction_failure_is_explicit, sym:packages/ai-parrot/tests/knowledge/pageindex/test_builder_pages.py#test_layout_pages_propagates_errors",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-layout-fixes#enumerated-caps-rows-are-headings",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#LayoutHeaders"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:750fe6fb7a54c958f806bbaadd734147aceccc17448a9b471cd8312200655caf",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#_level_to_depth impacts 2 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#build_structure, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#insert_layout_headings",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-layout-fixes#hybrid-level-map-strictly-increasing",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#_level_to_depth"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:4620d037145e1740990ac837715a3d364a17c54690710feb301130b9f2042c54",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:8db73b0c58e88f62314c8fa3a8f29f10c8d8921811f67299898ff9d0100d22eb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Require the `|` separator? — *Resolved by evidence*: yes; no PDF in the corpus or the Bookstore books has a
      caps-only enumerated row without it (§1 fact 1, Non-Goals).
- [x] Join wrapped titles? — *Resolved by evidence*: yes, up to two continuation rows; 59 of 868 titles wrap and the
      prototype ends with 0 titles cut mid-phrase (10 cut without it).
- [x] Nest enhancements under their controls? — *Resolved by M2*: the hybrid map, not the prefix, flattened them.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — the source is ledger issue `issue:92245af971f3`)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

| Page | Change |
|---|---|
| `wiki/knowledge/pageindex-layout-structure.md` | Enumerated-row rule (shape, separator, continuation rows, level, repeat filter) in "Heading detection"; strictly increasing level map in "Hybrid rule"; new `layout_eval` and `optimizer_eval` runs with report paths and sha256; `CONTROL SUMMARIES` / `issue:38e4627b2284` note; re-import gotcha |

API modules with complete docstrings: `parrot.knowledge.pageindex.layout`, `parrot.knowledge.pageindex.layout_structure`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara (with Claude) | Initial spec from `/sdd-fix issue:92245af971f3` (group `fixgroup:303847bb291a`) |
