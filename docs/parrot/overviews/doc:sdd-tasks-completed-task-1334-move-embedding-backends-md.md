---
type: Wiki Overview
title: 'TASK-1334: Move embedding backends (google / huggingface / openai) to satellite'
id: doc:sdd-tasks-completed-task-1334-move-embedding-backends-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of the spec — relocate the three concrete
relates_to:
- concept: mod:parrot._imports
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.google
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
---

# TASK-1334: Move embedding backends (google / huggingface / openai) to satellite

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1333
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec — relocate the three concrete
embedding backends from `packages/ai-parrot/src/parrot/embeddings/` to
the satellite, and add the per-backend extras to the satellite
pyproject. The `EmbeddingRegistry._build_model` dispatcher
(`registry.py:149-178`) resolves backends by import string
(`importlib.import_module(f"parrot.embeddings.{model_type}")`), so the
move is transparent at runtime as long as the import path stays
identical — which it does, because PEP 420 namespace merging
co-locates the satellite modules under the existing `parrot.embeddings`
package.

Reference: spec §3 Module 2, §6 Codebase Contract.

---

## Scope

- `git mv` (preserve history) these three files:
  - `packages/ai-parrot/src/parrot/embeddings/google.py` →
    `packages/ai-parrot-embeddings/src/parrot/embeddings/google.py`
  - `packages/ai-parrot/src/parrot/embeddings/huggingface.py` →
    `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py`
  - `packages/ai-parrot/src/parrot/embeddings/openai.py` →
    `packages/ai-parrot-embeddings/src/parrot/embeddings/openai.py`
- Add per-backend extras to
  `packages/ai-parrot-embeddings/pyproject.toml`:
  - `google = [...]` — deps that the host's `google` extra used to pull,
    pruned to what `parrot.embeddings.google` actually imports.
  - `huggingface = [...]` — deps the host's `embeddings` extra carried
    for sentence-transformers etc. (sentence-transformers, tokenizers,
    safetensors, einops, accelerate, peft, xformers, bm25s, simsimd…).
  - `openai = [...]` — `openai`, `tiktoken`.
- Confirm internal imports in the three moved files still resolve:
  - `from parrot.embeddings.base import EmbeddingModel` (resolves
    against the host — STAYS in core).
  - `from parrot.embeddings.matryoshka import MatryoshkaConfig,
    validate_against_catalog` (matryoshka — STAYS in core).
  - `from parrot.embeddings.catalog import EMBEDDING_MODELS` (catalog
    — STAYS in core).
- After move, `uv sync --all-packages` still works.
- After move, the host directory
  `packages/ai-parrot/src/parrot/embeddings/` contains only:
  `__init__.py`, `base.py`, `registry.py`, `catalog.py`,
  `matryoshka.py`, `processor.py`.

**NOT in scope**:
- Touching `parrot.embeddings.__init__` (its `supported_embeddings`
  dispatch map STAYS unchanged).
- Removing/rewriting host `pyproject.toml` extras — that's TASK-1337.
- Wheel-content test — that's TASK-1338.
- Cross-distribution import test — that's TASK-1339.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/google.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot/src/parrot/embeddings/huggingface.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot/src/parrot/embeddings/openai.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/google.py` | CREATE (via git mv) | Satellite location |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py` | CREATE (via git mv) | Satellite location |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/openai.py` | CREATE (via git mv) | Satellite location |
| `packages/ai-parrot-embeddings/pyproject.toml` | MODIFY | Add `google`, `huggingface`, `openai` extras |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports the moved files rely on (all STAY in core)

```python
# All of these resolve from packages/ai-parrot/src/parrot/embeddings/
# after the move, because PEP 420 merges satellite + host directories.
from parrot.embeddings.base import EmbeddingModel              # verified: packages/ai-parrot/src/parrot/embeddings/base.py:15
from parrot.embeddings.matryoshka import (                     # verified: packages/ai-parrot/src/parrot/embeddings/matryoshka.py:10
    MatryoshkaConfig,
    validate_against_catalog,
)
from parrot.embeddings.catalog import EMBEDDING_MODELS         # verified: packages/ai-parrot/src/parrot/embeddings/matryoshka.py:32
from parrot._imports import lazy_import                        # verified: packages/ai-parrot/src/parrot/_imports.py
```

### Verified Dispatch Table (STAYS in core; do NOT modify)

```python
# packages/ai-parrot/src/parrot/embeddings/__init__.py:14-18
supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}
```

### Verified Registry Dispatcher (STAYS in core; do NOT modify)

