# TASK-304 — Episodic Memory Data Models and Enums

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: (none)
**Parallel**: true
**Parallelism notes**: Pure data models and enums with no imports from other new episodic modules. Foundation for all subsequent tasks.

---

## Objective

Create all Pydantic models, enums, and dataclasses for the episodic memory system. These are the foundational types that all other episodic modules import.

## Files to Create/Modify

- `parrot/memory/episodic/__init__.py` — create package with public exports
- `parrot/memory/episodic/models.py` — new file
- `parrot/memory/episodic/backends/__init__.py` — create empty backends subpackage

## Implementation Details

### Enums

```python
class EpisodeOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    TIMEOUT = "timeout"

class EpisodeCategory(str, Enum):
    TOOL_EXECUTION = "tool_execution"
    QUERY_RESOLUTION = "query_resolution"
    ERROR_RECOVERY = "error_recovery"
    USER_PREFERENCE = "user_preference"
    WORKFLOW_PATTERN = "workflow_pattern"
    DECISION = "decision"
    HANDOFF = "handoff"
```

### EpisodicMemory (Pydantic BaseModel)

All fields from spec section 2 data model:
- `episode_id: str` (UUID, auto-generated)
- `created_at`, `updated_at`, `expires_at` (datetime)
- Namespace dimensions: `tenant_id`, `agent_id`, `user_id`, `session_id`, `room_id`, `crew_id`
- Content: `situation`, `action_taken`, `outcome` (EpisodeOutcome), `outcome_details`, `error_type`, `error_message`
- Reflection: `reflection`, `lesson_learned`, `suggested_action`
- Classification: `category` (EpisodeCategory), `importance` (1-10), `is_failure`, `related_tools`, `related_entities`
- Vector: `embedding` (list[float] | None)
- Metadata: `metadata` (dict[str, Any])

Methods:
- `to_dict() -> dict` — serialize for storage
- `@classmethod from_dict(cls, data: dict) -> EpisodicMemory` — deserialize
- `searchable_text() -> str` — returns `"{situation} | {action_taken} | {lesson_learned}"` for embedding

### MemoryNamespace (Pydantic BaseModel)

Per brainstorm section 2.3:
- Fields: `tenant_id`, `agent_id`, `user_id`, `session_id`, `room_id`, `crew_id`
- `build_filter() -> dict[str, Any]` — generates SQL WHERE filter dict
- `scope_label` property — human-readable scope string
- `redis_prefix` property — Redis key prefix

### EpisodeSearchResult (Pydantic BaseModel)

- Inherits all EpisodicMemory fields + `score: float`

### ReflectionResult (Pydantic BaseModel)

- `reflection: str`
- `lesson_learned: str`
- `suggested_action: str`

## Acceptance Criteria

- [ ] All enums have correct string values.
- [ ] `EpisodicMemory` validates all fields with proper types and defaults.
- [ ] `MemoryNamespace.build_filter()` produces correct filter dicts at all scope levels.
- [ ] `searchable_text()` concatenates situation + action + lesson.
- [ ] `to_dict()` / `from_dict()` round-trip correctly.
- [ ] Package `parrot/memory/episodic/` is importable.
