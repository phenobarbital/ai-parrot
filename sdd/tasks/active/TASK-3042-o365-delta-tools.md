# TASK-3042: SharePoint and OneDrive delta tools and registration

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3041
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in O365 worktree feat-FEAT-539-contracts-o365-delta. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M8 in spec §3 and the corresponding normative §2 behavior. Covers AC9, AC13; full feature acceptance remains governed by spec §§4–5.

## Scope

- Add DeltaSharePointFilesTool and DeltaOneDriveFilesTool backed by shared delta helper through O365Tool._execute_graph_operation and authenticated O365Client.graph_client.
- Resolve configured drive/folder identity without model-supplied endpoint expansion; expose typed pages and tombstones via normal tool result/auth lifecycle.
- Register/export in existing bundles without removing existing list/search/download/upload tools. Keep this O365 lane independent and integrate its commits before contracts delta-job work.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/src/parrot_tools/o365/__init__.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/test_o365_delta_tools.py` | CREATE | Focused verification / fixtures |

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

Existing O365 registration files re-read: `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py:15`, `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py:14`, `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py:9`, `packages/ai-parrot-tools/src/parrot_tools/o365/__init__.py:17`. Delta classes/helper do not yet exist.

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3041`: O365 drive delta pages, validation and retry helper; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Both tools preserve O365 authentication/error wrapping and produce equivalent typed continuation/deletion outcomes.
- [ ] Bundle regression retains prior tools and adds both delta tools; no contracts or scheduler import appears.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Both tools preserve O365 authentication/error wrapping and produce equivalent typed continuation/deletion outcomes.
2. Bundle regression retains prior tools and adds both delta tools; no contracts or scheduler import appears.

Validation: `uv run pytest packages/ai-parrot-tools/tests/test_o365_delta_tools.py -q`

Store execution logs in `artifacts/logs/task-3042.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3042-o365-delta-tools.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
