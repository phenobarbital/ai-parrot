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

# Feature Specification: PageIndex Layout Structure Fixes

**Feature ID**: FEAT-855
**Date**: 2026-11-09
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Ledger-driven follow-up to FEAT-845 (`pageindex-layout-structure`, closed 2026-11-08). Drains the
> `/sdd-fix` group `fixgroup:b959c598b65b` — one issue, `issue:a3d282c67ed0`, found by the 2026-11-09 host
> layout evaluation (`artifacts/logs/layout_eval/20261109T122050Z.json`). No brainstorm or proposal: the issue
> body is the requirement. Every cause below was reproduced on the host against the corpus PDFs and every fix
> was prototyped (monkeypatched, nothing committed) and measured with the real `layout_eval` before this spec
> was written; code anchors are verified against `dev` at `42fac6d7f1`.

---

## 1. Motivation & Business Requirements

### Problem Statement

The FEAT-845 layout path builds a deterministic tree for every corpus PDF, but in dense documents it misses the
control-level headings. The 2026-11-09 four-pair run measured `recall_all` 0.409 on NIST SP 800-53 r5 (164
reference nodes, 117 layout nodes, page agreement 0.627) and 0.389 on AICPA TSC; the chosen candidates all score
≥ 0.94, so `structure_min_confidence` is not the cause (that run fixed it at 0.6). The issue suggested a new
"small-caps / all-caps" heading class. Reproduction showed four concrete causes instead:

1. **One mis-filed bookmark discards the whole outline** (800-53). The PDF has 358 bookmarks — every control
   family and every control (`AC-2 ACCOUNT MANAGEMENT`, level 3). Entry 223, `PS-1 POLICY AND PROCEDURES`, is
   filed under §3.15 PT but points back to page 249. `_read_bookmarks` (`layout.py:130`) rejects the outline
   as `non-monotonic: page decreases at entry 223`, so `score_bookmarks` scores 0.000 and the 357 good entries
   are lost.
2. **Bold headings at a second body-text size are never headings** (800-53, AICPA). The control headings are
   11 pt bold (body 10 pt); AICPA's section sub-headings are 12 pt bold (body 10 pt). Both sizes carry so much
   prose (11 pt = 11.3 % of 800-53's characters, 12 pt = 34.7 % of AICPA's) that the 10 % share cap
   (`_HEADING_SHARE_CAP`, `layout.py:30`) keeps them out of `heading_sizes`, and the bold-line rule only
   accepts spans at exactly the body size (`layout.py:226`, `layout.py:291`). They come out as
   `**AC-2** **ACCOUNT MANAGEMENT**` paragraphs.
3. **A heading split into two PDF lines is never standalone** (800-53, AICPA). PyMuPDF stores `AC-2` and
   `ACCOUNT MANAGEMENT` as two lines of one block on the same baseline (a code cell and a title cell). The
   standalone test (`layout.py:236`) sees a two-line block whose second line is also bold and rejects both.
4. **The existing rules over-tag once the outline is usable** (found by the prototype, latent today because
   800-53's outline was rejected). With bookmarks accepted, the bookmark rule (`layout.py:294`) tags any span
   that is bold *or larger than body* and shares text with a bookmark title on its page in either direction:
   11 pt prose lines containing `requirements and controls`, a lone `requirement`, bold words `attempts.` and
   `information` inside control titles. Separately, the body-size bold-line rule already makes heading
   candidates of 82 standalone bold lines in 800-53; only 4 of them are neither enumerated list items nor list
   lead-ins (`(a) Have expired;`, `… ; and`, `Release information outside of the system only if:`). FEAT-845's
   wiki page wrongly states the rule is off.

Two reported misses are not structure bugs and stay out of scope: the five unmatched NIST CSF 2.0 titles
(`CSF Core structure`, `CSF Functions`, …) are **figure captions** (`Fig. 1. CSF Core structure`, 10 pt bold) that
the LLM reference tree listed as sections, and seven of AICPA's unmatched titles sit inside markdown table cells
that pymupdf4llm renders as tables, where no header rule applies.

### Goals

- G1 — An outline whose out-of-order entries are a small minority is kept after dropping the fewest entries that
  restore page order; the drop count is visible in the `StructureReport` (`CandidateScore.dropped`).
- G2 — A standalone, all-bold visual row is a heading candidate at the body size **or** at a larger body-text
  size, ranked one heading level per size (larger first), below every size-ranked heading.
- G3 — Lines of one block that share a baseline are judged as one visual row, so a code cell plus title cell
  (`AC-2` + `ACCOUNT MANAGEMENT`) is one heading `AC-2 ACCOUNT MANAGEMENT`.
- G4 — Bold rows that are list items (start with a parenthesized marker, end with `;`/`:`/`; and`/`; or`), start
  with a lowercase letter (glossary terms), or repeat on ≥ 3 pages (table headers, labels) are not headings.
- G5 — The bookmark rule tags a span only when it is bold or larger than every body-text size, and its text is
  the title, a word-boundary prefix of the title, or begins with the whole title.
- G6 — Measured on the host four-pair run: NIST 800-53 `recall_all` ≥ 0.95 with bounded noise, AICPA
  `recall_all` ≥ 0.6, arxiv and CSF 2.0 unchanged (§5 has the exact thresholds).

### Non-Goals (explicitly out of scope)

- Figure captions as headings (the CSF 2.0 misses) — captions are not sections; the reference tree is wrong there.
- Headings inside markdown table cells (seven AICPA misses) — pymupdf4llm table rendering is not changed.
- 800-53 control **enhancements** (`(1) ACCOUNT MANAGEMENT | AUTOMATED SYSTEM ACCOUNT MANAGEMENT`, bold marker +
  9 pt small caps) — mixed-style lines stay body text; the long controls they would split (SA-8, 15 pages) and the
  38-page `CONTROL SUMMARIES` tables stay over the optimizer's target. Filed as a follow-up ledger issue.
- pymupdf4llm's merging of consecutive same-level heading lines (one `Quick link … PT-1 POLICY AND PROCEDURES`
  title in 800-53) — upstream behaviour, cosmetic.
