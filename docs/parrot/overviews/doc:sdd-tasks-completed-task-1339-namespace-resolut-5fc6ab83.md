---
type: Wiki Overview
title: 'TASK-1339: Cross-distribution namespace-resolution test suite'
id: doc:sdd-tasks-completed-task-1339-namespace-resolution-test-suite-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 7** of the spec — verifies the user-facing
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.google
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.openai
  rel: mentions
- concept: mod:parrot.rerankers
  rel: mentions
- concept: mod:parrot.rerankers.llm
  rel: mentions
- concept: mod:parrot.rerankers.local
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.arango
  rel: mentions
- concept: mod:parrot.stores.bigquery
  rel: mentions
- concept: mod:parrot.stores.faiss_store
  rel: mentions
- concept: mod:parrot.stores.milvus
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
---

# TASK-1339: Cross-distribution namespace-resolution test suite

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1333, TASK-1334, TASK-1335, TASK-1336
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec — verifies the user-facing
contract that imports stay byte-identical when the satellite is
installed, and that they fail with a clear ImportError when it is
not. This is the most important integration test in the feature
because it proves the load-bearing FEAT-201 promise (PEP 420 namespace
merging works) and the user-experience guard (missing-package errors
tell users what to install).

Reference: spec §3 Module 7, §5 acceptance criteria 7-8, §7
integration risks (first-of-its-kind namespace extension).

---

## Scope

Create
`packages/ai-parrot-embeddings/tests/test_namespace_imports.py` with
three test classes:

1. **`TestSatelliteInstalled`** — runs in the normal test env
   (satellite installed via `uv sync --all-packages`). Asserts every
   moved backend imports successfully AND its `__file__` resolves
   inside the satellite distribution, NOT inside `ai-parrot` core.

2. **`TestSatelliteAbsent`** — simulates absence of the satellite by
   mocking the satellite distribution out of `sys.path` (or via a
   subprocess in a temp venv that only has `ai-parrot` installed).
   Asserts that `from parrot.stores.pgvector import PgVectorStore`
   raises a clear, actionable `ImportError` whose message mentions
   `ai-parrot-embeddings[pgvector]`.

3. **`TestCorePublicSurfaceUnchanged`** — independent of satellite
   presence, asserts the host's `supported_stores` and
   `supported_embeddings` dispatch maps and the rerankers public
   surface still load and contain the expected keys.

**NOT in scope**:
- Verifying wheel layout — TASK-1338.
- Matryoshka cross-distribution test — TASK-1340.
- Touching production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/tests/test_namespace_imports.py` | CREATE | Three test classes above |
| `packages/ai-parrot-embeddings/tests/_helpers.py` | CREATE (if needed) | Helper to run import attempts in a subprocess with a pruned PYTHONPATH |

---

## Codebase Contract (Anti-Hallucination)

### Verified Module Paths and Expected Class Names

These are the (path, class) pairs the test must verify after the move:

```python
EMBEDDINGS_BACKENDS = [
    ("parrot.embeddings.google",       "GoogleEmbeddingModel"),
    ("parrot.embeddings.huggingface",  "SentenceTransformerModel"),
    ("parrot.embeddings.openai",       "OpenAIEmbeddingModel"),
]

STORE_BACKENDS = [
    ("parrot.stores.postgres",     "PgVectorStore"),
    ("parrot.stores.milvus",       "MilvusStore"),
    ("parrot.stores.arango",       "ArangoDBStore"),     # ← class name, NOT "ArangoStore"
    ("parrot.stores.bigquery",     "BigQueryStore"),
    ("parrot.stores.faiss_store",  "FAISSStore"),        # ← class name, NOT "FaissStore"
]

RERANKER_BACKENDS = [
    ("parrot.rerankers.local", "LocalCrossEncoderReranker"),
    ("parrot.rerankers.llm",   "LLMReranker"),
]
```

### Verified Host-Side Public Surface (must NOT change)

```python
# packages/ai-parrot/src/parrot/embeddings/__init__.py:14-18
supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}

# packages/ai-parrot/src/parrot/stores/__init__.py:3-10
supported_stores = {
    'postgres': 'PgVectorStore',
    'milvus': 'MilvusStore',
    'kb': 'KnowledgeBaseStore',
    'faiss_store': 'FaissStore',     # ← dispatch-dict value; preserves pre-existing mismatch
    'arango': 'ArangoStore',         # ← dispatch-dict value; preserves pre-existing mismatch
    'bigquery': 'BigQueryStore',
}

