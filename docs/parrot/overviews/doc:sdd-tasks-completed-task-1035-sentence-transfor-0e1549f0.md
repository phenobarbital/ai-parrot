---
type: Wiki Overview
title: 'TASK-1035: SentenceTransformerModel Matryoshka encoding'
id: doc:sdd-tasks-completed-task-1035-sentence-transformer-matryoshka-encoding-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires Matryoshka truncation into the actual embedding hot path
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.exceptions
  rel: mentions
---

# TASK-1035: SentenceTransformerModel Matryoshka encoding

**Feature**: FEAT-150 — Matryoshka Embedding Truncation
**Spec**: `sdd/specs/matryoshka-embedding-truncation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1034
**Assigned-to**: unassigned

---

## Context

Wires Matryoshka truncation into the actual embedding hot path
(`SentenceTransformerModel`). After this task, `embed_documents` and
`embed_query` produce truncated, L2-renormalized vectors when the
operator opts in via the `matryoshka` config sub-dict, and
`get_embedding_dimension()` reports the truncated dim so pgvector
table creation downstream sees the right size.

Implements spec §3 Module 2.

---

## Scope

- Extend `SentenceTransformerModel.__init__` to accept an optional
  `matryoshka` kwarg (a dict matching `MatryoshkaConfig`) alongside
  the existing `model_name` and `**kwargs`.
- Parse the dict into `MatryoshkaConfig` and run
  `validate_against_catalog(cfg, self.model_name)` at construction time.
- Store `self._matryoshka_dim: Optional[int]` (the truncated dim, or
  `None` when disabled).
- In `_create_embedding`, after the existing line
  `self._dimension = model.get_embedding_dimension()`, override
  `self._dimension = self._matryoshka_dim` when active.
- Add private helper
  `_apply_matryoshka(vectors)` that no-ops when disabled, otherwise
  slices each vector to `self._matryoshka_dim` and re-normalizes L2.
  Must work on numpy arrays (output of `model.encode(...)`) and on
  plain `list[list[float]]` (the path `.tolist()` produces).
- Hook the helper into `embed_documents` (between `await self.encode(...)`
  and the final return / `tolist()`) and `embed_query` (between
  `await self.encode(...)` and `embedding = result[0]`).
- Add unit tests with a stubbed `_create_embedding` that returns
  predictable native-dim vectors so the suite does not download real
  weights.

**NOT in scope**: registry cache-key changes (TASK-1036), store-layer
forwarding (TASK-1037), provisioning enforcement (TASK-1038),
end-to-end real-weights tests (TASK-1039). Do NOT export
`MatryoshkaConfig` from `parrot.embeddings.__init__`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/embeddings/huggingface.py` | MODIFY | Accept `matryoshka` kwarg; truncate + renorm in `embed_documents` / `embed_query`; override `_dimension` |
| `packages/ai-parrot/tests/embeddings/test_matryoshka_encoding.py` | CREATE | Unit tests with stub model |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import numpy as np
from typing import Any, List, Optional, Tuple
from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog  # from TASK-1034
from parrot.embeddings.base import EmbeddingModel              # verified: base.py:15
from parrot.exceptions import ConfigError                       # verified: parrot/exceptions.py:45
```

### Existing Signatures to Use

```python
# parrot/embeddings/base.py
class EmbeddingModel(ABC):
    def __init__(self, model_name: str, **kwargs):  # line 20
        self.model_name = model_name                # line 21
        self._dimension = None                       # line 25
        self._kwargs = kwargs                        # line 29

    def get_embedding_dimension(self) -> int:        # line 133
        return self._dimension

