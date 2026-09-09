# TASK-3031: Deterministic assembly, status and parent resolution

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3030, TASK-3052
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M3 in spec §3 and the corresponding normative §2 behavior. Covers AC2; full feature acceptance remains governed by spec §§4–5.

## Scope

- Complete contract-specific assembly with stable party/signatory/obligation IDs, alias normalization, provenance input paths and injected today.
- Derive notice_deadline and next_renewal_date exactly as specified. Apply status precedence: incoming supersedes, human-confirmed elapsed termination, expired nonrenewing, active effective, unsigned draft, unknown.
- Resolve SOW/order_form to MSA and amendments to referenced base using same counterparty and normalized rapidfuzz similarity >=0.85; multiple qualifying candidates leave parent null and stale_fields populated.
- Lazily load approved rapidfuzz extra with actionable missing-dependency errors; never infer termination from a clause.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py` | MODIFY | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_derivations.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc  # packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| slugify / unique_slug | slugify(text: str) -> str; unique_slug(base: str, taken: set[str]) -> str | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49 |
| derive_toc | derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str] | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:88 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3030`: Bounded evidenced header and obligation extraction; inspect its completed artifact and committed interface before use.
- `TASK-3052`: Declare approved rapidfuzz extra and refresh lock; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Frozen dates exercise expiration boundary, missing dates, renewal, explicit termination and supersession precedence.
- [ ] Parent fixtures cover incompatible types/counterparties, score normalization, exact threshold and ambiguity.
- [ ] Rule provenance identifies source paths; assembly never elevates unsupported draft evidence.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Frozen dates exercise expiration boundary, missing dates, renewal, explicit termination and supersession precedence.
2. Parent fixtures cover incompatible types/counterparties, score normalization, exact threshold and ambiguity.
3. Rule provenance identifies source paths; assembly never elevates unsupported draft evidence.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_derivations.py -q`

Store execution logs in `artifacts/logs/task-3031.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3031-contracts-carding-derivations.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