# packages/ai-parrot/src/parrot/rerankers/__init__.py:53-59
__all__ = [
    "AbstractReranker",
    "LocalCrossEncoderReranker",
    "LLMReranker",
    "RerankedDocument",
    "RerankerConfig",
]
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.stores.FaissStore` (mixed case)~~ — actual class is
  `FAISSStore`. The dispatch dict's `'faiss_store': 'FaissStore'` is a
  preserved pre-existing mismatch.
- ~~`parrot.stores.ArangoStore`~~ — actual class is `ArangoDBStore`.
  Same pre-existing mismatch.
- ~~`importlib.metadata.distributions()` filtering by namespace~~ —
  not the right API for this test. Use `module.__file__` instead.
- ~~Monkey-patching `sys.modules` to remove a single submodule~~ —
  unreliable for verifying "satellite not installed". Prefer a real
  subprocess with a clean venv (or with `PYTHONPATH` pruned of the
  satellite's `src/` dir).

---

## Implementation Notes

### Suggested helper for the "satellite-absent" subprocess

```python
# packages/ai-parrot-embeddings/tests/_helpers.py
import json
import subprocess
import sys
from pathlib import Path


def run_in_pruned_venv(snippet: str) -> tuple[int, str, str]:
    """Run a Python snippet with PYTHONPATH excluding the satellite's src/.

    Returns (returncode, stdout, stderr).

    Approach: build a clean sys.path that contains only the host's site-packages
    entry for ai-parrot (its workspace .pth file) and excludes the satellite's
    workspace entry. Then invoke a fresh Python with that PYTHONPATH.
    """
    satellite_src = (
        Path(__file__).parent.parent / "src"
    ).resolve()
    # The current PYTHONPATH that uv constructs at workspace dev time
    # may include the satellite's src. Filter it out.
    pruned = [
        p for p in sys.path
        if str(satellite_src) not in p and "ai-parrot-embeddings" not in p
    ]
    env_path = ":".join(pruned)
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        env={"PYTHONPATH": env_path, **__import__("os").environ},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr
```

### Test bodies

```python
# packages/ai-parrot-embeddings/tests/test_namespace_imports.py
import importlib

import pytest

from ._helpers import run_in_pruned_venv


EMBEDDINGS_BACKENDS = [
    ("parrot.embeddings.google",       "GoogleEmbeddingModel"),
    ("parrot.embeddings.huggingface",  "SentenceTransformerModel"),
    ("parrot.embeddings.openai",       "OpenAIEmbeddingModel"),
]
STORE_BACKENDS = [
    ("parrot.stores.postgres",     "PgVectorStore"),
    ("parrot.stores.pgvector",     "PgVectorStore"),     # shim re-export
    ("parrot.stores.milvus",       "MilvusStore"),
    ("parrot.stores.arango",       "ArangoDBStore"),
    ("parrot.stores.bigquery",     "BigQueryStore"),
    ("parrot.stores.faiss_store",  "FAISSStore"),
]
RERANKER_BACKENDS = [
    ("parrot.rerankers.local", "LocalCrossEncoderReranker"),
    ("parrot.rerankers.llm",   "LLMReranker"),
]


class TestSatelliteInstalled:
    """Default test env (uv sync --all-packages installed both)."""

    @pytest.mark.parametrize("module_path,cls_name", EMBEDDINGS_BACKENDS)
    def test_embedding_backend_imports(self, module_path, cls_name):
        mod = importlib.import_module(module_path)
        assert hasattr(mod, cls_name), f"{module_path} missing {cls_name}"
        assert "ai-parrot-embeddings" in mod.__file__, \
            f"{module_path} resolved to host, not satellite: {mod.__file__}"

    @pytest.mark.parametrize("module_path,cls_name", STORE_BACKENDS)
    def test_store_backend_imports(self, module_path, cls_name):
        mod = importlib.import_module(module_path)
        assert hasattr(mod, cls_name), f"{module_path} missing {cls_name}"
        # pgvector is the 3-line shim — its __file__ is in the satellite too
        assert "ai-parrot-embeddings" in mod.__file__, \
            f"{module_path} resolved to host, not satellite: {mod.__file__}"

    @pytest.mark.parametrize("module_path,cls_name", RERANKER_BACKENDS)
    def test_reranker_backend_imports(self, module_path, cls_name):
        mod = importlib.import_module(module_path)
        assert hasattr(mod, cls_name), f"{module_path} missing {cls_name}"
        assert "ai-parrot-embeddings" in mod.__file__, \
            f"{module_path} resolved to host, not satellite: {mod.__file__}"

    def test_lazy_rerankers_through_host_init(self):
        """The host's __getattr__ in rerankers/__init__.py still produces the satellite classes."""
        from parrot.rerankers import LocalCrossEncoderReranker, LLMReranker
        assert LocalCrossEncoderReranker.__module__ == "parrot.rerankers.local"
        assert LLMReranker.__module__ == "parrot.rerankers.llm"