# parrot/embeddings/huggingface.py
class SentenceTransformerModel(EmbeddingModel):                              # line 102
    def __init__(self, model_name: str, **kwargs):                            # line 108
        super().__init__(model_name=model_name, **kwargs)
        self._query_prefix, self._passage_prefix = _resolve_prefixes(self.model_name)

    async def embed_documents(self, texts, batch_size=None) -> List[List[float]]:  # line 144
        prefixed = self._apply_passage_prefix(texts)        # line 156
        result = await self.encode(prefixed, normalize_embeddings=True)  # 157
        if hasattr(result, "tolist"):
            return result.tolist()                          # line 159
        return result

    async def embed_query(self, text, as_nparray=False):    # line 162
        prefixed = self._apply_query_prefix(text)
        result = await self.encode([prefixed], convert_to_tensor=False,
                                    normalize_embeddings=True, show_progress_bar=False)
        if hasattr(result, "tolist"):
            result = result.tolist()
        embedding = result[0]                                # line 183

    def _create_embedding(self, model_name=None, **kwargs):  # line 188
        ...
        self._dimension = model.get_embedding_dimension()    # line 232  ← override AFTER this
        ...
```

### Does NOT Exist

- ~~`SentenceTransformer.encode(truncate_dim=N)`~~ — some recent
  versions support it, but the project does not pin to those. Do NOT
  rely on it. Implementation MUST do its own slice + L2 renorm.
- ~~`np.linalg.matrix_norm`~~ — use `np.linalg.norm(v, axis=-1, keepdims=True)`.
- ~~A factory in `parrot.embeddings` that builds the model from a dict~~ —
  there is `EmbeddingRegistry._build_model` (`registry.py:115`) which
  forwards `**kwargs` to `klass(model_name=..., **kwargs)`. The
  `matryoshka` kwarg therefore must be accepted by
  `SentenceTransformerModel.__init__` as a regular parameter.

---

## Implementation Notes

### Pattern to Follow

Mirror the existing prefix-resolution pattern at
`huggingface.py:120-130` — resolve `MatryoshkaConfig` once in
`__init__`, store the resolved truncation dim on `self`, then check
the boolean cheaply in the hot path. Avoid re-validating on every
`encode` call.

### Truncation math (do this exactly)

```python
def _apply_matryoshka(self, vectors):
    if self._matryoshka_dim is None:
        return vectors

    is_list = isinstance(vectors, list)
    arr = np.asarray(vectors, dtype=np.float32)
    sliced = arr[..., : self._matryoshka_dim]
    norms = np.linalg.norm(sliced, axis=-1, keepdims=True)
    # Avoid divide-by-zero: a zero vector remains zero (rare edge case
    # but possible for empty or all-pad inputs).
    norms = np.where(norms == 0, 1.0, norms)
    normalized = sliced / norms
    return normalized.tolist() if is_list else normalized
