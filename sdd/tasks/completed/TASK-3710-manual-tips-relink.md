# TASK-3710: Technician tips: add/retire and idempotent relink_tips (M9)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3699, TASK-3701
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 9** (tips half) and goal **G3 — tips survive re-ingest** (U3, R1). Technician
tips live in technician-owned collections (`tech_tip`, `tech_tip_on`, `tech_tip_by`) that
the graph loader never reconciles. When a manual is re-published, `relink_tips` re-attaches
each active tip to the new revision's step: first by `source_identity`, then by exact
`content_hash` equality; a text-similar step only becomes a **curator candidate**; anything
else is **orphaned** (kept, never deleted). Implements AC6 and feeds AC5 (TASK-3712 calls
`relink_tips` after `publish_all`). `add_tip` / `retire_tip` back the `proc_add_tip` /
`proc_retire_tip` tools (TASK-3724).

Parallelism: uses Tip/Step/StepIdentity from TASK-3699 (manuals/models.py) and
TECHNICIAN_COLLECTIONS/resolve_context from TASK-3701 (manuals/domain.py).

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/manuals/tips.py` with `RelinkOutcome`,
  `RelinkReport`, `relink_tips`, `add_tip`, `retire_tip` exactly per the spec §3 M9 skeleton.
- Relink algorithm (fixed order, R1): (1) same non-null `source_identity` among current steps
  ⇒ relink (`method="source_identity"`, or `"unchanged"` when the step_id is identical);
  (2) exact `content_hash` equality ⇒ relink (`method="content_hash"`); (3) text similarity
  (rapidfuzz `token_sort_ratio`/100) on step **text** ≥ 0.85 ⇒ `method="candidate"`, tip set
  `orphaned=True`, candidates recorded; (4) else `method="orphaned"`, tip `orphaned=True`.
- Idempotent: a second run over the same inputs produces no new edges and only `unchanged`
  outcomes; appends to `Tip.history` only when the attachment actually changes.
- Never cross manuals or tenants: only steps whose `step_id` starts with `f"{manual_id}:"`
  are candidates; the `ctx` passed in is the only tenant touched.
- Per-tip failures (graph write raises) are retried once, then collected into
  `RelinkReport.failed` — never raised.
- `add_tip` writes a `tech_tip` document (`origin="technician"`,
  `author_employee_id` as passed — the caller supplies it from the trusted `RequestContext`),
  a `tech_tip_on` edge to the step (`linked_by="technician"`, `linked_at`) and returns the `Tip`.
- `retire_tip` sets `active=False` on the tip and appends a history entry `{"action": "retired", "by": by, "at": …}`.
- Write `packages/ai-parrot/tests/knowledge/manuals/test_tips.py` covering the
  `test_relink_tips_matrix` cases.

**NOT in scope**: the graph loader (TASK-3712) — it only *calls* `relink_tips`; the
`proc_*` tools (TASK-3724); curator UI; moderation; hash similarity of any kind (AC4 — hashes
are compared with `==` only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/manuals/tips.py` | CREATE | relink/add/retire tips over technician collections |
| `packages/ai-parrot/tests/knowledge/manuals/test_tips.py` | CREATE | relink matrix, idempotency, failure collection, add/retire |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.ontology.schema import TenantContext  # verified: packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:529
# Created by TASK-3699 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py) — spec §3 M2 skeleton:
from parrot.knowledge.manuals.models import Step, StepIdentity, Tip
# Created by TASK-3701 (packages/ai-parrot/src/parrot/knowledge/manuals/domain.py) — spec §3 M3 skeleton:
from parrot.knowledge.manuals.domain import TECHNICIAN_COLLECTIONS
# Optional third-party, already declared in the `graphindex` extra (no new dep):
from rapidfuzz import fuzz  # lazy import inside the similarity helper, RuntimeError with install hint
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py:529
class TenantContext(BaseModel):
    tenant_id: str; arango_db: str; pgvector_schema: str; ontology: MergedOntology

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py (OntologyGraphStore)
async def create_edges(self, ctx, edge_collection: str, edges: list[dict]) -> int          # :411 — UPSERT on {_from,_to}; NEVER updates properties; count inflated on no-op
async def get_document(self, ctx, collection: str, key: str) -> Optional[dict]               # :598
async def upsert_document(self, ctx, collection: str, doc: dict) -> None                     # :622 — full replace by _key
async def query_documents(self, ctx, collection: str, filters=None, sort_desc=None, limit=None) -> list[dict]  # :697 — ANDed equality filters
async def edges_incident(self, ctx, collection: str, node_id: str) -> list[dict]             # :764 — matches source_id/target_id
async def remove_edge_by_triple(self, ctx, collection, source_id, target_id, kind) -> bool   # :791