class TestSatelliteAbsent:
    """In an environment without ai-parrot-embeddings, imports fail with a clear error."""

    def test_pgvector_raises_clear_error(self):
        snippet = (
            "try:\n"
            "    from parrot.stores.pgvector import PgVectorStore\n"
            "    print('UNEXPECTED_SUCCESS')\n"
            "except ImportError as e:\n"
            "    print(f'IMPORTERROR:{e}')\n"
        )
        rc, out, err = run_in_pruned_venv(snippet)
        assert rc == 0, f"subprocess crashed: {err}"
        assert out.startswith("IMPORTERROR:"), \
            f"expected ImportError when satellite is absent; got: {out!r}"
        # The error message should help the user install the satellite.
        # If the current ImportError text doesn't yet mention the install
        # instructions, file a follow-up to add a friendlier message in
        # the satellite import path. For now we assert at minimum the
        # missing-module name appears.
        assert "pgvector" in out, f"error should reference pgvector: {out!r}"


class TestCorePublicSurfaceUnchanged:
    """Independent of satellite presence: dispatch maps and rerankers __all__ are byte-identical."""

    def test_supported_embeddings_unchanged(self):
        from parrot.embeddings import supported_embeddings
        assert supported_embeddings == {
            'huggingface': 'SentenceTransformerModel',
            'google': 'GoogleEmbeddingModel',
            'openai': 'OpenAIEmbeddingModel',
        }

    def test_supported_stores_unchanged(self):
        from parrot.stores import supported_stores
        assert supported_stores == {
            'postgres': 'PgVectorStore',
            'milvus': 'MilvusStore',
            'kb': 'KnowledgeBaseStore',
            'faiss_store': 'FaissStore',
            'arango': 'ArangoStore',
            'bigquery': 'BigQueryStore',
        }

    def test_rerankers_all_unchanged(self):
        import parrot.rerankers as r
        assert set(r.__all__) == {
            "AbstractReranker",
            "LocalCrossEncoderReranker",
            "LLMReranker",
            "RerankedDocument",
            "RerankerConfig",
        }
```

### If the "absent" subprocess test is too brittle in CI

Alternative: use `importlib.util.find_spec` and patch `__path__` of
the relevant package to simulate absence. The subprocess approach is
preferred for honest user-environment fidelity.

### References in Codebase

- `packages/ai-parrot/src/parrot/rerankers/__init__.py:30-50` — the
  lazy `__getattr__` whose behavior is checked.
- `packages/ai-parrot/src/parrot/embeddings/__init__.py:14-18` —
  dispatch dict checked verbatim.
- `packages/ai-parrot/src/parrot/stores/__init__.py:1-10` — dispatch
  dict checked verbatim (mismatches preserved).

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-embeddings/tests/test_namespace_imports.py`
      exists with the three test classes.
- [ ] All `TestSatelliteInstalled` parametrized cases pass when the
      satellite is installed.
- [ ] `TestSatelliteAbsent::test_pgvector_raises_clear_error` passes
      and verifies the subprocess approach.
- [ ] All `TestCorePublicSurfaceUnchanged` cases pass.
- [ ] If a follow-up is needed to improve the user-facing ImportError
      message (the current import-machinery default may not mention
      `pip install ai-parrot-embeddings[pgvector]`), it is recorded in
      the completion note as a known limitation + a proposal for a
      small `parrot/stores/__init__.py` enhancement (NOT in scope for
      this task; just flagged).
- [ ] Test suite runs in under 90 seconds.

---

## Test Specification

The test file IS the deliverable. The acceptance criteria are the
contract.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 7 and §6 Codebase Contract.
2. **Check dependencies** — TASK-1333 through TASK-1336 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-confirm the dispatch maps
   and `__all__` lists in core.
4. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
5. **Implement** the helper + three test classes. Iterate until the
   subprocess-based "absent" test is reliable (or pivot to the
   patching approach if subprocess proves brittle on the CI runner —
   document the choice).
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: …

**Deviations from spec**: none | describe if any
