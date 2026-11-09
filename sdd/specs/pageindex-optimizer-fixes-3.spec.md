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

# Feature Specification: PageIndex Optimizer Fixes 3 — Document-Wide Running Lines for Pseudo-Headings

**Feature ID**: FEAT-859
**Date**: 2026-11-09
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Ledger-driven follow-up to FEAT-857 (`pageindex-optimizer-fixes-2`). Drains the `/sdd-fix` group
> `fixgroup:051ce1990e8b`: `issue:5a605ae51f61` (minor), found while re-measuring NIST SP 800-53 after FEAT-857.
> FEAT-857 is closed, so this is a new feature. No brainstorm or proposal: the issue body is the requirement.

---

## 1. Motivation & Business Requirements

### Problem Statement

`pseudo_heading_segments` (`optimizer.py:486`) drops a candidate title as a running header or footer only when its
`running_key` occurs more than `PSEUDO_HEADING_MAX_REPEATS` (2) times **among the paragraphs of the one leaf being
split** (`optimizer.py:508-521`). A long leaf holds its footer many times, so FEAT-857 fixed the 38-page
`CONTROL SUMMARIES` section. But `expand_at_headings` (`optimizer.py:717`) recurses into the pieces, and a two- or
three-page piece holds its footer once or twice, so the footer passes the filter and becomes a split point.

Observed on `dev` @ `d643c0c0d4` (FEAT-856 + FEAT-857), deterministic optimize of NIST SP 800-53 r5, target 1500 /
min 200 (report `artifacts/logs/optimizer_eval/dev_d643c0c0d4_deterministic/optimizer_eval-20261109T163506928918Z.json`,
sha256 `550ff81dc66dc73684b04e4f4a1c53af123f20014497059e125df4cb6fae2c04`): `TABLE C-3: AUDIT AND ACCOUNTABILITY
FAMILY`, `TABLE C-5` and `TABLE C-7` are each split once more, at pieces titled `APPENDIX C PAGE 434`, `APPENDIX C PAGE
437` and `APPENDIX C PAGE 441`.

### Evidence gathered for the rule (probe, `dev` @ `ac571679fe`, optimizer identical to `4ce5eeaf3d`)

Every single-line paragraph shaped like a pseudo-heading (bold-wrapped or upper case, passing `is_heading_text`) whose
`running_key` occurs more than twice in the whole revision, across 8 PDFs (the 5 compliance-corpus PDFs, the arxiv
fixture, and 3 book PDFs from `~/proyectos/parrot/parrot-bookstore/books`):

| Document | Title (sample) | Occurrences | Distinct pages | Max per page | Pages / page range | Page-number offset |
|---|---|---|---|---|---|---|
| 800-53 | `CHAPTER THREE PAGE 16` | 358 | 358 | 1 | 1.00 | constant (−27) |
| 800-53 | `APPENDIX C PAGE 428` | 38 | 38 | 1 | 1.00 | constant (−27) |
| 800-53 | `APPENDIX A PAGE 394`, `REFERENCES PAGE 374`, `CHAPTER TWO PAGE 7`, `CHAPTER ONE PAGE 1` | 30 / 20 / 9 / 6 | same | 1 | 1.00 | constant (−27) |
| 800-53 | `________…` (a full-width underscore separator line) | 490 | 490 | 1 | 1.00 | — |
| 800-53 | reference labels (`[OMB A-130]`, `[CNSSI 4009]`, `[SP 800-39]`, …) and `system` | 4–37 | 4–22 | 1–5 | 0.22–0.76 | varies |
| Analectas (Confucio) | `Capítulo 1` … `Capítulo 20` (one key once digits collapse) | 20 | 20 | 1 | 0.30 | varies |
| Crítica de la razón pura (Kant) | `PRIMERA SECCIÓN`, `SEGUNDA SECCIÓN` | 4 each | 4 | 1 | 0.03 | — |

AICPA, CSF 2.0, HIPAA, arxiv and Marco Aurelio have no repeated pseudo-heading titles.

So a plain whole-document count (the issue's first suggestion) would also drop legitimate repeated headings — Kant's
section titles today split leaves in which they occur once. Page footers differ from them by covering **every** page of
their range, once per page. The layout profile's running lines (the issue's second suggestion) do not help:
`analyze_layout` needs a line on `RUNNING_MIN_SHARE` (0.3) of all pages (`layout.py:524`), 148 of 800-53's 492, and
`APPENDIX C PAGE #` is on 38; the optimizer also receives only `DocumentRevision`, not the profile.

