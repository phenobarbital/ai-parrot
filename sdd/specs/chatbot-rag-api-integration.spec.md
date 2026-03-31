# Feature Specification: chatbot-rag-api-integration

**Feature ID**: FEAT-072
**Date**: 2026-03-31
**Author**: Jesus Lara
**Status**: approved
**Target version**: current

---

## 1. Motivation & Business Requirements

### Problem Statement

When querying a chatbot via the REST API `POST /api/v1/chat/{agent_name}`, RAG (vector context retrieval) is silently skipped — the LLM responds without any document context. However, the same vector store works correctly when tested directly via `PgVectorStore.similarity_search()` or when bots are configured manually in example scripts (e.g., `examples/chatbots/assembly/bot.py`).

**Evidence from logs:**
- No `"Retrieving vector context"` log line appears during API requests.
- The LLM responds with generic answers like "I cannot provide details on how compensation works" instead of using stored documents.
- Direct store tests confirm data exists and is retrievable.

### Root Cause Analysis

There are **three independent bugs** that cause RAG to fail via the API:

1. **Vector store never instantiated during `configure()`**: The `configure()` method only calls `configure_store()` when `self._use_vector is True`. But when bots are loaded from YAML agent definitions or the database, the `vector_store_config` dict is passed to `__init__` kwargs while `use_vectorstore` is **not** set to `True`. Result: `self._vector_store` has the config, but `self.store` stays `None`.

2. **YAML agent definition parsing doesn't propagate the use-vector flag**: `AgentRegistry._parse_agent_definition()` (registry.py:640-642) converts `StoreConfig` to `vector_store_config` in kwargs but never sets `use_vectorstore=True`. Separately, `AgentDefinition.instantiate()` (registry.py:130) pops `vector_store` (not `vector_store_config`) — key mismatch means the secondary config path also fails.

3. **Store `__aexit__` destroys `_embed_` on every context exit** (already fixed in this session): `AbstractStore.__aexit__` was calling `_free_resources()` on every exit regardless of nesting depth, nullifying the embedding model after the first `async with self.store` block.

### Goals
- RAG works correctly when chatbots are accessed via `POST /api/v1/chat/{agent_name}`
- Vector store is automatically configured when `vector_store_config` is present, without requiring an explicit `use_vectorstore=True` flag
- YAML agent definitions with a `vector_store:` section produce a working vector store
- Database-loaded bots with `vector_store_config` produce a working vector store
- Add diagnostic logging so silent RAG failures are visible

### Non-Goals (explicitly out of scope)
- Changing the vector store query logic (similarity_search, mmr_search, ensemble)
- Modifying the embedding model registry or loading
- Adding new vector store backends
- Changing the HTTP API contract

---

## 2. Architectural Design

### Overview

The fix involves three layers:

1. **`AbstractBot.configure()`** — auto-enable vector store when config is present
2. **`AgentRegistry` / `AgentDefinition`** — propagate `use_vectorstore=True` when `vector_store` config exists
3. **Diagnostic logging** — log why RAG was skipped when `_build_vector_context` returns early

### Component Diagram
```
POST /api/v1/chat/{name}
  │
  ▼
ChatHandler.post()
  │
  ▼
BotManager.get_bot(name) ──► AgentRegistry.get_instance()
  │                                │
  │                         AgentDefinition.instantiate()
  │                           ├─ pop 'vector_store' from kwargs  ◄── BUG: key mismatch
  │                           ├─ cls(**merged_kwargs)
  │                           └─ _apply_store_config() + _use_vector = True
  │
  ▼
bot.configure(app)
  ├─ define_store_config()         ◄── declarative override (optional)
  ├─ _apply_store_config()
  └─ if self._use_vector:          ◄── BUG: False when vector_store_config is present
       configure_store()            ◄── NEVER CALLED → self.store stays None
  │
  ▼
bot.conversation(question=...)
  └─ _build_vector_context()
       └─ if not (use_vectors and self.store):  ◄── self.store is None → RAG SKIPPED
            return "", {}
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot.configure()` | modifies | Auto-enable vector store when config present |
| `AbstractBot._build_vector_context()` | modifies | Add diagnostic logging |
| `AgentDefinition.instantiate()` | modifies | Fix key mismatch, set `_use_vector` flag |
| `AgentRegistry._parse_agent_definition()` | modifies | Pass `use_vectorstore=True` with vector config |
| `VectorInterface.configure_store()` | unchanged | Already correct when called |
| `ChatHandler.post()` | unchanged | Already passes params correctly |

### Data Models

No new data models. Existing `StoreConfig` is sufficient.

### New Public Interfaces

No new public interfaces. This is a bug fix to existing initialization logic.

---

## 3. Module Breakdown

