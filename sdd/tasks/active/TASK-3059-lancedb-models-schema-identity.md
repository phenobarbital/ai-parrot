# TASK-3059: Define LanceDB configuration, schema and identities

**Feature**: FEAT-542 - Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3057
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Independent of manifest packaging and coordinator implementation after the gate. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC3, AC4, AC5

---

## Context

M1 data contract shared by persistence, search and the origin. Must freeze names/types before those tasks.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Implement LanceDBConfig, version-1 manifest and LanceDBHybridHit exactly as reconciled spec; distinguish explicitly supplied creation defaults from manifest-derived reopen settings.
- **Open question gating this contract — spec §8 Q6 (raised by design research S2, spec §9).** Whether `LanceDBHybridHit` must also carry the per-leg vector and lexical component scores/ranks alongside the fused RRF relevance is undecided by the user. This task freezes that model for every downstream module, so: implement the single fused score plus `score_kind`/`higher_is_better` as specified, and do **not** invent component fields on your own. If TASK-3057's gate recorded that the pinned SDK exposes pre-fusion `_distance`/`_score` columns on a hybrid query, say so in the completion note so the question can be decided cheaply; if Q6 has been answered "yes" by the time you start, add the fields then rather than retrofitting after M2–M4 consume the model.
- Build fixed Arrow row schema with original document, float32 vector, canonical JSON and nullable typed metadata projections. Validate reserved fields, finite numbers, dimensions and supported JSON types.
- Implement ID precedence/conflict checks, canonical SHA-256 fallback calculated before augmentation, and collection-UUID namespaced result IDs.
- Add deterministic provider and corpus fixtures including ZXQ731, semantic-only match, two sources, null/absent fields, parents, contradictory markers and cross-collection ID overlap. Freeze pure helper signatures in the completion note.

**NOT in scope**: SDK I/O, query execution, runtime locks, source document mutation and backend registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_models.py` | CREATE | Pydantic configuration, manifest, hybrid hit, schema and pure identity helpers |
| `packages/ai-parrot-embeddings/tests/test_lancedb_models.py` | CREATE | Strict model/schema/identity tests |
| `packages/ai-parrot-embeddings/tests/lancedb_fixtures.py` | CREATE | Deterministic 8-D provider and 24-document corpus for store tests |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/stores/models.py:13
from parrot.models.stores import SearchResult  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |

### Does NOT Exist

- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Independent of manifest packaging and coordinator implementation after the gate. Do not import the tools distribution or eagerly import lancedb.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3059-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Acceptance Criteria

- [ ] U1 configuration/schema matrix passes with strict typing, no silent coercion or inferred first-row schema.
- [ ] Canonical IDs are reproducible and unrelated collections cannot collide on local ID alone.
- [ ] Hybrid payload remains backend-owned with explicit RRF direction and no distance alias.
- [ ] Fixtures require no network/downloads and helper contracts are documented for dependent tasks.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_config_explicit_and_manifest_defaults` | Reopen doesn't accidentally overwrite persisted dimension/projection/settings. |
| `test_json_projection_and_hybrid_score_model` | Roundtrip nested JSON; reject invalid fields; hybrid has no distance alias. |
| `test_stable_identity_and_collection_namespace` | Deterministic IDs, aligned explicit IDs, conflict/duplicate validation and collection isolation. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_models.py -v
```

These are test contracts, not executed test results or placeholder production implementations. Use pytest-asyncio for async cases, temporary directories for datasets, bounded subprocess joins, and explicit process barriers for race tests. Reuse the deterministic 8-D fixture unless real local model evidence is explicitly required. Required feature tests may not all skip just because the SDK or assets were omitted.

---

## Agent Instructions

1. Read the spec and the approved-answer precedence in this task.
2. Work only inside the FEAT-542 feature worktree. Verify dependency tasks are `done` in `sdd/tasks/index/lancedb-vector-store.json` and their task files are under `sdd/tasks/completed/`.
3. Re-verify every needed import/signature and dependency-produced helper before writing code.
4. Update only this task entry in `sdd/tasks/index/lancedb-vector-store.json` to `in-progress`, with assignment/start timestamps. Never use the historical monolithic index.
5. Outline the implementation plan and uncertainties, then implement within the listed file ownership. Preserve unrelated work.
6. Run all task acceptance checks and save logs; unresolved gate failures prevent completion.
7. Move this task to `sdd/tasks/completed/TASK-3059-lancedb-models-schema-identity.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
