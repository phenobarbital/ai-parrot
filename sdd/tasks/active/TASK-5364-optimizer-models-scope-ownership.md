# TASK-5364: Optimizer models, scope, repair, normalize and ownership

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

First half of spec Module 1 (§2 "Deterministic passes": *scope*, *repair*, *normalize*, *assign ownership*; §2 Data
Models; §3 M1 Interface Skeleton). `optimizer.py` is a pure module — tree dicts + `DocumentRevision` in, no I/O, no
LLM. TASK-5365 adds expansion, cost model, stamps, `plan_deterministic` and `validate_candidate` to the same file.

## Scope

- Create `optimizer.py` with `OPTIMIZER_VERSION`, `Revisions`, and the Pydantic models exactly as spec §2 Data Models:
  `OptimizerSettings` (+ `settings_hash()`), `KeyItem`, `PassStamp`, `OptimizerStamp`, `MergeAction`, `ExpandAction`,
  `OptimizeReport`; plus the plain class `OptimizePlan` (§3 M1).
- Implement `owned_tokens`, `is_locked`, `optimizable_roots`, `repair_ownership`, `normalize`, `assign_ownership`.
- Write the unit tests `test_owned_tokens_and_scope`, `test_repair_gaps_and_reject_overlaps`,
  `test_normalize_duplicates_empty_and_tiny`, `test_assign_ownership_residuals`.

**NOT in scope**: `heading_segments`, `routing_cost`, `should_expand`, `split_at`, `expand_at_headings`, stamp helpers,
`plan_deterministic`, `validate_candidate`, `leaves_over_target` (TASK-5365); anything LLM (TASK-5366/5367); toolkit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | CREATE | settings/report/stamp models, OptimizePlan, scope, repair, normalize, ownership |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | CREATE | M1 unit tests (first half) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.segments import (  # verified: segments.py:33,59,305,312,323,340,475,490
    DocumentRevision, Segment, _heading_text, _subtract, _titles_match, normalize_title, render_body, validate_ownership,
)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: layout_structure.py:23,61
from parrot.knowledge.pageindex.utils import structure_to_list, find_node_by_id  # verified: utils.py:294,353
from parrot.knowledge.pageindex import utils as _utils  # count_tokens via module attr (segments.py:11 pattern; tests stub it)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py
class Segment(BaseModel):            # :33  seq, kind, page, ordinal, section, level, text, tokens, sha16, flags, injection
class DocumentRevision(BaseModel):   # :59  doc_id, revision, source, segmenter, scored_by, created_at, segments
Range = tuple[int, int]              # :302
def _subtract(span: Range, holes: Sequence[Range]) -> list[Range]                      # :323
def _heading_text(text: str) -> str                                                    # :340
def render_body(revision: DocumentRevision, node: dict, children: Sequence[dict]) -> str  # :475
def validate_ownership(nodes: Sequence[dict], revision: DocumentRevision) -> list[str]  # :490 (empty => partition of [0, n))
# node dict fields set by attach_pdf_document (:358) / attach_section_document (:447): doc_id, revision, span, owned
# layout_structure.py
MAX_HEADING_WORDS = 20                 # :23
def heading_title(text: str) -> str    # :61
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.optimizer`~~ — created by this feature (TASK-5364 creates it)
- ~~`key_items`, `locked`, `locked_reason`, `aliases`, `optimizer` writers~~ — nothing writes them on `dev`
- ~~sibling dedup in `ensure_concept_ids`~~ — not there (`generation.py:105`); not this task's concern
- ~~a page-count trigger~~ — the expansion trigger is tokens over owned segments (G3); never use `max_page_num_each_node`
- ~~`Segment.is_heading`~~ — heading segments are recognised by `kind == "heading"` (check `Segment.kind` values in segments.py before use)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#DocumentRevision",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#_subtract",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#validate_ownership"
  ]
}
```

---

## Implementation Notes

- Token counts go through `_utils.count_tokens` (module attribute), never a direct `from ... import count_tokens` —
  tests monkeypatch `parrot.knowledge.pageindex.utils.count_tokens`. Prefer `segment.tokens` when the revision carries it.
