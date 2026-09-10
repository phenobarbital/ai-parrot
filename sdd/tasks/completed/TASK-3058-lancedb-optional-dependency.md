# TASK-3058: Package the optional LanceDB dependency

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
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

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived from
> the spec's §2 New Public Interfaces and re-verified against the Codebase Contract above
> when this task was written. This is NOT the full implementation: business-logic branches,
> edge cases and test bodies are `FILL IN` stubs by design. Never change a signature, class
> name, or file path the blueprint fixes.

### Steps (in order)
1. Add the `lancedb` extra next to the other backend extras — *why*: the file groups vector-store backends together under the "Vector-store backends (TASK-1335)" comment, and a stray extra elsewhere breaks that grouping.
2. Add `lancedb` to the `all` aggregator — *why*: `pip install ai-parrot[all]` must pull it, per spec §2 "Configuration and Compatibility".
3. Regenerate `uv.lock` from the workspace root, never by hand — *why*: a hand-edited lock is not reproducible and will not match CI.
4. Assert the manifest contract in tests rather than the installed environment — *why*: the packaging test must pass whether or not the extra is installed (AC1).

### `packages/ai-parrot-embeddings/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'bigquery = [' packages/ai-parrot-embeddings/pyproject.toml)
# AFTER — insert below the `bigquery = [ ... ]` block, before `faiss = []` (verified: packages/ai-parrot-embeddings/pyproject.toml:73)
lancedb = [
    "lancedb==0.38.0",  # FILL IN: use the exact pin TASK-3057's gate resolved — bounded by AC1
]
```
**Why**: the pin is exact, not a floor, because spec §7 requires a gated release rather than "whatever resolves today". If TASK-3057 moved the pin, this value moves with it — do not leave `0.38.0` here if the gate chose otherwise.

### `packages/ai-parrot-embeddings/pyproject.toml` (MODIFY — aggregator)
```toml
# occurrences: 1 (verified: grep -c 'all = [' packages/ai-parrot-embeddings/pyproject.toml)
# REPLACE the single line inside the `all = [ ... ]` block (verified: packages/ai-parrot-embeddings/pyproject.toml:98)
    "ai-parrot-embeddings[huggingface,google,openai,pgvector,milvus,arango,bigquery,faiss,chroma,lancedb,reranker-local,reranker-llm,multimodal]",
```
**Why**: `lancedb` is inserted after `chroma` so the list keeps its existing embeddings-then-stores-then-rerankers order. Every other name in that string must survive verbatim — dropping one silently un-installs a backend for every `[all]` user.

### `uv.lock` (MODIFY)
```bash
# occurrences: n/a — this is a fully generated file with no anchor line to attach to;
#   the "block" below is the command that regenerates it, not an edit to apply.
# Generated file — do NOT hand-edit. Regenerate from the workspace root:
uv lock
# then confirm the new backend actually resolved, and that nothing else moved:
git diff --stat uv.lock
```
**Why**: a hand-edited lock is not reproducible and will diverge from what CI resolves. If
`uv lock` pulls the pin but also bumps unrelated packages, stop and report it — spec §7 says
not to downgrade `pyarrow` (core pins `>=25.0` at `packages/ai-parrot/pyproject.toml:157`)
merely to force LanceDB to resolve. A resolution conflict here is a TASK-3057 gate failure,
not something to solve by loosening a constraint.

### `packages/ai-parrot-embeddings/tests/test_lancedb_packaging.py` (CREATE)
```python
"""Manifest contract for the optional LanceDB extra (FEAT-542, AC1).

Reads pyproject.toml directly: these assertions must hold whether or not the
extra is installed in the running environment.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def extras() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]


def test_lancedb_extra_declares_exact_pin(extras):
    """The lancedb extra exists and pins one exact version."""
    # FILL IN: assert the extra exists and every requirement uses '==' — bounded by
    # spec §7 "Version/platform compatibility" (no floors for this backend)
    raise NotImplementedError


def test_all_aggregator_includes_lancedb_without_dropping_backends(extras):
    """The all extra gains lancedb and keeps every pre-existing name."""
    # FILL IN: assert the aggregator string contains lancedb AND each of
    # huggingface, google, openai, pgvector, milvus, arango, bigquery, faiss, chroma,
    # reranker-local, reranker-llm, multimodal — bounded by AC1
    raise NotImplementedError


def test_importing_core_does_not_require_the_sdk():
    """parrot.stores imports cleanly with no lancedb installed."""
    # FILL IN: import parrot.stores in a subprocess with lancedb blocked from sys.modules
    # — bounded by AC1 (unrelated core/tools imports work without the SDK)
    raise NotImplementedError
```
**Why this shape**: reading the manifest with `tomllib` rather than inspecting installed distributions is what makes these tests environment-independent — the whole point of AC1 is that the default suite passes without the extra. The third test is the one that actually catches an eager `import lancedb` sneaking into `parrot/stores/__init__.py`.

### FILL IN checklist
- [ ] `pyproject.toml::lancedb` — the exact pin from TASK-3057's gate; bounded by AC1
- [ ] `test_lancedb_packaging.py::test_lancedb_extra_declares_exact_pin` — exact-pin assertion; bounded by spec §7
- [ ] `test_lancedb_packaging.py::test_all_aggregator_includes_lancedb_without_dropping_backends` — full name list; bounded by AC1
- [ ] `test_lancedb_packaging.py::test_importing_core_does_not_require_the_sdk` — subprocess import guard; bounded by AC1
- [ ] `uv.lock` — regenerated via `uv lock` from the workspace root, never hand-edited

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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Added `lancedb = ["lancedb==0.38.0"]` extra (TASK-3057's gated pin) to `packages/ai-parrot-embeddings/pyproject.toml`, inserted `lancedb` into the `[all]` aggregator preserving every other name. Ran `uv lock` from the workspace root: resolved cleanly, added exactly 4 packages (`lancedb`, `deprecation`, `lance-namespace`, `lance-namespace-urllib3-client`) with no other package version changes — core `pyarrow>=25.0` floor untouched. Wrote `packages/ai-parrot-embeddings/tests/test_lancedb_packaging.py` (3 tests, all pass: `uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_packaging.py -v`, log at `artifacts/logs/TASK-3058-lancedb.log`). `ruff check` clean.
**Deviations from spec**: `uv.lock` is NOT committed. The task's Codebase Contract listed `uv.lock:1` as an existing tracked file, but `git log -- uv.lock` shows it was deliberately removed and gitignored repo-wide (commit `4ffd761b84 "Delete uv.lock"`, `.gitignore:258`) — a repo-level policy change that predates this task and is out of this task's scope to reverse. The regenerated lockfile was verified locally (see above) but only the two manifest files are committed. This is a stale-contract finding, not a scope decision made here; downstream tasks/CI should regenerate `uv.lock` via `uv lock`/`uv sync` rather than expect a committed copy.
