---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot]  # FEAT-576 — core only: parrot.knowledge.pageindex (optimizer)
tags: [pageindex, tree-optimizer, ledger-fix]  # FEAT-576
docs:
  policy: required
  pages: [wiki/knowledge/pageindex-tree-optimizer.md]
  api_modules: [parrot.knowledge.pageindex.optimizer]
---

# Feature Specification: PageIndex Optimizer Fixes 2 — Page Fields and Footer-Safe Pseudo-Headings

**Feature ID**: FEAT-857
**Date**: 2026-11-09
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 2.2.0

> Ledger-driven follow-up to FEAT-853 (`pageindex-optimizer-fixes`). Drains the `/sdd-fix` group
> `fixgroup:7620973f861f`: `issue:5396799daf67` (major) and `issue:38e4627b2284` (minor). Both were found
> while validating FEAT-856 and both live in `optimizer.py`, which FEAT-856 lists as out of scope. No brainstorm or
> proposal: the issue bodies are the requirements.

---

## 1. Motivation & Business Requirements

### Problem Statement

1. **Optimizer children carry no page fields** (`issue:5396799daf67`). `split_at` (`optimizer.py:645`) builds each
   piece with `doc_id`, `revision`, `span`, `owned`, `title` and `nodes` only. Every node created by
   `expand_at_headings` therefore lacks `start_index` / `end_index`. On `dev`,
   `test_fixture_import_is_hybrid_and_anchored` (`test_layout_integration.py:152`) fails with
   `KeyError: 'start_index'`, because `PageIndexToolkit(optimize_on_import=True)` now expands the arxiv fixture's
   leaves (FEAT-853's pseudo-heading fallback). Retrieval (`retriever.py:108`, `:142`) reads those fields for
   paged documents.
2. **Pseudo-headings take running footers as titles** (`issue:38e4627b2284`). `pseudo_heading_segments`
   (`optimizer.py:485`) counts repeats by `heading_title(text).casefold()`. A footer such as `CHAPTER THREE PAGE 19`
   differs on each page only by its number, so each occurs once and passes the `PSEUDO_HEADING_MAX_REPEATS` filter.
   NIST 800-53's controls split into pieces titled `CHAPTER THREE PAGE 19`, `APPENDIX C PAGE 428`, and so on.

### Goals
- Every piece `split_at` creates from a paged revision carries `start_index` (page of its first owned segment)
  and `end_index` (page of its last owned segment, never below `start_index`). Pieces from unpaged revisions
  (ebook, markdown) carry neither key, as the root nodes of such trees do not.
- `test_fixture_import_is_hybrid_and_anchored` passes.
- Repeat counts in `pseudo_heading_segments` use `layout.running_key`, so a footer that differs only by digits is
  one repeated title and is dropped once it occurs more than `PSEUDO_HEADING_MAX_REPEATS` times.

### Non-Goals (explicitly out of scope)
- `layout.py`, `layout_structure.py` and the page-convention of FEAT-856 (another session owns them).
- Changing `OptimizerSettings`, `PROMPT_VERSION` or `OPTIMIZER_VERSION`.
- The `CONTROL SUMMARIES` table section's remaining expansion beyond the footer titles.
- Merging or re-deriving page fields of nodes the optimizer does not create.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:bc124c59b59a17c589f90a110a7d7cfd6e41570c45ec563b32b5b5197a1d132f evaluation_digest=sha256:e875587ad8d0dc85233f090db9847de6283febce60f4725229c810e2ac4acb49 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Two independent edits in `optimizer.py`.

**A. Page fields.** A private helper `_piece_pages(piece, revision)` returns `(start, end)` from the first and last
owned segment that has a `page`, or `None` when no owned segment is paged. `split_at` sets `start_index` and
`end_index` on each piece right after `assign_ownership(node)` (ownership may shrink a piece's `owned`).
`end_index` is the page of the last owned segment, a page-level value, not the "next item's page minus 1" rule
FEAT-856 uses for layout nodes: an optimizer piece's pages are exactly the pages it owns.

**B. Footer-safe repeat counts.** `pseudo_heading_segments` keys `counts` with
`running_key(heading_title(segment.text))` and looks candidates up with the same key. `running_key` is imported from
`parrot.knowledge.pageindex.layout`, which imports only `segments`, so there is no cycle.

### Integration Points
| Existing component | Interaction |
|---|---|
| `split_at` / `expand_at_headings` | Pieces gain page fields |
| `retriever.py:108,142` | Reads `start_index`/`end_index` when present |
| `layout.running_key` | Reused, not modified |

## 3. Module Breakdown

### Module 1: Piece page fields and footer-safe repeat counts
- **Path**: `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py`
- **Responsibility**: both edits above.
- **Interface Skeleton**:
```python
from parrot.knowledge.pageindex.layout import running_key  # verified: layout.py:97

def _piece_pages(piece: dict, revision: DocumentRevision) -> Optional[tuple[int, int]]:
    """Return (first, last) page of the piece's owned segments, or None when none is paged."""
```
- **Tests**: `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (new cases), plus the existing
  `test_layout_integration.py::test_fixture_import_is_hybrid_and_anchored`.

### Module 2: Documentation
- **Path**: `wiki/knowledge/pageindex-tree-optimizer.md`
- **Responsibility**: document the page fields on expanded pieces and the `running_key` repeat rule.
- **Tests**: `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py` (extend the names assertion).
- Depends on Module 1 (documents its behaviour).

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_split_at_sets_page_fields` | 1 | pieces over a paged revision get `start_index`/`end_index` from first/last owned page |
| `test_split_at_unpaged_has_no_page_fields` | 1 | an unpaged revision's pieces carry neither key |
| `test_pseudo_headings_drop_numbered_footers` | 1 | `CHAPTER THREE PAGE 19/21/22` footers (one per page) are not candidates; a real bold title is |

### Integration Tests
| Test | Description |
|---|---|
| `test_layout_integration.py::test_fixture_import_is_hybrid_and_anchored` | previously failing on dev |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py
- packages/ai-parrot/tests/knowledge/pageindex/test_layout_integration.py
- packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_docs.py
markers: none

## 5. Acceptance Criteria
- [ ] Pieces of a paged revision carry `start_index <= end_index` taken from their owned segments' pages.
- [ ] Pieces of an unpaged revision carry no page keys.
- [ ] `test_fixture_import_is_hybrid_and_anchored` passes.
- [ ] A footer differing from its siblings only by digits is never a pseudo-heading once it repeats more than
      `PSEUDO_HEADING_MAX_REPEATS` times.
- [ ] `ruff check` is clean on the changed files; the pageindex test directory still passes.
- [ ] `wiki/knowledge/pageindex-tree-optimizer.md` describes both behaviours.

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.pageindex.layout import running_key  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py:97
from parrot.knowledge.pageindex.segments import Segment  # Segment.page: Optional[int], segments.py:77
```

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py
def pseudo_heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]  # :485
def split_at(node, revision, seqs, *, source, settings, report) -> list[dict]  # :645
def expand_at_headings(node, revision, settings, report, *, depth) -> None  # :701
PSEUDO_HEADING_MAX_REPEATS = 2  # :29
# packages/ai-parrot/src/parrot/knowledge/pageindex/layout.py
def running_key(text: str) -> str  # :97 casefold, collapse whitespace, digit runs -> '#'
```

### Does NOT Exist
- No `start_index`/`end_index` is set anywhere in `optimizer.py` today.
- `layout.py` does not import `optimizer.py` (no import cycle).

### Edit Sites (Blueprint Anchors)
| File | Anchor | Action |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | `    assign_ownership(node)\n    _move_key_items_to_pieces(node, pieces, report)` (inside `split_at`, ~:688) | MODIFY |
| same | `key = heading_title(segment.text).casefold()` (`pseudo_heading_segments`, :509) and `counts.get(title.casefold(), 0)` (:519) | MODIFY |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | end of file | MODIFY |
| `wiki/knowledge/pageindex-tree-optimizer.md` | optimizer expansion section | MODIFY |

## 7. Implementation Notes & Constraints
- Set page fields after `assign_ownership(node)`, since ownership may change a piece's `owned`.
- Keep the diff to `optimizer.py`; do not refactor.
- Ledger linkage: `issue:5396799daf67`, `issue:38e4627b2284`.

## Worktree Strategy
One feature worktree. Module 2 depends on Module 1. No shared files between modules, no exclusive resources,
no cross-feature dependency (FEAT-856 does not touch `optimizer.py`).

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:bc124c59b59a17c589f90a110a7d7cfd6e41570c45ec563b32b5b5197a1d132f evaluation_digest=sha256:e875587ad8d0dc85233f090db9847de6283febce60f4725229c810e2ac4acb49 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/pageindex-optimizer-fixes-2.spec.md; message: no fenced yaml block under '## Decisions'

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
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/pageindex-optimizer-fixes-2.spec.md"
    }
  ],
  "evaluation_digest": "sha256:e875587ad8d0dc85233f090db9847de6283febce60f4725229c810e2ac4acb49",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:bc124c59b59a17c589f90a110a7d7cfd6e41570c45ec563b32b5b5197a1d132f",
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
- [x] Route through a new FEAT or add tasks to open FEAT-856? — *Resolved by user*: new FEAT.

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
- `wiki/knowledge/pageindex-tree-optimizer.md` — page fields on expanded pieces; `running_key` repeat rule.

## Revision History
| Date | Change |
|---|---|
| 2026-11-09 | Initial spec from `/sdd-fix` group `fixgroup:7620973f861f` |