- `structure_min_confidence` (stays 0.6), `score_layout`'s confidence factors, `items_to_tree`, the hybrid rule,
  `segments.py`, the optimizer — unchanged.
- The small-caps / repeated-prefix candidate class suggested in the issue — the misses are 11 pt bold rows and a
  rejected outline, not small caps; G1–G3 recover them without a pattern miner.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:be0c84f4ccb5a937e2eb8f2cc131752be38ee259831480e6b24bdc6712ea0dc9 evaluation_digest=sha256:ee7db769320e540f00234362bb4e4c6f1682169fb455a260b6835593edbe5e50 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

All changes sit in `analyze_layout` and `LayoutHeaders` (`layout.py`) — the layout-aware header detector that
FEAT-845's decision `structure-nodes-anchor-heading-segments` makes the only producer of structure headings — plus
one reporting field in `layout_structure.py`. `split_blocks` keeps typing non-`#` lines as paragraphs, so FEAT-853's
decision `pseudo-headings-in-optimizer` (bold/upper-case lines in already-segmented text are an optimizer fallback)
is untouched: this spec changes which PDF spans get a `#` prefix during extraction, not how text is segmented.

**Outline repair (M1).** `_read_bookmarks` first collects the valid entries (title present, page in range) exactly
as today, then keeps one longest non-decreasing page subsequence (`_keep_page_order`, patience sort — O(n log n),
deterministic). When the removed count is at most `floor(BOOKMARK_MAX_DROPPED_SHARE × entries)` (5 %, rounded
down — so outlines under 20 entries tolerate nothing and today's small-outline behaviour is unchanged), the kept
entries are level-normalized and checked as today (fewer than 2, per-page enumeration). Otherwise the outline is
rejected with today's message `non-monotonic: page decreases at entry N` and today's diagnostic entry list. The
function returns the drop count as a third value; `analyze_layout` stores it in `LayoutProfile.bookmarks_dropped`
and logs it at INFO; `score_bookmarks` copies it into `CandidateScore.dropped`.

**Bold-row headings (M2).** `analyze_layout` computes `bold_sizes` once: the body size plus at most one larger
body-text size — a size above body whose character share exceeds `_HEADING_SHARE_CAP` (so it is not in
`heading_sizes`) — largest first, body last (`MAX_BOLD_LEVELS = 2`). Bold-line detection then works on visual rows
instead of PyMuPDF lines: `_visual_rows` groups consecutive lines of one block whose vertical extents overlap by at
least `ROW_OVERLAP` (half) of the shorter line. A row is a candidate when `_bold_row_size` accepts it: every span
bold, one rounded size, that size in `bold_sizes`, at most `_MAX_BOLD_WORDS` words, not ending in `.`/`,` (today's
rules), not a list item (`_LIST_MARKER_RE` / `_LIST_TAIL_RE`), first alphanumeric character not lowercase.
Standalone keeps today's meaning at row level: the block has one row, or the row is the block's first row and no
other row is all-bold. After the page loop, candidates whose `running_key` text occurs on at least
`BOLD_REPEAT_MIN_PAGES` (3) distinct pages are discarded. Each kept row becomes a `BoldLine` with its normalized
joined text, the union bbox of its lines and its `size`. `LayoutHeaders` gives each bold size its own prefix —
`"#" × (len(heading_sizes) + 1 + rank)` — so with one bold size the prefix is today's `_body_bold_prefix`, and with
two the larger body-text size ranks above the body size. A span gets the prefix of its own size when it lies
inside a recorded bold row of its page. pymupdf4llm already gives a whole visual line the highest prefix found on
any of its spans (`max_header_id`), so tagging both spans of `AC-2` + `ACCOUNT MANAGEMENT` yields one heading line.

**Bookmark-rule guard (M3).** The bookmark rule considers a span when it is bold, or larger than body **and not
a bold size** (a body-text size carries prose). It matches a bookmark title on the span's page with
`_bookmark_prefix_match`: normalized equality, the span a word-boundary prefix of the title
(`title.startswith(span + " ")`), or the span beginning with the whole title (`span.startswith(title + " ")`).
Mid-title fragments (`attempts.`, `information`, `requirement`) no longer match; the title's first span still does,
and that tags the line.

**Measured effect (prototype, host, 2026-11-09 — M4 re-measures with the real code).**

| Pair | Baseline source / recall_all / page agreement / layout nodes | Prototype source / recall_all / page agreement / layout nodes |
|---|---|---|
| arxiv | hybrid / 1.000 / 1.000 / 17 | hybrid / 1.000 / 1.000 / 17 |
| nist_800_53 | layout / 0.409 / 0.627 / 117 | hybrid / 1.000 / 0.805 / 391 (bookmarks 0.997, 357 entries, 1 dropped; 34 inserted) |
| nist_csf_2_0 | hybrid / 0.643 / 1.000 / 22 | hybrid / 0.643 / 1.000 / 22 |
| aicpa_tsc | layout / 0.389 / 1.000 / 11 (recall_top 0.778) | layout / 0.611 / 1.000 / 16 (recall_top 1.000) |

Ablation: the outline repair alone or the bold-row rule alone each lift 800-53 to `recall_all` 1.000; only the
bold-row rule lifts AICPA. Without the M2 guards and M3, 800-53 reached 605 layout nodes (226 prose fragments and
glossary terms at control depth); with them, 14 non-control nodes remain at control depth (front-matter
sub-headings and four `Quick link …` lines). Deterministic optimizer on the prototype tree: leaf tokens p50
1214 → 611, p90 8271 → 1694; max leaf (28,862, `CONTROL SUMMARIES`) and leaves over target (28 → 35, more leaves
overall) do not improve — that needs the control-enhancement split listed under Non-Goals.

### Component Diagram

```
analyze_layout(pdf)                                  (layout.py)
 ├─ _read_bookmarks ──→ _keep_page_order             M1: drop ≤5 % out-of-order entries
 │     └─→ LayoutProfile.bookmarks, .bookmark_rejection, .bookmarks_dropped
 ├─ size statistics ──→ heading_sizes, bold_sizes    M2: body + one larger body-text size
 └─ per block: _visual_rows ─→ _bold_row_size ─→ standalone ─→ repeat filter
       └─→ LayoutProfile.bold_lines[page] = [BoldLine(text, bbox, size)]
LayoutHeaders(profile).get_header_id(span, page)     (pymupdf4llm hdr_info)
 ├─ size in heading_sizes            → "#"…          unchanged
 ├─ bold, size in bold_sizes, inside a bold row → bold-size prefix   M2
 └─ (bold or size > body and not a bold size) and _bookmark_prefix_match → top bold prefix   M3
score_bookmarks(profile, segments)                   (layout_structure.py)
 └─→ CandidateScore(…, dropped=profile.bookmarks_dropped)            M1
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `_read_bookmarks` (`layout.py:104`) | modifies | 3-tuple return; drop step before level normalization |
| `analyze_layout` (`layout.py:147`) | modifies | `bold_sizes`, row-based bold detection, guards, `bookmarks_dropped` |
| `LayoutHeaders` (`layout.py:260`) | modifies | per-size bold prefixes; bookmark rule condition and matcher |
| `BoldLine` / `LayoutProfile` (`layout.py:64`, `:71`) | extends | new optional fields with defaults (old profiles still validate) |
| `CandidateScore` / `score_bookmarks` (`layout_structure.py:28`, `:96`) | extends | `dropped` field, populated from the profile |
| `build_page_index` → `_layout_pages` (`builder.py:1682`) | uses (unchanged) | calls `analyze_layout` and `LayoutHeaders(profile)` by name |
| `layout_eval` (`layout_eval.py:81`) | uses (unchanged) | `CandidateScore.model_validate` accepts the new field |
| pymupdf4llm 0.0.27 `max_header_id` | relies on | a line takes the shortest non-empty prefix among its spans |

### Data Models

```python
class BoldLine(BaseModel):            # layout.py:64
    text: str
    bbox: tuple[float, float, float, float]
    size: Optional[int] = None        # NEW — None (profiles written before FEAT-855) means the body size

class LayoutProfile(BaseModel):       # layout.py:71
    ...                               # existing fields unchanged
    bold_sizes: list[int] = Field(default_factory=list)   # NEW — largest first, body last; [] means [body_size]
    bookmarks_dropped: int = 0                            # NEW — out-of-order outline entries removed

class CandidateScore(BaseModel):      # layout_structure.py:28
    ...                               # existing fields unchanged
    dropped: int = 0                  # NEW — bookmarks candidate only
```

### New Public Interfaces

None. The new names are module-level constants and private helpers of `layout.py`; `LayoutProfile`,
`BoldLine` and `CandidateScore` gain optional fields only.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Outline repair | yes | `_keep_page_order`, 3-tuple `_read_bookmarks`, `BOOKMARK_MAX_DROPPED_SHARE = 0.05`, rejection message unchanged, `bookmarks_dropped`, `CandidateScore.dropped` | — |
| M2: Bold-row headings | yes | constants and helper signatures below; standalone and repeat rules fixed; prefix formula fixed | — |
| M3: Bookmark-rule guard | yes | `_bookmark_prefix_match` semantics and the rule-5 condition fixed | — |
| M4: Evaluation & documentation | no | — | host-only run over the git-ignored corpus; numbers must be copied from the report, never written by a seat |

### Module 1: Outline repair
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py`,
  `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py`
- **Responsibility**: Keep an outline with a few out-of-order entries, report how many were dropped.
- **Depends on**: existing `_read_bookmarks`, `analyze_layout`, `score_bookmarks`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py  (modifies layout.py:31, :80, :104, :245, :256)
  BOOKMARK_MAX_DROPPED_SHARE: float = 0.05
  """Out-of-order entries an outline may lose (share of its valid entries, rounded down) and still be used."""

  def _keep_page_order(pages: Sequence[int]) -> list[int]:
      """Return the indices of one longest non-decreasing subsequence of ``pages``, in order.

      Deterministic patience sort (``bisect.bisect_right`` over the tails, predecessor links); empty input
      returns ``[]``.
      """

  def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str], int]:  # verified: layout.py:104
      """Return usable normalized bookmarks, any rejection reason and the out-of-order entries dropped.

      Valid entries (title, integer level/page, page in range) are collected first. When removing the entries
      outside ``_keep_page_order`` costs at most ``floor(BOOKMARK_MAX_DROPPED_SHARE * len(entries))`` entries, they
      are removed; otherwise nothing is removed and the outline is rejected as
      ``"non-monotonic: page decreases at entry N"`` (N = 1-based index of the first decrease among the
      normalized entries, today's message). Levels are normalized after the removal. The ``fewer than 2 usable
      entries`` and ``per-page enumeration`` checks run on the kept entries, as today. The third value is the
      number removed (0 whenever the outline is rejected as non-monotonic).
      """

  class LayoutProfile(BaseModel):  # verified: layout.py:71
      bookmarks_dropped: int = 0
  ```
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py  (modifies layout_structure.py:35, :101, :130)
  class CandidateScore(BaseModel):  # verified: layout_structure.py:28
      dropped: int = 0  # out-of-order bookmarks removed before scoring (bookmarks candidate only)

  def score_bookmarks(profile: LayoutProfile, segments: Sequence[Segment]) -> tuple[CandidateScore, list[dict]]:  # verified: layout_structure.py:96
      """Unchanged scoring; both returned scores carry ``dropped=profile.bookmarks_dropped``."""
  ```

