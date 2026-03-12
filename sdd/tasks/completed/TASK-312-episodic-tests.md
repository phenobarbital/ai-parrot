# TASK-312 — Unit and Integration Tests for Episodic Memory Store

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: medium
**Effort**: L
**Depends on**: TASK-304, TASK-305, TASK-306, TASK-307, TASK-308, TASK-309, TASK-310, TASK-311
**Parallel**: false
**Parallelism notes**: Tests all prior tasks; must run after all episodic modules are complete.

---

## Objective

Create comprehensive unit and integration tests covering all episodic memory modules: models, backends, embedding, reflection, cache, store, tools, and mixin.

## Files to Create/Modify

- `tests/test_episodic_memory.py` — new test file

## Implementation Details

### Unit Tests — Models (TASK-304)

1. **test_episode_creation_defaults**: Verify EpisodicMemory auto-generates episode_id, created_at.
2. **test_episode_outcome_enum**: All EpisodeOutcome values are valid strings.
3. **test_episode_category_enum**: All EpisodeCategory values are valid strings.
4. **test_namespace_build_filter_agent_only**: Only tenant_id + agent_id in filter.
5. **test_namespace_build_filter_with_user**: tenant_id + agent_id + user_id.
6. **test_namespace_build_filter_with_room**: tenant_id + agent_id + room_id.
7. **test_namespace_build_filter_with_crew**: tenant_id + crew_id.
8. **test_namespace_scope_label**: Correct label at each scope level.
9. **test_namespace_redis_prefix**: Correct prefix at each scope level.
10. **test_episode_searchable_text**: Concatenates situation + action + lesson.
11. **test_episode_to_dict_from_dict**: Round-trip serialization.

### Unit Tests — FAISS Backend (TASK-306)

12. **test_faiss_store_and_search**: Store episode, search by embedding, verify result.
13. **test_faiss_namespace_filter**: Store episodes for different agents, verify filtering.
14. **test_faiss_persistence**: Save to disk, create new backend, load, verify episodes.
15. **test_faiss_max_episodes_cap**: Exceed cap, verify oldest removed.
16. **test_faiss_get_failures**: Store mixed outcomes, verify only failures returned.

### Unit Tests — Embedding (TASK-307)

17. **test_embedding_lazy_load**: Model is None before first embed(), loaded after.
18. **test_embedding_dimension**: Output vector length matches configured dimension.
19. **test_embedding_batch**: Batch embedding returns correct number of vectors.
20. **test_embedding_searchable_text**: _get_searchable_text formats correctly.

### Unit Tests — Reflection (TASK-307)

21. **test_reflection_llm_success**: Mock LLM returns structured ReflectionResult.
22. **test_reflection_llm_failure_fallback**: LLM fails → heuristic fallback used.
23. **test_reflection_heuristic_timeout**: Error with "timeout" → appropriate lesson.
24. **test_reflection_heuristic_rate_limit**: Error with "rate limit" → appropriate lesson.
25. **test_reflection_heuristic_not_found**: Error with "not found" → appropriate lesson.
26. **test_reflection_heuristic_success**: Success outcome → positive lesson.

### Unit Tests — Redis Cache (TASK-308)

27. **test_cache_store_and_get_recent**: Cache episode, retrieve via get_recent.
28. **test_cache_failures**: Cache failure episode, retrieve via get_failures.
29. **test_cache_invalidation**: Invalidate namespace, verify cache miss.
30. **test_cache_max_recent**: Exceed max_recent, verify oldest evicted.
31. **test_cache_graceful_degradation**: Redis unavailable → returns None, no exception.

### Unit Tests — Tools (TASK-310)

32. **test_tool_search**: search_episodic_memory returns formatted results.
33. **test_tool_record_lesson**: record_lesson stores episode with correct fields.
34. **test_tool_get_warnings**: get_warnings returns formatted warning text.

### Integration Tests

35. **test_store_full_recording_flow**: record_episode → embed → store → cache (FAISS backend, mocked embedding).
36. **test_store_recall_similar**: Record 5 episodes → recall_similar returns most relevant.
37. **test_store_failure_warnings_format**: Record failures → get_failure_warnings produces injectable text.
38. **test_store_tool_episode_from_toolresult**: record_tool_episode extracts fields correctly from ToolResult mock.
39. **test_store_namespace_isolation**: Episodes for user A not returned when querying user B.
40. **test_mixin_build_context**: Mock store → _build_episodic_context returns formatted string.
41. **test_mixin_skip_trivial_tools**: _record_post_tool skips tools in trivial set.
42. **test_mixin_configure**: _configure_episodic_memory creates store with correct backend.

### Test Fixtures

```python
@pytest.fixture
def faiss_backend():
    """In-memory FAISS backend for testing."""
    ...

@pytest.fixture
def mock_embedding_provider():
    """Mock embedding provider returning fixed-dimension random vectors."""
    ...

@pytest.fixture
def mock_reflection_engine():
    """Mock reflection engine returning fixed ReflectionResult."""
    ...

@pytest.fixture
def episodic_store(faiss_backend, mock_embedding_provider, mock_reflection_engine):
    """Fully configured EpisodicMemoryStore with mocked components."""
    ...

@pytest.fixture
def sample_namespace():
    """MemoryNamespace for testing."""
    return MemoryNamespace(tenant_id="test", agent_id="test-agent", user_id="user-1")
```

## Acceptance Criteria

- [ ] All 42 tests pass.
- [ ] Models tests cover creation, serialization, namespace filtering.
- [ ] FAISS backend tests cover CRUD, persistence, namespace filtering.
- [ ] Embedding tests verify lazy loading, dimension, batching.
- [ ] Reflection tests cover LLM path, heuristic fallback, known patterns.
- [ ] Redis cache tests cover store/retrieve, invalidation, graceful degradation.
- [ ] Integration tests verify full recording and recall flows.
- [ ] Mixin tests verify context building and trivial tool filtering.
- [ ] No real PostgreSQL or Redis required (all mocked/in-memory).