### Goals
- A pseudo-heading candidate whose `running_key` is a **document running line** is never a split point, whatever
  leaf it falls in. A key is a document running line when the revision's paragraphs with that key sit on more than
  `PSEUDO_HEADING_MAX_REPEATS` distinct pages, never twice on one page, and those pages cover at least
  `RUNNING_LINE_MIN_DENSITY` (0.8) of the page range they span.
- The existing per-leaf repeat rule stays (it still handles unpaged revisions and stacked labels).
- The document running-line set is computed once per `expand_at_headings` call tree, not once per leaf.
- On 800-53 no optimizer node is titled after a page footer.

### Non-Goals (explicitly out of scope)
- `layout.py`, `layout_structure.py`, `segments.py`; the layout profile's own running-line detection.
- Splitting long table sections (four `CONTROL SUMMARIES` tables stay single leaves over the target; table rows have no
  headings).
- Re-admitting chapter headings the per-leaf rule already drops (Analectas: the whole book is one leaf holding 20
  `Capítulo #` lines).
- Reference labels such as `[SP 800-39]` (they stack on one page, so they are not document running lines; the per-leaf
  rule keeps handling them as today).
- `OptimizerSettings`, `PSEUDO_HEADING_MAX_REPEATS`, `OPTIMIZER_VERSION`, `PROMPT_VERSION`.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:e9fe21915f741694f912797ee98d3452dfec7d6d217021047bc31909f208134e evaluation_digest=sha256:06a86a0c01d171de8e3cd26beb5b1200d40f81ab0e9bd150548e94764192d067 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One edit in `optimizer.py`, plus documentation.

**A. `document_running_keys(revision)`.** New public helper. It groups the revision's `paragraph` segments that have
a `page` by `running_key(heading_title(segment.text))` and returns the keys that qualify (Goals, first bullet). Unpaged
segments are skipped, so a markdown or ebook revision returns an empty set and keeps today's behaviour.

**B. `pseudo_heading_segments(..., *, running_keys=None)`.** A candidate whose key is in `running_keys` is skipped in
the same loop as the per-leaf repeat check, before the first-candidate-matches-node-title rule. When `running_keys`
is `None` the function computes `document_running_keys(revision)` itself, so direct callers keep working.

**C. `expand_at_headings(..., *, depth, running_keys=None)`.** When `running_keys` is `None`, it computes the set once
and passes it to its recursive calls (children and pieces) and to `pseudo_heading_segments`. `plan_deterministic`
(`optimizer.py:896`) calls it with the default, so each document root computes the set once.

### Measured effect (prototype, same probe)

| Document | Pieces titled after a footer | Leaves over target after | Max leaf | Other split points |
|---|---|---|---|---|
| 800-53 | 3 → 0 | 5 → 8 | 3,864 (unchanged) | unchanged |
| AICPA, CSF 2.0, HIPAA, arxiv, Analectas, Kant, Marco Aurelio | 0 → 0 | unchanged | unchanged | identical |

The three tables the footer used to cut (`TABLE C-3` 1,654 tokens, `TABLE C-5` 1,545, `TABLE C-7` 1,801) become single
leaves slightly over the 1,500 target. This is the same trade FEAT-857 made for the 38-page section: meaningful
titles over smaller pieces cut at page breaks. The prototype recomputed the set on every call and added ≈0.6 s to
800-53 and Kant; computing it once per call tree (C) removes that.

### Integration Points
| Existing component | Interaction |
|---|---|
| `expand_at_headings` / `plan_deterministic` | pass the running-line set down the recursion |
| `layout.running_key`, `layout_structure.heading_title` | reused, not modified |

## 3. Module Breakdown

### Module 1: Document running lines in the pseudo-heading fallback
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py`
- **Responsibility**: A, B and C above.
- **Interface Skeleton**:
```python
PSEUDO_HEADING_MAX_REPEATS = 2  # verified: optimizer.py:30 (unchanged)
RUNNING_LINE_MIN_DENSITY = 0.8
"""Share of its page range a repeated paragraph title must cover to count as a running header or footer."""


def document_running_keys(revision: DocumentRevision) -> frozenset[str]:
    """Return the ``running_key`` of every paragraph title that runs through the revision as a header or footer.

    A key qualifies when its paged ``paragraph`` segments sit on more than ``PSEUDO_HEADING_MAX_REPEATS`` distinct
    pages, never twice on one page, and those pages cover at least ``RUNNING_LINE_MIN_DENSITY`` of the page range
    they span. Segments without a page are ignored, so an unpaged revision returns an empty set.
    """


def pseudo_heading_segments(  # verified: optimizer.py:486
    node: dict, revision: DocumentRevision, *, running_keys: Optional[frozenset[str]] = None
) -> list[Segment]:
    """(existing docstring) + candidates whose key is in ``running_keys`` are dropped; ``None`` computes
    ``document_running_keys(revision)``."""