### Module 2: Bold-row headings
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py`
- **Responsibility**: Detect standalone bold visual rows at the body size and at one larger body-text size, with
  list/lowercase/repeat guards, and give each bold size its own heading level.
- **Depends on**: Module 1 (same file; `LayoutProfile` edited by both).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py  (modifies layout.py:31, :68, :80, :208, :221-243, :268, :291)
  MAX_BOLD_LEVELS: int = 2
  """Bold-row heading levels: the body size plus at most one larger body-text size."""
  ROW_OVERLAP: float = 0.5
  """Lines of one block share a visual row when their vertical extents overlap by this share of the shorter one."""
  BOLD_REPEAT_MIN_PAGES: int = 3
  """A bold row whose running_key text occurs on this many distinct pages is a label or table header."""
  _LIST_MARKER_RE = re.compile(r"^\(\s*[A-Za-z0-9]{1,4}\s*\)")
  _LIST_TAIL_RE = re.compile(r"(?:[;:]|;\s*(?:and|or))$", re.IGNORECASE)

  class BoldLine(BaseModel):  # verified: layout.py:64
      size: Optional[int] = None  # rounded font size of the row; None means the body size

  class LayoutProfile(BaseModel):  # verified: layout.py:71
      bold_sizes: list[int] = Field(default_factory=list)

  def _bold_sizes(size_counts: Mapping[int, int], body_size: Optional[int], heading_sizes: Sequence[int]) -> list[int]:
      """Return the body size preceded by at most ``MAX_BOLD_LEVELS - 1`` larger body-text sizes, largest first.

      A body-text size is above ``body_size``, not in ``heading_sizes`` and holds more than
      ``_HEADING_SHARE_CAP`` of the counted characters. ``[]`` when ``body_size`` is None.
      """

  def _visual_rows(block_lines: Sequence[dict]) -> list[list[dict]]:
      """Group a block's lines, in order, into visual rows.

      A line joins the current row when its vertical extent (bbox y0..y1) overlaps the row's extent by at
      least ``ROW_OVERLAP`` of the shorter of the two heights; otherwise it starts a new row.
      """

  def _bold_row_size(row: Sequence[dict], bold_sizes: Sequence[int]) -> Optional[int]:
      """Return the row's rounded size when the row is a bold heading candidate, else None.

      Candidate: at least one span; every span bold (``_is_bold``); one rounded size, in ``bold_sizes``; the
      joined text has at most ``_MAX_BOLD_WORDS`` words, does not end with ``.`` or ``,``, does not match
      ``_LIST_MARKER_RE`` / ``_LIST_TAIL_RE``, and its first alphanumeric character is not lowercase.
      """

  def analyze_layout(pdf_path: str) -> LayoutProfile:  # verified: layout.py:147
      """As today, plus ``bold_sizes``; bold lines come from standalone candidate rows (block with one row, or
      first row with no other all-bold row), skipping rows that contain a running line, then dropping rows
      whose ``running_key`` occurs on ``BOLD_REPEAT_MIN_PAGES`` or more pages. ``BoldLine.text`` is
      ``normalize_title`` of the space-joined line texts, ``bbox`` the union of the row's line boxes."""

  class LayoutHeaders:  # verified: layout.py:260
      def __init__(self, profile: LayoutProfile) -> None:
          """Adds ``self._bold_prefixes: dict[int, str]`` — ``"#" * (len(heading_sizes) + 1 + rank) + " "`` per
          size of ``profile.bold_sizes or [body_size]``; ``_body_bold_prefix`` keeps today's value."""
      def get_header_id(self, span: dict, page: Any = None) -> str:  # verified: layout.py:277
          """Rule 4 becomes: bold span, size in ``_bold_prefixes``, inside a bold row of its page → that size's prefix."""
  ```