```

Apply BEFORE the final `tolist()` in `embed_documents` (so we work on
the numpy array when possible) or AFTER it (when the path already
produced a list). The helper handles both.

### Key Constraints

- The kwarg name is `matryoshka` (not `matryoshka_config`, not
  `mrl`, not `truncate_dim`) — matches the JSONB shape declared in
  the spec.
- `__init__` MUST tolerate `matryoshka=None` (default) and an empty
  dict `{}` (treats as disabled).
- Validation failures at construction time raise `ConfigError`, not
  `ValueError` — operator config errors should be distinguishable.
- Logging: emit ONE INFO log via `self.logger` when Matryoshka is
  active, including the model name and the effective truncation dim.

### References in Codebase

- `huggingface.py:118-130` — prefix resolution pattern in `__init__`.
- `huggingface.py:144-186` — the two methods to hook the helper into.
- `huggingface.py:230-232` — where `_dimension` gets set; override
  after this line.

---

## Acceptance Criteria

- [ ] `SentenceTransformerModel(model_name="nomic-ai/nomic-embed-text-v1.5", matryoshka={"enabled": True, "dimension": 512})` constructs without error.
- [ ] Same constructor with `dimension=300` raises `ConfigError` at `__init__`.
- [ ] `get_embedding_dimension()` returns `512` after `_create_embedding`
      runs (verify with a stub that returns 768 from
      `model.get_embedding_dimension()`).
- [ ] `embed_documents([...])` returns vectors of length 512.
- [ ] `embed_query("...")` returns a vector of length 512.
- [ ] Each returned vector has L2 norm ≈ 1.0 (within 1e-5).
- [ ] Without the `matryoshka` kwarg (or with `enabled=False`), output
      vectors are bit-identical to the pre-FEAT baseline (snapshot test
      with a fixed stub).
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/embeddings/test_matryoshka_encoding.py -v`
- [ ] Existing tests still pass: `pytest packages/ai-parrot/tests/embeddings/ -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/embeddings/huggingface.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/embeddings/test_matryoshka_encoding.py
import numpy as np
import pytest
from unittest.mock import patch

from parrot.embeddings.huggingface import SentenceTransformerModel
from parrot.exceptions import ConfigError


class _StubModel:
    """Minimal stand-in for SentenceTransformer."""
    def __init__(self, native_dim: int = 768):
        self._native_dim = native_dim

    def get_embedding_dimension(self) -> int:
        return self._native_dim

    def encode(self, texts, **kwargs):
        # Deterministic non-zero vectors so renorm has work to do.
        n = len(texts) if isinstance(texts, list) else 1
        v = np.linspace(1.0, 2.0, self._native_dim, dtype=np.float32)
        v = v / np.linalg.norm(v)
        return np.tile(v, (n, 1))

    def eval(self): pass
    def half(self): pass


@pytest.fixture
def stub_create(monkeypatch):
    def _stub(self, model_name=None, **kwargs):
        m = _StubModel(native_dim=768)
        self._dimension = m.get_embedding_dimension()
        return m
    monkeypatch.setattr(SentenceTransformerModel, "_create_embedding", _stub)
    yield


class TestMatryoshkaEncoding:
    @pytest.mark.asyncio
    async def test_truncated_dim(self, stub_create):
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 512},
        )
        # Force the lazy load
        _ = m.model
        assert m.get_embedding_dimension() == 512
        vecs = await m.embed_documents(["hello", "world"])
        assert len(vecs) == 2
        assert all(len(v) == 512 for v in vecs)

    @pytest.mark.asyncio
    async def test_truncated_renorm(self, stub_create):
        m = SentenceTransformerModel(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            matryoshka={"enabled": True, "dimension": 256},
        )
        _ = m.model
        v = await m.embed_query("hello")
        norm = float(np.linalg.norm(np.asarray(v)))
        assert abs(norm - 1.0) < 1e-5

    @pytest.mark.asyncio
    async def test_disabled_no_change(self, stub_create):
        m = SentenceTransformerModel(model_name="nomic-ai/nomic-embed-text-v1.5")
        _ = m.model
        v = await m.embed_query("hello")
        assert len(v) == 768

    def test_invalid_dim_raises(self):
        with pytest.raises(ConfigError):
            SentenceTransformerModel(
                model_name="nomic-ai/nomic-embed-text-v1.5",
                matryoshka={"enabled": True, "dimension": 300},
            )

    def test_unknown_model_raises(self):
        with pytest.raises(ConfigError):
            SentenceTransformerModel(
                model_name="does-not-exist/foo",
                matryoshka={"enabled": True, "dimension": 512},
            )
```

---

## Agent Instructions

1. Verify TASK-1034 is in `tasks/completed/` (`MatryoshkaConfig` and
   `validate_against_catalog` must exist).
2. Re-read spec §2 Overview, §3 Module 2, and §6 Codebase Contract.
3. Implement the `__init__` extension, the helper, the two hot-path
   hookups, and the `_dimension` override.
4. Run all tests in `tests/embeddings/`. Investigate any regressions.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-06
**Notes**: Implemented matryoshka kwarg, _apply_matryoshka() helper, _dimension override, hooks in embed_documents/embed_query. Added model property override to sync _dimension when registry-cached path is used. 15/15 new tests pass; full suite 233/233 pass.
**Deviations from spec**: Added model property override (not explicitly mentioned) to propagate _dimension to the calling instance when the registry lazy-load path is used.
