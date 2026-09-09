# TASK-3055: Measure 100-card catalog query performance

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-3054
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M12 in spec §3 and the corresponding normative §2 behavior. Covers AC14; full feature acceptance remains governed by spec §§4–5.

## Scope

- Build deterministic 100-card synthetic fixture and reproducible warm SQL search/queue/window benchmark against explicit temporary Postgres schema.
- Record hardware, dataset/query mix, warmup, sample count and per-operation p95; exclude LLM/network-generation time. Keep detailed logs in artifacts/logs and summarized measurements in performance doc.
- Require warm p95 below 1 second for each operation; diagnose failing plans and report follow-up scope instead of silently changing acceptance threshold.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/contracts/test_catalog_performance.py` | CREATE | Focused verification / fixtures |
| `docs/knowledge/contracts-performance.md` | CREATE | Task-owned deliverable |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| PostgresPersistence constructor | (self, dsn: Optional[str] = None, *, pool: Optional[asyncpg.Pool] = None, schema: str = "graphindex") -> None | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:226 |
| apply_update | async (self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt; independent transaction and generated commit_id | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:834 |
| list_commits / get_commit | async list_commits(self, ctx, run_id=None, agent_id=None, limit=50); async get_commit(self, ctx, commit_id) | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:1005; packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:976 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3054`: Cross-store integration and regression acceptance; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Repeatable benchmark produces measured warm p95 <1s for search, verification queue and date windows.
- [ ] Report documents hardware/configuration and exact command; no fabricated measurement or skipped-service pass.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Repeatable benchmark produces measured warm p95 <1s for search, verification queue and date windows.
2. Report documents hardware/configuration and exact command; no fabricated measurement or skipped-service pass.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_catalog_performance.py -q`

Store execution logs in `artifacts/logs/task-3055.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3055-contracts-catalog-performance.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
