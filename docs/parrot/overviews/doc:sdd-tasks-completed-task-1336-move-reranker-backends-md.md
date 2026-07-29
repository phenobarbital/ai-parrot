---
type: Wiki Overview
title: 'TASK-1336: Move reranker backends (local / llm) to satellite'
id: doc:sdd-tasks-completed-task-1336-move-reranker-backends-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** of the spec — relocate the two concrete
relates_to:
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.rerankers
  rel: mentions
- concept: mod:parrot.rerankers.abstract
  rel: mentions
- concept: mod:parrot.rerankers.factory
  rel: mentions
- concept: mod:parrot.rerankers.llm
  rel: mentions
- concept: mod:parrot.rerankers.local
  rel: mentions
- concept: mod:parrot.rerankers.models
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
---

# TASK-1336: Move reranker backends (local / llm) to satellite

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1333
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec — relocate the two concrete
rerankers (`local.py`, `llm.py`) from
`packages/ai-parrot/src/parrot/rerankers/` to the satellite. The
host's `parrot.rerankers.__init__.py` already uses module-level
`__getattr__` for lazy import, and `parrot.rerankers.factory.create_reranker`
uses local `import` statements inside the factory function — both
resolve concrete backends through merged namespace at call time, so
no host code needs to change.

Reference: spec §3 Module 4, §6 Codebase Contract.

---

## Scope

- `git mv` (preserve history) these two files:
  - `packages/ai-parrot/src/parrot/rerankers/local.py` →
    `packages/ai-parrot-embeddings/src/parrot/rerankers/local.py`
  - `packages/ai-parrot/src/parrot/rerankers/llm.py` →
    `packages/ai-parrot-embeddings/src/parrot/rerankers/llm.py`