### Module 3: Bookmark-rule guard
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py`
- **Responsibility**: Stop the bookmark rule from tagging body-text prose and mid-title fragments.
- **Depends on**: Module 2 (`LayoutHeaders._bold_prefixes`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py  (modifies layout.py:294, :317)
  def _bookmark_prefix_match(text: str, title: str) -> bool:
      """Whether a span's text is a bookmark title, a word-boundary prefix of it, or begins with all of it.

      Both sides go through ``normalize_title``; empty sides never match.
      True when ``span == title``, ``title.startswith(span + " ")`` or ``span.startswith(title + " ")``.
      """

  class LayoutHeaders:
      def get_header_id(self, span: dict, page: Any = None) -> str:
          """Rule 5 considers a span when it is bold, or larger than body and not in ``_bold_prefixes``."""
      def _matches_bookmark(self, page_no: int, text: str) -> bool:  # verified: layout.py:317
          """``_bookmark_prefix_match`` against the usable bookmark titles of ``page_no``."""
  ```

### Module 4: Evaluation & documentation
- **Path**: `wiki/knowledge/pageindex-layout-structure.md`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py`
- **Responsibility**: Re-run the documented four-pair evaluation on the host with the real code, record the
  numbers, and correct the page (outline repair, bold-row rule with its guards, bookmark rule, CSF captions,
  the wrong "Open question 2" paragraph).
- **Depends on**: Modules 1–3.
- **Interface Skeleton**: none (documentation and a content test). The run reads the corpus from the main
  checkout (`corpus/compliance_soc2_hipaa/`, git-ignored) on the host — never from a coder seat. Every number in
  the page is copied from the report, with the report path and its sha256; if the corpus is unavailable the page
  says "not run" and §5's evaluation criteria are reported unmet, never estimated. AICPA stays metrics-only.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_keep_page_order_longest_subsequence` | M1 | `_keep_page_order([1, 5, 2, 3, 4]) == [0, 2, 3, 4]`; `[]` → `[]`; already sorted keeps all |
