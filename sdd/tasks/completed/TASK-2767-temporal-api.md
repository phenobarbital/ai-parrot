# TASK-2767: Temporal plane — `as_of` / `history` / `diff`

**Feature**: FEAT-520 — GraphIndex Postgres Backend
**Spec**: `sdd/specs/graphindex-postgres-backend.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2765
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-520 — the reason this backend exists (spec D1–D5). The
bitemporal write semantics already land in TASK-2765; this task adds the
temporal READ contract: deterministic snapshot, per-concept history, and a
structured diff an LLM can consume ("what changed between t1 and t2"), never
"compare these two texts". Postgres-only in v1: the other backends do NOT
grow these methods; callers feature-detect via `hasattr`.

---

## Scope

- Add Pydantic models `NodeVersionRow` and `TemporalDiff` (spec §2 Data
  Models — copy the field lists verbatim) in `persist_postgres.py` or a
  small sibling `pg_models.py`.
- Add to `PostgresPersistence`:
  - `as_of(ctx, t: datetime) -> tuple[list[UniversalNode], list[UniversalEdge]]`
    — snapshot read: versions with `validity @> $t` AND edges with
    `validity @> $t`; rehydrates the same models as `load_graph` (a caller
    can swap `load_graph()` for `as_of(t)` transparently).
  - `history(ctx, concept_id: str) -> list[NodeVersionRow]` — all versions
    ordered by `lower(validity)`, including closed ones; `[]` for unknown id.
  - `diff(ctx, concept_id: str, t1: datetime, t2: datetime) -> TemporalDiff`
    — version rows closed/opened between t1 and t2 (range operators `&&`,
    comparison on bounds) + incident edges valid at t2 but not t1
    (`edges_added`) and valid at t1 but not t2 (`edges_removed`).
- Ensure `load_graph` and `as_of(now())` return identical results (test).
- Verify (once, recorded in the test or a docstring) that current-path
  queries plan on the partial `upper_inf(validity)` indexes (spec D3
  acceptance criterion — `EXPLAIN` in a live-gated test that asserts the
  index name appears in the plan).

**NOT in scope**: toolkit tools (TASK-2773), hybrid retrieval's `as_of` leg
(TASK-2771 — it reuses the same predicate), `valid_from` extraction from
sources (out of spec scope — OQ5, legal ingest).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` | MODIFY | temporal methods + models |
| `packages/ai-parrot/tests/knowledge/graphindex/test_temporal_postgres.py` | CREATE | as_of/history/diff tests, live-gated |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge  # schema.py:149, :184
from parrot.knowledge.ontology.schema import TenantContext
# NodeVersionRow / TemporalDiff — created by THIS task (spec §2 Data Models is normative):
#   NodeVersionRow: version_id, concept_id, valid_from, valid_to(None=open), tx_from,
#                   title, summary, body, body_ref, provenance, derived
#   TemporalDiff:   concept_id, t1, t2, version_changes, edges_added, edges_removed
```

### Existing Signatures to Use
```python
# persist_postgres.py (TASK-2765) — reuse its row→model rehydration helpers
async def load_graph(self, ctx) -> tuple[list[UniversalNode], list[UniversalEdge]]
# DDL (TASK-2764): node_versions.validity tstzrange, EXCLUDE constraint,
#   nv_validity GiST index, nv_current partial index WHERE upper_inf(validity)
```

### Does NOT Exist
- ~~`as_of`/`history`/`diff` on `SQLitePersistence`/`GraphIndexPersistence`/
  `BaseWikiStore`~~ — Postgres-only in v1; do NOT touch the other backends.
- ~~a `versions[]` array column~~ — history is the `node_versions` rows.
- ~~timezone-naive datetimes~~ — all params are `timestamptz`; reject naive
  `datetime` inputs explicitly (raise `ValueError`).

---

## Implementation Notes

### Pattern to Follow
```sql
-- as_of snapshot (both planes of the temporal filter):
SELECT ... FROM graphindex.node_versions WHERE validity @> $1::timestamptz;
SELECT ... FROM graphindex.edges         WHERE validity @> $1::timestamptz;
-- diff edge deltas:
--   added:   validity @> t2 AND NOT validity @> t1  (src = $cid OR dst = $cid)
--   removed: validity @> t1 AND NOT validity @> t2
```

### Key Constraints
- Deterministic ordering everywhere (ORDER BY lower(validity), version_id).
- `diff` output is structured data for the LLM — no prose, no raw text bodies
  (body/body_ref pointers only).
- Exclusion-violation on ingest is TASK-2765's concern; here reads only.

### References in Codebase
- Spec §2 "Data Models" and §3 Module 4 — normative field lists.

---

## Acceptance Criteria

- [ ] `as_of(now())` ≡ `load_graph()` (test).
- [ ] `as_of(t_past)` excludes versions/edges not valid at t (test builds a
      two-version concept with a closed range).
- [ ] `history` returns contiguous, ordered ranges (test).
- [ ] `diff` reports version change + edge added + edge removed in one
      scenario (test).
- [ ] Naive datetime input → `ValueError` (test).
- [ ] `EXPLAIN` on the current-path read shows the partial index (test,
      live-gated — spec D3 criterion).
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/graphindex/test_temporal_postgres.py
async def test_as_of_now_equals_load_graph(pg_persistence, ctx): ...
async def test_as_of_past_snapshot(pg_persistence, ctx): ...
async def test_history_ordering_and_ranges(pg_persistence, ctx): ...
async def test_diff_structured_output(pg_persistence, ctx): ...
async def test_naive_datetime_rejected(pg_persistence, ctx): ...
async def test_current_path_uses_partial_index(pg_persistence, ctx): ...
```

---

## Agent Instructions

1. Read spec §2 (Data Models, DDL) and §3 Module 4.
2. Verify contract; reuse TASK-2765's rehydration helpers — do not duplicate.
3. Update index status; move to completed + note when done.

---

## Completion Note

Added `NodeVersionRow`/`TemporalDiff` Pydantic models (field lists copied
verbatim from spec §2) and `as_of`/`history`/`diff` to `PostgresPersistence`
(same file, Module 4). `as_of` reuses the TASK-2765 `_row_to_node`/
`_row_to_edge` rehydration helpers unchanged — only the WHERE predicate
differs (`validity @> $t` vs. `upper_inf(validity)`), so `as_of(now())`
and `load_graph()` are verified byte-identical. `diff`'s version-changes
predicate uses explicit bound comparisons (opened/closed strictly within
`(t1, t2]`) rather than range overlap (`&&`), matching the spec's literal
"closed/opened between t1 and t2" wording — overlap would also match
long-lived unchanged versions spanning the window. Edge deltas use the
spec's literal `validity @> t2 AND NOT validity @> t1` / inverse formula.
Naive datetimes rejected via a shared `_require_aware` guard on every
temporal entry point. `SQLitePersistence`/`GraphIndexPersistence`
untouched, per D5.

D3 EXPLAIN test: the planner may pick either the plain `nv_current`
partial index or the EXCLUDE constraint's own `(concept_id, validity)`
GiST index for `WHERE concept_id = $1 AND upper_inf(validity)` — both are
valid current-path outcomes (indexed, not a full historical scan); the
test asserts "no Seq Scan" plus "one of the two expected index names"
rather than a single hardcoded index name, documented inline as to why.

All 7 tests pass (as_of≡load_graph, past snapshot, history ordering +
contiguous ranges, unknown-concept empty history, structured diff with
version+edge deltas, naive-datetime ValueError, EXPLAIN index-scan
check). Ran the full graphindex-postgres suite together: 42/42 green.
`ruff check` clean.