```python
# packages/ai-parrot/src/parrot/embeddings/registry.py:149-178
def _build_model(self, model_name: str, model_type: str, **kwargs) -> Any:
    if model_type not in self._supported_embeddings:
        raise ValueError(...)
    cls_name = self._supported_embeddings[model_type]
    module_path = f"parrot.embeddings.{model_type}"
    try:
        module = importlib.import_module(module_path)   # ← resolves through merged namespace
        klass = getattr(module, cls_name)
        return klass(model_name=model_name, **kwargs)
    except ImportError as exc:
        raise ImportError(
            f"Cannot import embedding module '{module_path}': {exc}"
        ) from exc
```

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.embeddings.huggingface` `parrot_embeddings.huggingface`~~
  alternative import path — does NOT exist; do NOT alias. The whole
  point of FEAT-201 is that the import path stays
  `parrot.embeddings.huggingface`.
- ~~`__init__.py` in `packages/ai-parrot-embeddings/src/parrot/embeddings/`~~
  — does NOT exist; do NOT create one (U3).
- ~~Entry-point registration~~ — the satellite does NOT use
  `[project.entry-points]` to register backends with the host. The
  Registry uses string-based `importlib.import_module`, which works
  through PEP 420 merging.

---

## Implementation Notes

### Suggested per-backend extras content

Read the host pyproject's `embeddings` extra (lines 287-308) and the
host `google` extra (lines 382-387) and the host `openai` extra (lines
377-380) to source the deps. **Do not blindly copy everything from
`embeddings`** — split it across the three new extras + leave only
shared transitive deps. Reasonable starting partition:

```toml
[project.optional-dependencies]
huggingface = [
    "sentence-transformers>=5.0.0",
    "tokenizers>=0.20.0,<=0.22.2",
    "safetensors>=0.4.3",
    "einops>=0.7.0",
    "accelerate>=0.30.0",
    "peft>=0.10.0",
    "xformers>=0.0.27",
    "simsimd>=4.3.1",
    "bm25s[full]==0.2.14",
    "rank_bm25==0.2.2",
    "sentencepiece==0.2.1",
]
google = [
    "google-genai>=2.6.0",
    "google-cloud-aiplatform==1.133.0",
]
openai = [
    "openai==2.8.1",
    "tiktoken>=0.9.0",
]
```

Refine the partition by `grep`ing each moved file for `import` /
`from` lines and tracing the actual runtime deps. Don't drag a
backend's deps into another backend's extra.

### Pattern to follow

Same shape as `packages/ai-parrot-tools/pyproject.toml:33-72` —
per-backend extras, one block each.

### Use `git mv` (NOT `git rm` + create)

To preserve `git blame` and `git log --follow` history, run:

```bash
git mv packages/ai-parrot/src/parrot/embeddings/google.py \
       packages/ai-parrot-embeddings/src/parrot/embeddings/google.py
# ...etc
```

### References in Codebase

- `packages/ai-parrot/src/parrot/embeddings/__init__.py` — dispatch
  table (STAYS).
- `packages/ai-parrot/src/parrot/embeddings/registry.py:149-178` —
  string-dispatch (STAYS).
- `packages/ai-parrot/src/parrot/embeddings/base.py:15` — Abstract
  class moved backends inherit from (STAYS).

---

## Acceptance Criteria

- [ ] All three files moved via `git mv` (history preserved).
- [ ] `packages/ai-parrot/src/parrot/embeddings/` contains only
      `__init__.py`, `base.py`, `registry.py`, `catalog.py`,
      `matryoshka.py`, `processor.py` (no `google.py` / `huggingface.py`
      / `openai.py`).
- [ ] `packages/ai-parrot-embeddings/src/parrot/embeddings/` contains
      exactly `google.py`, `huggingface.py`, `openai.py` (and NO
      `__init__.py`).
- [ ] Satellite `pyproject.toml` declares extras `google`,
      `huggingface`, `openai`, each with the appropriate deps.
- [ ] `uv sync --all-packages` succeeds.
- [ ] With the satellite installed:
      `python -c "from parrot.embeddings.huggingface import SentenceTransformerModel; print(SentenceTransformerModel.__module__)"`
      prints `parrot.embeddings.huggingface`.
- [ ] `python -c "import parrot.embeddings.huggingface as m; print(m.__file__)"`
      shows a path inside `packages/ai-parrot-embeddings/...`, NOT
      inside `packages/ai-parrot/...`.
- [ ] Existing test:
      `pytest packages/ai-parrot/tests/ -k embeddings -x` still passes.
- [ ] No `__init__.py` was created at
      `packages/ai-parrot-embeddings/src/parrot/embeddings/`.

---

## Test Specification

Beyond the existing core test suite (which must stay green), add to
the satellite a smoke test verifying the move:

```python
# packages/ai-parrot-embeddings/tests/test_embedding_backends_present.py
import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize("backend", ["google", "huggingface", "openai"])
def test_backend_resolves_to_satellite(backend):
    """Moved backend modules resolve inside the satellite distribution."""
    importlib.invalidate_caches()
    mod = importlib.import_module(f"parrot.embeddings.{backend}")
    assert "ai-parrot-embeddings" in mod.__file__


def test_satellite_does_not_create_embeddings_init():
    """Satellite did not accidentally create __init__.py at the embeddings level."""
    init = (
        Path(__file__).parent.parent
        / "src" / "parrot" / "embeddings" / "__init__.py"
    )
    assert not init.exists(), f"forbidden file: {init}"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 2 and §6 Codebase Contract.
2. **Check dependencies** — TASK-1333 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** —
   - `grep` the three files to be moved and list their actual imports.
   - Re-confirm `supported_embeddings` keys (`huggingface`, `google`,
     `openai`) still match the file basenames.
4. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
5. **Implement** — `git mv`, edit satellite pyproject, run `uv sync`,
   run the smoke test + core test suite.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: All 3 files moved via `git mv`. Added `extend_path` to sub-package
`__init__.py` files (embeddings, stores, rerankers) to enable PEP 420 namespace
merging at sub-package level. Fixed a pre-existing `Optional` missing import in
`google.py`. All 4 tests pass.

**Deviations from spec**: Added `extend_path` calls to
`parrot/embeddings/__init__.py`, `parrot/stores/__init__.py`, and
`parrot/rerankers/__init__.py` in the host package. This is a necessary PEP 420
implementation detail not explicitly stated in the spec, but consistent with what
`parrot/__init__.py` already does. Without it, sub-package namespace merging does
not work. Also fixed a pre-existing `Optional` import missing in google.py.
