---
type: Wiki Overview
title: 'TASK-1037: AbstractStore.create_embedding forwards matryoshka kwarg'
id: doc:sdd-tasks-completed-task-1037-store-create-embedding-matryoshka-forwarding-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: operator-supplied `embedding_model` dict (from
relates_to:
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.exceptions
  rel: mentions
- concept: mod:parrot.stores.abstract
  rel: mentions
---

# TASK-1037: AbstractStore.create_embedding forwards matryoshka kwarg

**Feature**: FEAT-150 — Matryoshka Embedding Truncation
**Spec**: `sdd/specs/matryoshka-embedding-truncation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1036
**Assigned-to**: unassigned

---

## Context

`AbstractStore.create_embedding` is the bridge that converts the
operator-supplied `embedding_model` dict (from
`vector_store_config['embedding_model']`) into an actual
`EmbeddingModel` instance via the registry. Today it extracts ONLY
`model_type` and `model_name` from the dict and forwards `**kwargs`
from its own caller (`stores/abstract.py:298-329`). The new
`matryoshka` sub-dict therefore never reaches the registry.

This task closes that gap so when a bot's `vector_store_config`
declares Matryoshka, `SentenceTransformerModel.__init__` actually
receives the kwarg.

Implements spec §3 Module 4.

---

## Scope

- In `AbstractStore.create_embedding(embedding_model, **kwargs)`:
  - Extract `embedding_model.get('matryoshka')` if present.
  - Merge it into the kwargs passed to `registry.get_or_create_sync`
    (do NOT overwrite a `matryoshka` already in `**kwargs` — the
    explicit caller arg wins).
- Add a unit test that asserts the `matryoshka` key is forwarded into
  the registry call.

**NOT in scope**: any change to the registry itself (TASK-1036), to
the embedding model class (TASK-1035), or to provisioning
(TASK-1038). Do NOT add validation here — the model class validates
on its own.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/stores/abstract.py` | MODIFY | Forward `matryoshka` from embedding_model dict |
| `packages/ai-parrot/tests/stores/test_create_embedding_matryoshka.py` | CREATE | Forwarding unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.exceptions import ConfigError                       # parrot/exceptions.py:45
# embeddings imported lazily inside the method to avoid circular imports —
# keep that pattern.
```

### Existing Signatures to Use

```python
# parrot/stores/abstract.py
def create_embedding(self, embedding_model: dict, **kwargs):    # line 298
    from ..embeddings import EmbeddingRegistry                    # line 321
    model_type = embedding_model.get('model_type', 'huggingface') # line 322
    model_name = embedding_model.get('model_name', EMBEDDING_DEFAULT_MODEL)  # line 323
    if model_type not in supported_embeddings:
        raise ConfigError(f"Embedding Model Type: {model_type} not supported.")  # 325
    registry = EmbeddingRegistry.instance()
    return registry.get_or_create_sync(model_name, model_type, **kwargs)  # line 329
```

### Does NOT Exist

- ~~`EmbeddingRegistry.create_with_matryoshka`~~ — not a real method.
  Use the existing `get_or_create_sync` path with the kwarg.
- ~~A separate `embedding_factory` module~~ — does not exist; this is
  THE factory call site.

---

## Implementation Notes

### Pattern to Follow

Tiny, surgical change. Build a merged kwargs dict that prefers the
explicit caller-supplied `matryoshka` over the dict-supplied one:

```python
def create_embedding(self, embedding_model: dict, **kwargs):
    from ..embeddings import EmbeddingRegistry
    model_type = embedding_model.get('model_type', 'huggingface')
    model_name = embedding_model.get('model_name', EMBEDDING_DEFAULT_MODEL)
    if model_type not in supported_embeddings:
        raise ConfigError(f"Embedding Model Type: {model_type} not supported.")

    # FEAT-150: forward Matryoshka config from the embedding_model dict
    # into the registry, unless the caller already provided one.
    matryoshka = embedding_model.get("matryoshka")
    if matryoshka is not None and "matryoshka" not in kwargs:
        kwargs = {**kwargs, "matryoshka": matryoshka}

    registry = EmbeddingRegistry.instance()
    return registry.get_or_create_sync(model_name, model_type, **kwargs)
```

### Key Constraints

- Do NOT modify `EMBEDDING_DEFAULT_MODEL`, `supported_embeddings`, or
  the lazy import.
- Do NOT validate the matryoshka dict here. The validation belongs to
  `SentenceTransformerModel.__init__` (TASK-1035), which invokes
  `validate_against_catalog`.
- Caller-supplied kwarg wins — useful for tests that want to override
  config without rebuilding the dict.

### References in Codebase

- `parrot/stores/abstract.py:298-329` — the function to modify.
- `parrot/embeddings/registry.py` — `get_or_create_sync` signature
  forwards `**kwargs` to `_build_model` to `klass(**kwargs)`, so the
  kwarg flows through automatically once we add it.

---

## Acceptance Criteria

- [ ] `create_embedding({"model_name": "...", "model_type": "huggingface", "matryoshka": {...}})` results in a registry call that includes `matryoshka` in its kwargs.
- [ ] When the dict has no `matryoshka` key, behaviour is unchanged.
- [ ] When the caller passes `matryoshka=...` explicitly AND the dict also has one, the caller's wins.
- [ ] No regression in existing store tests: `pytest packages/ai-parrot/tests/stores/ -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/stores/abstract.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/stores/test_create_embedding_matryoshka.py
import pytest
from unittest.mock import MagicMock, patch

from parrot.stores.abstract import AbstractStore
from parrot.embeddings.registry import EmbeddingRegistry


def _make_store():
    # AbstractStore is abstract; use a concrete-ish subclass or the
    # method-only invocation via a thin subclass that fills the abstract
    # methods with stubs. Adjust to whatever already exists in the test
    # suite (see tests/stores/conftest.py for fixtures, if any).
    class _Stub(AbstractStore):
        async def add_documents(self, *a, **k): pass
        async def similarity_search(self, *a, **k): return []
        async def connection(self): pass
    return _Stub()


class TestCreateEmbeddingForwarding:
    def test_forwards_matryoshka_from_dict(self, monkeypatch):
        captured = {}
        def fake_get_or_create_sync(name, mtype, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock()
        monkeypatch.setattr(EmbeddingRegistry, "instance",
                            classmethod(lambda cls: cls.__new__(cls)))
        monkeypatch.setattr(EmbeddingRegistry, "get_or_create_sync",
                            fake_get_or_create_sync)

        store = _make_store()
        store.create_embedding({
            "model_name": "nomic-ai/nomic-embed-text-v1.5",
            "model_type": "huggingface",
            "matryoshka": {"enabled": True, "dimension": 512},
        })
        assert captured["kwargs"].get("matryoshka") == {"enabled": True, "dimension": 512}

    def test_caller_kwarg_wins(self, monkeypatch):
        captured = {}
        def fake_get_or_create_sync(name, mtype, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock()
        monkeypatch.setattr(EmbeddingRegistry, "instance",
                            classmethod(lambda cls: cls.__new__(cls)))
        monkeypatch.setattr(EmbeddingRegistry, "get_or_create_sync",
                            fake_get_or_create_sync)

        store = _make_store()
        store.create_embedding(
            {
                "model_name": "nomic-ai/nomic-embed-text-v1.5",
                "model_type": "huggingface",
                "matryoshka": {"enabled": True, "dimension": 512},
            },
            matryoshka={"enabled": True, "dimension": 256},
        )
        assert captured["kwargs"]["matryoshka"]["dimension"] == 256

    def test_no_matryoshka_no_change(self, monkeypatch):
        captured = {}
        def fake_get_or_create_sync(name, mtype, **kwargs):
            captured["kwargs"] = kwargs
            return MagicMock()
        monkeypatch.setattr(EmbeddingRegistry, "instance",
                            classmethod(lambda cls: cls.__new__(cls)))
        monkeypatch.setattr(EmbeddingRegistry, "get_or_create_sync",
                            fake_get_or_create_sync)

        store = _make_store()
        store.create_embedding({
            "model_name": "BAAI/bge-base-en-v1.5",
            "model_type": "huggingface",
        })
        assert "matryoshka" not in captured["kwargs"]
```

> **Note for the agent**: the fixture mocking style above is a sketch.
> Inspect `packages/ai-parrot/tests/stores/conftest.py` (if present)
> for the project's idiomatic way to instantiate or patch
> `AbstractStore` / `EmbeddingRegistry`. Adapt accordingly.

---

## Agent Instructions

1. Verify TASK-1034..1036 are completed.
2. Re-read spec §3 Module 4 and §6 Codebase Contract for `stores/abstract.py:298-329`.
3. Make the surgical change. Do NOT refactor adjacent code.
4. Run the store and embedding test suites.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-06
**Notes**: Surgical change to create_embedding() forwarding matryoshka kwarg. Also removed pre-existing unused `importlib` import from abstract.py. 4/4 new tests pass, 247/247 total.
**Deviations from spec**: None
