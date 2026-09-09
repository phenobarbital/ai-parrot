# TASK-3032: Public asynchronous DOCX conversion helper

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1–2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M3 in spec §3 and the corresponding normative §2 behavior. Covers AC2, AC13; full feature acceptance remains governed by spec §§4–5.

## Scope

- Extract public async docx_to_markdown(path: Path) -> str in bookstore/library.py; existing Bookstore._docx_to_markdown delegates.
- Preserve lazy MSWordLoader import, asyncio.to_thread conversion, exception behavior and empty-content checks. This task alone owns bookstore/library.py.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_docx_helper.py` | CREATE | Focused verification / fixtures |

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
| Bookstore._docx_to_markdown | async (self, path: Path) -> str; lazy MSWordLoader import, conversion via asyncio.to_thread | packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1073 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- Public docx_to_markdown does not exist yet; the existing private helper is asynchronous.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- No feature prerequisites; preserve the independent scope.

## Acceptance Criteria

- [ ] Public helper and existing private method return identical markdown and raise equivalent conversion/empty-content errors.
- [ ] Missing ai-parrot-loaders remains an actionable lazy error; affected existing bookstore DOCX regressions pass.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Public helper and existing private method return identical markdown and raise equivalent conversion/empty-content errors.
2. Missing ai-parrot-loaders remains an actionable lazy error; affected existing bookstore DOCX regressions pass.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_docx_helper.py -q`

Store execution logs in `artifacts/logs/task-3032.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3032-contracts-public-docx-helper.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