| `test_bookmarks_out_of_order_entry_dropped` | M1 | 41-entry outline (page_count 200) with one backward entry → 40 usable, rejection None, dropped 1, stray title gone |
| `test_bookmarks_too_many_out_of_order_rejected` | M1 | 22 entries, 2 backward (> floor(0.05 × 22)) → `non-monotonic` rejection, all entries returned, dropped 0 |
| `test_bookmarks_usable_and_levels_normalized` (updated) | M1 | unpacks the 3-tuple; dropped 0 |
| `test_bookmarks_rejected_non_monotonic` (unchanged) | M1 | 2-entry outline is still rejected |
| `test_score_bookmarks_reports_dropped` | M1 | profile with `bookmarks_dropped=1` → `CandidateScore.dropped == 1` |
| `test_visual_rows_groups_same_baseline_lines` | M2 | two lines on one baseline → one row; a line below → new row |
| `test_secondary_text_size_bold_rows` | M2 | synthetic PDF, 10 pt body + 12 pt prose (> 10 %) + a 12 pt bold line → `bold_sizes == [12, 10]`, bold line with `size == 12` |
| `test_split_row_heading` | M2 | `AC-2` and `ACCOUNT MANAGEMENT` bold on one baseline → bold line `ac-2 account management`; pymupdf4llm emits one heading line with both |
| `test_bold_row_guards` | M2 | `(a) Have expired;`, `… ; and`, a lowercase term, a label on 3 pages → no bold line; `Important Notes` kept |
| `test_header_prefix_levels_with_secondary_size` | M2 | heading_sizes `[16, 14]`, bold_sizes `[12, 10]` → 12 pt bold row `"### "`, 10 pt bold row `"#### "` |
| `test_header_detector_rules` (unchanged) | M2/M3 | today's rules and prefixes hold for a profile without `bold_sizes` |
| `test_bookmark_match_prefix_only` | M3 | `attempts.` / `information` bold spans → `""`; `AC-7` bold → prefix; 11 pt non-bold prose with bold_sizes `[11, 10]` → `""` |
| `test_page_has_frontmatter_and_names` (extended) | M4 | page names `bookmarks_dropped`, `bold_sizes`, `BOLD_REPEAT_MIN_PAGES` |

### Integration Tests
| Test | Description |
|---|---|
| `test_builder_layout.py` / `test_layout_integration.py` (existing) | arxiv fixture through `build_page_index` still yields the same structure source and recall |
| `test_layout_import.py` / `test_layout_eval.py` (existing) | toolkit import and eval report models accept the new fields |

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

Synthetic PDFs written with `pymupdf` (`_write_pdf` / `insert_text`, fonts `helv` and `hebo`) as the existing
`test_layout.py` does; the committed arxiv fixture for integration. Assertions on split rows check the outcome
(bold-line text, markdown heading line), never how PyMuPDF happened to split the lines. The corpus PDFs are
host-only and are used by M4's evaluation run, never by a test.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] The Validation Contract tests pass with `PYTHONPATH=packages/ai-parrot/src`; `ruff check` is clean on every
      changed file.
- [ ] An outline with out-of-order entries ≤ `floor(0.05 × valid entries)` is used and `CandidateScore.dropped`
      reports the count; a larger share, and any outline under 20 entries, is rejected exactly as today.
- [ ] Standalone bold rows at the body size and at one larger body-text size are headings, one level per size;
      a split code+title row is one heading; list items, lowercase-start rows and rows repeated on ≥ 3 pages are not.
- [ ] The bookmark rule ignores non-bold spans at a body-text size and matches only equal, word-boundary-prefix or
      whole-title-prefix spans.
- [ ] Profiles and scores built without the new fields still validate (`bold_sizes=[]`, `size=None`,
      `bookmarks_dropped=0`, `dropped=0`) and `LayoutHeaders` gives today's prefixes for them.
- [ ] Host four-pair run (`python -m parrot.knowledge.pageindex.layout_eval`, the command in the wiki page,
      `--min-confidence 0.6`): nist_800_53 source `bookmarks` or `hybrid`, bookmarks candidate `dropped == 1` and
      confidence ≥ 0.95, `recall_all` ≥ 0.95, `page_agreement` ≥ 0.75, `layout_nodes` ≤ 420; aicpa_tsc
      `recall_all` ≥ 0.6 and `recall_top` = 1.0; arxiv `recall_top` = `recall_all` = `page_agreement` = 1.0 with 17
      layout nodes; nist_csf_2_0 `recall_all` 0.643 with 22 layout nodes. Numbers are copied from the report.
- [ ] `wiki/knowledge/pageindex-layout-structure.md` documents the outline repair, the bold-row rule and its guards,
      the bookmark-rule guard, the new run (report path + sha256), the CSF caption finding, and replaces the wrong
      "Open question 2" paragraph; AICPA appears as metrics only.
- [ ] The control-enhancement follow-up is filed in the ledger with `--discovered-from spec:FEAT-855`.
- [ ] No breaking change to public API: `build_page_index`, `import_pdf`, `StructureReport` keep their shapes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# layout.py today (layout.py:3-19)
from __future__ import annotations
import logging, math, re                                   # verified: layout.py:5-7
from collections import Counter                            # verified: layout.py:8
from typing import Any, Literal, Optional                  # verified: layout.py:10
from pydantic import BaseModel, Field                      # verified: layout.py:12
from parrot.knowledge.pageindex.segments import _titles_match, normalize_title  # verified: layout.py:14
# M1/M2 add: import bisect; from typing import Mapping, Sequence (stdlib)
# layout_structure.py today
from parrot.knowledge.pageindex.layout import LayoutProfile, StructureMode, StructureSource, running_key  # verified: layout_structure.py:17
# tests
from parrot.knowledge.pageindex.layout import (Bookmark, BoldLine, LayoutHeaders, LayoutProfile, RunningLine,
    UnreadablePDFError, _read_bookmarks, analyze_layout)    # verified: test_layout.py:13-22
