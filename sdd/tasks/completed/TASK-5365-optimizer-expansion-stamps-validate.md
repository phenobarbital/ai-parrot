# TASK-5365: Optimizer expansion, cost model, stamps, planning and validation

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5364
**Assigned-to**: unassigned

---

## Context

Second half of spec Module 1: *expand at headings*, *decide*, *prepare pass inputs* (stamp lifecycle, normative §2
paragraph "Stamp lifecycle and retry cache"), *validate*. After this task `plan_deterministic` produces a full
`OptimizePlan`; M2 adds LLM work on top and the toolkit finalizes stamps.

## Scope

- Add `heading_segments`, `routing_cost`, `should_expand`, `split_at`, `expand_at_headings`, `stamp_input`, `pass_input`,
  `pass_cache_key`, `is_stamped`, `finalize_stamps`, `plan_deterministic`, `validate_candidate`, `leaves_over_target`
  with the spec §3 M1 signatures.
- Tests: `test_expand_at_headings_and_cost_model`, `test_stamp_idempotence`, `test_stamp_summary_dependencies`,
  `test_validate_candidate`.

**NOT in scope**: LLM proposals (`split_at` is called by them later with `source="llm"`); toolkit staging; tuning the
`target_leaf_tokens` default (TASK-5376).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` | MODIFY | expansion, cost model, stamp helpers, plan_deterministic, validate_candidate |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` | MODIFY | M1 unit tests (second half) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported by TASK-5364 at the top of optimizer.py:
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
# optimizer.py (TASK-5364): OptimizerSettings, KeyItem, PassStamp, OptimizerStamp, ExpandAction, OptimizeReport,
#   OptimizePlan(candidate, report), owned_tokens, is_locked, optimizable_roots, repair_ownership, normalize, assign_ownership
```

### Does NOT Exist
- ~~`parrot.knowledge.pageindex.optimizer`~~ — created by this feature (TASK-5364 creates it)
- ~~`key_items`, `locked`, `locked_reason`, `aliases`, `optimizer` writers~~ — nothing writes them on `dev`
- ~~sibling dedup in `ensure_concept_ids`~~ — not there (`generation.py:105`); not this task's concern
- ~~a page-count trigger~~ — the expansion trigger is tokens over owned segments (G3); never use `max_page_num_each_node`
- ~~`Segment.is_heading`~~ — heading segments are recognised by `kind == "heading"` (check `Segment.kind` values in segments.py before use)
- ~~a blanket node-level "optimized" flag~~ — completion is per pass under `node["optimizer"]["passes"]`; a legacy blanket stamp is a cache miss

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#validate_ownership",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/layout_structure.py#heading_title"
  ]
}
```

---

## Implementation Notes

- `should_expand`: `cost + max(piece_tokens) < node_tokens and min(piece_tokens) >= settings.min_leaf_tokens` (G3).
- `split_at`: the text before the first split seq stays with the node (no synthetic intro). New children get
  `doc_id`, `revision`, `span`, `owned`, `title=heading_title(segment.text)`, `nodes=[]`; record one `ExpandAction`.
- `expand_at_headings`: shallowest heading level present first, recurse into the new pieces, never below `max_depth`.
- Stamps (normative): `plan_deterministic` NEVER writes completion records; it keeps the input stamps so M2 can compare.
  `finalize_stamps` writes `plan.pending_stamps` for mutable nodes only, discarding records whose input hash no longer
  matches the final node, and leaves matching existing records (and their `at`) untouched.
- `validate_candidate` runs twice in the toolkit (before and after staging/finalization); compare protected nodes to
  `base_tree` ignoring only `node_id`, including `body_ref`.

---

## Implementation Blueprint

**Steps (in order)**
1. Append the block below after `assign_ownership` in `optimizer.py`.
2. Fill the bodies; `plan_deterministic` order is fixed: scope → repair → normalize → ownership → expand.
3. Extend `test_optimizer.py` with the four tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer.py` (MODIFY)
```python
# AFTER — append below `def assign_ownership(node: dict) -> None:` and its body
# occurrences: 1 (verified after TASK-5364: grep -c 'def assign_ownership' optimizer.py)

def heading_segments(node: dict, revision: DocumentRevision) -> list[Segment]:
    """Heading segments inside the owned ranges, excluding the node's own title heading when it is the first one."""
    # FILL IN: use _titles_match(normalize_title(...)) to drop the node's own title heading


def routing_cost(pieces: list[dict], revision: DocumentRevision, settings: OptimizerSettings) -> int:
    """Tokens of the pieces' titles + summaries when present, else ``routing_tokens_per_child`` each."""
    # FILL IN


def should_expand(node_tokens: int, piece_tokens: list[int], cost: int, settings: OptimizerSettings) -> bool:
    """``cost + max(piece_tokens) < node_tokens`` and every piece >= ``min_leaf_tokens``."""
    if not piece_tokens:
        return False
    return cost + max(piece_tokens) < node_tokens and min(piece_tokens) >= settings.min_leaf_tokens


