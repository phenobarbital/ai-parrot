# TASK-3058: Package the optional LanceDB dependency

**Feature**: FEAT-542 - Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h) — target 1.5 hours
**Depends-on**: TASK-3057
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Can run alongside schema and coordinator work after the gate; exclusive ownership of the embeddings manifest and uv.lock.. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC1

---

## Context

M5 dependency delivery, deliberately early so store work uses a resolved SDK instead of undocumented imports.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Add the exact release proven by TASK-3057 to a new lancedb optional extra and the existing all aggregator.
- Generate uv.lock with the normal resolver; preserve the core Arrow floor and unrelated dependency choices. Report unavoidable conflicts before broad changes.
- Test the extra's declaration/resolution and verify a minimal core/tools environment does not acquire the SDK through this addition. Keep class import checks for registration task.

**NOT in scope**: Core dispatch, backend/origin code, provider-package changes and graph relocation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/pyproject.toml` | MODIFY | New lancedb extra and existing all aggregator |
| `uv.lock` | MODIFY | Generated compatible workspace resolution |
| `packages/ai-parrot-embeddings/tests/test_lancedb_packaging.py` | CREATE | Manifest and optional-install contract checks |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
import importlib  # packages/ai-parrot-embeddings/tests/test_store_backends_present.py:2
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot-embeddings/pyproject.toml:10` | requires-python >=3.11; optional dependencies at :32; backend extras at :62; all aggregator at :97. No LanceDB declaration. |
| `packages/ai-parrot/pyproject.toml:157` | Core pyarrow>=25.0; existing faiss-cpu at :163, rustworkx at :169 and aiosqlite at :172. |
| `uv.lock:1` | uv-generated workspace lockfile; requires-python >=3.11 and Linux supported markers. Regenerate with the resolver, not manual package entries. |
| `.github/workflows/ci.yml:1` | Existing monorepo CI uses checkout/setup-python/setup-uv and explicit workspace/test commands; a dedicated new workflow must not silently skip SDK-present tests. |

### Does NOT Exist

- No existing lancedb optional extra or resolved SDK contract; TASK-3057 supplies version/API evidence.
- No satellite parrot/stores/__init__.py may be created; core owns namespace extension.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Can run alongside schema and coordinator work after the gate; exclusive ownership of the embeddings manifest and uv.lock.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3058-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Acceptance Criteria

- [ ] Optional lancedb and all extras resolve with the verified SDK and existing workspace constraints.
- [ ] No SDK dependency is added to core or tools base requirements.
- [ ] Packaging tests pass and generated lock changes are explained.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_lancedb_extra_is_optional` | SDK appears only in the intended optional dependency graph. |
| `test_lancedb_extra_uses_verified_release` | Declared version matches gate evidence and lock resolution. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_packaging.py packages/ai-parrot-embeddings/tests/test_lancedb_sdk_contract.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3058-lancedb-optional-dependency.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
