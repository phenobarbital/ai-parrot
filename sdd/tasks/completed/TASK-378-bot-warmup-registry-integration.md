# TASK-378: Integrate Bot Warmup with EmbeddingRegistry

**Feature**: first-time-caching-embedding-model
**Feature ID**: FEAT-054
**Spec**: `sdd/specs/first-time-caching-embedding-model.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-374, TASK-375, TASK-376, TASK-377
**Assigned-to**: unassigned

---

## Context

> `AbstractBot.warmup_embeddings()` currently performs manual warmup by calling
> `encode(["warmup"])` on KB store and vector store embeddings. This task simplifies
> it to delegate to `EmbeddingRegistry.preload()`, which ensures all embedding models
> used by the bot are loaded into the registry cache.
> Implements Spec Module 6.

---

## Scope

- Refactor `AbstractBot.warmup_embeddings()` to collect model configs and call `registry.preload()`
- Preserve the vector store connection pool warmup (not embedding-related)
- Preserve the KB document loading (not embedding-related)
- Update `configure()` to pass model configs to registry preload when `warmup_on_configure=True`
- Write tests verifying the new behavior

**NOT in scope**: EmbeddingModel base integration (TASK-379).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/abstract.py` | MODIFY | Refactor `warmup_embeddings()` |
| `tests/bots/test_bot_warmup_registry.py` | CREATE | Tests for warmup integration |

---

## Implementation Notes

### Pattern to Follow

Current warmup:
```python
async def warmup_embeddings(self) -> None:
    if self.kb_store:
        self.kb_store.embeddings.encode(["warmup"], normalize_embeddings=True)
    for kb in self.knowledge_bases:
        if hasattr(kb, "load_documents"):
            await kb.load_documents()
    if self.store:
        if hasattr(self.store, 'connection') and not self.store.connected:
            await self.store.connection()
        self.store.generate_embedding(["warmup"])
```

Refactored:
```python
async def warmup_embeddings(self) -> None:
    from parrot.embeddings import EmbeddingRegistry
    registry = EmbeddingRegistry.instance()

    # Collect embedding model configs to preload
    models_to_preload = []

    # KB Store embedding
    if self.kb_store:
        models_to_preload.append({
            'model_name': self.kb_store._embedding_model_name,
            'model_type': 'huggingface'
        })

    # Vector store embedding
    if self.store and self.embedding_model:
        if isinstance(self.embedding_model, dict):
            models_to_preload.append(self.embedding_model)

    # Preload all embedding models via registry
    if models_to_preload:
        await registry.preload(models_to_preload)

    # Keep non-embedding warmup: KB document loading
    for kb in self.knowledge_bases:
        try:
            if hasattr(kb, "load_documents"):
                await kb.load_documents()
        except Exception as e:
            self.logger.debug(f"KB warmup skipped for {getattr(kb, 'name', kb)}: {e}")

    # Keep non-embedding warmup: vector store connection pool
    if self.store:
        try:
            if hasattr(self.store, 'connection') and not self.store.connected:
                await self.store.connection()
                self.logger.debug("Vector store connection pool warmed up")
        except Exception as e:
            self.logger.debug(f"Vector store connection warmup skipped: {e}")
```

### Key Constraints
- `warmup_embeddings()` must remain `async`
- Keep vector store connection pool warmup (non-embedding concern)
- Keep KB document loading (non-embedding concern)
- Only embedding model loading moves to `registry.preload()`
- Import `EmbeddingRegistry` inside the method to avoid circular imports

### References in Codebase
- `parrot/bots/abstract.py:1004-1042` — current `warmup_embeddings()`
- `parrot/bots/abstract.py:976-977` — where `warmup_embeddings()` is called from `configure()`

---

## Acceptance Criteria

- [ ] `warmup_embeddings()` calls `registry.preload()` for embedding models
- [ ] Vector store connection pool warmup still works
- [ ] KB document loading still works
- [ ] `warmup_on_configure=True` causes registry preload during `configure()`
- [ ] No duplicate model loading (registry handles deduplication)
- [ ] Tests pass: `pytest tests/bots/test_bot_warmup_registry.py -v`

---

## Test Specification

```python
# tests/bots/test_bot_warmup_registry.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestBotWarmupRegistryIntegration:
    @pytest.mark.asyncio
    async def test_warmup_calls_registry_preload(self):
        """warmup_embeddings() delegates to registry.preload()."""
        ...

    @pytest.mark.asyncio
    async def test_warmup_preserves_connection_pool(self):
        """Vector store connection warmup still happens."""
        ...

    @pytest.mark.asyncio
    async def test_warmup_preserves_kb_loading(self):
        """KB document loading still happens."""
        ...

    @pytest.mark.asyncio
    async def test_warmup_collects_all_model_configs(self):
        """Both KB and vector store models are collected for preload."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-374, TASK-375, TASK-376, TASK-377 must be completed
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-378-bot-warmup-registry-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-20
**Notes**: Refactored `warmup_embeddings()` to collect embedding model configs from `kb_store._embedding_model_name` and `self.embedding_model`, then calls `registry.preload(models_to_preload)`. Preserved vector store connection pool warmup and KB document loading. Removed the `self.store.generate_embedding(["warmup"])` call (now handled by registry preload). Created `tests/bots/test_bot_warmup_registry.py`.

**Deviations from spec**: none