- Ranges are half-open `[a, b)` lists of `[a, b]` pairs in node dicts (`owned`, `span`); read them as tuples.
- `normalize` merge rule (spec §2): previous contiguous sibling first, else the next; both must be unlocked leaves and
  the merged owned ranges must stay contiguous. Absorbed title → `literal` `KeyItem` anchored at its heading segment
  (or first owned seq); absorbed `concept_id` → absorber `aliases` (dedup, keep order). Record a `MergeAction`.
- Overlaps found by `repair_ownership` are returned, not raised; the caller records them in `report.errors`.

---

## Implementation Blueprint

**Steps (in order)**
1. Create `optimizer.py` with the block below — because every later task imports these names verbatim.
2. Fill the `FILL IN` bodies — each bounded by the spec rule quoted next to it.
3. Create `test_optimizer.py` with a synthetic revision fixture (spec §4 Test Data) and the four tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (CREATE)
```python
"""Deterministic PageIndex tree optimizer (FEAT-846, Module 1)."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.pageindex.segments import (  # verified: segments.py:33,59,305,312,323,340,475,490
    DocumentRevision, Segment, _heading_text, _subtract, _titles_match, normalize_title, render_body, validate_ownership,
)
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS, heading_title  # verified: layout_structure.py:23,61
from parrot.knowledge.pageindex.utils import structure_to_list, find_node_by_id  # verified: utils.py:294,353
from parrot.knowledge.pageindex import utils as _utils  # count_tokens via module attr (segments.py:11 pattern; tests stub it)

logger = logging.getLogger(__name__)

OPTIMIZER_VERSION = "v1"
Revisions = dict[tuple[str, str], DocumentRevision]


class OptimizerSettings(BaseModel):
    """Provisional defaults (tuned by optimizer_eval, TASK-5376)."""

    target_leaf_tokens: int = 1500
    min_leaf_tokens: int = 200
    inline_summary_tokens: int = 120
    summary_max_words: int = 60
    max_key_items: int = 8
    routing_tokens_per_child: int = 48
    max_depth: int = 8
    llm_passes: bool = True

    def settings_hash(self) -> str:
        """sha256 of the sorted model dump, 16 hex chars."""
        raw = json.dumps(self.model_dump(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class KeyItem(BaseModel):
    label: str
    kind: Literal["literal", "abstractive"]
    seq: int
    page: Optional[int] = None
    ordinal: int = 0


class PassStamp(BaseModel):
    version: str
    input: str
    settings: str
    execution: str
    at: str


class OptimizerStamp(BaseModel):
    passes: dict[Literal["headings", "key_items", "summary"], PassStamp] = Field(default_factory=dict)
    summary: Literal["inline", "llm", "composed", "none"] = "none"


class MergeAction(BaseModel):
    absorbed_concept_id: Optional[str]
    absorbed_title: str
    into_concept_id: Optional[str]
    into_title: str
    reason: Literal["duplicate_span", "empty", "under_minimum"]


class ExpandAction(BaseModel):
    parent_title: str
    parent_concept_id: Optional[str]
    pieces: list[str]
    source: Literal["layout", "llm"]


class OptimizeReport(BaseModel):
    # FILL IN: every field of spec §2 Data Models `OptimizeReport`, same names/types; list fields default to
    #          empty lists, counters to 0, llm_passes to "skipped (disabled)", settings default OptimizerSettings()
    ...


class OptimizePlan:
    """A candidate tree (deep copy of the input) plus the report and the per-node LLM cache."""

    def __init__(self, candidate: dict[str, Any], report: OptimizeReport) -> None:
        self.candidate = candidate
        self.report = report
        self.mutable: set[int] = set()
        self.touched: set[int] = set()
        self.pending_stamps: dict[int, dict[str, PassStamp]] = {}
        self.llm_cache: dict[str, Any] = {}


def owned_tokens(node: dict, revision: DocumentRevision) -> int:
    """Sum of ``segments[seq].tokens`` over the node's owned ranges."""
    # FILL IN: iterate node.get("owned") or []; use seg.tokens, fall back to _utils.count_tokens(seg.text)


def is_locked(node: dict) -> bool:
    """``node.get("locked") is True``."""
    return node.get("locked") is True


def optimizable_roots(tree: dict, revisions: Revisions, *, node_id: Optional[str] = None) -> list[dict]:
    """Imported subtree roots in scope (spec §3 M1 docstring)."""
    # FILL IN: top-most nodes with doc_id/revision whose (doc_id, revision) is in `revisions` and not effectively
    #          locked (self or any ancestor locked); with node_id restrict to that subtree (KeyError when absent,
    #          [] when an ancestor is locked) — bounded by AC-8


def repair_ownership(doc_nodes: list[dict], revision: DocumentRevision, report: OptimizeReport) -> list[str]:
    """Re-own every unowned range to the deepest in-scope ancestor whose span covers it; return overlap problems."""
    # FILL IN: build coverage over [0, len(revision.segments)); gaps -> append to deepest covering node's owned
    #          (merge adjacent ranges), report.repaired_gaps += 1 per gap; overlaps -> return messages, change nothing


def normalize(parent_children: list[dict], revision: DocumentRevision, settings: OptimizerSettings,
              report: OptimizeReport) -> None:
    """Collapse identical spans, drop empty leaves, merge contiguous under-minimum leaves. Recurses."""
    # FILL IN: spec §2 *normalize*; never touch a locked node; append MergeAction per merge


def assign_ownership(node: dict) -> None:
    """Widen ``span`` to cover descendants; ``owned = _subtract(span, child spans)``; recursive, bottom-up."""
    # FILL IN: recurse children first; locked children keep their owned ranges fixed (spec §2 "Locked nodes")
```
**Why**: the models and names are fixed by spec §2/§3 and imported by TASK-5365..5378; keeping them in one block
prevents drift. `OptimizePlan` is a plain class (holds `id()` sets), not a Pydantic model.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (CREATE)
```python
"""Unit tests for parrot.knowledge.pageindex.optimizer (FEAT-846 M1)."""
import pytest

from parrot.knowledge.pageindex.optimizer import (
    OptimizeReport, OptimizerSettings, assign_ownership, normalize, optimizable_roots, owned_tokens, repair_ownership,
)
from parrot.knowledge.pageindex.segments import render_body, segment_text  # verified: segments.py:240,475


@pytest.fixture(autouse=True)
def _stub_tokens(monkeypatch):
    monkeypatch.setattr("parrot.knowledge.pageindex.utils.count_tokens", lambda t, model="gpt-4o": max(1, len(t) // 4))


def test_owned_tokens_and_scope(): ...            # FILL IN: spec §4 row
def test_repair_gaps_and_reject_overlaps(): ...   # FILL IN: spec §4 row
def test_normalize_duplicates_empty_and_tiny(): ...  # FILL IN: spec §4 row (alias + literal key_item)
def test_assign_ownership_residuals(): ...        # FILL IN: spec §4 row; render_body shows continues-in markers
```
**Why**: `segment_text` builds a revision from markdown with no PDF, as spec §4 Test Data prescribes. Check its exact
signature at `segments.py:240` before use.

**FILL IN checklist**
- [ ] `OptimizeReport` fields match spec §2 exactly
- [ ] `owned_tokens`, `optimizable_roots`, `repair_ownership`, `normalize`, `assign_ownership` bodies
- [ ] four tests

---

## Acceptance Criteria

- [ ] All names in the blueprint exist in `optimizer.py` with the spec §2 fields and defaults.
- [ ] Locked nodes and their descendants are never modified by `normalize`/`assign_ownership` (AC-8 part).
- [ ] Merges keep text: absorbed title is a `literal` key_item, absorbed `concept_id` in `aliases` (AC-11 part).
- [ ] The four tests pass.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`

---

## Test Specification

Spec §4 rows `test_owned_tokens_and_scope`, `test_repair_gaps_and_reject_overlaps`,
`test_normalize_duplicates_empty_and_tiny`, `test_assign_ownership_residuals`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5364 — Optimizer models, scope, repair, normalize and ownership`.

---

## Completion Note

*(Agent fills this in when done)*
