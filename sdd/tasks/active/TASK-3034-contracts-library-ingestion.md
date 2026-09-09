# TASK-3034: Staged library ingestion and canonical source identity

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3029, TASK-3031, TASK-3032, TASK-3033
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M4 in spec §3 and the corresponding normative §2 behavior. Covers AC2, AC4; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement ContractLibrary.add_contract/add_folder with source validation, temporary bytes/hash, URI-first identity and explicit IngestReport outcomes.
- Skip unchanged SHA; same bytes at another URI resolve to existing card and retain canonical URI. Enforce SQL slug uniqueness and stable source identity.
- Build staging trees for MD/TXT/DOCX/text-PDF, deterministic heading-less/no-LLM sectioning and physical-page anchors; skip no-text PDF explicitly.
- Apply most-specific folder owner/department rules, assemble card and initial immutable snapshot, then persist revision/outbox with consistent evidence publication; recover staging failures without deleting current data.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/library.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_ingestion.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc  # packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| slugify / unique_slug | slugify(text: str) -> str; unique_slug(base: str, taken: set[str]) -> str | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49 |
| derive_toc | derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str] | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:88 |
| Bookstore._docx_to_markdown | async (self, path: Path) -> str; lazy MSWordLoader import, conversion via asyncio.to_thread | packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:1073 |
| PageIndexToolkit | async create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]; delete_tree/get_tree take tree_name | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:377 |
| insert_markdown | async (self, tree_name: str, markdown: str, parent_node_id: Optional[str] = None, doc_name: Optional[str] = None) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:692 |
| import_pdf | async (self, tree_name: str, pdf_path: str, parent_node_id: Optional[str] = None, with_summaries: bool = True, with_doc_description: bool = False) -> dict[str, Any] | packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:803 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| ContractLibrary | async add_contract(source, *, source_uri, force=False), add_folder(folder, *, recursive=False, force=False), verify_card(contract_id, fields, *, user, expected_revision), refresh_card(contract_id, *, source=None), relate_contracts(contract_ids=None, *, force=False); ingest returns card-or-null + added/updated/skipped and an explicit reason in the report |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3031`: Deterministic assembly, status and parent resolution; inspect its completed artifact and committed interface before use.
- `TASK-3032`: Public asynchronous DOCX conversion helper; inspect its completed artifact and committed interface before use.
- `TASK-3033`: Immutable tenant and version-scoped evidence storage; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Synthetic format fixtures cover heading-less inputs, recursive folders, no-text skip, duplicate URI/hash and no-model fallback.
- [ ] Failure between staging and catalog publication preserves a usable previous card/evidence pair.
- [ ] Unchanged content creates no revision; report distinguishes added/updated/skipped/error and pending publication.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Synthetic format fixtures cover heading-less inputs, recursive folders, no-text skip, duplicate URI/hash and no-model fallback.
2. Failure between staging and catalog publication preserves a usable previous card/evidence pair.
3. Unchanged content creates no revision; report distinguishes added/updated/skipped/error and pending publication.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_ingestion.py -q`

Store execution logs in `artifacts/logs/task-3034.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3034-contracts-library-ingestion.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
