# TASK-3053: Contracts installation, deployment and operating guide

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1–2h)
**Depends-on**: TASK-3051, TASK-3052
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M12 in spec §3 and the corresponding normative §2 behavior. Covers AC7, AC12, AC13; full feature acceptance remains governed by spec §§4–5.

## Scope

- Document ai-parrot[graphindex,graphindex-postgres], existing PDF/indexing extra, loaders, embeddings[arango] and tools[office365] for enabled paths.
- Document schema-per-tenant configuration, canonical source/owner rules, O365 credentials/cursors, publication recovery, service-principal scope, tool confirmation and deployer-owned scheduler/send_result wiring.
- Explain effective versus recorded time with late amendment, verification/stale candidates, broad retirement suppression, fallback/no-text skip, callable transports and pilot exclusions.
- Describe live-test opt-in, benchmark procedure and twelve-case pilot review without claiming unexecuted acceptance.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/knowledge/contracts.md` | CREATE | Task-owned deliverable |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207
from parrot.tools.toolkit import AbstractToolkit  # packages/ai-parrot/src/parrot/tools/toolkit.py:257
from parrot_tools.o365.base import O365Tool, O365ToolArgsSchema  # packages/ai-parrot-tools/src/parrot_tools/o365/base.py:31
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| PostgresPersistence constructor | (self, dsn: Optional[str] = None, *, pool: Optional[asyncpg.Pool] = None, schema: str = "graphindex") -> None | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:226 |
| apply_update | async (self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt; independent transaction and generated commit_id | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:834 |
| list_commits / get_commit | async list_commits(self, ctx, run_id=None, agent_id=None, limit=50); async get_commit(self, ctx, commit_id) | packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:1005; packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:976 |
| Toolkit confirmation | tool_prefix: str or None; confirming_tools: frozenset of unprefixed method names; generates requires_confirmation metadata | packages/ai-parrot/src/parrot/tools/toolkit.py:257; packages/ai-parrot/src/parrot/tools/toolkit.py:686 |
| O365Tool._execute_graph_operation | async (self, client: O365Client, **kwargs) -> Any; _execute handles authentication and ToolResult | packages/ai-parrot-tools/src/parrot_tools/o365/base.py:200 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3051`: Contracts operator CLI and administrative commands; inspect its completed artifact and committed interface before use.
- `TASK-3052`: Declare approved rapidfuzz extra and refresh lock; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Commands and configuration match implemented CLI/services; installation instructions use verified extra names.
- [ ] Guide clearly separates deterministic retrieval from drafting, graph partial failure from success and automated checks from Bob signoff.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Commands and configuration match implemented CLI/services; installation instructions use verified extra names.
2. Guide clearly separates deterministic retrieval from drafting, graph partial failure from success and automated checks from Bob signoff.

Validation: `Review the document against the implemented public interfaces and the acceptance criteria below.`

Store execution logs in `artifacts/logs/task-3053.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3053-contracts-deployment-documentation.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: wrote `docs/knowledge/contracts.md` covering installation
(`ai-parrot[graphindex,graphindex-postgres]`, `ai-parrot[pdf]`, `ai-parrot-loaders`,
`ai-parrot-embeddings[arango]`, `ai-parrot-tools[office365]`, and why rapidfuzz comes
with the graphindex extra), schema-per-tenant configuration, canonical source identity
and folder owner rules with manual overrides, the 1+N carding bound with its fallback
and the explicit scanned-PDF skip, verification/refresh semantics including the four
evidence outcomes and stale candidates, **effective vs recorded time** with the
late-recorded amendment example, publication (why `publish` delegates to
`publish_all`, why a partial target failure is not success, outbox recovery without
duplicate versions, retraction preserving history), the shared answer gate with
deterministic retrieval separated from drafting, broad retirement suppression, the
O365 delta tools and the three scheduler-free jobs with the cursor rule and
deployer-owned `@schedule`/`send_result` wiring, the full CLI with exit codes and the
`--confirm` rule, live-test opt-in, the benchmark pointer, pilot exclusions and the
known ArangoDB upsert limitation.

**Validation**: verified against the implementation rather than from memory — a script
checked that every extra named exists in the three pyprojects, that every public
symbol referenced imports, and that **all 10 documented CLI invocations parse with the
real `build_parser()`**; the confirming-command list matches
`CONFIRMING_COMMANDS`. The guide states plainly that automated tests are not pilot
acceptance and points at the twelve-case signoff document.

**Deviations**: none.
