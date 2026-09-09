# TASK-3049: Durable O365 delta ingestion job

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3039, TASK-3040, TASK-3042, TASK-3048
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M11 in spec §3 and the corresponding normative §2 behavior. Covers AC9, AC12; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement scheduler-free ingest_delta with injected delta tools, library, publishers, trusted service principal and configured source scope.
- Map O365 pages to core report/source records without core importing parrot_tools. Commit final cursor only after every item is durable or explicitly skipped; retain old cursor on failure for idempotent replay.
- Track source/drive/item identity through rename/move and duplicate SHA; tombstones retract projections while retaining history/original source.
- Handle 410 reset/rescan and partial enumeration without mass deletion; record no-text skip and per-target publication state. No schedule decorators or automatic send.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/jobs.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_ingest_delta.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot_tools.o365.base import O365Tool, O365ToolArgsSchema  # packages/ai-parrot-tools/src/parrot_tools/o365/base.py:31
from parrot.interfaces.o365 import O365Client  # packages/ai-parrot/src/parrot/interfaces/o365.py:339
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| O365Tool._execute_graph_operation | async (self, client: O365Client, **kwargs) -> Any; _execute handles authentication and ToolResult | packages/ai-parrot-tools/src/parrot_tools/o365/base.py:200 |
| O365Client.graph_client | Authenticated GraphServiceClient property | packages/ai-parrot/src/parrot/interfaces/o365.py:339 |

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

- `TASK-3039`: Recoverable GraphIndex temporal revision publisher; inspect its completed artifact and committed interface before use.
- `TASK-3040`: Explicit bounded relation judgements and invalidation; inspect its completed artifact and committed interface before use.
- `TASK-3042`: SharePoint and OneDrive delta tools and registration; inspect its completed artifact and committed interface before use.
- `TASK-3048`: ReAct ContractsAgent with shared release gate; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Fake Graph-to-library integration covers paging, duplicate item, rename/move, tombstone, unchanged SHA and interrupted batch replay.
- [ ] Final cursor advances only after durable outcomes; 410 partial listing never retracts unseen items en masse.
- [ ] Service-principal/recipient scope is enforced and job imports no scheduler.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Fake Graph-to-library integration covers paging, duplicate item, rename/move, tombstone, unchanged SHA and interrupted batch replay.
2. Final cursor advances only after durable outcomes; 410 partial listing never retracts unseen items en masse.
3. Service-principal/recipient scope is enforced and job imports no scheduler.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_ingest_delta.py -q`

Store execution logs in `artifacts/logs/task-3049.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3049-contracts-delta-ingest-job.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot_tools/contracts/jobs.py` with `ingest_delta` —
a plain async callable with every dependency injected (library, delta tool, source
scope, trusted service principal, optional retrieval/graph loader/temporal publisher/
downloader/clock). It authorizes the principal **before** enumerating, maps O365 delta
items onto core `SourceItem`/`IngestReport` records (core never imports parrot_tools),
records stable drive/item identity so a rename keeps the same contract, retracts
tombstoned contracts through the graph loader while keeping catalog history, archived
evidence and the original document, and skips folders and undownloadable items with
explicit reasons. **Cursor discipline**: the final delta link is committed only when
the enumeration completed *and* every item was durably processed or explicitly
skipped; otherwise the old cursor is retained so the batch replays idempotently. A 410
sets `rescan_required` and retracts nothing — a partial listing is never mass
deletion.

**Validation**: `pytest .../test_ingest_delta.py -q` -> 13 passed (whole contracts
tools suite 151 passed, `artifacts/logs/task-3049.log`); ruff clean. Coverage: full
batch + cursor commit, source-item identity, unchanged SHA creating no revision,
duplicate item in one batch, rename keeping one contract, tombstone retraction with
surviving history/evidence, folder/undownloadable skips, interrupted batch retaining
the cursor and replaying cleanly, truncated enumeration committing nothing, 410 rescan
leaving every card active, unauthorized principal blocking enumeration entirely,
temporal drain wiring, and an AST proof that the module imports no scheduler, carries
no schedule decorator and calls no send/notify API.

**Deviations**: deepened the shared `FakeCatalog` test double (owned by TASK-3043) so
`upsert` tracks revisions and version history — the shallow version reported every
write as `created`, which would have made this task's rename and tombstone assertions
pass vacuously.
