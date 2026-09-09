# TASK-3050: Deterministic renewal and obligation reports

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3049, TASK-3047
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M11 in spec §3 and the corresponding normative §2 behavior. Covers AC12; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement renewals_report with nonoverlapping inclusive 30/60/90-day notice/expiration buckets and obligations_digest for fixed dates/recognized anchored recurrences.
- Inject today, trusted service principal, recipient scope and dependencies; query SQL/Python without LLM or Arango requirement for core results.
- Surface unrecognized/unanchored recurrence for review. Optional prose uses fixed draft/verifier/audit runner; return data for deployer scheduling and send_result only.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/jobs.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_report_jobs.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
# No existing integration import is required; standard-library typing and declared Pydantic v2 are available.
# Contracts interfaces are NEW dependency outputs, not verified pre-existing imports.
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| build_legal_librarian_crew | Inspection artifact; explicitly not executable via run_flow | packages/ai-parrot-tools/src/parrot_tools/legal/librarian/flow.py:494 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| Watcher jobs | async renewals_report(...), obligations_digest(...), ingest_delta(...); dependencies, principal, dates and source configs injected |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3049`: Durable O365 delta ingestion job; inspect its completed artifact and committed interface before use.
- `TASK-3047`: Executable fixed contracts answer runner; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Frozen boundary fixtures exercise notice fallback, null dates, deterministic buckets and known/unknown recurrences.
- [ ] Recipient scope excludes unauthorized contracts; deterministic report works with Arango/LLM unavailable.
- [ ] Optional prose passes shared gate, and neither job imports scheduler nor performs implicit delivery.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Frozen boundary fixtures exercise notice fallback, null dates, deterministic buckets and known/unknown recurrences.
2. Recipient scope excludes unauthorized contracts; deterministic report works with Arango/LLM unavailable.
3. Optional prose passes shared gate, and neither job imports scheduler nor performs implicit delivery.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_report_jobs.py -q`

Store execution logs in `artifacts/logs/task-3050.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3050-contracts-report-jobs.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
