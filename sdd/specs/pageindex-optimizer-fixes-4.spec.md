---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — core only: parrot.knowledge.pageindex (optimizer)
tags: [pageindex, tree-optimizer, ledger-fix]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-tree-optimizer.md, wiki/knowledge/pageindex-layout-structure.md]
  api_modules: [parrot.knowledge.pageindex.optimizer]
---

# Feature Specification: PageIndex Optimizer Fixes 4 — Page Splits for Long Table Leaves

**Feature ID**: FEAT-861
**Date**: 2026-11-09
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Ledger-driven follow-up to FEAT-859 (`pageindex-optimizer-fixes-3`). Drains the `/sdd-fix` group
> `fixgroup:f3227810f34d`: `issue:f31b01d845b0` (minor, `feature_gap`), found while re-measuring NIST SP 800-53 after
> FEAT-859. FEAT-859 is merged (PR #2061) and its index is closed, so this is a new feature. No brainstorm or
> proposal: the issue body is the requirement.

---

## 1. Motivation & Business Requirements

### Problem Statement

`expand_at_headings` (`optimizer.py:752`) splits a leaf over `target_leaf_tokens` only at heading segments, and when
there are none, at pseudo-heading paragraphs (`pseudo_heading_segments`, `optimizer.py:515`). A leaf that is one long
table has neither: its rows are `table` segments, and since FEAT-857/FEAT-859 the only repeated one-line paragraph
inside such a leaf, the page footer, is correctly ignored. The leaf stays whole, however many pages it covers.

Observed on `dev` @ `f245375ced` (FEAT-859 merged), deterministic `plan_deterministic` over cached revisions, target
1500 / min 200:

- **NIST SP 800-53 r5**: 7 of its 8 leaves over the target are `CONTROL SUMMARIES` tables — `TABLE C-17` 3,864 tokens
  (pages 481–485), `C-18` 3,789, `C-1` 3,213, `C-19` 2,828, `C-7` 1,801, `C-3` 1,654, `C-5` 1,545. The eighth is the
  enhancement `(17) INFORMATION FLOW ENFORCEMENT | DOMAIN AUTHENTICATION` (1,704, not a table).
- **AICPA TSC 2017**: its largest leaf is a table — 27,651 tokens over pages 14–67, the largest leaf in the corpus.

### Evidence gathered for the rule (probe over 8 PDFs, same `dev` code)

Every leaf still over the target after the deterministic pass that holds any `table` segment:

| Document | Leaf | Tokens | Table share | Table segments / pages | Table segment tokens | Last page |
|---|---|---|---|---|---|---|
| 800-53 | `TABLE C-17` | 3,864 | 0.94 | 4 / 4 | 539–1,227 | 43-token stub |
| 800-53 | `C-18`, `C-1`, `C-19`, `C-7`, `C-3`, `C-5` | 1,545–3,789 | 0.93–0.94 | 2–4 / same | 464–1,088 | 43-token stub |
| AICPA | largest leaf (title not reproduced: `redistributable: false`) | 27,651 | 0.97 | 54 / 54 | 98–650 | a table page |
| arxiv fixture | `Baselines for Object Detection` | 2,361 | 0.79 | 2 / **1** | 785–1,083 | — |
| CSF 2.0 | `Table 1. CSF 2.0 Core …` | 4,200 | 0.06 | 1 / 1 | 251 | — |

No `table` segment in any of the 8 PDFs exceeds 1,500 tokens. Each 800-53 table page is one `table` segment framed by
three paragraphs: the running header (40 tokens), a rule line (3) and the footer (7). Each table leaf ends with a
43-token stub — the next page's running header and rule, printed just before the next table's title. The Kant,
Confucio and Marco Aurelio books and HIPAA have no table-dominated leaf.

### Goals
- A leaf over the target with no heading and no pseudo-heading split point, whose owned tokens are at least
  `TABLE_SPLIT_MIN_SHARE` (0.5) `table` tokens and whose `table` segments sit on at least two pages, is split at page
  boundaries.
- The split points are the leaf's first `table` segment and the first owned segment of later pages, packed so that each
  piece stays within `target_leaf_tokens` where whole pages allow it; the existing `_coalesce_split_points` keeps every
  piece at or above `min_leaf_tokens`.
- Each piece is titled after the leaf plus its page range — `TABLE C-17: … (page 481)`, `(pages 484-485)` — so titles
  stay meaningful and no two pieces of one leaf share a title.
- On 800-53 every `TABLE C-*` leaf ends at or under the target; on AICPA the 27,651-token leaf is split; every other
  document in the probe keeps its splits.

### Non-Goals (explicitly out of scope)
- Splitting inside one `table` segment (row-level splits in `segments.py`): no segment in the corpus needs it.
- Page splits for leaves that are not table-dominated (the Kant, Confucio and Marco Aurelio prose leaves, CSF 2.0's
  `Table 1 …` leaf at 0.06 table share, AICPA's three prose leaves over the target).
- Single-page tables (the arxiv leaf: both tables are on page 9).
- The 800-53 enhancement over the target (`(17) … DOMAIN AUTHENTICATION`, 1,704) and AICPA's non-table leaves.
- The LLM heading pass (`optimizer_llm.py`), `layout.py`, `layout_structure.py`, `segments.py`, `OptimizerSettings`,
  `ExpandAction` (the table split records `source="layout"`), `OPTIMIZER_VERSION`.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:5c0a6c1be725cda7aeb1a7c126cb14931bf81885fc3175d81131695f515b0c49 evaluation_digest=sha256:b45f07834ca9f06ea1ce1c8aeb5a9a84e98b0ca2cb16bf09d5467ccb6b0b13c7 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One edit in `optimizer.py`, plus documentation.

**A. `table_page_splits(node, revision, settings) -> dict[int, str]`.** New public helper. It returns `{}` unless the
leaf's owned `table` tokens are at least `TABLE_SPLIT_MIN_SHARE` of its owned tokens and its `table` segments sit on at
least two distinct pages. Otherwise it walks the owned segments from the first `table` segment on and groups them into
page blocks: a new block starts at the first segment whose page differs from the previous paged segment's page; an
unpaged segment joins the current block. Blocks are packed **from the last block backward**: a boundary is placed before
a block when adding it to the running piece would exceed `target_leaf_tokens`. The points are the first `table` segment
plus those boundaries, passed through `_coalesce_split_points`; fewer than two kept points return `{}`. Each kept point
maps to the piece title: the leaf title plus `(page N)` or `(pages N-M)` from the piece's paged segments, or
`(part K)` if a piece had no paged segment.

**B. `split_at(..., titles=None)`.** New keyword-only `titles: Optional[dict[int, str]] = None`. A piece whose start
sequence is in `titles` takes that title; every other piece keeps `heading_title(revision.segments[seq].text)`. The
LLM pass and the heading/pseudo-heading paths pass nothing and are unchanged.

**C. `expand_at_headings`.** When the pseudo-heading fallback yields no split point, it calls `table_page_splits`; a
non-empty result supplies both the split points and `titles=` for `split_at`. Headings still win over pseudo-headings,
and pseudo-headings over page splits.

Why backward: packing forward leaves the 43-token stub as a last piece under `min_leaf_tokens`; `_coalesce_split_points`
then merges it backward, which pushed `TABLE C-1`'s last piece to 1,509 tokens and left `TABLE C-5` with a single
point, so it was not split at all. Packing backward joins the stub to the piece before it.

Why the parent keeps the text before the first table: the first point is the first `table` segment, not the leaf's
first segment, so the leaf's title paragraph and any lead-in prose (AICPA: the heading and a 104-token paragraph that
introduces the table) stay with the parent as residual, as they do for a heading split.

### Measured effect (prototype, same probe)

| Document | Leaves over target after | Max leaf | Nodes below root | New pieces | Piece tokens |
|---|---|---|---|---|---|
| 800-53 | 8 → 1 | 3,864 → 1,704 | 718 → 739 | 21 (7 tables) | 557–1,277 |
| AICPA | 4 → 3 | 27,651 → 4,206 | 15 → 38 | 23 (1 leaf) | 667–1,470 |
| arxiv, CSF 2.0, HIPAA, Kant, Confucio, Marco Aurelio | unchanged | unchanged | unchanged | 0 | — |

`validate_candidate` reports no error on either changed tree. Run time is unchanged: AICPA showed 0.01 → 0.25 s when it
ran first, which is the tokenizer warming up on the first split — with 800-53 run first, AICPA takes 0.01 s on both.
The forward-packing variant left 3 leaves over the target on 800-53 (`TABLE C-5` 1,545 unsplit, `C-1 (pages 458-460)`
1,509).

### Integration Points
| Existing component | Interaction |
|---|---|
| `expand_at_headings` / `plan_deterministic` | page splits as the third fallback |
| `split_at` | optional per-piece titles |
| `_coalesce_split_points`, `_owned_in_span`, `_piece_pages` | reused, not modified |
| `optimizer_llm.run_llm_passes` → `split_at(..., source="llm")` | unchanged (no `titles`) |

## 3. Module Breakdown

### Module 1: Page splits for table-dominated leaves
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py`
- **Responsibility**: A, B and C above.
- **Interface Skeleton**:
```python
RUNNING_LINE_MIN_DENSITY = 0.8  # verified: optimizer.py:31 (unchanged)
TABLE_SPLIT_MIN_SHARE = 0.5
"""Share of a leaf's owned tokens that must be ``table`` segments before it may be split at page boundaries."""


def table_page_splits(node: dict, revision: DocumentRevision, settings: OptimizerSettings) -> dict[int, str]:
    """Return page-boundary split points for a long table leaf, mapped to their piece titles.

    Applies only when ``table`` segments hold at least ``TABLE_SPLIT_MIN_SHARE`` of the leaf's owned tokens and sit on
    at least two pages. Points are the first ``table`` segment and the first owned segment of later pages, packed from
    the last page backward up to ``settings.target_leaf_tokens`` and then passed through ``_coalesce_split_points``.
    Titles are the leaf title plus ``(page N)`` / ``(pages N-M)``. Returns ``{}`` when fewer than two points remain.
    """


def split_at(  # verified: optimizer.py:692
    node: dict,
    revision: DocumentRevision,
    seqs: list[int],
    *,
    source: str,
    settings: OptimizerSettings,
    report: OptimizeReport,
    titles: Optional[dict[int, str]] = None,
) -> list[dict]:
    """(existing docstring) + a piece whose start sequence is in ``titles`` takes that title."""


def expand_at_headings(  # verified: optimizer.py:752 (signature unchanged)
    node, revision, settings, report, *, depth, running_keys=None
) -> None:
    """(existing docstring) + a leaf with no heading and no pseudo-heading split point falls back to
    ``table_page_splits``."""
```
- **Tests**: `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (new cases, §4).

### Module 2: Host evaluation and documentation
- **Paths**: `wiki/knowledge/pageindex-tree-optimizer.md`, `wiki/knowledge/pageindex-layout-structure.md`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py`
- **Responsibility**: re-run the deterministic `optimizer_eval` on 800-53 + AICPA on the feature branch (host only, the
  corpus PDFs are git-ignored) plus a per-leaf dump of 800-53; document the page-split fallback in the optimizer page;
  add a report row, two result rows and an "After FEAT-861" paragraph to the layout page, copying every number from the
  report (and its sha256) or the dump; extend the docs test's names assertion.
- Depends on Module 1 (measures and documents its behaviour).

### Delegation-eligible modules
| Module | Eligible | Decided patterns / contracts |
|---|---|---|
| 1 | no | small; implemented in the `/sdd-fix` session |
| 2 | no | host-only evaluation (git-ignored corpus); numbers must come from the report |

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_table_page_splits_packs_pages_backward` | 1 | a 4-page table leaf with a tiny last page: points are the first table segment and page starts, the tiny page joins the piece before it, titles carry page ranges |
| `test_table_page_splits_requires_table_share_and_two_pages` | 1 | a prose-dominated leaf, a table leaf on one page, and an unpaged table leaf all return `{}` |
| `test_split_at_uses_given_titles` | 1 | `titles=` names the pieces it covers; without it titles come from the segment text as before |
| `test_expand_splits_long_table_leaf_at_pages` | 1 | `plan_deterministic` over a paged table leaf yields page-range pieces, each within the target, with the title paragraph left on the parent; fails on `dev` |
| `test_expand_prefers_pseudo_headings_over_table_pages` | 1 | a table leaf that also has a usable pseudo-heading is split at the pseudo-heading, not at pages |

### Integration Tests
| Test | Description |
|---|---|
| `test_optimizer_integration.py`, `test_layout_integration.py` | unchanged behaviour of optimize-on-import over the fixtures |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_docs.py
markers: none

## 5. Acceptance Criteria
- [ ] `table_page_splits` returns `{}` unless `table` tokens are ≥ `TABLE_SPLIT_MIN_SHARE` of the leaf's owned tokens
      and its `table` segments sit on ≥ 2 pages; an unpaged leaf returns `{}`.
- [ ] Its points are the first `table` segment plus page starts, packed from the last page backward within
      `target_leaf_tokens`, then coalesced to `min_leaf_tokens`; fewer than two points return `{}`.
- [ ] Piece titles are the leaf title plus `(page N)` / `(pages N-M)`; no two pieces of one leaf share a title.
- [ ] `split_at` without `titles` behaves exactly as before (the LLM pass and heading splits are unchanged).
- [ ] `expand_at_headings` uses page splits only when headings and pseudo-headings give no split point.
- [ ] Host `optimizer_eval` on 800-53 shows no `TABLE C-*` leaf over the target; AICPA's largest leaf is split.
- [ ] `ruff check` is clean on the changed files; the Validation Contract passes.
- [ ] Both wiki pages describe the rule and the measured result; every number has its report and sha256 or the dump.

## 6. Codebase Contract

Verified against `origin/dev` @ `6dad873974` (optimizer identical to `f245375ced`).

### Verified Imports
```python
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: optimizer.py:15
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment  # verified: optimizer.py:16-24
from typing import Any, Literal, Optional  # verified: optimizer.py:9
from parrot.knowledge.pageindex.segments import segment_pages  # verified: segments.py:231 (tests)
```

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
RUNNING_LINE_MIN_DENSITY = 0.8  # :31
def owned_tokens(node: dict, revision: DocumentRevision) -> int  # :164
def pseudo_heading_segments(node, revision, *, running_keys=None) -> list[Segment]  # :515
def _coalesce_split_points(node, revision, seqs: list[int], settings) -> list[int]  # :565
def _owned_in_span(owned: list[list[int]], start: int, end: int) -> list[list[int]]  # :621
def _piece_pages(piece: dict, revision: DocumentRevision) -> Optional[tuple[int, int]]  # :681
def split_at(node, revision, seqs, *, source: str, settings, report) -> list[dict]  # :692; title at :725
def expand_at_headings(node, revision, settings, report, *, depth, running_keys=None) -> None  # :752
def plan_deterministic(tree, revisions, settings, *, tree_name, node_id=None) -> OptimizePlan  # :920
class ExpandAction(BaseModel): ...; source: Literal["layout", "llm"]  # :92-98
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq: int; kind: SegmentKind; page: Optional[int] = None; text: str; tokens: int  # :33-43
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]  # :231; a line starting with "|" is a table block (:195-201)
# packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py
_PROSE = "Una frase larga de prosa …" * 30  # :400
def _paged_tree(pages: list[tuple[int, str]], title: str = "Libro") -> tuple[dict, dict]  # :499
```

### Does NOT Exist
- No page-based split anywhere in `optimizer.py`; `split_at` titles every piece from its first segment's text.
- No `titles` parameter on `split_at`; no `TABLE_*` constant in `optimizer.py`.
- No other caller of `split_at` in `packages/` besides `optimizer.py:794` and `optimizer_llm.py:565`.
- `ExpandAction.source` has no `"table"` value (and this feature adds none).

### Edit Sites (Blueprint Anchors)
| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | `RUNNING_LINE_MIN_DENSITY = 0.8` | 31 | 1 | MODIFY (add constant after) |
| same | `def _piece_pages(piece: dict, revision: DocumentRevision) -> Optional[tuple[int, int]]:` | 681 | 1 | MODIFY (new helper after this function) |
| same | `def split_at(` | 692 | 1 | MODIFY (signature, docstring) |
| same | `                "title": heading_title(revision.segments[seq].text),` | 725 | 1 | MODIFY |
| same | `    (``_coalesce_split_points``) before ``split_at``; the expand action` | 765 | 1 | MODIFY (docstring) |
| same | `        seqs = _coalesce_split_points(node, revision, [segment.seq for segment in candidates], settings)` | 791 | 1 | MODIFY (fallback after) |
| same | `    pieces = split_at(node, revision, seqs, source="layout", settings=settings, report=report)` | 794 | 1 | MODIFY |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | end of file (after `test_expand_computes_running_keys_once`) | 694 | 1 | MODIFY |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | `        "RUNNING_LINE_MIN_DENSITY",` | 50 | 1 | MODIFY |
| `wiki/knowledge/pageindex-tree-optimizer.md` | ``   moves the split leaf's key items onto the piece that now owns their anchor.`` | 96 | 1 | MODIFY (paragraph after) |
| `wiki/knowledge/pageindex-layout-structure.md` | ``\| FEAT-859 branch (`60237d38c6`) \|`` | 265 | 1 | MODIFY (add a row after) |
| same | `\| nist_800_53_r5 \| FEAT-859 \| 1259 → 719 \| 341 / 755 / 3864 \| 1 / 8 \|` | 272 | 1 | MODIFY (add a row after) |
| same | `\| aicpa_tsc_2017 \| all four \| 17 → 16 \| 1273 / 11239 / 27651 \| 4 / 4 \|` | 273 | 1 | MODIFY (relabel, add a row) |
| same | `arxiv fixture, CSF 2.0, HIPAA, AICPA and three book PDFs, the same code leaves every split unchanged.` | 298 | 1 | MODIFY (paragraph after) |

## 7. Implementation Notes & Constraints
- Keep `_coalesce_split_points` unchanged; the backward packing runs before it.
- Compute page blocks in one pass over the owned segments; no caching.
- `split_at` must keep its current behaviour for callers that omit `titles` (heading splits, pseudo-heading splits,
  the LLM pass).
- Host evaluation reads the PDFs from the main checkout (`corpus/compliance_soc2_hipaa/raw/`); runs with
  `PYTHONPATH=<worktree>/packages/ai-parrot/src`, `--no-llm`/deterministic only; no coder seat.
- AICPA is `redistributable: false`: metrics only, never its titles, in committed files.
- Ledger linkage: `issue:f31b01d845b0`.

### Known Risks / Gotchas
- A piece holding a single table page larger than the target stays over it (no corpus segment does); row-level splits
  are a non-goal.
- Page numbers in titles are PDF page indexes (`Segment.page`), the same numbers as `start_index` / `end_index`, not
  the page labels printed in the document (800-53 prints `APPENDIX C PAGE 454` on PDF page 481).
- A last piece still smaller than `min_leaf_tokens` after backward packing is merged by `_coalesce_split_points`, as for
  every other split.

## Worktree Strategy
One feature worktree. Module 2 → Module 1 (it measures and documents Module 1's behaviour). No file is shared between
the modules. Exclusive resource: Module 2's host evaluation (reads the git-ignored corpus from the main checkout).
No cross-feature dependency.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:5c0a6c1be725cda7aeb1a7c126cb14931bf81885fc3175d81131695f515b0c49 evaluation_digest=sha256:b45f07834ca9f06ea1ce1c8aeb5a9a84e98b0ca2cb16bf09d5467ccb6b0b13c7 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/b2358426-4665-42f0-a439-ce41a0bb07aa/scratchpad/dev-clone/sdd/specs/pageindex-optimizer-fixes-4.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: ledger-fix, tree-optimizer
- Targets resolved: 0/0
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
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "ledger-fix",
      "tree-optimizer"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/b2358426-4665-42f0-a439-ce41a0bb07aa/scratchpad/dev-clone/sdd/specs/pageindex-optimizer-fixes-4.spec.md"
    }
  ],
  "evaluation_digest": "sha256:b45f07834ca9f06ea1ce1c8aeb5a9a84e98b0ca2cb16bf09d5467ccb6b0b13c7",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:5c0a6c1be725cda7aeb1a7c126cb14931bf81885fc3175d81131695f515b0c49",
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
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions
- [x] Split points at every `table` segment or at page starts? — *Resolved in /sdd-fix research*: page starts (plus the
      first table segment); splitting at the table segment drags the next page's running header into the piece and
      widens its page range.
- [x] Pack forward or backward? — *Resolved*: backward; forward leaves the trailing 43-token stub to push the last
      piece over the target or veto the split (§2).
- [x] Apply to single-page tables (arxiv)? — *Resolved*: no; the rule needs table segments on ≥ 2 pages.

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
- `wiki/knowledge/pageindex-tree-optimizer.md` — the page-split fallback (`table_page_splits`,
  `TABLE_SPLIT_MIN_SHARE`, `split_at(titles=)`).
- `wiki/knowledge/pageindex-layout-structure.md` — 800-53 and AICPA results after FEAT-861.

## Revision History
| Date | Change |
|---|---|
| 2026-11-09 | Initial spec from `/sdd-fix` group `fixgroup:f3227810f34d` |
