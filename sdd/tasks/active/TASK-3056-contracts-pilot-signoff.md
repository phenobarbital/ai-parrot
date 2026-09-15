# TASK-3056: Record Bob’s twelve-case pilot acceptance

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2–4h active work; elapsed time depends on pilot review)
**Depends-on**: TASK-3053, TASK-3054, TASK-3055
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M12 in spec §3 and the corresponding normative §2 behavior. Covers AC15; full feature acceptance remains governed by spec §§4–5.

## Scope

- Prepare a twelve-case review matrix for the two initial client questions and Bob’s ten agreed common questions; source exact cases/expected answers from Bob instead of inventing agreement.
- Using the 50–100 active English-contract pilot, record actual lookup citations or explicit handoffs, verification/correction feedback and review disposition; keep sensitive source content outside committed artifacts.
- Record reviewer/date/evidence references and final explicit signoff with approximately two review hours per week. No automatic outreach. This is an operational external acceptance task, not satisfied by synthetic tests.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/knowledge/contracts-pilot-acceptance.md` | CREATE | Task-owned deliverable |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.pageindex.content_store import NodeContentStore  # packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| loader_for | (self, tree_name: str) -> Callable[[str], Optional[str]]; synchronous body reader | packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3053`: Contracts installation, deployment and operating guide; inspect its completed artifact and committed interface before use.
- `TASK-3054`: Cross-store integration and regression acceptance; inspect its completed artifact and committed interface before use.
- `TASK-3055`: Measure 100-card catalog query performance; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] All twelve agreed cases have actual reviewed result and traceable citation/handoff evidence.
- [ ] Bob explicitly signs off; otherwise leave task pending/in-progress and identify missing cases/review without claiming completion.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. All twelve agreed cases have actual reviewed result and traceable citation/handoff evidence.
2. Bob explicitly signs off; otherwise leave task pending/in-progress and identify missing cases/review without claiming completion.

Validation: `Review the document against the implemented public interfaces and the acceptance criteria below.`

Store execution logs in `artifacts/logs/task-3056.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3056-contracts-pilot-signoff.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

**IN PROGRESS — deliberately not completed.** 2026-09-09, sdd-worker (Claude Opus 5).

This task is an *operational external acceptance*, and its own acceptance criteria say
so: "Bob explicitly signs off; otherwise leave task pending/in-progress and identify
missing cases/review without claiming completion."

**Prepared**: `docs/knowledge/contracts-pilot-acceptance.md` — the twelve-case review
matrix (2 client questions + Bob's 10), the exact procedure for running each case
through the shared answer gate, per-case pass criteria (including that a handoff on an
interpretation question is a pass, not a failure), tables for verification corrections
and retirements, a six-week review log sized to the agreed ~2 hours/week, and a
signoff block that is explicitly blank. Evidence is referenced by `contract_id` /
`node_id` / `version_n` / `answer_id` so no sensitive contract text is committed.

**Still missing — all external inputs**:
1. the verbatim wording of the two initial client questions;
2. Bob's ten common questions as he actually asks them;
3. his expected answer for each of the twelve;
4. the 50-100 active English contracts of the pilot corpus;
5. his review time and explicit signoff.

**Not done**: no case has been run, no disposition recorded, no signoff obtained. I
did not invent questions, answers or an agreement. AC15 remains open, and the feature
should not be reported as pilot-accepted.