from parrot.knowledge.pageindex.layout_structure import score_bookmarks  # verified: layout_structure.py:96
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
_HEADING_SHARE_CAP: float = 0.10                     # line 30
_MAX_BOLD_WORDS: int = 12                            # line 31
class Bookmark(BaseModel): level: int; title: str; page: int          # line 48
class BoldLine(BaseModel): text: str; bbox: tuple[float, float, float, float]   # lines 64-68
class LayoutProfile(BaseModel):                      # line 71
    page_count: int; body_size: Optional[int] = None; heading_sizes: list[int]; running: list[RunningLine]
    bold_lines: dict[int, list[BoldLine]]; bookmarks: list[Bookmark]; bookmark_rejection: Optional[str] = None  # line 80
def running_key(text: str) -> str                    # line 83 — casefold, collapse spaces, digits → '#'
def _is_bold(span: dict) -> bool                     # line 88 — flag 16 or "bold" in the font name
def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str]]  # line 104
def analyze_layout(pdf_path: str) -> LayoutProfile   # line 147; line dicts carry page, block, index,
    # block_lines, spans, text, bbox, band, key (lines 170-180); size_counts at 203-206; heading_sizes 208-219;
    # bold-line loop 221-243; _read_bookmarks call 245; LayoutProfile(...) 249-257
class LayoutHeaders:                                 # line 260
    TOLERANCE: float = 0.5                           # line 263
    def __init__(self, profile: LayoutProfile) -> None          # line 265; _size_rank 267, _body_bold_prefix 268
    def get_header_id(self, span: dict, page: Any = None) -> str  # line 277; rule 4 at 291, rule 5 at 294
    def _in_running_line(self, text, bbox, height) -> bool       # line 299
    def _inside_bold_line(self, page_no: int, bbox) -> bool      # line 305
    def _matches_bookmark(self, page_no: int, text: str) -> bool # line 317 — any(_titles_match(text, title))

# packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py
class CandidateScore(BaseModel): source; confidence: float; entries: int; anchored: int; rejected: Optional[str] = None  # 28-35
def score_bookmarks(profile, segments) -> tuple[CandidateScore, list[dict]]   # line 96; returns at 101 and 130

# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
def normalize_title(title: str) -> str               # line 305 — casefold, strip leading numbering and trailing punct
def _titles_match(a: str, b: str) -> bool            # line 312 — equality or containment (shorter >= 3 chars)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `bookmarks_dropped` | `_read_bookmarks` 3rd value | assignment in `analyze_layout` | `layout.py:245` |
| `CandidateScore.dropped` | `LayoutProfile.bookmarks_dropped` | `score_bookmarks` kwargs | `layout_structure.py:101`, `:130` |
| `bold_sizes`, `BoldLine.size` | `LayoutHeaders._bold_prefixes` | `__init__` | `layout.py:265-275` |
| bold rows | pymupdf4llm `max_header_id` | `hdr_info.get_header_id` per span | `.venv/.../pymupdf4llm/helpers/pymupdf_rag.py:425` |

### Does NOT Exist (Anti-Hallucination)
- ~~`LayoutProfile.bold_sizes`~~, ~~`LayoutProfile.bookmarks_dropped`~~, ~~`BoldLine.size`~~, ~~`CandidateScore.dropped`~~ —
  added by this spec, absent at `42fac6d7f1`.
- ~~`_keep_page_order`~~, ~~`_visual_rows`~~, ~~`_bold_sizes`~~, ~~`_bold_row_size`~~, ~~`_bookmark_prefix_match`~~ — new.
- ~~a small-caps / font-variant flag in `_is_bold` or the profile~~ — no small-caps detection exists or is added.
- ~~`StructureReport.dropped`~~ — the count lives on the bookmarks `CandidateScore` inside `report.candidates`.
- ~~`layout_eval` output of the drop count in its markdown~~ — the JSON report carries it via `CandidateScore`; the
  markdown table is unchanged.

### Edit Sites (Blueprint Anchors)

Verified against: `42fac6d7f1`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `_MAX_BOLD_WORDS: int = 12` | `layout.py:31` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    bbox: tuple[float, float, float, float]` | `layout.py:68` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    bookmark_rejection: Optional[str] = None` | `layout.py:80` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `def _read_bookmarks(raw_toc: list[list], page_count: int) -> tuple[list[Bookmark], Optional[str]]:` | `layout.py:104` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    heading_sizes = (` | `layout.py:208` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    bold_lines: dict[int, list[BoldLine]] = {}` | `layout.py:221` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    bookmarks, rejection = _read_bookmarks(raw_toc, page_count)` | `layout.py:245` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `        bookmark_rejection=rejection,` | `layout.py:256` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `        self._body_bold_prefix = "#" * (len(profile.heading_sizes) + 1) + " "` | `layout.py:268` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `        if page_no is not None and bbox is not None and bold and body is not None and size == body:` | `layout.py:291` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `        if page_no is not None and (bold or (body is not None and size > body)):` | `layout.py:294` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py` | MODIFY | `    def _matches_bookmark(self, page_no: int, text: str) -> bool:` | `layout.py:317` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | MODIFY | `    rejected: Optional[str] = None` | `layout_structure.py:35` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | MODIFY | `        return CandidateScore(source="bookmarks", confidence=0.0, entries=len(usable), anchored=0, rejected=reason), []` | `layout_structure.py:101` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py` | MODIFY | `    return CandidateScore(source="bookmarks", confidence=confidence, entries=len(usable), anchored=anchored), items` | `layout_structure.py:130` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | `    bookmarks, rejection = _read_bookmarks([[1, "A", 1], [3, "B", 2], [1, "C", 9], [1, "  ", 2], [2, "D", 3]], 4)` | `test_layout.py:119` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout.py` | MODIFY | `def test_running_lines_never_headings(tmp_path: Path) -> None:` | `test_layout.py:232` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py` | MODIFY | `def test_score_bookmarks_found_and_anchored():` | `test_layout_structure.py:49` | 1 |
| `packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py` | MODIFY | `        "layout_eval",` | `test_layout_docs.py:24` | 1 |
| `wiki/knowledge/pageindex-layout-structure.md` | MODIFY | `## Evaluation` | `pageindex-layout-structure.md:103` | 1 |

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- Pure helpers over line/span dicts (no I/O) so they unit-test without PDFs; `analyze_layout` stays the only
  function that opens a document.
- Pydantic v2 models with defaulted new fields; `logger = logging.getLogger(__name__)` already exists in `layout.py`.
- Keep today's messages (`non-monotonic: page decreases at entry N`, `fewer than 2 usable entries`,
  `per-page enumeration`) — tests and the wiki quote them.