# packages/ai-parrot/src/parrot/knowledge/contracts/carding.py:868 — pattern ONLY (do not import contracts):
def similarity(left: str, right: str) -> float   # rapidfuzz.fuzz.token_sort_ratio / 100; 0.0 on empty; 1.0 on identical

# Spec §3 M2 (TASK-3699) shapes relied on here:
class StepIdentity(BaseModel): step_id: str; source_identity: str | None = None; content_hash: str
class Tip(BaseModel): tip_id; text; origin: TipOrigin; author_employee_id; created_at; active=True; orphaned=False; source_revision; attached_step_id; history: list[dict]
```

### Does NOT Exist
- ~~`parrot.knowledge.manuals.tips`~~ — this task creates it.
- ~~Any hash "similarity" (Hamming, prefix, fuzzy on `content_hash`)~~ — rejected by R1/AC4; hashes are `==` only.
- ~~A `step_key` derived from `slug:order`~~ — identity is the minted `step_id`.
- ~~`OntologyGraphStore.update_edge` / edge property update~~ — `create_edges` never updates; to change edge props remove by triple then create.
- ~~Importing `parrot.knowledge.contracts.*` from manuals~~ — M1 exists so manuals never imports contracts; re-implement the tiny `similarity` helper locally.
- ~~A `tech_tip` entry in `OWNED_VERTEX_COLLECTIONS`~~ — technician collections are disjoint from owned ones (TASK-3701).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/manuals/tips.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/manuals/test_tips.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TenantContext",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.create_edges",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.query_documents",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.upsert_document",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#OntologyGraphStore.remove_edge_by_triple"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest …` (the shared venv is editable-installed against the main checkout).
- Ontology imports from submodules only (`parrot.knowledge.ontology.schema`), never the package root (AC17).
- No new dependency; `rapidfuzz` is imported lazily with a `RuntimeError("… pip install 'ai-parrot[graphindex]'")` like `contracts/carding.py:868-892`.
- Google-style docstrings, strict type hints, Pydantic v2 models, `logging.getLogger(__name__)` — no `print`.
- Graph document shape for a tip: `{"_key": tip_id, **Tip.model_dump(mode="json")}` in collection `tech_tip`; edge `tech_tip_on`: `{"_from": f"tech_tip/{tip_id}", "_to": f"step/{step_id}", "source_id": …, "target_id": …, "kind": "tech_tip_on", "origin": "technician", "linked_by": …, "linked_at": iso}`.
- Relinking an edge = `remove_edge_by_triple` on the old `(tip, old step)` edge, then `create_edges` for the new one — because `create_edges` never updates.
- Tests use `FakeGraphStore` from `packages/ai-parrot/tests/knowledge/_support/graph.py` (TASK-3698). If it lacks `query_documents`/`upsert_document`/`get_document`, subclass it **inside `test_tips.py`** — do not edit `_support/` (another task's file).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py:502-548` — remove-then-create edge pattern.
- `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py:868-892` — similarity helper to re-implement.

---

## Implementation Blueprint

### Steps (in order)
1. Write the models `RelinkOutcome`/`RelinkReport` verbatim from the skeleton — *why*: TASK-3712's `GraphPublicationReport.tip_relink` embeds `RelinkReport` and reads `.failed`.
2. Implement `_text_similarity` locally — *why*: manuals must not import contracts (M1 goal).
3. Implement `_match(step, current_steps)` returning `(method, new_step_id, candidates)` in the fixed R1 order — *why*: AC4/AC6 require identity → exact hash → candidate → orphan and nothing else.
4. Implement `relink_tips` iterating active tips attached to previous steps of this manual, writing edges/tip docs with one retry per tip — *why*: failures must be reported, not raised (AC6 "failed relink + retry").
5. Implement `add_tip` / `retire_tip` — *why*: the confirming tools in TASK-3724 call them.
6. Write the matrix tests — *why*: `test_relink_tips_matrix` is the AC6 evidence.

### `packages/ai-parrot/src/parrot/knowledge/manuals/tips.py` (CREATE)
```python
"""Technician tips: add, retire and re-link across manual revisions (FEAT-601 M9).

Tips live in technician-owned collections the graph loader never reconciles.
Re-linking follows R1 strictly: source identity, then exact content-hash
equality; text similarity only ever yields curator candidates.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.ontology.schema import TenantContext

from .domain import TECHNICIAN_COLLECTIONS
from .models import Step, Tip

logger = logging.getLogger(__name__)

CANDIDATE_THRESHOLD = 0.85
TIP_COLLECTION, TIP_EDGE, TIP_AUTHOR_EDGE = TECHNICIAN_COLLECTIONS  # ("tech_tip", "tech_tip_on", "tech_tip_by")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RelinkOutcome(BaseModel):
    """What happened to one tip during a relink run."""

    tip_id: str
    previous_step_id: str | None
    new_step_id: str | None
    method: Literal["source_identity", "content_hash", "unchanged", "candidate", "orphaned"]
    candidates: list[tuple[str, float]] = Field(default_factory=list)


class RelinkReport(BaseModel):
    """Aggregate relink result for one manual; ``failed`` lists tip ids that could not be written."""

    manual_id: str
    relinked: list[RelinkOutcome] = Field(default_factory=list)
    orphaned: list[RelinkOutcome] = Field(default_factory=list)
    candidates: list[RelinkOutcome] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)


def _text_similarity(left: str, right: str) -> float:
    """rapidfuzz token_sort_ratio / 100 on step TEXT (never on hashes)."""
    # FILL IN: mirror contracts/carding.py:868-892 (empty ⇒ 0.0, identical ⇒ 1.0, lazy import + RuntimeError hint)
    raise NotImplementedError


def _match(previous: Step, current: Sequence[Step], *, manual_id: str) -> tuple[str, str | None, list[tuple[str, float]]]:
    """Return (method, new_step_id, candidates) following the fixed R1 order."""
    # FILL IN: restrict `current` to step_id.startswith(f"{manual_id}:") — bounded by AC6 "no cross-manual"
    # FILL IN: (1) source_identity equal & not None ⇒ "unchanged" if same step_id else "source_identity"
    # FILL IN: (2) identity.content_hash == ⇒ "content_hash"; ties (duplicated steps) ⇒ lowest order wins, document it
    # FILL IN: (3) _text_similarity(text) >= CANDIDATE_THRESHOLD ⇒ ("candidate", None, sorted desc list)
    # FILL IN: (4) ("orphaned", None, [])
    raise NotImplementedError


async def relink_tips(
    graph_store: Any,
    ctx: TenantContext,
    *,
    manual_id: str,
    previous_steps: Sequence[Step],
    current_steps: Sequence[Step],
    linked_by: str = "manuals.relink",
    now: Callable[[], datetime] = _utcnow,
) -> RelinkReport:
    """Re-attach active tips of ``manual_id`` from previous to current steps. Idempotent; never raises per tip."""
    report = RelinkReport(manual_id=manual_id)
    by_id = {step.identity.step_id: step for step in previous_steps}
    # FILL IN: tips = graph_store.query_documents(ctx, TIP_COLLECTION, filters={"active": True}) filtered to
    #          attached_step_id in by_id OR (orphaned and attached_step_id startswith manual prefix) — bounded by AC6 idempotency
    # FILL IN: per tip: _match → on relink: remove_edge_by_triple(old) + create_edges(new edge doc with linked_by/linked_at),
    #          update tip doc (attached_step_id, orphaned=False, history append) via upsert_document;
    #          on candidate/orphaned: tip orphaned=True, keep attached_step_id + source_revision, history append once
    # FILL IN: wrap each tip in try/except; retry once; on second failure append tip_id to report.failed and logger.warning
    logger.info("relink_tips %s: %d relinked, %d orphaned, %d candidates, %d failed", manual_id,
                len(report.relinked), len(report.orphaned), len(report.candidates), len(report.failed))
    return report


async def add_tip(
    graph_store: Any,
    ctx: TenantContext,
    *,
    step_id: str,
    text: str,
    author_employee_id: str,
    source_revision: str,
    now: Callable[[], datetime] = _utcnow,
) -> Tip:
    """Write a technician tip + its ``tech_tip_on`` edge; author comes from the trusted context, never the model."""
    tip = Tip(
        tip_id=f"tip-{uuid.uuid4().hex[:16]}", text=text, origin="technician", author_employee_id=author_employee_id,
        created_at=now(), source_revision=source_revision, attached_step_id=step_id, history=[],
    )
    # FILL IN: upsert_document(ctx, TIP_COLLECTION, {"_key": tip.tip_id, **tip.model_dump(mode="json")});
    #          create_edges(ctx, TIP_EDGE, [edge doc with origin="technician", linked_by="technician", linked_at])
    return tip


async def retire_tip(graph_store: Any, ctx: TenantContext, *, tip_id: str, by: str) -> None:
    """Deactivate a tip (curator action) and append an audit entry to its history."""
    # FILL IN: get_document → KeyError-style ValueError when missing; set active=False; history.append({"action": "retired", "by": by, "at": iso})
    raise NotImplementedError
```
**Why this shape**: signatures are the spec §3 M9 skeleton (fixed). The collection names are
taken from `TECHNICIAN_COLLECTIONS` so there is one source of truth with the loader's exclusion
list; if TASK-3701 orders the tuple differently, unpack by name instead — do not hard-code a
second list.

### `packages/ai-parrot/tests/knowledge/manuals/test_tips.py` (CREATE)
```python
"""relink_tips matrix (FEAT-601 AC6)."""
from __future__ import annotations

import pytest

from parrot.knowledge.manuals.tips import add_tip, relink_tips, retire_tip

from .._support.graph import FakeGraphStore  # created by TASK-3698


def _steps(manual_id: str, rows: list[tuple[str, str | None, str]]):
    """Build Step objects (step_id, source_identity, text) with substantiated evidence."""
    # FILL IN: construct parrot.knowledge.manuals.models.Step with Extracted(value=text, evidence=Evidence(node_id="n1", quote=text, page=1))
    #          and StepIdentity(step_id=..., source_identity=..., content_hash=content_hash(text))
    raise NotImplementedError


@pytest.mark.asyncio
async def test_relink_tips_matrix() -> None:
    """Renumbered→source_identity, reworded-same-hash→content_hash, deleted→orphaned, changed torque→candidate."""
    # FILL IN: cases insert, renumber, reword, duplicate, delete, changed numeric (torque) ⇒ candidate not relink


@pytest.mark.asyncio
async def test_relink_is_idempotent() -> None:
    """Second run: only 'unchanged' outcomes, no new edges, history not re-appended."""


@pytest.mark.asyncio
async def test_relink_collects_failures() -> None:
    """A store that raises on one tip twice ⇒ tip_id in report.failed, others still processed."""


@pytest.mark.asyncio
async def test_relink_never_crosses_manuals() -> None:
    """A step of another manual with the same hash is never a target."""


@pytest.mark.asyncio
async def test_add_and_retire_tip() -> None:
    """add_tip writes tech_tip + tech_tip_on with origin=technician; retire flips active and appends history."""
```
**Why**: test names follow spec §4 (`test_relink_tips_matrix`); the extra tests split the AC6
bullets so failures point at one rule.

### FILL IN checklist
- [ ] `_text_similarity` — rapidfuzz on text; bounded by AC4 (no hash similarity)
- [ ] `_match` — fixed R1 order + same-manual restriction; bounded by AC6
- [ ] `relink_tips` — remove-then-create edges, history append once, one retry, failures collected; bounded by AC6
- [ ] `add_tip` / `retire_tip` — document + edge shapes above
- [ ] tests — full matrix incl. concurrent tip (tip added between two relink runs is left attached)

---

## Acceptance Criteria

- [ ] `relink_tips` follows source_identity → exact content_hash → candidate → orphaned; no hash similarity anywhere (AC4).
- [ ] Idempotent; matrix covers insert, renumber, reword, duplicate, delete, changed numeric, repeated run, concurrent tip, failed relink + retry, no cross-manual (AC6).
- [ ] Orphans keep `source_revision` + `history`; never deleted.
- [ ] Per-tip failures land in `RelinkReport.failed`; the function never raises for one tip.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/manuals/tips.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/manuals/test_tips.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/manuals/test_tips.py
async def test_relink_tips_matrix(): ...        # spec §4 M9
async def test_relink_is_idempotent(): ...
async def test_relink_collects_failures(): ...
async def test_relink_never_crosses_manuals(): ...
async def test_add_and_retire_tip(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3710-manual-tips-relink.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3710
- Feature: training-agent
- Implementation SHA: 3366a79b3411b73844020e6f7e47c0f92f135987
- Closed at (UTC): 2026-09-25T13:35:51+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
| supplementary_test_evidence | 120 passed, 1 skipped, 0 failed (scoped direct pytest over manuals+catalog+figures+carding+video+tips+contracts/test_ontology_domain, after review-fix commits) |