### Module 1: Fix `configure()` auto-detection
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: In `configure()`, if `self._vector_store` is set (non-None, non-empty dict/list), auto-set `self._use_vector = True` before the guard check. This is the **primary defense** — regardless of how the bot was created, if it has a vector store config, it should use it.
- **Depends on**: nothing

### Module 2: Fix YAML agent definition key mismatch
- **Path**: `packages/ai-parrot/src/parrot/registry/registry.py`
- **Responsibility**: Two fixes:
  - In `_parse_agent_definition()` (~line 640): also set `merged_args['use_vectorstore'] = True` when `config.vector_store` is present.
  - In `AgentDefinition.instantiate()` (~line 130): also check for `vector_store_config` key (not just `vector_store`) when extracting vector store conf from kwargs.
- **Depends on**: Module 1 (Module 1 is the safety net)

### Module 3: Add diagnostic logging to `_build_vector_context`
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`
- **Responsibility**: When `_build_vector_context` returns early (store is None or use_vectors is False), log **why** at DEBUG level so operators can diagnose RAG failures without guessing.
- **Depends on**: nothing

### Module 4: Integration test
- **Path**: `packages/ai-parrot/tests/bots/test_vector_context_integration.py`
- **Responsibility**: Test that a bot created with `vector_store_config` kwarg (simulating YAML/DB-loaded bots) actually has `self.store` set after `configure()`.
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_configure_auto_enables_vector_store` | Module 1 | Bot created with `vector_store_config` but without `use_vectorstore=True` should have `store` set after `configure()` |
| `test_configure_no_vector_store_config` | Module 1 | Bot created without any vector config should NOT attempt to configure store |
| `test_configure_explicit_use_vector_false` | Module 1 | Verify `define_store_config()` returning a StoreConfig still works |
| `test_agent_definition_instantiate_with_vector_store` | Module 2 | AgentDefinition with vector_store config produces bot with working store |
| `test_build_vector_context_logs_skip_reason` | Module 3 | Verify debug log emitted when store is None |

### Integration Tests
| Test | Description |
|---|---|
| `test_bot_from_yaml_has_vector_store` | Load a bot from YAML definition with vector_store section, verify `self.store` is not None |
| `test_conversation_uses_vector_context` | Mock store with known results, verify vector context appears in system prompt |

### Test Data / Fixtures
```python
@pytest.fixture
def vector_store_config():
    return {
        'vector_store': 'postgres',
        'embedding_model': {
            'model_name': 'thenlper/gte-base',
            'model_type': 'huggingface'
        },
        'table': 'test_embeddings',
        'schema': 'public',
        'dimension': 768,
    }
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] A bot created with `vector_store_config` kwarg (no explicit `use_vectorstore`) has `self.store` set after `configure()`
- [ ] A bot loaded from YAML agent definition with `vector_store:` section has `self.store` set
- [ ] `_build_vector_context()` logs a DEBUG message when RAG is skipped, stating whether `store is None` or `use_vectors is False`
- [ ] Existing bots that explicitly set `use_vectorstore=True` continue to work unchanged
- [ ] Bots without any vector store configuration do NOT attempt to configure a store
- [ ] `POST /api/v1/chat/{agent_name}` returns responses that include vector context when the bot has a configured store
- [ ] All existing tests continue to pass
- [ ] No breaking changes to public API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- The fix in `configure()` should be a **one-liner guard** before the existing `if self._use_vector:` check — not a refactor of the entire method
- Logging additions should use `self.logger.debug()` to avoid noise in production
- The registry fix should handle both `vector_store` and `vector_store_config` keys for backwards compatibility

### Known Risks / Gotchas
- **Risk: Breaking bots that have a vector_store_config but intentionally don't want RAG**. Mitigation: This scenario is nonsensical — if you configure a vector store, you want to use it. An explicit `use_vectorstore=False` override could be added but is YAGNI.
- **Risk: Store connection failure during configure()**. Mitigation: Already handled by existing try/except in `configure()`. The store config is validated at `configure_store()` time, not at `__init__` time.
- **Risk: `_get_database_store()` fails if embedding model or DSN not set**. Mitigation: Already raises with a clear error message. No change needed.

### External Dependencies

No new dependencies.

---

## 7. Open Questions

- [x] Is there any bot that has `vector_store_config` but intentionally disables RAG? — *Assumed no, based on codebase analysis.*: in table navigator.ai_bots there are many bots with vector_store_config but not use_vectorstore=True.

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks are sequential and touch overlapping files.
- **Cross-feature dependencies**: None. The `__aexit__` fix and `embed_documents` await fixes from the current session should be committed to `dev` before starting this feature.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-31 | Jesus Lara | Initial draft |