- Google-style docstrings, strict type hints, 120 columns, `ruff check` clean.

### Known Risks / Gotchas
- **Re-imports create new revisions.** Any PDF with a body-text-size bold row, a split row, a repaired outline or
  a formerly over-tagged span renders different markdown, so its revision id changes on re-import (as FEAT-845
  documented for its own change).
- **Body-size list items disappear from today's trees.** 800-53's `(a) …;` headings were noise, but a document
  whose real bold headings end with `:` or start lowercase loses them; the wiki states the guards.
- **Repeat filter.** A real bold heading printed identically on 3+ pages (e.g. `Summary` per chapter at body size)
  is dropped; size-ranked headings are unaffected.
- **Prefix rule.** A bookmarked title whose first span is neither bold nor larger than every body-text size is no
  longer tagged through a later span; bold rows and size-ranked headings still cover the corpus cases.
- **Corpus.** `corpus/compliance_soc2_hipaa/` is git-ignored and present only in the main checkout on the host;
  M4 must read it from there (memory precedent: a seat once invented a metrics table).

### Ledger Linkage
Every task carries `**Discovered-from**: issue:a3d282c67ed0`; `/sdd-done` (or `/sdd-fix` step 6) closes the issue
with `--resolved-by task:<M4 task>` once the evaluation criteria are met. The control-enhancement follow-up is a new
ledger issue opened by M4 (`--discovered-from spec:FEAT-855`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pymupdf` | 1.27.1 (installed) | span geometry, outline |
| `pymupdf4llm` | 0.0.27 (installed) | `hdr_info` / `max_header_id` behaviour relied on |

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-855-pageindex-layout-structure-fixes`).
- **Module dependency graph**: M3 → M2 (M3's rule-5 condition reads `LayoutHeaders._bold_prefixes`, added by M2);
  M4 → M1, M2, M3 (it measures their combined effect). M1 and M2 have no logical edge.
- **Shared files**: `layout.py` is modified by M1, M2 and M3, and `test_layout.py` by M1, M2 and M3 — their tasks are
  serialized (M1 → M2 → M3).
- **Exclusive resources**: M4's evaluation reads the git-ignored corpus in the main checkout on the host and writes
  `artifacts/logs/layout_eval/` — `parallel: false`, host only, never a coder seat.
- **Cross-feature dependencies**: none. FEAT-853 (`pageindex-optimizer-fixes`, open) only reads `heading_title` and
  `MAX_HEADING_WORDS` from `layout_structure.py`, which this spec does not change.

---

## Decisions

```yaml
schema_version: 1
document_id: pageindex-layout-structure-fixes
entries:
  - id: outline-out-of-order-entries-dropped
    statement: A PDF outline is used after dropping the fewest entries that restore page order when that costs at most floor(BOOKMARK_MAX_DROPPED_SHARE x valid entries) entries; otherwise it is rejected as non-monotonic, and the drop count is reported on the bookmarks CandidateScore.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_read_bookmarks, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#score_bookmarks]
    contradicts: []
    supersedes: []
    rationale: One mis-filed bookmark (1 of 358) made NIST 800-53 lose its whole outline and fall back to a layout tree with recall_all 0.409.
    rejected_alternatives: ["drop only the first backward entry greedily (one early forward-pointing entry would then discard the rest)", "accept any order and sort entries by page (silently reorders a scrambled outline)"]
  - id: bold-rows-at-body-text-sizes
    statement: The layout header detector treats a standalone all-bold visual row as a heading at the body size or at one larger body-text size, one level per size below every size-ranked heading, unless the row is a list item, starts with a lowercase letter, or its text recurs on BOLD_REPEAT_MIN_PAGES or more pages.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout, file:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py]
    contradicts: []
    supersedes: []
    rationale: Control headings (800-53, 11 pt bold) and section sub-headings (AICPA, 12 pt bold) sit at a size that carries prose, so the size ranking excludes them, and the body-size-only bold rule turned list items into headings.
    rejected_alternatives: ["raise _HEADING_SHARE_CAP (would rank prose sizes as heading sizes and make every 11 pt line a heading)", "a small-caps / repeated-prefix pattern class (the misses are plain bold rows; a pattern miner adds a heuristic without recall gain)"]
  - id: bookmark-rule-prefix-match
    statement: The layout header detector tags a span from a bookmark title only when the span is bold or larger than every body-text size, and its normalized text equals the title, is a word-boundary prefix of it, or begins with the whole title.
    relation: constrains
    about: [knowledge-pageindex]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py]
    contradicts: []
    supersedes: []
    rationale: With a usable outline, containment in either direction tagged 11 pt prose lines and mid-title words (attempts., information) as headings in NIST 800-53.
    rejected_alternatives: ["keep containment and require bold only (still tags bold mid-title words)"]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:be0c84f4ccb5a937e2eb8f2cc131752be38ee259831480e6b24bdc6712ea0dc9 evaluation_digest=sha256:ee7db769320e540f00234362bb4e4c6f1682169fb455a260b6835593edbe5e50 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-layout-structure-fixes#outline-out-of-order-entries-dropped@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_read_bookmarks; message: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_read_bookmarks impacts 10 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_body_size_and_heading_sizes, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_heading_occurrence_collision, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_standalone_lines, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_non_monotonic, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_per_page_enumeration, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_usable_and_levels_normalized, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_excluded, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_never_headings, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_unreadable_pdf
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-layout-structure-fixes#bold-rows-at-body-text-sizes@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout; message: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout impacts 8 dependent(s): sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_body_size_and_heading_sizes, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_heading_occurrence_collision, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_standalone_lines, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_non_monotonic, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_per_page_enumeration, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_excluded, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_never_headings, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_unreadable_pdf
- `blast-radius` [advisory]; waived_by: not recorded; participants: adr:spec:pageindex-layout-structure-fixes#outline-out-of-order-entries-dropped@1; scope: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#score_bookmarks; message: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#score_bookmarks impacts 7 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_choose_structure, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#build_structure, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_choice_order_and_modes, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_hybrid_confidence_and_empty_mapping, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_hybrid_insertion, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_hybrid_rejects_noisy_layout, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_score_bookmarks_found_and_anchored; inferred: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_candidate_scores

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: layout-structure, ledger-fix, pdf
- Targets resolved: 4/4
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
    "targets_resolved": 4,
    "targets_total": 4,
    "unmapped_tags": [
      "layout-structure",
      "ledger-fix",
      "pdf"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:ee7db769320e540f00234362bb4e4c6f1682169fb455a260b6835593edbe5e50",
  "exit_code": 0,
  "findings": [
    {
      "blocking": false,
      "fingerprint": "sha256:504c25d69ea92be7f792866ecefba029d764bd887f0025e196dcceee4af23f0b",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_read_bookmarks impacts 10 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_body_size_and_heading_sizes, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_heading_occurrence_collision, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_standalone_lines, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_non_monotonic, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_per_page_enumeration, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_usable_and_levels_normalized, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_excluded, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_never_headings, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_unreadable_pdf",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-layout-structure-fixes#outline-out-of-order-entries-dropped",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#_read_bookmarks"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:6940ff9f346b056de0cdf8bd11150bc54195f33390db933e5e68856bfddb4ed3",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout impacts 8 dependent(s): sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_body_size_and_heading_sizes, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_heading_occurrence_collision, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bold_standalone_lines, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_non_monotonic, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_bookmarks_rejected_per_page_enumeration, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_excluded, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_running_lines_never_headings, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout.py#test_unreadable_pdf",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-layout-structure-fixes#bold-rows-at-body-text-sizes",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py#analyze_layout"
      ],
      "waived_by": null
    },
    {
      "blocking": false,
      "fingerprint": "sha256:f8ac9630c151fddf23e561d15323eab5b91ddb25e5072593f2b8b9adf3b15736",
      "kind": "blast-radius",
      "message": "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#score_bookmarks impacts 7 dependent(s): sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_choose_structure, sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#build_structure, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_choice_order_and_modes, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_hybrid_confidence_and_empty_mapping, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_hybrid_insertion, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_hybrid_rejects_noisy_layout, sym:packages/ai-parrot/tests/knowledge/pageindex/test_layout_structure.py#test_score_bookmarks_found_and_anchored; inferred: sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_candidate_scores",
      "participants": [
        {
          "decision_id": "adr:spec:pageindex-layout-structure-fixes#outline-out-of-order-entries-dropped",
          "revision": 1
        }
      ],
      "rule_version": 1,
      "scope": [
        "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#score_bookmarks"
      ],
      "waived_by": null
    }
  ],
  "input_digest": "sha256:be0c84f4ccb5a937e2eb8f2cc131752be38ee259831480e6b24bdc6712ea0dc9",
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
    "structural_revision": "sha256:fb1239fa18575be8f1f85078982e7c0d18dc8b2288749543ff9da17fca77d83c",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Does `structure_min_confidence` need to move? — *Resolved (ledger issue, 2026-11-09 run)*: no; it stays 0.6
      (chosen candidates score ≥ 0.94; the gap is candidate classes).
- [x] Should body-size standalone bold lines count as headings? (FEAT-845 §8, owner M10, never settled — its wiki
      page says "no" while the code says "yes") — *Resolved by evidence in this spec*: yes, as visual rows with the
      G4 guards; in 800-53 the guards cut 82 body-size bold rows to 4, and the arxiv and CSF trees are unchanged.
- [x] Is a small-caps class needed (issue suggestion)? — *Resolved by reproduction*: no; see §1 Non-Goals.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document — the source is ledger issue `issue:a3d282c67ed0`)
> · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

| Page | Change |
|---|---|
| `wiki/knowledge/pageindex-layout-structure.md` | Outline repair and `CandidateScore.dropped`; bold-row rule (`bold_sizes`, visual rows, guards, `BOLD_REPEAT_MIN_PAGES`); bookmark-rule guard; new four-pair run with report path and sha256; CSF misses are figure captions; replace the "Open question 2" paragraph; re-import gotcha |

API modules with complete docstrings: `parrot.knowledge.pageindex.layout`, `parrot.knowledge.pageindex.layout_structure`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-09 | Jesus Lara (with Claude) | Initial spec from `/sdd-fix issue:a3d282c67ed0` (group `fixgroup:b959c598b65b`) |