def expand_at_headings(  # verified: optimizer.py:717
    node: dict,
    revision: DocumentRevision,
    settings: OptimizerSettings,
    report: OptimizeReport,
    *,
    depth: int,
    running_keys: Optional[frozenset[str]] = None,
) -> None:
    """(existing docstring) + computes ``document_running_keys`` once when ``running_keys`` is ``None`` and passes it
    down the recursion."""
```
- **Tests**: `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (new cases, §4).

### Module 2: Host evaluation and documentation
- **Paths**: `wiki/knowledge/pageindex-tree-optimizer.md`, `wiki/knowledge/pageindex-layout-structure.md`,
  `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py`
- **Responsibility**: re-run the deterministic `optimizer_eval` on 800-53 + AICPA on the feature branch (host only, the
  corpus PDFs are git-ignored); document the document running-line rule in the optimizer page; replace the "still cut
  once at a footer … `issue:5a605ae51f61`" sentence and add a result row in the layout page, copying every number from
  the report plus its sha256; extend the docs test's names assertion.
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
| `test_document_running_keys_finds_page_footers` | 1 | a footer on every page of a 6-page paged revision (`APPENDIX C PAGE 428…433`) is a running key |
| `test_document_running_keys_ignores_spread_stacked_and_unpaged` | 1 | a title on 3 pages spread over 15, a title twice on one page, and any unpaged revision give no running key |
| `test_pseudo_headings_drop_document_footer_in_short_leaf` | 1 | a leaf owning the last two pages (two footers, below the per-leaf threshold) offers only its real bold title; fails on `dev` |
| `test_pseudo_headings_explicit_running_keys_override` | 1 | `running_keys=frozenset()` falls back to the per-leaf rule alone (the footer is offered again) |
| `test_expand_does_not_split_short_leaf_at_document_footer` | 1 | `plan_deterministic` over a paged tree leaves no node titled after a footer; fails on `dev` |
| `test_expand_computes_running_keys_once` | 1 | one `document_running_keys` call per document root during `plan_deterministic` |

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
- [ ] `document_running_keys` returns exactly the keys whose paged paragraphs sit on more than
      `PSEUDO_HEADING_MAX_REPEATS` distinct pages, at most once per page, covering ≥ `RUNNING_LINE_MIN_DENSITY` of their
      page range; an unpaged revision returns an empty set.
- [ ] `pseudo_heading_segments` never returns a candidate whose `running_key` is a document running line, in any leaf.
- [ ] The per-leaf repeat rule and the first-candidate title rule are unchanged.
- [ ] `document_running_keys` runs once per document root during `plan_deterministic`.
- [ ] Host `optimizer_eval` on 800-53 shows no node titled `… PAGE <n>`; AICPA is unchanged.
- [ ] `ruff check` is clean on the changed files; the Validation Contract passes.
- [ ] Both wiki pages describe the rule and the measured result; every number has its report and sha256.

## 6. Codebase Contract

Verified against `origin/dev` @ `4ce5eeaf3d`.

