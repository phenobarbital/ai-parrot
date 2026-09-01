# TASK-2672: Ingest orchestrator (§27, chronological, catch-up, §34 gate)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2664, TASK-2665, TASK-2666, TASK-2667, TASK-2668, TASK-2669, TASK-2670, TASK-2671
**Assigned-to**: unassigned

---

## Context

Spec Module 6. Wires the §27 24-step pipeline end-to-end and enforces the §34 gate.

## Scope

- `runner.py` (+ `nodes/__init__.py`): implement the §27 ordered flow using the nodes from prior tasks.
- **Sort the whole batch oldest→newest by `meeting_date`** (G5) — applies to hourly runs and large post-downtime catch-ups; process in bounded chunks (`WIKI_KB_INGEST_LIMIT`).
- Order per §27: read context (§12) → dedup gate → identify existing knowledge → summary → classify → transcript fallback → **detect contradictions first (§9/§22)** → choose destination → move bundle + verify → meeting page → project structure/reconcile → entities → concepts → daily → indexes → overview → registry mirror → log → **archive as step 22** (invoke TASK-2673) → §34 validation → §35 change summary → GraphIndex rebuild (TASK-2671).
- **§34 gate**: on failure roll back Claude-created compiled changes (never raw), queue a review item, write NO success registry/log entry.

**NOT in scope**: the node internals (owned by their tasks).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/runner.py` | MODIFY | full §27 pipeline |
| `.../wiki_ingest/nodes/__init__.py` | MODIFY | node wiring |
| `.../wiki_ingest/agent.py` | MODIFY | `ingest()` calls the runner |
| `packages/ai-parrot/tests/integration/test_wiki_kb_ingest.py` | CREATE | e2e + chronological + rollback tests |

## Codebase Contract (Anti-Hallucination)
### Notes
- Uses `validate()` from TASK-2661, all nodes from TASK-2663–2671, vault from TASK-2662.
- Model the DAG on `parrot/flows/dev_loop/runner.py`.
### Does NOT Exist
- ~~a revision step~~ — removed (R3).

## Implementation Notes
- Chronological ordering is load-bearing for §19 supersession — sort before processing.
- §35 summary printed after every run (created/updated/moved/skipped/contradicted/review/validation).

## Acceptance Criteria
- [ ] E2E: a Raw/Incoming bundle produces meeting + project + entities + concepts + daily + indexes + registry mirror + GraphIndex rebuild; §34 passes.
- [ ] A multi-meeting batch is processed oldest→newest.
- [ ] §34 failure rolls back compiled changes, queues a review item, writes no log/registry entry, leaves raw untouched.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_ingest_end_to_end(): ...
async def test_chronological_batch(): ...
async def test_validation_failure_rolls_back(): ...
```