- Add per-backend extras to
  `packages/ai-parrot-embeddings/pyproject.toml`:
  - `reranker-local = [...]` — local cross-encoder reranker deps
    (`sentence-transformers` is the cross-encoder backend; may overlap
    with the `huggingface` extra — see Implementation Notes).
  - `reranker-llm = []` — LLMReranker delegates to existing LLM
    clients; if it adds no deps beyond the core LLM clients (which
    live in core's `llms` extra), the list stays empty.
- Confirm internal imports in the moved files still resolve to the
  host:
  - `from parrot.rerankers.abstract import AbstractReranker`
  - `from parrot.rerankers.models import RerankedDocument, RerankerConfig`
  - `from parrot.stores.models import SearchResult`
- After move,
  `packages/ai-parrot/src/parrot/rerankers/` contains only:
  `__init__.py`, `abstract.py`, `factory.py`, `models.py`.

**NOT in scope**:
- Touching `parrot.rerankers.__init__` (its `__getattr__` STAYS
  unchanged).
- Touching `parrot.rerankers.factory` (its local-import dispatch
  STAYS unchanged).
- Touching `parrot.rerankers.abstract` or `models` — they STAY in
  core.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/rerankers/local.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot/src/parrot/rerankers/llm.py` | DELETE (via git mv) | Moves to satellite |
| `packages/ai-parrot-embeddings/src/parrot/rerankers/local.py` | CREATE (via git mv) | Satellite location |
| `packages/ai-parrot-embeddings/src/parrot/rerankers/llm.py` | CREATE (via git mv) | Satellite location |
| `packages/ai-parrot-embeddings/pyproject.toml` | MODIFY | Add `reranker-local`, `reranker-llm` extras |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports the moved files rely on (all STAY in core)

```python
# packages/ai-parrot/src/parrot/rerankers/llm.py:29-31  (will move; the imports still resolve to host)
from parrot.rerankers.abstract import AbstractReranker
from parrot.rerankers.models import RerankedDocument
from parrot.stores.models import SearchResult

# packages/ai-parrot/src/parrot/rerankers/local.py:40-42  (will move; same)
from parrot.rerankers.abstract import AbstractReranker
from parrot.rerankers.models import RerankedDocument, RerankerConfig
from parrot.stores.models import SearchResult
```

### Verified Host-Side Resolution Mechanism (STAYS unchanged)

```python
# packages/ai-parrot/src/parrot/rerankers/__init__.py:26-50
from parrot.rerankers.abstract import AbstractReranker
from parrot.rerankers.models import RerankedDocument, RerankerConfig


def __getattr__(name: str):
    if name == "LocalCrossEncoderReranker":
        from parrot.rerankers.local import LocalCrossEncoderReranker  # ← resolves through merged namespace
        return LocalCrossEncoderReranker
    if name == "LLMReranker":
        from parrot.rerankers.llm import LLMReranker                  # ← resolves through merged namespace
        return LLMReranker
    raise AttributeError(...)


__all__ = [
    "AbstractReranker",
    "LocalCrossEncoderReranker",
    "LLMReranker",
    "RerankedDocument",
    "RerankerConfig",
]
```

```python
# packages/ai-parrot/src/parrot/rerankers/factory.py:54,83
def create_reranker(...) -> AbstractReranker:
    ...
    from parrot.rerankers.local import LocalCrossEncoderReranker  # noqa: PLC0415 — line 54
    ...
    from parrot.rerankers.llm import LLMReranker                  # noqa: PLC0415 — line 83
```

### Verified Abstract (STAYS in core)

```python
# packages/ai-parrot/src/parrot/rerankers/abstract.py:35
class AbstractReranker(ABC):
    async def rerank(self, query, documents, ...) -> List[RerankedDocument]:  # line 50
    async def load(self) -> None:                                             # line 74
    async def cleanup(self) -> None:                                          # line 82
```

### Does NOT Exist (Anti-Hallucination)

- ~~`__init__.py` in the satellite's `src/parrot/rerankers/`~~ — does
  NOT exist; must NOT be created (U3).
- ~~`reranker` (singular) extra~~ — use `reranker-local` and
  `reranker-llm` (plural-style with hyphen). The hyphen-suffix matches
  the spec.
- ~~A standalone `sentence-transformers` extra in the satellite~~ —
  if `reranker-local` needs `sentence-transformers`, declare it
  directly in `reranker-local` (or share via the `huggingface` extra
  if the implementation prefers that route).

---

## Implementation Notes

### Suggested extras

`LocalCrossEncoderReranker` typically uses HuggingFace cross-encoders
via the `sentence-transformers` package. `LLMReranker` typically
re-uses the existing `parrot.clients.*` infrastructure for LLM calls,
so it may have no extra deps.

```toml
[project.optional-dependencies]
reranker-local = [
    "sentence-transformers>=5.0.0",
    "tokenizers>=0.20.0,<=0.22.2",
    "safetensors>=0.4.3",
]
reranker-llm = []   # uses existing LLM clients (anthropic/openai/etc.) declared elsewhere
```

If the implementation discovers `LLMReranker` does in fact pull a
backend lib, declare it. If `reranker-local` overlaps heavily with
`huggingface` (TASK-1334), share via:

```toml
reranker-local = ["ai-parrot-embeddings[huggingface]"]
```

— pick whichever option keeps the install surface clearer.

### `parrot.rerankers.__init__.py` and `factory.py` are UNCHANGED

The lazy `__getattr__` and the in-function imports already do the
right thing under merged namespace. Do NOT modify them.

### Use `git mv`

```bash
git mv packages/ai-parrot/src/parrot/rerankers/local.py \
       packages/ai-parrot-embeddings/src/parrot/rerankers/local.py
git mv packages/ai-parrot/src/parrot/rerankers/llm.py \
       packages/ai-parrot-embeddings/src/parrot/rerankers/llm.py
```

### References in Codebase

- `packages/ai-parrot/src/parrot/rerankers/__init__.py:30-50` —
  lazy `__getattr__` (STAYS).
- `packages/ai-parrot/src/parrot/rerankers/factory.py:54,83` —
  local-import dispatch (STAYS).
- `packages/ai-parrot/src/parrot/rerankers/abstract.py:35` —
  abstract base (STAYS).

---

## Acceptance Criteria

- [ ] Both files moved via `git mv` (history preserved).
- [ ] `packages/ai-parrot/src/parrot/rerankers/` contains only
      `__init__.py`, `abstract.py`, `factory.py`, `models.py`.
- [ ] `packages/ai-parrot-embeddings/src/parrot/rerankers/` contains
      exactly `local.py` and `llm.py` (and NO `__init__.py`).
- [ ] Satellite `pyproject.toml` declares extras `reranker-local`
      and `reranker-llm`.
- [ ] `uv sync --all-packages` succeeds.
- [ ] With satellite installed:
      `python -c "from parrot.rerankers import LocalCrossEncoderReranker; print(LocalCrossEncoderReranker.__module__)"`
      prints `parrot.rerankers.local`.
- [ ] `python -c "from parrot.rerankers import LLMReranker"` succeeds.
- [ ] `python -c "import parrot.rerankers.local as m; print(m.__file__)"`
      shows a path inside `packages/ai-parrot-embeddings/...`.
- [ ] `python -c "from parrot.rerankers import AbstractReranker,
      RerankedDocument, RerankerConfig"` succeeds from the host.
- [ ] `from parrot.rerankers.factory import create_reranker` still
      works.
- [ ] Existing tests:
      `pytest packages/ai-parrot/tests/ -k reranker -x` still pass.

---

## Test Specification

```python
# packages/ai-parrot-embeddings/tests/test_reranker_backends_present.py
import importlib
from pathlib import Path

import pytest


@pytest.mark.parametrize("backend", ["local", "llm"])
def test_backend_resolves_to_satellite(backend):
    importlib.invalidate_caches()
    mod = importlib.import_module(f"parrot.rerankers.{backend}")
    assert "ai-parrot-embeddings" in mod.__file__


def test_lazy_getattr_still_resolves():
    """The host's __getattr__ lazy loader still returns the satellite-supplied classes."""
    from parrot.rerankers import LocalCrossEncoderReranker, LLMReranker
    assert LocalCrossEncoderReranker.__module__ == "parrot.rerankers.local"
    assert LLMReranker.__module__ == "parrot.rerankers.llm"


def test_factory_still_resolves():
    """create_reranker's local-import dispatch still finds the moved classes."""
    from parrot.rerankers.factory import create_reranker  # smoke import only
    assert create_reranker is not None


def test_satellite_did_not_create_rerankers_init():
    init = (
        Path(__file__).parent.parent
        / "src" / "parrot" / "rerankers" / "__init__.py"
    )
    assert not init.exists(), f"forbidden file: {init}"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 4 and §6 Codebase Contract.
2. **Check dependencies** — TASK-1333 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — `grep` `local.py` and `llm.py`
   for their actual imports.
4. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
5. **Implement** — `git mv`, edit satellite pyproject, run `uv sync`,
   run smoke test + core test suite.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker agent)
**Date**: 2026-05-28
**Notes**: …

**Deviations from spec**: none | describe if any
