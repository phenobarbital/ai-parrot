# TASK-3033: Immutable tenant and version-scoped evidence storage

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3025
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M4 in spec §3 and the corresponding normative §2 behavior. Covers AC4; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement tenant/contract/version/hash evidence references and staged PageIndex storage; archive derived exact node bodies and physical-page metadata without copying original binaries.
- Provide exact version/hash/node/page lookup and evidence mapping for moved nodes and unchanged excerpts; expose mapping to retirement propagation.
- Offload synchronous content-store reads, validate paths and preserve current published evidence on failure; never equate an empty quote with unchanged evidence.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/evidence.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_evidence.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377
from parrot.knowledge.pageindex.content_store import NodeContentStore  # packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| PageIndexToolkit | async create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]; delete_tree/get_tree take tree_name | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377 |
| insert_markdown | async (self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None, doc_name: Optional[str] = None) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:692 |
| import_pdf | async (self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None, with_summaries: bool = True, with_doc_description: bool = False) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:803 |
| loader_for | (self, tree_name: str) -> Callable[[str], Optional[str]]; synchronous body reader | packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py:197 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3025`: Typed contract models and standard aliases; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Tenants with identical slugs/node IDs cannot cross-read; wrong hash/version/page and traversal attempts fail.
- [ ] Archived citations resolve after refresh; a failed staging write preserves current tree and evidence.
- [ ] Moved nodes map only nonempty exact evidence; original source files remain untouched.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Tenants with identical slugs/node IDs cannot cross-read; wrong hash/version/page and traversal attempts fail.
2. Archived citations resolve after refresh; a failed staging write preserves current tree and evidence.
3. Moved nodes map only nonempty exact evidence; original source files remain untouched.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_evidence.py -q`

Store execution logs in `artifacts/logs/task-3033.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3033-contracts-versioned-evidence.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot/knowledge/contracts/evidence.py` with two
pieces. `StagingArea` splits a tenant's PageIndex storage into `published/` and
`staging/` roots: `begin()` clears only staging, `promote()` swaps the tree JSON and
content directory into place (restoring the previous pair if the swap fails), and
`discard()` drops staged data while never touching published trees or archived
evidence — deliberately not the bookstore's delete-before-reimport behaviour.
`EvidenceArchive` writes immutable derived node text per
`tenant/contract/vN-rM-<hash>` with a manifest carrying node ids and physical pages;
re-archiving the same reference raises unless `overwrite=True`. `resolve()` checks
contract, version, source hash, node existence, nonempty verbatim quote (whitespace-
normalised) and page, returning an explicit failure reason. `map_evidence()` rebinds
only nonempty exact quotes to their new node (lowest node id wins deterministically);
empty quotes map to `None` so the field stays stale. All filesystem work is offloaded
with `asyncio.to_thread` and every path segment is validated against traversal.

**Validation**: `pytest .../test_evidence.py -q` -> 30 passed (whole contracts suite
299 passed, `artifacts/logs/task-3033.log`); ruff clean. Tests cover: two tenants
reusing the same slug and node ids cannot cross-read (a foreign reference raises),
traversal/separator rejection on read and write, wrong version/hash/node/page/contract
lookups failing with distinct reasons, a historical citation still resolving after the
clause was renumbered by a refresh, immutability, only derived `.md`/`.json` reaching
the archive while the original PDF is untouched, deterministic evidence remapping, and
a failed staging write leaving the published tree and archived evidence intact.

**Deviations**: none.