def split_at(node: dict, revision: DocumentRevision, seqs: list[int], *, source: str,
             settings: OptimizerSettings, report: OptimizeReport) -> list[dict]:
    """One child per split seq owning ``[seq, next_seq)`` within the node's owned ranges (spec §3 M1)."""
    # FILL IN: build pieces, check should_expand, mutate node only when taken; call assign_ownership(node)


def expand_at_headings(node: dict, revision: DocumentRevision, settings: OptimizerSettings,
                       report: OptimizeReport, *, depth: int) -> None:
    """Recursive layout expansion: shallowest heading level first, down to ``max_depth``."""
    # FILL IN: only leaves over target_leaf_tokens; source="layout"


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def stamp_input(node: dict) -> str:
    """sha256[:16] of json (doc_id, revision, owned, title, [(child.title, child.span)])."""
    kids = [(c.get("title"), c.get("span")) for c in node.get("nodes") or []]
    return _digest([node.get("doc_id"), node.get("revision"), node.get("owned"), node.get("title"), kids])


def pass_input(node: dict, pass_name: str) -> str:
    """Structural input plus consumed dependencies (summary: own key_items + ordered child outputs)."""
    # FILL IN: headings/key_items -> stamp_input(node); summary -> also key_items and
    #          [(title, summary, key_items, span) for each child] — bounded by AC-7 / test_stamp_summary_dependencies


def pass_cache_key(pass_name: str, input_hash: str, execution: str, settings: OptimizerSettings) -> str:
    """Hash pass name, OPTIMIZER_VERSION, settings hash, input hash and execution digest."""
    return _digest([pass_name, OPTIMIZER_VERSION, settings.settings_hash(), input_hash, execution])


def is_stamped(node: dict, settings: OptimizerSettings, *, pass_name: str, input_hash: str, execution: str) -> bool:
    """Matching completed record for this pass only; missing or legacy blanket stamps are cache misses."""
    # FILL IN: read node.get("optimizer", {}).get("passes", {}).get(pass_name); compare all four fields


def finalize_stamps(plan: OptimizePlan) -> None:
    """Persist successful pending pass records for mutable nodes only (spec §3 M1 docstring)."""
    # FILL IN


def plan_deterministic(tree: dict, revisions: Revisions, settings: OptimizerSettings, *,
                       tree_name: str, node_id: Optional[str] = None) -> OptimizePlan:
    """Deep-copy ``tree``; scope -> repair -> normalize -> ownership -> expand; never write completion records."""
    candidate = copy.deepcopy(tree)
    report = OptimizeReport(tree_name=tree_name, node_id=node_id, dry_run=True, settings=settings)
    plan = OptimizePlan(candidate, report)
    # FILL IN: fill documents, nodes_before/after, leaves_over_target_before/after, skipped_locked, mutable, touched
    return plan


def validate_candidate(plan: OptimizePlan, revisions: Revisions, *, base_tree: dict) -> list[str]:
    """Per-document partition, key_item anchors, protected-node equality (except node_id). Non-empty => abort."""
    # FILL IN


def leaves_over_target(nodes: list[dict], revisions: Revisions, settings: OptimizerSettings) -> int:
    """Count leaves whose owned tokens exceed ``target_leaf_tokens``."""
    # FILL IN
```
**Why**: `should_expand`, `stamp_input` and `pass_cache_key` are fully specified by the spec, so they are complete
here; everything with tree-walking judgement is a bounded FILL IN.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py` (MODIFY)
```python
# AFTER — append at end of file (after test_assign_ownership_residuals)
def test_expand_at_headings_and_cost_model(): ...   # FILL IN: spec §4 row
def test_stamp_idempotence(): ...                   # FILL IN: spec §4 row
def test_stamp_summary_dependencies(): ...          # FILL IN: spec §4 row
def test_validate_candidate(): ...                  # FILL IN: spec §4 row
```

**FILL IN checklist**
- [ ] all `FILL IN` bodies; `plan_deterministic` leaves `report.dry_run=True`
- [ ] four tests

---

## Acceptance Criteria

- [ ] AC-3: a leaf over target with heading segments splits when the cost model allows; never under `min_leaf_tokens`;
      tokens over owned segments, never pages.
- [ ] AC-5 (planner part): `validate_candidate` returns errors for a broken partition, out-of-range anchors or a changed
      protected node.
- [ ] AC-7 (planner part): planning writes no completion stamps; a second `plan_deterministic` on its own output reports
      zero merges/expansions.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer.py -q`

---

## Test Specification

Spec §4 rows `test_expand_at_headings_and_cost_model`, `test_stamp_idempotence`, `test_stamp_summary_dependencies`,
`test_validate_candidate`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5365 — Optimizer expansion, cost model, stamps, planning and validation`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: b59f004b87

Delivered via sdd-coder pool (merged). Scope: optimizer expansion, stamps, validate.
Validation: merge-tier — 8 passed, exit 0.
Deviations: none noted.

