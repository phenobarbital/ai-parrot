# TASK-307 — Embedding Provider and Reflection Engine

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-304
**Parallel**: true
**Parallelism notes**: Only imports EpisodeOutcome/ReflectionResult from TASK-304 models. No file overlap with TASK-305 or TASK-306. Can run in parallel.

---

## Objective

Implement the `EpisodeEmbeddingProvider` (lazy-loading sentence-transformers) and the `ReflectionEngine` (LLM-powered with heuristic fallback).

## Files to Create/Modify

- `parrot/memory/episodic/embedding.py` — new file
- `parrot/memory/episodic/reflection.py` — new file

## Implementation Details

### EpisodeEmbeddingProvider

Per brainstorm section 8:

```python
class EpisodeEmbeddingProvider:
    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384,
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        self._model = None  # Lazy loaded
```

- `async embed(text: str) -> list[float]` — lazy-load model on first call, use `asyncio.to_thread()` for non-blocking.
- `async embed_batch(texts: list[str]) -> list[list[float]]` — batch embedding.
- `_get_searchable_text(episode: EpisodicMemory) -> str` — formats `"{situation} | {action_taken} | {lesson_learned}"`.
- `_load_model()` — imports `sentence_transformers` and loads model (only when first needed).

### ReflectionEngine

Per brainstorm section 7:

```python
class ReflectionEngine:
    REFLECTION_PROMPT = """Analyze this agent interaction episode and extract a concise lesson.
    ...
    """

    def __init__(
        self,
        llm_client: AbstractClient | None = None,
        llm_provider: str = "google",
        model: str = "gemini-2.5-flash",
        fallback_to_heuristic: bool = True,
    ) -> None: ...
```

- `async reflect(situation, action_taken, outcome, error_message) -> ReflectionResult`:
  1. If `llm_client` available: format prompt, call LLM with structured output, parse response.
  2. If LLM unavailable or fails and `fallback_to_heuristic`: use `_heuristic_reflect()`.

- `_heuristic_reflect(situation, action_taken, outcome, error_message) -> ReflectionResult`:
  Pattern-match known error types:
  - `"not found"` / `"does not exist"` → "Verify resource exists before accessing"
  - `"timeout"` → "Consider reducing scope or adding timeout"
  - `"rate limit"` / `"429"` → "Add delay between API calls"
  - `"permission"` / `"403"` / `"unauthorized"` → "Check permissions before action"
  - `"connection"` / `"refused"` → "Verify service availability before calling"
  - Default failure → "Review approach and consider alternatives"
  - Success → "Approach worked; remember this pattern"

## Acceptance Criteria

- [ ] `EpisodeEmbeddingProvider` lazy-loads model on first `embed()` call.
- [ ] `embed()` returns vector of correct dimension (384 for default model).
- [ ] `embed()` is non-blocking (uses asyncio.to_thread).
- [ ] `embed_batch()` processes multiple texts efficiently.
- [ ] `ReflectionEngine.reflect()` produces ReflectionResult via LLM when available.
- [ ] Heuristic fallback produces sensible reflections for known error patterns.
- [ ] Heuristic fallback works when no LLM client is provided.
- [ ] Graceful handling when sentence-transformers is not installed.
