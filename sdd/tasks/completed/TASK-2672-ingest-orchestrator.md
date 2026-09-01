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

### Completion Note

`runner.py`: `run_ingest(ctx)` wires every prior module into the ordered
pipeline — fetch-gate → **G5 chronological sort of the whole batch**
(`sorted(..., key=lambda m: m.meeting_date)`) → per meeting: raw bundle
(Uncategorized default) → classify → **contradiction detection against
the meeting's own summary text vs. the existing project's parsed claims**
(run here, before the meeting page renders / the project is reconciled —
per this task's own literal Scope ordering, ahead of "choose
destination"/"meeting page", not after Module 8 as the spec's Component
Diagram sketch alone might suggest — the meeting page's own future
vault path is pre-computed deterministically via `naming.
meeting_source_filename` so contradiction pages can cite it before it
exists, `queued in the same operation` per §8.1) → meeting page →
project reconcile/new-project → entities/concepts → daily synthesis →
§24 index/overview → §25 registry mirror → §34 gate → §33 log → §27 step
22 archive (lazily picked up via `try/except ImportError` — TASK-2673
lands after this task with no need to re-touch `runner.py`) → derived
GraphIndex rebuild (never blocks, wrapped in try/except).

**§34 gate**: every compiled write is snapshotted before it happens
(`_write_note`/`_PageWrite` — previous content, or `None` for a fresh
create); on failure, `_rollback()` restores/deletes every recorded write
in reverse order, a review item is queued, and — critically — neither
`registry.record_synced()` nor the `ingest` log entry are ever reached
for that meeting (both sit after the `if not outcome.validation_passed`
early-continue). Raw bytes are never part of the rollback set.

**Retroactive fix to TASK-2661's `validation.py`** (caught by this
task's own `test_ingest_chronological_batch`): `diff_guard_violations`
was originally wired as a hard §34 *failure*, but
`project_reconcile._apply_diff_guard` (TASK-2667) already reinserts any
claim the LLM's draft dropped — by the time validation runs, the Q2
invariant already holds in the rendered page. Treating every
self-healing correction as a blocking failure would make ordinary
multi-meeting reconciliation fail routinely. Moved to
`ValidationResult.warnings` instead; no existing TASK-2661 test
asserted the old (incorrect) behavior.

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_*.py
packages/ai-parrot/tests/integration/test_wiki_kb_ingest.py` (84 passed
— e2e ingest producing meeting+project+entity+concept+daily+registry-
mirror+log, chronological batch processed oldest→newest with a spy
confirming call order, §34-forced-failure rollback with raw untouched
and no log/registry entry); `ruff check` clean; `mypy` clean.