### Verified Imports
```python
from parrot.knowledge.pageindex.layout import running_key  # verified: optimizer.py:14 (already imported)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: optimizer.py:15
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment  # verified: optimizer.py:16-24
from typing import Any, Literal, Optional  # verified: optimizer.py:9
from parrot.knowledge.pageindex.segments import segment_pages  # verified: segments.py:231 (tests)
```

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
PSEUDO_HEADING_MAX_REPEATS = 2  # :30
def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]  # :486
def expand_at_headings(node, revision, settings, report, *, depth) -> None  # :717
def plan_deterministic(tree, revisions, settings, *, tree_name, node_id=None) -> OptimizePlan  # :876
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel): seq: int; kind: SegmentKind; page: Optional[int] = None; text: str  # :33-43
def segment_pages(pages: list[tuple[int, str]]) -> list[Segment]  # :231
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
def running_key(text: str) -> str  # :109 casefold, collapse whitespace, digit runs -> '#'
# packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py
def _paged_tree(pages: list[tuple[int, str]], title: str = "Libro") -> tuple[dict, dict]  # :499
```

### Does NOT Exist
- No document-wide repeat count anywhere in `optimizer.py`; `counts` in `pseudo_heading_segments` is per leaf.
- `DocumentRevision` carries no layout profile and no running-line list (`segments.py:59-68`).
- No other caller of `pseudo_heading_segments` or `expand_at_headings` in `packages/` besides `optimizer.py` and
  `tests/knowledge/pageindex/test_optimizer.py` (+ names in `test_optimizer_docs.py`).

### Edit Sites (Blueprint Anchors)
| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | `PSEUDO_HEADING_MAX_REPEATS = 2` | 30 | 1 | MODIFY (add constant after) |
| same | `def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:` | 486 | 1 | MODIFY (signature, docstring; new helper above it) |
| same | `        if counts.get(running_key(title), 0) > PSEUDO_HEADING_MAX_REPEATS:` | 520 | 1 | MODIFY |
| same | `def expand_at_headings(` | 717 | 1 | MODIFY (signature, docstring) |
| same | `            expand_at_headings(child, revision, settings, report, depth=depth + 1)` | 731 | 1 | MODIFY |
| same | `            node, revision, [segment.seq for segment in pseudo_heading_segments(node, revision)], settings` | 746 | 1 | MODIFY |
| same | `        expand_at_headings(piece, revision, settings, report, depth=depth + 1)` | 752 | 1 | MODIFY |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | end of file (after `test_pseudo_headings_drop_numbered_footers`) | 564 | 1 | MODIFY |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` | `        "PSEUDO_HEADING_MAX_REPEATS",` | 48 | 1 | MODIFY |
| `wiki/knowledge/pageindex-tree-optimizer.md` | ``   ignored once it occurs more than `PSEUDO_HEADING_MAX_REPEATS` times. Pieces created from a paged revision (a PDF)`` | 83 | 1 | MODIFY |
| `wiki/knowledge/pageindex-layout-structure.md` | `` `C-5`, `C-7`) are still cut once at a footer (`APPENDIX C PAGE 434`): the repeat rule counts footers inside one leaf, `` | 286 | 1 | MODIFY |
| same | `` \| nist_800_53_r5 \| FEAT-856 + FEAT-857 \| 1259 → 722 \| 341 / 735 / 3864 \| 1 / 5 \| `` | 270 | 1 | MODIFY (add a row after) |

## 7. Implementation Notes & Constraints
- Keep the per-leaf `counts` rule as is; the document rule is an extra skip in the same loop.
- Iterate `revision.segments` once in `document_running_keys`; no caching keyed on object identity or on
  `(doc_id, revision)` strings (tests reuse those strings with different segments).
- The prototype applied the document filter after the first-candidate title rule; the real code applies it in the
  loop, before that rule. Module 2's re-run is the authoritative measurement.
- Host evaluation reads the PDFs from the main checkout (`corpus/compliance_soc2_hipaa/raw/`); runs with
  `PYTHONPATH=<worktree>/packages/ai-parrot/src`, `--no-llm`/deterministic only; no coder seat.
- AICPA is `redistributable: false`: metrics only, never its titles, in committed files.
- Ledger linkage: `issue:5a605ae51f61`.

### Known Risks / Gotchas
- A legitimate title printed on more than two consecutive pages, once per page (a continued table header), now counts
  as a running line. That is the intended reading of such a line.
- A footer missing from more than a fifth of its pages (full-page figures) falls below the density threshold and is
  handled only by the per-leaf rule, as today.

## Worktree Strategy
One feature worktree. Module 2 → Module 1 (it measures and documents Module 1's behaviour). No file is shared between
the modules. Exclusive resource: Module 2's host evaluation (reads the git-ignored corpus from the main checkout).
No cross-feature dependency.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:e9fe21915f741694f912797ee98d3452dfec7d6d217021047bc31909f208134e evaluation_digest=sha256:06a86a0c01d171de8e3cd26beb5b1200d40f81ab0e9bd150548e94764192d067 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/b2358426-4665-42f0-a439-ce41a0bb07aa/scratchpad/dev-clone/sdd/specs/pageindex-optimizer-fixes-3.spec.md; message: no fenced yaml block under '## Decisions'

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
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/b2358426-4665-42f0-a439-ce41a0bb07aa/scratchpad/dev-clone/sdd/specs/pageindex-optimizer-fixes-3.spec.md"
    }
  ],
  "evaluation_digest": "sha256:06a86a0c01d171de8e3cd26beb5b1200d40f81ab0e9bd150548e94764192d067",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:e9fe21915f741694f912797ee98d3452dfec7d6d217021047bc31909f208134e",
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
- [x] Plain whole-document count, layout-profile running lines, or a page-evidence rule? — *Resolved in /sdd-fix
      research*: page-evidence rule (density + once per page); the other two fail on Kant / on the 30% page share (§1).

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
- `wiki/knowledge/pageindex-tree-optimizer.md` — the document running-line rule (`document_running_keys`,
  `RUNNING_LINE_MIN_DENSITY`).
- `wiki/knowledge/pageindex-layout-structure.md` — 800-53 result after FEAT-859; drop the open-issue sentence.

## Revision History
| Date | Change |
|---|---|
| 2026-11-09 | Initial spec from `/sdd-fix` group `fixgroup:051ce1990e8b` |
